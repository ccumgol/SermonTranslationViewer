"""오프라인 백엔드 — 로컬 STT(Qwen3-ASR) + MT(TranslateGemma via Ollama).

클라우드(Gemini)는 언어마다 음성→번역 세션을 따로 돌리지만, 로컬은
  STT 한국어 전사 1회(공유) → 언어별로 TranslateGemma 번역 N회
구조라 더 효율적이다.

품질·속도 개선 포인트:
  - STT 는 문장 단위로 모아 번역에 넘긴다(단어 조각마다 번역하면 느리고 어색).
  - STT 에 도메인 컨텍스트(성경 고유명사 등)를 주어 인식률을 높인다.
  - STT/MT 모델은 환경변수로 교체 가능 (정확도↔속도 튜닝).
"""

from __future__ import annotations

import asyncio
import os
import re
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

# STT 도메인 컨텍스트 — 자주 틀리는 성경 고유명사/용어를 힌트로 (환경변수로 덮어쓰기 가능)
DEFAULT_STT_CONTEXT = (
    "여호와 하나님 예수 그리스도 성령 아브람 아브라함 사래 사라 이삭 야곱 "
    "다메섹 엘리에셀 가나안 애굽 다윗 모세 바울 베드로 요한 "
    "창세기 출애굽기 시편 이사야 마태복음 요한복음 로마서 고린도전서 "
    "복음 은혜 믿음 구원 십자가 부활 회개 축복 말씀 기도 예배"
)
STT_CONTEXT = os.getenv("STT_CONTEXT", DEFAULT_STT_CONTEXT)

# 문장 끝 경계 (마침표류). STT 가 구두점을 붙여주므로 이를 기준으로 분절.
_SENTENCE_END = re.compile(r"[.!?。…！？]+")
# 구두점 없이 길어지면 강제로 끊는 길이(한글 기준)
_MAX_SENTENCE_CHARS = 60
# 발화가 이 시간(초) 이상 멈추면 버퍼에 남은 미완성분을 번역으로 흘려보냄
_IDLE_FLUSH_SEC = 2.5

# 번역 프롬프트에 쓸 언어 이름 (code → 영어 표기)
LANGUAGE_NAMES = {
    "en": "English", "ja": "Japanese", "zh-CN": "Chinese (Simplified)",
    "zh": "Chinese", "es": "Spanish", "vi": "Vietnamese",
    "fr": "French", "ru": "Russian", "ko": "Korean",
}


class KoreanSTT:
    """오디오(fanout)를 한국어로 스트리밍 전사.

    구독자에게 두 종류 이벤트를 전달:
      - ("delta", 글자)   : 화면에 흐르는 한국어 (즉시, 반응성)
      - ("sentence", 문장): 번역에 넘길 완성 문장 (정확도·속도)
    """

    def __init__(self, fanout: AudioFanout, loop: asyncio.AbstractEventLoop) -> None:
        self._fanout = fanout
        self._loop = loop
        self._subscribers: set = set()
        self._task: asyncio.Task | None = None
        self._last_stable = ""
        self._buf = ""              # 문장 분절 대기 버퍼
        self._last_delta_at = 0.0
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
        state = session.init_streaming(
            language="ko",
            context=STT_CONTEXT,
            chunk_size_sec=2.0,
            max_context_sec=30.0,
            finalization_mode="accuracy",
        )
        print("[local] STT 준비 완료 — 한국어 스트리밍 시작")

        queue = self._fanout.subscribe()
        idle = asyncio.create_task(self._idle_flusher())
        try:
            while True:
                chunk = await queue.get()
                pcm = (
                    np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
                    / 32768.0
                )
                state = await loop.run_in_executor(
                    self._executor, session.feed_audio, pcm, state
                )
                self._emit(state)
        finally:
            idle.cancel()
            self._fanout.unsubscribe(queue)

    def _emit(self, state) -> None:
        stable = getattr(state, "stable_text", "") or ""
        if stable == self._last_stable:
            return
        if not stable.startswith(self._last_stable):
            # 드물게 재정렬되면 기준만 갱신
            self._last_stable = stable
            return
        delta = stable[len(self._last_stable):]
        self._last_stable = stable
        if not delta:
            return
        self._last_delta_at = self._loop.time()
        self._publish("delta", delta)          # 화면용 (즉시)
        self._buf += delta
        self._flush_sentences()                # 번역용 (문장 단위)

    def _flush_sentences(self) -> None:
        """버퍼에서 완성된 문장을 잘라 번역 대상으로 내보낸다."""
        while True:
            match = _SENTENCE_END.search(self._buf)
            if match:
                end = match.end()
                sentence = self._buf[:end].strip()
                self._buf = self._buf[end:]
                if sentence:
                    self._publish("sentence", sentence)
                continue
            # 구두점 없이 너무 길면 마지막 공백에서 끊어 흘려보냄
            if len(self._buf) >= _MAX_SENTENCE_CHARS:
                cut = self._buf.rfind(" ", 0, _MAX_SENTENCE_CHARS)
                cut = cut if cut > 0 else _MAX_SENTENCE_CHARS
                sentence = self._buf[:cut].strip()
                self._buf = self._buf[cut:]
                if sentence:
                    self._publish("sentence", sentence)
                continue
            break

    async def _idle_flusher(self) -> None:
        """발화가 멈추면 버퍼에 남은 미완성 문장을 번역으로 흘려보낸다."""
        while True:
            await asyncio.sleep(1.0)
            if (
                self._buf.strip()
                and self._loop.time() - self._last_delta_at >= _IDLE_FLUSH_SEC
            ):
                sentence = self._buf.strip()
                self._buf = ""
                self._publish("sentence", sentence)


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
                translated = await translate(sentence, self._code)
            except Exception as exc:  # noqa: BLE001
                print(f"[local] 번역 실패({self._code}): {exc}")
                continue
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
        self._stt = KoreanSTT(fanout, loop)
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
        return LocalSession(self._stt, target_language)

    async def aclose(self) -> None:
        """서버 종료 시 정리 — STT 태스크/스레드풀, 예열 태스크 정돈."""
        if self._warmup_task is not None:
            self._warmup_task.cancel()
            try:
                await self._warmup_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await self._stt.stop()
