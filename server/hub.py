"""WebSocket 브로드캐스트 허브 — ws_server.py 에서 분리(모듈 분리 2단계).

연결된 모든 클라이언트에 브로드캐스트하고, 운영자 인증 연결에만 보내는
채널(send_operators)을 따로 둔다. 입력 레벨처럼 자주(≈5회/초) 갱신되는 정보를
교인 폰까지 보내면 대역폭 낭비라, 그런 건 운영자에게만 보낸다.
"""

from __future__ import annotations

import json

from fastapi import WebSocket

from constants import MAX_WS_CLIENTS


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


# 전역 싱글턴 — 여러 모듈이 공유한다(from hub import hub).
hub = Hub()
