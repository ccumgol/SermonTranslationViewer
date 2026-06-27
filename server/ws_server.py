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
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from audio_input import AudioCapture, AudioFanout, input_devices, queue_chunks
from config import Settings
from live_session import TranscriptEvent
from local_backend import LocalBackend
from subtitle_engine import RollingTranscript, SubtitleEngine
from translation_backend import GeminiBackend, TranslationBackend

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# 송출 화면 공유 스타일 (글자색은 언어별로 따로 지정하므로 여기엔 없음)
DEFAULT_STYLE: dict = {
    "fontSize": 4.0,       # vw 단위 글자 크기
    "bgColor": "#000000",  # 화면 전체 배경색 (검정 / 그린스크린 등)
    "padding": 4.0,        # 화면 테두리에서의 안여백 (vw)
}

# 운영자 화면에 노출할 목표 언어 목록 (실제 API 로 검증된 코드)
LANGUAGES: list[dict] = [
    {"code": "en", "label": "English 영어"},
    {"code": "ja", "label": "日本語 일본어"},
    {"code": "zh-CN", "label": "中文 중국어"},
    {"code": "es", "label": "Español 스페인어"},
    {"code": "vi", "label": "Tiếng Việt 베트남어"},
    {"code": "fr", "label": "Français 프랑스어"},
    {"code": "ru", "label": "Русский 러시아어"},
    {"code": "ko", "label": "한국어"},
]
LABELS: dict[str, str] = {item["code"]: item["label"] for item in LANGUAGES}
VALID_CODES = set(LABELS)

# 언어 슬롯별 기본 글자색 (1번/2번/3번)
DEFAULT_COLORS = ["#ffffff", "#ffd54a", "#5ad1ff"]
MAX_LANGUAGES = 3


hub: "Hub"


