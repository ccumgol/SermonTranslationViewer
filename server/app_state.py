"""송출 제어 상태와 언어 워커 — ws_server.py 에서 분리(모듈 분리 2단계).

- LangWorker: 한 목표 언어의 Live 세션 + 자막 엔진 워커
- AppState: 전체 송출 상태(스타일·언어·워커·캡처 등). 새 연결 동기화에 쓴다
- state: 전역 싱글턴(여러 모듈이 from app_state import state 로 공유)

전역 state·hub 를 공유하는 구조라, 하위 모듈(hub/constants/엔진)만 import 해
순환 import 를 만들지 않는다.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from audio_input import AudioCapture, AudioFanout, queue_chunks
from config import Settings
from constants import DEFAULT_STYLE, LABELS
from hub import hub
from live_session import TranscriptEvent
from sermon_script import ScriptCorrector
from subtitle_engine import RollingTranscript, SubtitleEngine
from transcript_logger import TranscriptLogger
from translation_backend import TranslationBackend


class LangWorker:
    """한 목표 언어에 대한 Live 세션 + 자막 엔진 워커."""

    def __init__(
        self,
        backend: TranslationBackend,
        fanout: AudioFanout,
        code: str,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.code = code
        self.last_text = ""
        self._loop = loop
        self._fanout = fanout
        self._queue = fanout.subscribe()
        self._engine = SubtitleEngine()
        self._session = backend.make_session(code)
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        await self._session.run(
            lambda: queue_chunks(self._queue), self._on_event
        )

    def _on_event(self, ev: TranscriptEvent) -> None:
        # 현재 활성 언어가 아니면(정리 중/유령 워커) 송출하지 않는다.
        # primary 는 "현재 언어 목록의 첫 번째"로 매번 판정해 stale 상태를 배제.
        active_codes = [item["code"] for item in state.languages]
        if self.code not in active_codes:
            return
        is_primary = bool(active_codes) and self.code == active_codes[0]

        state.last_speech_at = time.monotonic()   # 무발화 타이머 갱신
        if ev.kind == "source":
            # 입력(설교) 전사는 대표 워커 하나만 송출 (중복 방지)
            if is_primary and state.source_roller is not None:
                # 원고 기반 교정(로컬은 STT 에서 이미 적용=무해, 온라인은 여기서 표시 교정)
                text = state.script.correct(ev.text)
                sub = state.source_roller.add_delta(text, ev.is_final)
                if ev.is_final and state.logger is not None:
                    state.logger.log("ko", text)
                self._loop.create_task(
                    hub.broadcast(
                        {"type": "source", "text": sub.text, "final": sub.is_final}
                    )
                )
            return
        sub = self._engine.add(ev.text, ev.is_final)
        self.last_text = sub.text
        if ev.is_final and state.logger is not None:
            state.logger.log(self.code, ev.text)
        self._loop.create_task(
            hub.broadcast(
                {
                    "type": "subtitle",
                    "lang": self.code,
                    "text": sub.text,
                    "final": sub.is_final,
                }
            )
        )

    def reset_subtitle(self) -> None:
        self._engine.reset()
        self.last_text = ""

    async def stop(self) -> None:
        self._session.stop()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._fanout.unsubscribe(self._queue)


@dataclass
class AppState:
    """송출 제어 상태. 새 연결을 현재 상태로 동기화하는 데 사용."""

    style: dict = field(default_factory=lambda: dict(DEFAULT_STYLE))
    output_enabled: bool = True
    broadcasting: bool = True   # 번역 파이프라인 가동 여부(방송 시작/종료)
    source_roller: RollingTranscript | None = None
    capture: AudioCapture | None = None
    fanout: AudioFanout | None = None
    settings: Settings | None = None
    backend: TranslationBackend | None = None
    loop: asyncio.AbstractEventLoop | None = None
    # 현재 활성 언어 목록: [{"code","color"}] (순서 = 행 순서)
    languages: list[dict] = field(default_factory=list)
    workers: dict[str, LangWorker] = field(default_factory=dict)
    # 사용량/무발화 추적 + 전사 로깅
    started_at: float = 0.0
    last_speech_at: float = 0.0
    logger: TranscriptLogger | None = None
    script: ScriptCorrector = field(default_factory=ScriptCorrector)
    # 명령별 마지막 실행 시각(쿨다운 판정용) — {명령이름: monotonic 초}
    last_command_at: dict[str, float] = field(default_factory=dict)
    # 워커 재구성(언어/백엔드/장치) 동시 실행 방지 — 유령 워커 발생 차단
    reconfig_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def layout(self) -> list[dict]:
        """송출/운영자 화면이 행을 구성하는 데 쓰는 레이아웃 정보."""
        result = []
        for item in self.languages:
            code = item["code"]
            worker = self.workers.get(code)
            result.append(
                {
                    "code": code,
                    "color": item["color"],
                    "label": LABELS.get(code, code),
                    "text": worker.last_text if worker else "",
                }
            )
        return result

    def reset_all(self) -> None:
        for worker in self.workers.values():
            worker.reset_subtitle()
        if self.source_roller is not None:
            self.source_roller.reset()


# 전역 싱글턴 — 여러 모듈이 공유한다(from app_state import state).
state = AppState()
