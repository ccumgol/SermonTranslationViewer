"""입력 레벨 게이지 테스트.

실제로 겪은 문제: BlackHole(컴퓨터 소리)을 선택했지만 macOS 출력이 그쪽으로
가지 않아 신호가 0 이었는데, 화면상으로는 정상으로 보여 원인을 찾기 어려웠다.
게이지가 '무음'을 정확히 알려주는지 검증한다.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from audio_input import (
    INT16_FULL_SCALE,
    SILENCE_DBFS,
    AudioCapture,
    rms_to_dbfs,
)


# ── dBFS 변환 ───────────────────────────────────────────────────


def test_무음은_바닥값이다():
    assert rms_to_dbfs(0.0) == SILENCE_DBFS


def test_풀스케일은_0dB():
    assert rms_to_dbfs(1.0) == pytest.approx(0.0)


def test_절반_진폭은_약_마이너스6dB():
    assert rms_to_dbfs(0.5) == pytest.approx(-6.02, abs=0.05)


def test_아주_작은_신호도_바닥_아래로_내려가지_않는다():
    """게이지가 음수로 발산해 막대가 깨지지 않도록 하한을 둔다."""
    assert rms_to_dbfs(1e-12) == SILENCE_DBFS


def test_큰_소리일수록_dB_가_높다():
    assert rms_to_dbfs(0.01) < rms_to_dbfs(0.1) < rms_to_dbfs(0.9)


# ── 피크 추적 ───────────────────────────────────────────────────


def _chunk(amplitude: float, n: int = 1600) -> np.ndarray:
    """진폭(0.0~1.0)에 해당하는 int16 사인파 청크."""
    t = np.linspace(0, 1, n, endpoint=False)
    return (np.sin(2 * np.pi * 5 * t) * amplitude * (INT16_FULL_SCALE - 1)).astype(
        np.int16
    )


def test_신호가_없으면_레벨이_0():
    cap = AudioCapture()
    cap._track_level(np.zeros(1600, dtype=np.int16))
    assert cap.pop_level() == 0.0


def test_신호가_있으면_레벨이_올라간다():
    cap = AudioCapture()
    cap._track_level(_chunk(0.5))
    level = cap.pop_level()
    assert level > 0.0
    # 사인파 RMS = 진폭/√2 ≈ 0.354
    assert level == pytest.approx(0.354, abs=0.01)


def test_읽으면_초기화된다():
    """게이지는 '최근 구간'의 피크를 보여야 한다 — 안 지우면 계속 최댓값에 붙어 있다."""
    cap = AudioCapture()
    cap._track_level(_chunk(0.5))
    assert cap.pop_level() > 0.0
    assert cap.pop_level() == 0.0


def test_구간_내_최댓값을_유지한다():
    """조용한 청크가 뒤따라도, 그 사이의 말소리가 묻히면 안 된다."""
    cap = AudioCapture()
    cap._track_level(_chunk(0.8))
    cap._track_level(np.zeros(1600, dtype=np.int16))
    assert cap.pop_level() == pytest.approx(0.566, abs=0.01)


def test_장치를_바꾸면_레벨이_초기화된다():
    """이전 장치의 신호가 남아 새 장치가 정상인 것처럼 보이면 안 된다."""
    cap = AudioCapture()
    cap._track_level(_chunk(0.8))
    cap._close_stream()  # 스트림 없이도 레벨은 초기화돼야 한다
    assert cap.pop_level() == 0.0


def test_잘못된_입력이어도_예외를_던지지_않는다():
    """레벨 표시는 부가 기능 — 실패해도 오디오 흐름을 끊으면 안 된다."""
    cap = AudioCapture()
    cap._track_level(None)  # 비정상 입력
    assert cap.pop_level() == 0.0


# ── 레벨 전송 대상 (운영자 전용) ────────────────────────────────


class _FakeWS:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, message: str) -> None:
        self.sent.append(message)


def test_레벨은_운영자에게만_간다():
    """초당 5회 갱신 — 교인 폰 수십 대에 보내면 대역폭 낭비다."""
    from ws_server import Hub

    h = Hub()
    operator, phone = _FakeWS(), _FakeWS()

    async def scenario():
        await h.register(operator)
        await h.register(phone)
        h.mark_operator(operator)
        await h.send_operators({"type": "level", "dbfs": -20})

    asyncio.run(scenario())
    assert len(operator.sent) == 1
    assert phone.sent == [], "인증하지 않은 연결에 레벨이 가면 안 됨"


def test_연결이_끊기면_운영자_목록에서도_빠진다():
    from ws_server import Hub

    h = Hub()
    ws = _FakeWS()
    asyncio.run(h.register(ws))
    h.mark_operator(ws)
    assert h.has_operator
    asyncio.run(h.unregister(ws))
    assert not h.has_operator, "끊긴 연결에 계속 전송하면 자원이 샌다"
