"""정보 노출·엔드포인트 보호 테스트 (M-1 · M-3 · L-1)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

TOKEN = "expo-token-abcdef123456"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OPERATOR_TOKEN", TOKEN)
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("WS_HOST", "0.0.0.0")

    import ws_server

    async def fake_pipeline(settings):
        ws_server.state.settings = settings
        ws_server.state.loop = asyncio.get_running_loop()
        ws_server.state.languages = [{"code": "en", "color": "#ffffff"}]
        await asyncio.Event().wait()

    monkeypatch.setattr(ws_server, "pipeline", fake_pipeline)
    ws_server.state.last_command_at.clear()
    with TestClient(ws_server.app) as c:
        yield c


# ── M-1: 인증 전 내부정보 미노출 ────────────────────────────────

_OPERATOR_ONLY = ("devices", "current_device", "backend", "script_terms")


def test_인증_없는_init_에는_내부정보가_없다(client):
    """주소만 아는 사람(교인 폰 등)에게 장치명·백엔드가 노출되지 않아야 한다."""
    with client.websocket_connect("/ws") as ws:
        init = ws.receive_json()
        assert init["type"] == "init"
        for key in _OPERATOR_ONLY:
            assert key not in init, f"인증 전에 노출되면 안 됨: {key}"


def test_공용_init_은_화면_동작에_필요한_필드를_포함한다(client):
    """송출·모바일 화면이 쓰는 필드는 그대로 있어야 한다(회귀 방지)."""
    with client.websocket_connect("/ws") as ws:
        init = ws.receive_json()
        for key in ("style", "output_enabled", "layout", "languages"):
            assert key in init, f"화면 동작에 필요: {key}"


def test_토큰_인증_후에는_운영자_정보를_받는다(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # 공용 init
        ws.send_json({"cmd": "list_devices", "token": TOKEN})
        # operator_init 이 도착해야 한다(순서는 구현에 따라 다를 수 있어 몇 개 확인)
        seen = {}
        for _ in range(3):
            msg = ws.receive_json()
            if msg.get("type") == "operator_init":
                seen = msg
                break
        assert seen, "인증 후 operator_init 을 받아야 함"
        for key in _OPERATOR_ONLY:
            assert key in seen, f"운영자 정보에 포함돼야 함: {key}"


def test_틀린_토큰이면_운영자_정보를_받지_못한다(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"cmd": "list_devices", "token": "wrong"})
        msg = ws.receive_json()
        assert msg["type"] == "auth_error"


# ── M-3: /qr.svg 길이 상한 ──────────────────────────────────────


def test_정상_길이_QR_은_생성된다(client):
    r = client.get("/qr.svg", params={"text": "http://192.168.0.10:8000/m"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg")


def test_과도하게_긴_QR_텍스트는_거부된다(client):
    import ws_server

    r = client.get(
        "/qr.svg", params={"text": "A" * (ws_server.MAX_QR_TEXT_CHARS + 1)}
    )
    assert r.status_code == 400


def test_빈_QR_텍스트는_거부된다(client):
    assert client.get("/qr.svg", params={"text": ""}).status_code == 400


# ── L-1: 보안 헤더 ──────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/", "/operator", "/m", "/health"])
def test_보안_헤더가_설정된다(client, path):
    r = client.get(path)
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    # 토큰이 담긴 URL 이 외부로 새지 않도록
    assert r.headers.get("Referrer-Policy") == "no-referrer"


# ── 화면 HTML 캐시 방지 (실제로 겪은 회귀) ─────────────────────


@pytest.mark.parametrize("path", ["/", "/operator", "/m", "/qr-view"])
def test_화면_HTML_은_캐시되지_않는다(client, path):
    """캐시되면 코드를 고쳐도 브라우저가 옛 화면을 재사용해 '기능이 사라진 것처럼'
    보인다(실제 발생: operator_init 핸들러가 없는 옛 JS 가 재사용되어 장치 목록·
    백엔드 배지가 비어 있었음)."""
    r = client.get(path)
    assert r.status_code == 200
    assert "no-store" in r.headers.get("Cache-Control", "")
    # 조건부 요청으로 304 를 받지 않도록 검증자를 제거해야 한다
    assert "etag" not in {k.lower() for k in r.headers}
    assert "last-modified" not in {k.lower() for k in r.headers}


def test_QR_은_캐시를_허용한다(client):
    """자막 화면과 달리 QR 이미지는 자주 바뀌지 않아 캐시해도 된다."""
    r = client.get("/qr.svg", params={"text": "http://192.168.0.10:8000/m"})
    assert r.status_code == 200
    assert "no-store" not in r.headers.get("Cache-Control", "")
