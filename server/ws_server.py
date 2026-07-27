"""FastAPI + WebSocket 자막 서버 (메인 엔트리포인트).

구성:
  - 오디오 캡처 → (언어별) Gemini Live Translate 세션 → 자막 안정화 → push
  - 목표 언어를 1~3개까지 동시에 운용 (언어마다 별도 세션, 같은 오디오를 fan-out)
  - 송출 화면(/)        : 언어 수만큼 행을 나눠 표시 (행별 글자색 지정)
  - 운영자 화면(/operator): 한/영 전사 + 송출 제어(언어/색/리셋/종료/스타일/소스)
  - WebSocket(/ws)      : 서버→클라이언트 자막/상태 push, 클라이언트→서버 명령 수신

운영자 명령(client → server):
  {"cmd": "reset"}                              화면 리셋
  {"cmd": "set_output", "enabled": bool}        송출 종료/재개
  {"cmd": "set_style", "style": {...}}          폰트/배경/안여백 변경
  {"cmd": "set_languages", "languages": [...]}  목표 언어 목록 [{code,color}]
  {"cmd": "set_device", "device": int|str}      오디오 입력 장치 전환
  {"cmd": "list_devices"}                       장치 목록 새로고침

실행:
    python server/ws_server.py
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import socket
import tempfile
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response

from audio_input import (
    SILENCE_DBFS,
    AudioCapture,
    AudioFanout,
    input_devices,
    queue_chunks,
    rms_to_dbfs,
)
from config import Settings
from languages import LANGUAGES, VALID_CODES
from live_session import TranscriptEvent
from local_backend import SILENCE_RMS as STT_SILENCE_RMS
from local_backend import LocalBackend
from logging_setup import setup_logging
from sermon_script import ScriptCorrector
from subtitle_engine import RollingTranscript, SubtitleEngine
from transcript_logger import TranscriptLogger
from translation_backend import GeminiBackend, TranslationBackend

log = logging.getLogger("server")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
# 기동 시 운영자 접속 URL(토큰 포함)을 남기는 위치 — start.sh 가 읽는다(git 제외).
# ⚠️ 저장소 안에 두면 실수로 커밋되어 토큰이 공개될 수 있다(실제로 한 번 발생).
#    그래서 저장소 밖(OS 임시 디렉터리)에 저장한다 — git 에 들어갈 경로 자체가 없다.
RUNTIME_DIR = Path(tempfile.gettempdir()) / "translateviewer"
OPERATOR_URL_FILE = RUNTIME_DIR / "operator_url.txt"
# 설교 원고 저장 위치(재시작 후에도 유지). data/ 는 git 제외.
SCRIPT_PATH = Path(__file__).resolve().parent.parent / "data" / "sermons" / "current_script.txt"

# 온라인(Gemini) 분당 단가(USD, 입력+출력 전사 기준) — 예상 비용 표시용
COST_PER_MIN = float(os.getenv("COST_PER_MIN", "0.037"))
# 입력 레벨 게이지 전송 주기(초). 5회/초면 말소리 움직임이 자연스럽게 보인다.
LEVEL_PUSH_SEC = float(os.getenv("LEVEL_PUSH_SEC", "0.2"))
# 무발화 이 시간(분) 이상이면 "끄는 걸 잊지 않았나요?" 경고
IDLE_WARN_MIN = float(os.getenv("IDLE_WARN_MIN", "5"))
# 무발화 이 시간(분) 이상이면 방송을 '자동 종료'해 온라인 비용을 막는다.
# 0=비활성(기본). 예배 중 오종료를 막기 위해 기본은 꺼두고, 켤 때도 넉넉히 잡는다.
IDLE_STOP_MIN = float(os.getenv("IDLE_STOP_MIN", "0"))
# 한 WebSocket 연결에서 허용하는 인증 실패 횟수(초과 시 연결 종료 — 브루트포스 차단)
MAX_AUTH_FAILURES = 5

# ── 남용 방지 상한 (H-3 / H-4) ─────────────────────────────────
# 운영 명령 연타로 세션 재시작 스톰·과금 급증이 생기는 것을 막는 쿨다운(초).
COMMAND_COOLDOWN_SEC = float(os.getenv("COMMAND_COOLDOWN_SEC", "2"))
# 백엔드 전환은 모델 로딩이 있어 더 길게 잡는다.
BACKEND_COOLDOWN_SEC = float(os.getenv("BACKEND_COOLDOWN_SEC", "10"))
# 쿨다운을 적용할 명령(무해한 reset·list_devices 등은 제외)
_COOLDOWN_COMMANDS = {
    "set_languages", "set_backend", "set_broadcast", "set_device", "set_script",
}
# 설교 원고 최대 길이(자). 일반 설교 원고는 1~2만 자 수준.
MAX_SCRIPT_CHARS = int(os.getenv("MAX_SCRIPT_CHARS", "100000"))
# 색상 형식(#RGB / #RRGGBB) — 임의 문자열이 스타일 상태에 들어가는 것을 막는다
_HEX_COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")
# 동시 WebSocket 연결 상한(교인 폰 다수 접속 고려)
MAX_WS_CLIENTS = int(os.getenv("MAX_WS_CLIENTS", "100"))
# QR 텍스트 최대 길이(M-3) — 임의 QR 생성 오픈프록시·DoS 방지. URL 용도로 충분.
MAX_QR_TEXT_CHARS = int(os.getenv("MAX_QR_TEXT_CHARS", "512"))
# WebSocket 메시지 크기 상한(바이트) — 원고 10만 자(UTF-8 최대 3바이트) + 여유
WS_MAX_MESSAGE_BYTES = int(os.getenv("WS_MAX_MESSAGE_BYTES", str(512 * 1024)))

# 송출 화면 공유 스타일 (글자색은 언어별로 따로 지정하므로 여기엔 없음)
DEFAULT_STYLE: dict = {
    "fontSize": 4.0,       # vw 단위 글자 크기
    "bgColor": "#000000",  # 화면 전체 배경색 (검정 / 그린스크린 등)
    "padding": 4.0,        # 화면 테두리에서의 안여백 (vw)
    "region": "full",      # 자막 영역: full(전체) / bottom(하단 밴드) / top(상단 밴드)
    "maxLines": 0,         # 언어별 최대 줄 수 (0=제한없음). 예: 2 → 항상 2줄
}

# 언어 정의는 languages.py 단일 출처 사용
LABELS: dict[str, str] = {item["code"]: item["label"] for item in LANGUAGES}

# 언어 슬롯별 기본 글자색 (1번/2번/3번)
DEFAULT_COLORS = ["#ffffff", "#ffd54a", "#5ad1ff"]
MAX_LANGUAGES = 3


hub: "Hub"


class Hub:
    """연결된 모든 WebSocket 클라이언트에 이벤트를 브로드캐스트."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        # 운영자 인증을 마친 연결. 입력 레벨처럼 자주(≈5회/초) 갱신되는 정보는
        # 교인 폰까지 보내면 대역폭 낭비라 이쪽에만 보낸다.
        self._operators: set[WebSocket] = set()

    @property
    def is_full(self) -> bool:
        """동시 연결 상한 도달 여부(H-4) — 무한 연결로 자원이 고갈되는 것을 막는다."""
        return len(self._clients) >= MAX_WS_CLIENTS

    async def register(self, ws: WebSocket) -> None:
        self._clients.add(ws)

    async def unregister(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        self._operators.discard(ws)

    def mark_operator(self, ws: WebSocket) -> None:
        """운영자 인증을 마친 연결로 표시."""
        self._operators.add(ws)

    @property
    def has_operator(self) -> bool:
        return bool(self._operators)

    async def send_operators(self, payload: dict) -> None:
        """운영자 화면에만 전송(교인 폰·송출 화면 제외)."""
        message = json.dumps(payload, ensure_ascii=False)
        for ws in list(self._operators):
            try:
                await ws.send_text(message)
            except Exception:  # noqa: BLE001
                await self.unregister(ws)

    async def broadcast(self, payload: dict) -> None:
        message = json.dumps(payload, ensure_ascii=False)
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_text(message)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            await self.unregister(ws)


hub = Hub()


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


state = AppState()


def _is_hex_color(value: object) -> bool:
    """#RGB / #RRGGBB 형식인지 검사 (임의 길이 문자열이 상태에 들어가는 것을 막는다)."""
    return (
        isinstance(value, str)
        and _HEX_COLOR_RE.fullmatch(value) is not None
    )


def _sanitize_style(raw: object) -> dict:
    """set_style 입력을 화이트리스트로 검증 (M-2).

    기존에는 임의 키를 그대로 상태에 병합하고 색상 길이도 무제한이어서,
    쓰레기 값이 모든 클라이언트로 전파될 수 있었다. 허용된 키·타입·범위만 통과시킨다.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict = {}

    size = raw.get("fontSize")
    if isinstance(size, (int, float)) and not isinstance(size, bool):
        out["fontSize"] = min(max(float(size), 1.0), 20.0)

    pad = raw.get("padding")
    if isinstance(pad, (int, float)) and not isinstance(pad, bool):
        out["padding"] = min(max(float(pad), 0.0), 30.0)

    if _is_hex_color(raw.get("bgColor")):
        out["bgColor"] = raw["bgColor"]

    region = raw.get("region")
    if region in ("full", "bottom", "top"):
        out["region"] = region

    lines = raw.get("maxLines")
    if isinstance(lines, int) and not isinstance(lines, bool):
        out["maxLines"] = min(max(lines, 0), 10)

    return out


def _sanitize_languages(raw: object) -> list[dict]:
    """입력 언어 목록을 검증·정리. 최대 3개, 코드 중복 제거, 색 기본값 보정."""
    cleaned: list[dict] = []
    seen: set[str] = set()
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            code = entry.get("code")
            if code not in VALID_CODES or code in seen:
                continue
            color = entry.get("color")
            if not _is_hex_color(color):
                color = DEFAULT_COLORS[len(cleaned) % len(DEFAULT_COLORS)]
            cleaned.append({"code": code, "color": color})
            seen.add(code)
            if len(cleaned) >= MAX_LANGUAGES:
                break
    if not cleaned:  # 최소 1개 보장
        cleaned.append({"code": "en", "color": DEFAULT_COLORS[0]})
    return cleaned


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()  # 어떤 실행 경로로 뜨든 로깅이 켜지도록 보장(중복 호출은 무시)
    settings = Settings.load()
    # 운영자 접속 URL(토큰 포함)을 로컬 파일로 남긴다 — start.sh 가 읽어 브라우저를 연다.
    # 토큰이 담기므로 소유자만 읽을 수 있게 권한을 제한하고 git 에서도 제외한다.
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        url = f"http://localhost:{settings.ws_port}/operator"
        if settings.operator_token:
            url += f"?token={settings.operator_token}"
        OPERATOR_URL_FILE.write_text(url, encoding="utf-8")
        OPERATOR_URL_FILE.chmod(0o600)
    except Exception as exc:  # noqa: BLE001
        log.warning("운영자 URL 파일 기록 실패(무시): %s", exc)

    if settings.token_autogenerated:
        # 토큰이 없으면 자동 생성되므로 "인증 없음" 상태가 존재하지 않는다.
        # 운영자는 아래 URL 로 접속해야 조작할 수 있다.
        # 재사용/신규를 구분해 안내한다("재사용인데 매번 새로 만드는 듯" 오해 방지).
        head = (
            "저장된 운영자 토큰을 재사용합니다"
            if settings.token_reused
            else "운영자 토큰이 자동 생성되었습니다"
        )
        print(
            f"\n[server] 🔐 {head} (LAN 에 열려 있음).\n"
            f"          운영자 화면: http://localhost:{settings.ws_port}"
            f"/operator?token={settings.operator_token}\n"
            "          고정 토큰을 쓰려면 .env 에 OPERATOR_TOKEN 을 설정하세요.\n"
        )
    task = asyncio.create_task(pipeline(settings))
    log.info("파이프라인 시작 — 모델: %s", settings.model)
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def _security_headers(request, call_next):  # noqa: ANN001, ANN201
    """기본 보안 헤더(L-1).

    - X-Frame-Options: 다른 사이트가 이 화면을 iframe 으로 감싸 오조작을 유도하는 것을 막음
    - X-Content-Type-Options: MIME 스니핑 방지
    - Referrer-Policy: 토큰이 담긴 URL 이 외부로 새어나가지 않도록 최소화
    """
    response = await call_next(request)
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    # 화면(HTML)은 캐시하지 않는다. 캐시되면 코드를 고쳐도 브라우저가 옛 화면을
    # 재사용해 "기능이 사라진 것처럼" 보인다(실제로 발생). QR/아이콘은 캐시 허용.
    if request.url.path in ("/", "/operator", "/m", "/qr-view"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        # Starlette 의 MutableHeaders 는 pop() 이 없어 del 로 제거한다.
        for h in ("etag", "last-modified"):
            if h in response.headers:
                del response.headers[h]
    return response


@app.get("/")
async def overlay() -> FileResponse:
    return FileResponse(WEB_DIR / "subtitle-overlay" / "index.html")


@app.get("/operator")
async def operator() -> FileResponse:
    return FileResponse(WEB_DIR / "operator" / "index.html")


@app.get("/manifest.webmanifest")
async def manifest() -> dict:
    """송출 화면을 앱(PWA)으로 설치 가능하게 — 주소줄 없는 창으로 열림."""
    return {
        "name": "Sermon Subtitle",
        "short_name": "Subtitle",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",   # 타이틀 바 O, 주소줄 X
        "background_color": "#000000",
        "theme_color": "#000000",
        "icons": [
            {"src": "/subtitle-overlay/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/subtitle-overlay/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }


@app.get("/subtitle-overlay/{fname}")
async def overlay_asset(fname: str) -> FileResponse:
    """송출 화면 정적 자원(아이콘 등)."""
    path = (WEB_DIR / "subtitle-overlay" / fname).resolve()
    if path.parent != (WEB_DIR / "subtitle-overlay").resolve() or not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path)


@app.get("/m")
async def mobile() -> FileResponse:
    """교인용 모바일 자막 — 폰에서 언어를 골라 그 언어만 본다(읽기 전용)."""
    return FileResponse(WEB_DIR / "mobile" / "index.html")


@app.get("/qr-view")
async def qr_view() -> FileResponse:
    """QR 코드를 크게 보여주는 별도 창(운영자가 팝업으로 연다)."""
    return FileResponse(WEB_DIR / "qr-view" / "index.html")


def _lan_ips() -> tuple[str, list[str]]:
    """이 컴퓨터의 LAN IPv4 를 검출. (primary, 후보 목록) 반환. 오프라인에서도 동작."""
    primary = "127.0.0.1"
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # 패킷 전송 없이 기본 경로의 로컬 IP 만 확인
        primary = s.getsockname()[0]
    except Exception:  # noqa: BLE001
        pass
    finally:
        s.close()
    candidates = {primary}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                candidates.add(ip)
    except Exception:  # noqa: BLE001
        pass
    ordered = [primary] + [c for c in sorted(candidates) if c != primary]
    return primary, ordered


@app.get("/lan-info")
async def lan_info() -> dict:
    """모바일 접속 주소(LAN IP) 안내 — 운영자 화면의 'QR' 기능이 사용."""
    primary, candidates = _lan_ips()
    port = state.settings.ws_port if state.settings else 8000
    return {
        "primary": primary,
        "port": port,
        "mobile_url": f"http://{primary}:{port}/m",
        "candidates": [
            {"ip": ip, "mobile_url": f"http://{ip}:{port}/m"} for ip in candidates
        ],
    }


@app.get("/qr.svg")
async def qr_svg(text: str) -> Response:
    """주어진 텍스트(URL)의 QR 코드를 SVG 로 생성해 반환 (로컬 생성, 인터넷 불필요).

    M-3: 길이 상한을 둔다. 상한이 없으면 임의 텍스트로 QR 을 대량 생성하게 만들어
    (오픈프록시처럼 악용) CPU 를 소모시킬 수 있다.
    """
    import io

    import segno

    if not text or len(text) > MAX_QR_TEXT_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"text 는 1~{MAX_QR_TEXT_CHARS}자여야 합니다.",
        )

    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="svg", scale=6, border=2, dark="#000", light="#fff")
    return Response(content=buf.getvalue(), media_type="image/svg+xml")


@app.get("/health")
async def health() -> dict:
    """모니터링용 상태 엔드포인트."""
    return {
        "status": "ok",
        "backend": state.backend.name if state.backend else None,
        "languages": [item["code"] for item in state.languages],
        "output_enabled": state.output_enabled,
        "audio_device": state.capture.current_device if state.capture else None,
        "clients": len(hub._clients),
    }


def _cooldown_remaining(name: str) -> float:
    """쿨다운이 남아 있으면 남은 초, 아니면 0 (H-3).

    운영 명령을 연타하면 워커·세션이 반복 재시작되어 지연·과금이 급증한다.
    무해한 명령(reset, list_devices 등)은 대상에서 제외한다.
    """
    if name not in _COOLDOWN_COMMANDS:
        return 0.0
    window = BACKEND_COOLDOWN_SEC if name == "set_backend" else COMMAND_COOLDOWN_SEC
    last = state.last_command_at.get(name, 0.0)
    elapsed = time.monotonic() - last
    return max(0.0, window - elapsed)


async def _handle_command(cmd: dict) -> None:
    """운영자 화면에서 온 명령을 처리하고 결과를 전체에 브로드캐스트."""
    name = cmd.get("cmd")

    # 남용 방지: 같은 명령을 짧은 간격으로 반복하면 무시하고 운영자에게 알린다.
    remaining = _cooldown_remaining(name)
    if remaining > 0:
        await hub.broadcast(
            {
                "type": "command_throttled",
                "cmd": name,
                "retry_after": round(remaining, 1),
            }
        )
        return
    if name in _COOLDOWN_COMMANDS:
        state.last_command_at[name] = time.monotonic()

    if name == "reset":
        state.reset_all()
        await hub.broadcast({"type": "reset"})
    elif name == "set_output":
        state.output_enabled = bool(cmd.get("enabled", True))
        await hub.broadcast({"type": "output_state", "enabled": state.output_enabled})
    elif name == "set_style":
        # 화이트리스트 검증(M-2): 허용된 키·타입·범위만 반영한다.
        incoming = _sanitize_style(cmd.get("style"))
        if incoming:
            state.style = {**state.style, **incoming}
            await hub.broadcast({"type": "style", "style": state.style})
    elif name == "set_languages":
        async with state.reconfig_lock:   # 재구성 동시 실행 방지
            languages = _sanitize_languages(cmd.get("languages"))
            await apply_languages(languages)
            await hub.broadcast({"type": "reset"})
            await hub.broadcast({"type": "layout", "layout": state.layout()})
    elif name == "set_broadcast":
        async with state.reconfig_lock:
            await set_broadcast(bool(cmd.get("active", True)))
    elif name == "set_backend":
        async with state.reconfig_lock:
            await switch_backend(cmd.get("backend", ""))
    elif name == "set_device":
        async with state.reconfig_lock:
            await _switch_device(cmd.get("device"))
    elif name == "list_devices":
        await hub.broadcast(
            {
                "type": "device_list",
                "devices": input_devices(),
                "current": state.capture.current_device if state.capture else None,
            }
        )
    elif name == "set_script":
        await _set_script(cmd.get("text", ""))


async def _set_script(text: str) -> None:
    """설교 원고를 설정 — 교정 용어 추출 + 저장 + 상태 전파."""
    if not isinstance(text, str):
        text = ""
    # 길이 상한(H-4): 과도한 원고로 메모리·디스크·교정 연산이 폭증하는 것을 막는다.
    if len(text) > MAX_SCRIPT_CHARS:
        log.warning(
            "원고가 상한을 초과해 잘라 적용합니다 (%d > %d자)",
            len(text),
            MAX_SCRIPT_CHARS,
        )
        text = text[:MAX_SCRIPT_CHARS]
        await hub.broadcast(
            {"type": "script_truncated", "limit": MAX_SCRIPT_CHARS}
        )
    n = state.script.set_script(text)
    try:
        SCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCRIPT_PATH.write_text(text, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        log.warning("원고 저장 실패(무시): %s", exc)
    log.info("설교 원고 적용 — 교정 용어 %d개", n)
    await hub.broadcast(
        {"type": "script_state", "terms": n, "chars": len(text)}
    )


async def _switch_device(device) -> None:  # noqa: ANN001
    """오디오 입력 장치를 교체하고 결과를 브로드캐스트."""
    if state.capture is None:
        return
    if isinstance(device, str) and device.isdigit():
        device = int(device)
    try:
        state.capture.set_device(device)
        await hub.broadcast(
            {"type": "device_state", "current": state.capture.current_device}
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("장치 전환 실패: %s", exc)
        await hub.broadcast({"type": "device_error", "message": str(exc)})


def _public_init() -> dict:
    """인증 없이 보내도 안전한 초기 상태(송출 화면·교인 폰이 쓰는 필드만).

    M-1: 예전에는 장치 목록·백엔드·용어 개수까지 모두 보냈는데, 이는 주소만 아는
    사람에게 내부 구성을 노출한다. 화면 동작에 필요한 값만 남긴다.
    """
    return {
        "type": "init",
        "style": state.style,
        "output_enabled": state.output_enabled,
        "layout": state.layout(),
        "languages": LANGUAGES,      # 선택 가능한 언어 목록(모바일에서 표시)
    }


def _operator_init() -> dict:
    """운영자 인증 후에만 보내는 내부 정보(장치명·백엔드·원고 등)."""
    return {
        "type": "operator_init",
        "broadcasting": state.broadcasting,
        "backend": state.backend.name if state.backend else "unknown",
        "default_colors": DEFAULT_COLORS,
        "max_languages": MAX_LANGUAGES,
        "devices": input_devices(),
        "current_device": state.capture.current_device if state.capture else None,
        "script_terms": len(state.script.terms),
    }


def _origin_allowed(ws: WebSocket) -> bool:
    """WebSocket 핸드셰이크의 Origin 을 검증(CSWSH 방지).

    WebSocket 은 브라우저 동일출처정책 대상이 아니라서, 검사하지 않으면 임의의 외부
    웹페이지가 교회 LAN 의 이 서버에 붙어 명령을 보내거나 전사를 도청할 수 있다.

    이 앱의 화면(/, /operator, /m, /qr-view)은 모두 **이 서버가 서빙**하므로,
    Origin 의 host 가 요청이 들어온 host(=브라우저가 접속한 주소)와 같으면 허용한다.
    → 폰이 LAN IP 로 접속하는 모바일 자막도 그대로 동작한다.
    Origin 이 아예 없는 경우(curl, OBS 등 비브라우저)는 SOP 우회 위험이 없어 허용한다.
    허용 목록을 추가하려면 ALLOWED_ORIGINS(콤마 구분) 환경변수를 쓴다.
    """
    origin = ws.headers.get("origin")
    if not origin:
        return True  # 비브라우저 클라이언트(브라우저가 아니면 CSWSH 대상 아님)

    extra = {
        o.strip().rstrip("/")
        for o in os.getenv("ALLOWED_ORIGINS", "").split(",")
        if o.strip()
    }
    if origin.rstrip("/") in extra:
        return True

    try:
        origin_host = urlparse(origin).hostname
    except ValueError:
        return False
    if not origin_host:
        return False

    # 브라우저가 접속한 호스트(Host 헤더)와 같은 출처면 허용
    request_host = (ws.headers.get("host") or "").rsplit(":", 1)[0]
    if request_host and origin_host == request_host:
        return True
    # 로컬 접속은 항상 허용
    return origin_host in ("localhost", "127.0.0.1", "::1")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    if not _origin_allowed(ws):
        log.warning("⚠ 차단된 Origin 의 WebSocket 접속: %s", ws.headers.get("origin"))
        await ws.close(code=4403)
        return
    if hub.is_full:
        # 동시 연결 상한(H-4) — 자원 고갈 방지
        log.warning("⚠ 연결 상한(%d) 도달 — 새 접속 거부", MAX_WS_CLIENTS)
        await ws.close(code=4429)
        return
    await ws.accept()
    await hub.register(ws)
    auth_failures = 0
    operator_synced = False
    # 새 연결을 현재 상태로 동기화.
    # M-1: 인증 없는 연결(교인 폰·송출 화면)에는 **공용 필드만** 보낸다.
    #      장치명·백엔드·용어 개수 같은 내부 정보는 운영자 인증 후에 전달한다.
    await ws.send_text(json.dumps(_public_init(), ensure_ascii=False))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                cmd = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(cmd, dict) and "cmd" in cmd:
                token = state.settings.operator_token if state.settings else ""
                supplied = cmd.get("token")
                # 상수시간 비교(타이밍 공격 방지). 토큰이 있으면 항상 검사한다.
                ok = bool(token) and isinstance(supplied, str) and hmac.compare_digest(
                    supplied, token
                )
                # 인증이 확인되면(또는 토큰 미사용 환경이면) 운영자 정보를 1회 전달
                if (ok or not token) and not operator_synced:
                    operator_synced = True
                    hub.mark_operator(ws)
                    await ws.send_text(
                        json.dumps(_operator_init(), ensure_ascii=False)
                    )
                if token and not ok:
                    auth_failures += 1
                    await ws.send_text(
                        json.dumps(
                            {"type": "auth_error", "message": "운영자 토큰이 필요합니다."},
                            ensure_ascii=False,
                        )
                    )
                    # 브루트포스 차단: 실패가 누적되면 연결을 끊는다.
                    if auth_failures >= MAX_AUTH_FAILURES:
                        log.warning("⚠ 인증 실패 누적 — WebSocket 연결 종료")
                        await ws.close(code=4401)
                        break
                    await asyncio.sleep(0.5)  # 시도 속도 저하
                    continue
                await _handle_command(cmd)
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unregister(ws)


if __name__ == "__main__":
    import uvicorn

    setup_logging()
    cfg = Settings.load()
    uvicorn.run(
        "ws_server:app",
        host=cfg.ws_host,
        port=cfg.ws_port,
        reload=False,
        # WebSocket 메시지 크기 상한(H-4) — 과대 메시지로 메모리 고갈 방지
        ws_max_size=WS_MAX_MESSAGE_BYTES,
    )
