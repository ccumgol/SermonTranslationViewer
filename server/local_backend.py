"""오프라인 백엔드 — 로컬 STT(Qwen3-ASR) + MT(TranslateGemma via Ollama).

클라우드(Gemini)는 언어마다 음성→번역 세션을 따로 돌리지만, 로컬은
  STT 한국어 전사 1회(공유) → 언어별로 TranslateGemma 번역 N회
구조라 더 효율적이다.

  - STT: Qwen3-ASR (mlx-qwen3-asr), CJK 특화·스트리밍, Apple Silicon MLX
  - MT : TranslateGemma 12B (Ollama, OpenAI 호환 로컬 서버)

인터넷·API 비용 없이 동작한다. 정확도는 Gemini보다 약간 낮지만 설교 자막용으로
충분하며, STT context(용어집)와 번역으로 보완한다.
"""

from __future__ import annotations

import asyncio

import httpx
import numpy as np

from audio_input import AudioFanout
from live_session import TranscriptEvent

# Ollama 로컬 서버 (기본 포트)
OLLAMA_URL = "http://localhost:11434/api/generate"
MT_MODEL = "translategemma:12b"
STT_MODEL = "Qwen/Qwen3-ASR-0.6B"

# 번역 프롬프트에 쓸 언어 이름 (code → 영어 표기)
LANGUAGE_NAMES = {
    "en": "English",
    "ja": "Japanese",
    "zh-CN": "Chinese (Simplified)",
    "zh": "Chinese",
    "es": "Spanish",
    "vi": "Vietnamese",
    "fr": "French",
    "ru": "Russian",
    "ko": "Korean",
}


class KoreanSTT:
    """오디오(fanout)를 받아 한국어로 스트리밍 전사하고, 확정 텍스트 증가분을
    구독자 콜백으로 전달한다. (백엔드 전체에서 1개만 운용)"""

    def __init__(
        self,
        fanout: AudioFanout,
        loop: asyncio.AbstractEventLoop,
        context: str = "",
    ) -> None:
        self._fanout = fanout
        self._loop = loop
        self._context = context
        self._subscribers: set = set()
        self._task: asyncio.Task | None = None
        self._last_stable = ""

    def subscribe(self, cb) -> None:
        self._subscribers.add(cb)

    def unsubscribe(self, cb) -> None:
        self._subscribers.discard(cb)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        import mlx_qwen3_asr as asr

        # 모델 로드(블로킹) → 스레드에서
        print("[local] Qwen3-ASR 모델 로딩…")
        session = await asyncio.to_thread(asr.Session, STT_MODEL)
        state = session.init_streaming(
            language="ko",
            context=self._context,
            chunk_size_sec=2.0,
            finalization_mode="accuracy",
        )
        print("[local] STT 준비 완료 — 한국어 스트리밍 시작")

        queue = self._fanout.subscribe()
        try:
            while True:
                chunk = await queue.get()  # int16 PCM bytes (16kHz mono)
                pcm = (
                    np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
                    / 32768.0
                )
                state = await asyncio.to_thread(session.feed_audio, pcm, state)
                self._emit(state)
        finally:
            self._fanout.unsubscribe(queue)

    def _emit(self, state) -> None:
        stable = getattr(state, "stable_text", "") or ""
        if stable != self._last_stable and stable.startswith(self._last_stable):
            delta = stable[len(self._last_stable):]
            self._last_stable = stable
            if delta.strip():
                for cb in list(self._subscribers):
                    cb(delta)
        elif stable != self._last_stable:
            # 드물게 재정렬되면 전체를 새 기준으로
            self._last_stable = stable


async def translate(text: str, target_code: str) -> str:
    """TranslateGemma 로 한국어 → 목표 언어 번역."""
    target_name = LANGUAGE_NAMES.get(target_code, target_code)
    prompt = (
        f"Translate the following Korean text to {target_name}. "
        f"Output only the translation, no explanations.\n\n{text}"
    )
    payload = {
        "model": MT_MODEL,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "30m",  # 모델을 메모리에 유지(웜)
        "options": {"temperature": 0.2},
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(OLLAMA_URL, json=payload)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()


class LocalSession:
    """한 목표 언어 세션. 공유 STT의 한국어 전사를 받아 번역해 이벤트로 낸다.

    LiveTranslateSession 과 같은 인터페이스(run/set_target_language/stop)를 따른다.
    audio_source 는 사용하지 않는다(오디오는 공유 STT가 소비).
    """

    def __init__(self, stt: KoreanSTT, code: str) -> None:
        self._stt = stt
        self._code = code
        self._running = False
        self._on_event = None
        self._tx_queue: asyncio.Queue[str] = asyncio.Queue()
        self._tx_task: asyncio.Task | None = None

    @property
    def target_language(self) -> str:
        return self._code

    def set_target_language(self, code: str) -> None:
        self._code = code

    def stop(self) -> None:
        self._running = False
        self._stt.unsubscribe(self._on_korean)
        if self._tx_task is not None:
            self._tx_task.cancel()

    def _on_korean(self, delta: str) -> None:
        # 한국어 확정 증가분 → 대표 워커가 source 로 표시
        if self._on_event is not None:
            self._on_event(TranscriptEvent("source", delta, True))
        # 번역은 언어별로 순서 보존을 위해 큐에 넣어 순차 처리
        self._tx_queue.put_nowait(delta)

    async def _translate_loop(self) -> None:
        while self._running:
            text = await self._tx_queue.get()
            try:
                translated = await translate(text, self._code)
            except Exception as exc:  # noqa: BLE001
                print(f"[local] 번역 실패({self._code}): {exc}")
                continue
            if translated and self._on_event is not None:
                # 문장 끝 공백 추가로 다음 문장과 붙지 않게
                self._on_event(
                    TranscriptEvent("target", translated + " ", True)
                )

    async def run(self, audio_source, on_event) -> None:  # noqa: ANN001
        self._on_event = on_event
        self._running = True
        self._stt.start()  # 공유 STT (최초 1회만 실제 시작)
        self._stt.subscribe(self._on_korean)
        self._tx_task = asyncio.create_task(self._translate_loop())
        try:
            await self._tx_task
        except asyncio.CancelledError:
            pass


class LocalBackend:
    """오프라인 백엔드. 공유 STT 1개 + 언어별 LocalSession."""

    name = "local"

    def __init__(
        self,
        fanout: AudioFanout,
        loop: asyncio.AbstractEventLoop,
        stt_context: str = "",
    ) -> None:
        self._stt = KoreanSTT(fanout, loop, context=stt_context)

    def make_session(self, target_language: str) -> LocalSession:
        return LocalSession(self._stt, target_language)
