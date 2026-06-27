"""번역 백엔드 추상화.

같은 오디오 파이프라인/자막/웹 UI 를 공유하면서, 번역 엔진만 교체할 수 있게
한다. 현재는 온라인(Gemini) 백엔드만 있고, 추후 오프라인(로컬 STT+MT)
백엔드를 같은 인터페이스로 추가한다.

세션 인터페이스(TranslationSession)는 기존 LiveTranslateSession 이 이미
만족한다: run(audio_source, on_event) / set_target_language(code) /
target_language / stop().
"""

from __future__ import annotations

from typing import AsyncIterator, Callable, Protocol, runtime_checkable

from config import Settings
from live_session import LiveTranslateSession, TranscriptEvent

# 오디오 청크 비동기 제너레이터를 돌려주는 팩토리
AudioSource = Callable[[], AsyncIterator[bytes]]
# 전사/번역 이벤트 콜백
EventCallback = Callable[[TranscriptEvent], None]


@runtime_checkable
class TranslationSession(Protocol):
    """한 목표 언어에 대한 실시간 번역 세션."""

    @property
    def target_language(self) -> str: ...

    def set_target_language(self, code: str) -> None: ...

    def stop(self) -> None: ...

    async def run(
        self, audio_source: AudioSource, on_event: EventCallback
    ) -> None: ...


class TranslationBackend(Protocol):
    """언어별 번역 세션을 만들어 주는 백엔드."""

    name: str

    def make_session(self, target_language: str) -> TranslationSession: ...


class GeminiBackend:
    """온라인 백엔드 — Gemini Live Translate 사용 (기존 동작)."""

    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def make_session(self, target_language: str) -> TranslationSession:
        return LiveTranslateSession(
            self._settings, target_language=target_language
        )
