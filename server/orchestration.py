"""백엔드 전환·파이프라인·하트비트 — ws_server.py 에서 분리(모듈 분리 2단계).

오디오 캡처 → fan-out → 언어별 워커 기동, 온라인/오프라인 백엔드 전환,
방송 시작/종료, 사용량·입력레벨 하트비트를 담당한다. 전역 state·hub 를 공유한다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from app_state import LangWorker, state
from audio_input import SILENCE_DBFS, AudioCapture, AudioFanout, rms_to_dbfs
from config import Settings
from constants import (
    COST_PER_MIN,
    DEFAULT_COLORS,
    IDLE_STOP_MIN,
    IDLE_WARN_MIN,
    LEVEL_PUSH_SEC,
    SCRIPT_PATH,
)
from hub import hub
from local_backend import SILENCE_RMS as STT_SILENCE_RMS
from local_backend import LocalBackend
from subtitle_engine import RollingTranscript
from transcript_logger import TranscriptLogger
from translation_backend import GeminiBackend, TranslationBackend

log = logging.getLogger("server")


def _build_backend(name: str) -> TranslationBackend:
    """이름으로 백엔드 인스턴스 생성 (fanout/loop 가 준비된 뒤 호출)."""
    if name == "local":
        return LocalBackend(state.fanout, state.loop, script=state.script)
    return GeminiBackend(state.settings)


async def switch_backend(name: str) -> None:
    """실행 중 백엔드(온라인/오프라인) 전환 — 같은 언어 구성을 유지한다."""
    if name not in ("gemini", "local"):
        return
    if state.backend is not None and state.backend.name == name:
        return
    if name == "gemini" and not (state.settings and state.settings.gemini_api_key):
        await hub.broadcast(
            {
                "type": "backend_error",
                "message": "온라인 전환 실패: GEMINI_API_KEY 가 설정돼 있지 않습니다.",
            }
        )
        return

    languages = list(state.languages)
    # 1) 기존 워커 모두 정지
    for code in list(state.workers):
        await state.workers.pop(code).stop()
    # 2) 기존 백엔드 정리(로컬이면 STT 중지)
    old = state.backend
    close = getattr(old, "aclose", None) if old is not None else None
    if close is not None:
        await close()
    # 3) 새 백엔드로 교체 후 같은 언어로 재시작
    state.backend = _build_backend(name)
    log.info("백엔드 전환 → %s", name)
    await apply_languages(languages)
    await hub.broadcast({"type": "reset"})
    await hub.broadcast({"type": "backend_state", "backend": name})
    await hub.broadcast({"type": "layout", "layout": state.layout()})


async def set_broadcast(active: bool) -> None:
    """방송(번역 파이프라인) 시작/종료.

    종료 시 모든 워커를 멈춰 온라인 비용·연산을 실제로 중단한다(언어 구성은 유지).
    시작 시 마지막 언어 구성으로 워커를 다시 띄운다.
    """
    if active == state.broadcasting and state.workers:
        return
    if active:
        state.broadcasting = True
        state.last_speech_at = time.monotonic()  # 재시작 시 무발화 타이머 리셋(즉시 재종료 방지)
        langs = state.languages or [
            {"code": state.settings.target_language, "color": DEFAULT_COLORS[0]}
        ]
        await apply_languages(langs)
        log.info("▶ 방송 시작")
    else:
        state.broadcasting = False
        for code in list(state.workers):
            await state.workers.pop(code).stop()
        if state.source_roller is not None:
            state.source_roller.reset()
        log.info("■ 방송 종료 (워커 정지)")
    await hub.broadcast({"type": "reset"})
    await hub.broadcast({"type": "broadcast_state", "active": state.broadcasting})


async def apply_languages(languages: list[dict]) -> None:
    """활성 언어 목록을 적용 — 필요한 워커를 시작/중지하고 레이아웃 갱신."""
    assert state.backend is not None and state.fanout is not None
    codes = [item["code"] for item in languages]

    # 더 이상 필요 없는 워커 중지
    for code in list(state.workers):
        if code not in codes:
            await state.workers.pop(code).stop()

    # 활성 언어 목록을 먼저 갱신(워커 시작 전에) → on_event 가 새 목록 기준 판정
    state.languages = languages

    # 방송 종료 상태면 워커를 띄우지 않고 구성만 저장
    if not state.broadcasting:
        return

    # 새 워커 시작
    for item in languages:
        code = item["code"]
        if code not in state.workers:
            worker = LangWorker(
                state.backend, state.fanout, code, state.loop
            )
            state.workers[code] = worker
            worker.start()

    if state.source_roller is not None:
        state.source_roller.reset()


async def pipeline(settings: Settings) -> None:
    """오디오 캡처 + fan-out + 초기 언어 워커 기동."""
    state.settings = settings
    state.loop = asyncio.get_running_loop()
    state.source_roller = RollingTranscript()
    state.started_at = time.monotonic()
    state.last_speech_at = time.monotonic()
    state.logger = TranscriptLogger.maybe_create()
    if state.logger is not None:
        log.info(
            "전사 기록 ON → %s (읽기 쉬운 .txt + 기계판독 .jsonl 동시 저장 · "
            "끄려면 .env 에 LOG_TRANSCRIPTS=0)",
            state.logger.text_path,
        )
    # 저장된 설교 원고가 있으면 불러와 교정 용어 준비
    if SCRIPT_PATH.exists():
        n = state.script.set_script(SCRIPT_PATH.read_text(encoding="utf-8"))
        if n:
            log.info("저장된 설교 원고 로드 — 교정 용어 %d개", n)

    async with AudioCapture(settings.audio_input_device) as capture:
        state.capture = capture
        fanout = AudioFanout(capture)
        await fanout.start()
        state.fanout = fanout

        # 백엔드 선택 (온라인 Gemini / 오프라인 로컬)
        if settings.backend == "local":
            state.backend = LocalBackend(fanout, state.loop, script=state.script)
            log.info("백엔드: local (Qwen3-ASR + TranslateGemma)")
        else:
            state.backend = GeminiBackend(settings)
            log.info("백엔드: gemini (온라인)")

        # 부팅 시 자동 방송 시작 여부 (AUTO_START=0 이면 방송 종료 상태로 시작)
        auto = os.getenv("AUTO_START", "1").strip().lower() not in ("0", "false", "no")
        state.broadcasting = auto
        # 초기 언어 = .env 의 TARGET_LANGUAGE 1개 (워커는 broadcasting 일 때만 기동)
        await apply_languages(
            [{"code": settings.target_language, "color": DEFAULT_COLORS[0]}]
        )
        if not auto:
            log.info("방송 종료 상태로 시작 (AUTO_START=0) — 운영자 화면에서 시작")

        heartbeat = asyncio.create_task(_usage_heartbeat())
        level_task = asyncio.create_task(_level_heartbeat())
        try:
            await asyncio.Event().wait()  # 종료될 때까지 대기
        finally:
            heartbeat.cancel()
            level_task.cancel()
            for code in list(state.workers):
                await state.workers.pop(code).stop()
            close = getattr(state.backend, "aclose", None)
            if close is not None:
                await close()
            await fanout.stop()


def _is_too_quiet(rms: float, *, online: bool, silent: bool) -> bool:
    """게이지엔 신호가 보이지만(silent 아님) 오프라인 STT 의 침묵 임계값
    (STT_SILENCE_RMS)에 못 미쳐 전사되지 않는 낮은 입력인지 판정한다.

    온라인(Gemini)은 자체 게인/노이즈 처리가 있어 이 임계값과 무관하므로
    오프라인일 때만 참이 된다. (예: BlackHole 컴퓨터 소리 볼륨이 낮을 때)
    """
    return (not online) and (not silent) and (rms < STT_SILENCE_RMS)


async def _level_heartbeat() -> None:
    """입력 레벨을 운영자 화면에 주기적으로 push (게이지용).

    장치를 골라도 소리가 실제로 들어오는지 화면만 봐서는 알 수 없었기 때문에
    추가했다(예: BlackHole 을 골랐지만 macOS 출력이 그쪽으로 가지 않는 경우).
    방송 중이 아니어도 보낸다 — 방송 시작 전에 연결을 점검하는 것이 목적이다.
    """
    while True:
        await asyncio.sleep(LEVEL_PUSH_SEC)
        if state.capture is None or not hub.has_operator:
            continue  # 볼 사람이 없으면 계산도 전송도 하지 않는다
        try:
            rms = state.capture.pop_level()
        except Exception:  # noqa: BLE001
            continue
        dbfs = rms_to_dbfs(rms)
        silent = dbfs <= SILENCE_DBFS
        online = state.backend is not None and state.backend.name == "gemini"
        too_quiet = _is_too_quiet(rms, online=online, silent=silent)
        await hub.send_operators(
            {
                "type": "level",
                "rms": round(rms, 5),
                "dbfs": round(dbfs, 1),
                "silent": silent,
                "too_quiet": too_quiet,
            }
        )


def _should_auto_stop(idle_sec: float, broadcasting: bool) -> bool:
    """무발화가 IDLE_STOP_MIN(분)을 넘고 방송 중이면 자동 종료 대상.

    IDLE_STOP_MIN=0 이면 항상 False(기능 비활성, 기본값).
    """
    return IDLE_STOP_MIN > 0 and broadcasting and idle_sec >= IDLE_STOP_MIN * 60


async def _usage_heartbeat() -> None:
    """주기적으로 경과시간·예상비용·무발화 상태를 운영자 화면에 push."""
    while True:
        await asyncio.sleep(15)
        now = time.monotonic()
        elapsed = now - state.started_at
        idle = now - state.last_speech_at
        n_lang = max(1, len(state.languages))
        online = state.backend is not None and state.backend.name == "gemini"
        est_cost = (elapsed / 60.0) * n_lang * COST_PER_MIN if online else 0.0
        await hub.broadcast(
            {
                "type": "usage",
                "elapsed_sec": int(elapsed),
                "idle_sec": int(idle),
                "est_cost": round(est_cost, 2),
                "online": online,
                "idle_warn": idle >= IDLE_WARN_MIN * 60,
            }
        )
        # 무발화 자동 방송 종료(옵션) — 끄는 걸 잊어 온라인 비용이 쌓이는 것을 막는다.
        if _should_auto_stop(idle, state.broadcasting):
            async with state.reconfig_lock:   # 다른 재구성과 경합 방지
                # 잠금 획득 사이에 발화가 있었을 수 있으니 다시 판정한다.
                if _should_auto_stop(time.monotonic() - state.last_speech_at, state.broadcasting):
                    log.info("무발화 %.1f분 초과 — 방송 자동 종료(IDLE_STOP_MIN)", IDLE_STOP_MIN)
                    await hub.broadcast({"type": "auto_stopped", "idle_min": IDLE_STOP_MIN})
                    await set_broadcast(False)


def _log_pipeline_failure(task: asyncio.Task) -> None:
    """파이프라인이 예외로 끝나면 반드시 로그에 남긴다.

    `create_task` 의 결과를 아무도 await 하지 않으면 예외가 조용히 사라진다.
    그러면 서버는 200 OK 로 응답하고 화면도 정상으로 보이는데 자막만 안 나와서
    원인을 찾을 수 없다(실제로 겪음 — 오디오 장치 미연결).
    """
    if task.cancelled():
        return  # 정상 종료 경로
    exc = task.exception()
    if exc is not None:
        log.error("⚠ 파이프라인이 중단되었습니다: %s", exc, exc_info=exc)