class Hub:
    """연결된 모든 WebSocket 클라이언트에 이벤트를 브로드캐스트."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def register(self, ws: WebSocket) -> None:
        self._clients.add(ws)

    async def unregister(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

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
        self.primary = False           # 한국어(입력) 전사를 대표로 송출할지
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
        if ev.kind == "source":
            # 입력(설교) 전사는 대표 워커 하나만 송출 (중복 방지)
            if self.primary and state.source_roller is not None:
                sub = state.source_roller.add_delta(ev.text, ev.is_final)
                self._loop.create_task(
                    hub.broadcast(
                        {"type": "source", "text": sub.text, "final": sub.is_final}
                    )
                )
            return
        sub = self._engine.add(ev.text, ev.is_final)
        self.last_text = sub.text
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
    source_roller: RollingTranscript | None = None
    capture: AudioCapture | None = None
    fanout: AudioFanout | None = None
    settings: Settings | None = None
    backend: TranslationBackend | None = None
    loop: asyncio.AbstractEventLoop | None = None
    # 현재 활성 언어 목록: [{"code","color"}] (순서 = 행 순서)
    languages: list[dict] = field(default_factory=list)
    workers: dict[str, LangWorker] = field(default_factory=dict)

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
            if not isinstance(color, str) or not color.startswith("#"):
                color = DEFAULT_COLORS[len(cleaned) % len(DEFAULT_COLORS)]
            cleaned.append({"code": code, "color": color})
            seen.add(code)
            if len(cleaned) >= MAX_LANGUAGES:
                break
    if not cleaned:  # 최소 1개 보장
        cleaned.append({"code": "en", "color": DEFAULT_COLORS[0]})
    return cleaned


async def apply_languages(languages: list[dict]) -> None:
    """활성 언어 목록을 적용 — 필요한 워커를 시작/중지하고 레이아웃 갱신."""
    assert state.backend is not None and state.fanout is not None
    codes = [item["code"] for item in languages]

    # 더 이상 필요 없는 워커 중지
    for code in list(state.workers):
        if code not in codes:
            await state.workers.pop(code).stop()

    # 새 워커 시작
    for item in languages:
        code = item["code"]
        if code not in state.workers:
            worker = LangWorker(
                state.backend, state.fanout, code, state.loop
            )
            state.workers[code] = worker
            worker.start()

    # 첫 번째 언어를 대표(primary)로 — 한국어 입력 전사 송출 담당
    for index, item in enumerate(languages):
        state.workers[item["code"]].primary = index == 0

    state.languages = languages
    if state.source_roller is not None:
        state.source_roller.reset()


async def pipeline(settings: Settings) -> None:
    """오디오 캡처 + fan-out + 초기 언어 워커 기동."""
    state.settings = settings
    state.loop = asyncio.get_running_loop()
    state.source_roller = RollingTranscript()

    async with AudioCapture(settings.audio_input_device) as capture:
        state.capture = capture
        fanout = AudioFanout(capture)
        await fanout.start()
        state.fanout = fanout

        # 백엔드 선택 (온라인 Gemini / 오프라인 로컬)
        if settings.backend == "local":
            state.backend = LocalBackend(fanout, state.loop)
            print("[server] 백엔드: local (Qwen3-ASR + TranslateGemma)")
        else:
            state.backend = GeminiBackend(settings)
            print("[server] 백엔드: gemini (온라인)")

        # 초기 언어 = .env 의 TARGET_LANGUAGE 1개
        await apply_languages(
            [{"code": settings.target_language, "color": DEFAULT_COLORS[0]}]
        )

        try:
            await asyncio.Event().wait()  # 종료될 때까지 대기
        finally:
            for code in list(state.workers):
                await state.workers.pop(code).stop()
            close = getattr(state.backend, "aclose", None)
            if close is not None:
                await close()
            await fanout.stop()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.load()
    task = asyncio.create_task(pipeline(settings))
    print(f"[server] 파이프라인 시작 — 모델: {settings.model}")
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def overlay() -> FileResponse:
    return FileResponse(WEB_DIR / "subtitle-overlay" / "index.html")


@app.get("/operator")
async def operator() -> FileResponse:
    return FileResponse(WEB_DIR / "operator" / "index.html")


async def _handle_command(cmd: dict) -> None:
    """운영자 화면에서 온 명령을 처리하고 결과를 전체에 브로드캐스트."""
    name = cmd.get("cmd")
    if name == "reset":
        state.reset_all()
        await hub.broadcast({"type": "reset"})
    elif name == "set_output":
        state.output_enabled = bool(cmd.get("enabled", True))
        await hub.broadcast({"type": "output_state", "enabled": state.output_enabled})
    elif name == "set_style":
        incoming = cmd.get("style", {})
        if isinstance(incoming, dict):
            state.style = {**state.style, **incoming}
            await hub.broadcast({"type": "style", "style": state.style})
    elif name == "set_languages":
        languages = _sanitize_languages(cmd.get("languages"))
        await apply_languages(languages)
        await hub.broadcast({"type": "reset"})
        await hub.broadcast({"type": "layout", "layout": state.layout()})
    elif name == "set_device":
        await _switch_device(cmd.get("device"))
    elif name == "list_devices":
        await hub.broadcast(
            {
                "type": "device_list",
                "devices": input_devices(),
                "current": state.capture.current_device if state.capture else None,
            }
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
        print(f"[server] 장치 전환 실패: {exc}")
        await hub.broadcast({"type": "device_error", "message": str(exc)})


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    await hub.register(ws)
    # 새 연결을 현재 상태로 동기화
    await ws.send_text(
        json.dumps(
            {
                "type": "init",
                "style": state.style,
                "output_enabled": state.output_enabled,
                "backend": state.backend.name if state.backend else "unknown",
                "languages": LANGUAGES,          # 선택 가능한 전체 언어
                "layout": state.layout(),        # 현재 활성 언어(행) 구성
                "default_colors": DEFAULT_COLORS,
                "max_languages": MAX_LANGUAGES,
                "devices": input_devices(),
                "current_device": (
                    state.capture.current_device if state.capture else None
                ),
            },
            ensure_ascii=False,
        )
    )
    try:
        while True:
            raw = await ws.receive_text()
            try:
                cmd = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(cmd, dict) and "cmd" in cmd:
                await _handle_command(cmd)
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unregister(ws)


if __name__ == "__main__":
    import uvicorn

    cfg = Settings.load()
    uvicorn.run("ws_server:app", host=cfg.ws_host, port=cfg.ws_port, reload=False)
