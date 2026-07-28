"""남용 방지 상한(H-3 쿨다운 · H-4 크기/연결 상한) 테스트.

`test_ws_security.py` 와 같은 방식으로 `pipeline` 을 모킹해 하드웨어 없이 검증한다.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

TOKEN = "limits-token-abcdef123456"


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
    # 각 테스트가 이전 쿨다운 상태에 영향받지 않도록 초기화
    ws_server.state.last_command_at.clear()
    with TestClient(ws_server.app) as c:
        yield c


# ── H-3: 명령 쿨다운 ────────────────────────────────────────────


def test_같은_명령_연타는_쿨다운으로_차단된다(client, monkeypatch):
    """첫 명령은 통과하고, 곧바로 반복하면 쿨다운에 걸려야 한다.

    set_script 를 쓰는 이유: 워커 재기동 같은 부작용이 없고 **항상 응답**하므로
    (script_state) 테스트가 무한 대기하지 않는다.
    """
    import commands  # 쿨다운 로직은 commands 모듈로 분리됨

    monkeypatch.setattr(commands, "_COOLDOWN_COMMANDS", {"set_script"})
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # init
        first = _send(ws, {"cmd": "set_script", "text": "첫 번째"})
        assert first["type"] == "script_state", "첫 명령은 통과해야 함"

        # 곧바로 재시도 → 쿨다운
        assert _send(ws, {"cmd": "set_script", "text": "두 번째"})["type"] == (
            "command_throttled"
        )


def test_쿨다운_대상이_아닌_명령은_연타해도_통과한다(client):
    """reset 같은 무해한 명령은 막지 않는다(운영 편의)."""
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        for _ in range(3):
            reply = _send(ws, {"cmd": "reset"})
            assert reply["type"] != "command_throttled"


def test_백엔드_전환은_더_긴_쿨다운을_쓴다():
    """모델 로딩이 있어 일반 명령보다 길게 설정돼 있어야 한다."""
    import ws_server

    assert ws_server.BACKEND_COOLDOWN_SEC > ws_server.COMMAND_COOLDOWN_SEC


def test_쿨다운_경과_후에는_다시_실행된다(client, monkeypatch):
    """쿨다운 시간이 지나면 같은 명령이 다시 통과해야 한다."""
    import commands

    monkeypatch.setattr(commands, "_COOLDOWN_COMMANDS", {"set_script"})
    monkeypatch.setattr(commands, "COMMAND_COOLDOWN_SEC", 0.0)
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        assert _send(ws, {"cmd": "set_script", "text": "하나"})["type"] == "script_state"
        assert _send(ws, {"cmd": "set_script", "text": "둘"})["type"] == "script_state"


# ── H-4: 크기·연결 상한 ─────────────────────────────────────────


def test_과도하게_긴_원고는_잘려서_적용된다(client, monkeypatch):
    """상한을 넘는 원고는 잘려서 저장돼야 한다(H-4).

    응답 메시지 개수에 의존하지 않고 **저장된 결과**로 판정한다
    (상한이 없으면 truncated 알림이 오지 않아 테스트가 멈출 수 있으므로).
    """
    import commands
    import ws_server

    monkeypatch.setattr(commands, "MAX_SCRIPT_CHARS", 100)
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        _send(ws, {"cmd": "set_script", "text": "가" * 500})
        # 실제 적용 결과로 검증 — 상한이 동작하지 않으면 500자가 그대로 남는다
        assert len(ws_server.SCRIPT_PATH.read_text(encoding="utf-8")) <= 100


def test_연결_상한_설정이_존재한다():
    """상한이 실제로 정의되고 Hub 가 판정 수단을 제공하는지."""
    import ws_server

    assert ws_server.MAX_WS_CLIENTS >= 1
    assert hasattr(ws_server.hub, "is_full")


def test_연결_상한_도달시_새_접속을_거부한다(client, monkeypatch):
    import hub as hub_module

    # 상한을 0 으로 만들어 '가득 찬 상태'를 시뮬레이션.
    # Hub.is_full 은 hub 모듈의 MAX_WS_CLIENTS 를 참조하므로 그쪽을 패치한다.
    monkeypatch.setattr(hub_module, "MAX_WS_CLIENTS", 0)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()


def test_메시지_크기_상한이_설정되어_있다():
    import ws_server

    # 원고 상한(자) 을 UTF-8 로 담을 수 있어야 의미가 있다
    assert ws_server.WS_MAX_MESSAGE_BYTES >= 64 * 1024


def _send(ws, cmd: dict) -> dict:
    """토큰을 붙여 명령을 보내고 첫 '의미 있는' 응답을 받는다.

    인증이 처음 확인될 때 서버가 operator_init(내부정보)을 먼저 보내므로 건너뛴다.
    """
    cmd.setdefault("token", TOKEN)
    ws.send_json(cmd)
    for _ in range(4):
        msg = ws.receive_json()
        if msg.get("type") != "operator_init":
            return msg
    return msg
