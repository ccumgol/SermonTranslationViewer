"""오프라인 백엔드 — 로컬 STT(Qwen3-ASR) + MT(TranslateGemma via Ollama).

클라우드(Gemini)는 언어마다 음성→번역 세션을 따로 돌리지만, 로컬은
  STT 한국어 전사 1회(공유) → 언어별로 TranslateGemma 번역 N회
구조라 더 효율적이다.

품질·속도 개선 포인트:
  - STT 는 VAD(침묵)로 발화 구간을 끊어 그 구간 전체를 전사(스트리밍보다 정확).
  - 용어집(glossary)으로 STT 전사 후처리 치환 + 번역 고유명사 힌트를 적용.
  - 직전 문장을 번역 문맥으로 전달해 대명사/흐름 연속성 개선.
  - STT/MT 모델은 환경변수로 교체 가능 (정확도↔속도 튜닝).
"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

import httpx
import numpy as np

from audio_input import AudioFanout
from live_session import TranscriptEvent

# Ollama 로컬 서버 (기본 포트)
OLLAMA_URL = "http://localhost:11434/api/generate"

# 모델은 환경변수로 교체 가능 (정확도↔속도)
#   STT: Qwen/Qwen3-ASR-0.6B (빠름) / Qwen/Qwen3-ASR-1.7B (정확)
#   MT : translategemma:12b (정확) / translategemma:4b (빠름)
STT_MODEL = os.getenv("STT_MODEL", "Qwen/Qwen3-ASR-0.6B")
MT_MODEL = os.getenv("MT_MODEL", "translategemma:12b")

# ── VAD(침묵 감지) 기반 발화 구간 잘라내기 파라미터 ──
# Qwen3-ASR 의 스트리밍 모드는 정확도가 크게 떨어지므로, 침묵으로 발화를 끊어
# 그 구간 전체를 transcribe() 로 처리한다(= 전체파일급 정확도).
SAMPLE_RATE = 16000
# 이 RMS(정규화 -1~1) 미만은 침묵으로 본다. 마이크/환경에 맞춰 env 로 조정.
SILENCE_RMS = float(os.getenv("STT_SILENCE_RMS", "0.015"))
# 발화 후 이 시간(초) 이상 조용하면 한 구간으로 확정해 전사.
MIN_SILENCE_SEC = float(os.getenv("STT_MIN_SILENCE_SEC", "0.7"))
# 너무 짧은 잡음은 무시(실제 발화 최소 길이).
MIN_SPEECH_SEC = 0.3
# 쉼 없이 길게 말하면 이 길이에서 강제로 끊어 전사(지연 상한).
MAX_SEGMENT_SEC = float(os.getenv("STT_MAX_SEGMENT_SEC", "12.0"))
_CHUNK_SEC = 0.1  # fanout 청크 = 100ms

# 번역 프롬프트에 쓸 언어 이름은 languages.py 단일 출처 사용
from glossary import Glossary  # noqa: E402
from languages import LANGUAGE_NAMES  # noqa: E402


class KoreanSTT:
    """오디오(fanout)를 한국어로 스트리밍 전사.

    구독자에게 두 종류 이벤트를 전달:
      - ("delta", 글자)   : 화면에 흐르는 한국어 (즉시, 반응성)
      - ("sentence", 문장): 번역에 넘길 완성 문장 (정확도·속도)
    """

    def __init__(
        self,
        fanout: AudioFanout,
        loop: asyncio.AbstractEventLoop,
        glossary: Glossary | None = None,
    ) -> None:
        self._fanout = fanout
        self._loop = loop
        self._glossary = glossary or Glossary()
        self._subscribers: set = set()
        self._task: asyncio.Task | None = None
        # STT 블로킹 추론은 전용 스레드풀에서 (종료 시 기본 풀과의 race 방지)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")

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
        # 진행 중인 추론 스레드는 강제 종료 불가 → 기다리지 않고 정리
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _publish(self, kind: str, text: str) -> None:
        for cb in list(self._subscribers):
            cb(kind, text)

    async def _run(self) -> None:
        import mlx_qwen3_asr as asr

        loop = asyncio.get_running_loop()
        print(f"[local] Qwen3-ASR 모델 로딩… ({STT_MODEL})")
        session = await loop.run_in_executor(
            self._executor, asr.Session, STT_MODEL
        )
        print("[local] STT 준비 완료 — 발화 구간 단위 전사 시작")

        queue = self._fanout.subscribe()
        seg: list[np.ndarray] = []   # 현재 발화 구간 버퍼
        in_speech = False
        silence_sec = 0.0
        speech_sec = 0.0

        async def finalize() -> None:
            nonlocal seg, in_speech, silence_sec, speech_sec
            audio = np.concatenate(seg) if seg else None
            seg = []
            had_speech = speech_sec
            in_speech = False
            silence_sec = 0.0
            speech_sec = 0.0
            if audio is None or had_speech < MIN_SPEECH_SEC:
                return
            try:
                result = await loop.run_in_executor(
                    self._executor,
                    lambda: session.transcribe(audio, language="ko"),
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[local] 전사 실패: {exc}")
                return
            text = (getattr(result, "text", "") or "").strip()
            text = self._glossary.correct(text)     # 용어집 후처리 치환
            if text:
                self._publish("delta", text + " ")  # 한국어 화면 표시
                self._publish("sentence", text)     # 번역 대상

        try:
            while True:
                chunk = await queue.get()
                pcm = (
                    np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
                    / 32768.0
                )
                rms = float(np.sqrt(np.mean(pcm * pcm))) if pcm.size else 0.0
                is_speech = rms >= SILENCE_RMS

                if is_speech:
                    in_speech = True
                    seg.append(pcm)
                    speech_sec += _CHUNK_SEC
                    silence_sec = 0.0
                elif in_speech:
                    seg.append(pcm)             # 발화 뒤 짧은 침묵도 포함
                    silence_sec += _CHUNK_SEC

                seg_sec = len(seg) * _CHUNK_SEC
                if in_speech and (
                    silence_sec >= MIN_SILENCE_SEC or seg_sec >= MAX_SEGMENT_SEC
                ):
                    await finalize()
        finally:
            self._fanout.unsubscribe(queue)


async def translate(
    text: str,
    target_code: str,
    *,
    prev_korean: str = "",
    term_hint: str = "",
) -> str:
    """TranslateGemma 로 한국어 → 목표 언어 번역.

    prev_korean: 직전 문장(문맥 연속성용, 번역하지 않음)
    term_hint  : 고유명사 권장 표기 힌트("아브람→Abram, ...")
    """
    target_name = LANGUAGE_NAMES.get(target_code, target_code)
    lines = [f"Translate the following Korean text to {target_name}."]
    if term_hint:
        lines.append(f"Use these names/terms: {term_hint}.")
    if prev_korean:
        lines.append(f"(Previous sentence for context, do NOT translate: {prev_korean})")
    lines.append("Output only the translation, no explanations.")
    prompt = "\n".join(lines) + f"\n\n{text}"
    payload = {
        "model": MT_MODEL,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "30m",
        "options": {"temperature": 0.2},
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(OLLAMA_URL, json=payload)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()


class LocalSession:
    """한 목표 언어 세션. 공유 STT의 한국어를 받아 번역해 이벤트로 낸다.

    LiveTranslateSession 과 같은 인터페이스(run/set_target_language/stop)를 따른다.
    audio_source 는 사용하지 않는다(오디오는 공유 STT가 소비).
    """

    def __init__(self, stt: KoreanSTT, code: str, glossary: Glossary | None = None) -> None:
        self._stt = stt
        self._code = code
        self._glossary = glossary or Glossary()
        self._running = False
        self._on_event = None
        self._prev_korean = ""   # 직전 문장(번역 문맥용)
        self._tx_queue: asyncio.Queue[str] = asyncio.Queue()
        self._tx_task: asyncio.Task | None = None

    @property
    def target_language(self) -> str:
        return self._code

    def set_target_language(self, code: str) -> None:
        self._code = code

    def stop(self) -> None:
        self._running = False
        self._stt.unsubscribe(self._on_stt)
        if self._tx_task is not None:
            self._tx_task.cancel()

    def _on_stt(self, kind: str, text: str) -> None:
        if self._on_event is None:
            return
        if kind == "delta":
            # 한국어 화면 표시 (대표 워커만 송출)
            self._on_event(TranscriptEvent("source", text, False))
        elif kind == "sentence":
            # 문장 단위 번역 (순서 보존 위해 큐 → 순차 처리)
            self._tx_queue.put_nowait(text)

    async def _translate_loop(self) -> None:
        while self._running:
            sentence = await self._tx_queue.get()
            try:
                translated = await translate(
                    sentence,
                    self._code,
                    prev_korean=self._prev_korean,
                    term_hint=self._glossary.hint_for(sentence),
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[local] 번역 실패({self._code}): {exc}")
                continue
            self._prev_korean = sentence  # 다음 문장의 문맥으로
            if translated and self._on_event is not None:
                self._on_event(TranscriptEvent("target", translated + " ", True))

    async def run(self, audio_source, on_event) -> None:  # noqa: ANN001
        self._on_event = on_event
        self._running = True
        self._stt.start()
        self._stt.subscribe(self._on_stt)
        self._tx_task = asyncio.create_task(self._translate_loop())
        try:
            await self._tx_task
        except asyncio.CancelledError:
            pass


class LocalBackend:
    """오프라인 백엔드. 공유 STT 1개 + 언어별 LocalSession."""

    name = "local"

    def __init__(
        self, fanout: AudioFanout, loop: asyncio.AbstractEventLoop
    ) -> None:
        self._glossary = Glossary.load()  # data/glossary/glossary.txt (있으면)
        if not self._glossary.is_empty:
            print(
                f"[local] 용어집 로드: 치환 {len(self._glossary.corrections)}개 / "
                f"용어 {len(self._glossary.terms)}개"
            )
        self._stt = KoreanSTT(fanout, loop, glossary=self._glossary)
        # 번역 모델을 미리 메모리에 올려둔다(첫 문장 콜드 로딩 지연 방지)
        self._warmup_task = loop.create_task(self._warmup())

    async def _warmup(self) -> None:
        try:
            await translate("주님께 영광을 돌립니다", "en")
            print(f"[local] 번역 모델 예열 완료 ({MT_MODEL})")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"[local] 번역 모델 예열 실패(무시): {exc}")

    def make_session(self, target_language: str) -> LocalSession:
        return LocalSession(self._stt, target_language, glossary=self._glossary)

    async def aclose(self) -> None:
        """서버 종료 시 정리 — STT 태스크/스레드풀, 예열 태스크 정돈."""
        if self._warmup_task is not None:
            self._warmup_task.cancel()
            try:
                await self._warmup_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await self._stt.stop()
