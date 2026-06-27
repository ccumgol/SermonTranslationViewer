"""Gemini Live Translate 세션 관리 모듈 (이 프로젝트의 핵심).

공식 문서 확인 사항(ai.google.dev/gemini-api/docs/live-api):
  - 모델: gemini-3.5-live-translate-preview
  - 입력 오디오: 16kHz mono 16-bit PCM little-endian, 100ms 청크
  - 오디오 단독 세션은 15분 후 강제 종료된다.
  - 종료 직전 `go_away` 신호가 오고, `session_resumption` 핸들로
    다음 세션을 이어붙여 무중단(seamless) 운영이 가능하다.
  - input/output_audio_transcription 활성화 시 전사 텍스트를 받는다.

설교는 30~45분이므로 세션 재개(resumption)는 선택이 아니라 필수다.
이 모듈은 go_away 를 감지하면 보관해 둔 핸들로 새 세션을 열어
오디오 스트림을 끊김 없이 이어준다.

번역 음성(오디오 출력)은 받지 않고 텍스트 전사만 받는다.
→ 출력 토큰 비용(입력의 약 6배)을 절감하고 지연을 줄이기 위함.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator, Callable

from google import genai
from google.genai import types

from config import Settings


@dataclass(frozen=True)
class TranscriptEvent:
    """전사/번역 이벤트 한 건 (불변)."""

    kind: str          # "source" (한국어 인식) | "target" (영어 번역)
    text: str
    is_final: bool     # 턴 종료로 확정된 텍스트인지


# 오디오 청크를 공급하는 비동기 제너레이터 타입
AudioSource = Callable[[], AsyncIterator[bytes]]


class LiveTranslateSession:
    """15분 한계를 넘어 끊김 없이 동작하는 실시간 번역 세션 래퍼."""

    def __init__(self, settings: Settings, target_language: str | None = None) -> None:
        self._settings = settings
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._resumption_handle: str | None = None
        self._running = False
        # 런타임에 바꿀 수 있는 목표 언어 (초기값은 인자 또는 .env)
        self._target_language = target_language or settings.target_language
        self._restart_event = asyncio.Event()

    @property
    def target_language(self) -> str:
        return self._target_language

    def set_target_language(self, code: str) -> None:
        """목표 언어를 바꾸고 세션을 새 언어로 재시작하도록 신호."""
        code = (code or "").strip()
        if not code or code == self._target_language:
            return
        self._target_language = code
        # 언어가 바뀌면 이전 세션 이어받기는 무효 → 새 세션으로 시작
        self._resumption_handle = None
        self._restart_event.set()
        print(f"[live] 목표 언어 변경 → {code} (세션 재시작)")

    def _build_config(self) -> types.LiveConnectConfig:
        """세션 setup 설정. 보관 중인 핸들이 있으면 이어받기로 연결."""
        return types.LiveConnectConfig(
            # 자막만 필요 → 텍스트 전사만 수신, 오디오 출력은 받지 않는다.
            response_modalities=["TEXT"],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            # 목표 언어 지정 (입력 언어는 모델이 자동 감지). 짧은 코드: en, ja, zh ...
            translation_config=types.TranslationConfig(
                target_language_code=self._target_language
            ),
            # 15분 제한 우회: 항상 세션 재개 활성화.
            session_resumption=types.SessionResumptionConfig(
                handle=self._resumption_handle
            ),
        )

    async def run(
        self,
        audio_source: AudioSource,
        on_event: Callable[[TranscriptEvent], None],
    ) -> None:
        """오디오를 흘려보내며 전사 이벤트를 on_event 콜백으로 전달.

        go_away 수신 시 내부적으로 재연결하므로 호출자는 한 번만 run 하면 된다.
        """
        self._running = True
        while self._running:
            try:
                await self._run_one_session(audio_source, on_event)
            except Exception as exc:  # noqa: BLE001
                # 네트워크/세션 오류는 삼키지 않고 알린 뒤 잠깐 대기 후 재시도.
                print(f"[live] 세션 오류, 2초 후 재연결: {exc}")
                await asyncio.sleep(2.0)

    async def _run_one_session(
        self,
        audio_source: AudioSource,
        on_event: Callable[[TranscriptEvent], None],
    ) -> None:
        config = self._build_config()
        async with self._client.aio.live.connect(
            model=self._settings.model, config=config
        ) as session:
            print("[live] 세션 연결됨")

            # 송신(오디오) / 수신(전사) 을 동시에 처리하며,
            # 언어 변경(restart) 신호가 오면 즉시 세션을 끊고 재시작한다.
            send_task = asyncio.create_task(
                self._send_audio(session, audio_source)
            )
            recv_task = asyncio.create_task(
                self._receive_loop(session, on_event)
            )
            restart_task = asyncio.create_task(self._restart_event.wait())
            try:
                await asyncio.wait(
                    {recv_task, restart_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                # recv_task 가 예외로 끝났으면 run() 이 처리하도록 다시 던진다.
                recv_error = (
                    recv_task.exception()
                    if recv_task.done() and not recv_task.cancelled()
                    else None
                )
            finally:
                for task in (send_task, recv_task, restart_task):
                    task.cancel()
                for task in (send_task, recv_task, restart_task):
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

            if recv_error is not None:
                raise recv_error
            if self._restart_event.is_set():
                self._restart_event.clear()
                print("[live] 언어 변경으로 세션 재시작")
            return

    async def _send_audio(self, session, audio_source: AudioSource) -> None:
        """100ms PCM 청크를 실시간 입력으로 전송."""
        async for chunk in audio_source():
            await session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
            )

    async def _receive_loop(
        self,
        session,
        on_event: Callable[[TranscriptEvent], None],
    ) -> bool:
        """수신 루프. 재연결이 필요하면 True 반환."""
        async for response in session.receive():
            # 1) 세션 재개 핸들 갱신 → 다음 재연결을 위해 보관
            update = getattr(response, "session_resumption_update", None)
            if update is not None and getattr(update, "resumable", False):
                self._resumption_handle = update.new_handle

            # 2) 종료 임박 신호 → 새 세션으로 이어붙이기 위해 루프 탈출
            if getattr(response, "go_away", None) is not None:
                return True

            # 3) 전사 텍스트 추출
            content = getattr(response, "server_content", None)
            if content is None:
                continue

            in_tx = getattr(content, "input_transcription", None)
            if in_tx is not None and in_tx.text:
                on_event(TranscriptEvent("source", in_tx.text, _final(content)))

            out_tx = getattr(content, "output_transcription", None)
            if out_tx is not None and out_tx.text:
                on_event(TranscriptEvent("target", out_tx.text, _final(content)))

        # 세션이 정상 종료되면 재연결 불필요
        return False

    def stop(self) -> None:
        self._running = False


def _final(content) -> bool:  # noqa: ANN001
    return bool(getattr(content, "turn_complete", False))
