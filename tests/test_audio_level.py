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


# ── '너무 작음' 경고 (오프라인 STT 임계값 미달) ──────────────────
# 실제로 겪은 문제: BlackHole 컴퓨터 소리 볼륨이 낮아 게이지엔 신호가 보이는데
# (-42dB) 오프라인 STT 임계값(-36.5dB)에 못 미쳐 전사가 전혀 안 됐다.
# 볼륨을 100%로 올리자 전사가 시작됨 → 이 '죽은 구간'을 경고로 알린다.


def test_임계값_바로_아래_신호는_오프라인에서_작음경고():
    from local_backend import SILENCE_RMS
    from ws_server import _is_too_quiet

    assert _is_too_quiet(SILENCE_RMS - 0.001, online=False, silent=False) is True


def test_임계값_이상이면_경고하지_않는다():
    from local_backend import SILENCE_RMS
    from ws_server import _is_too_quiet

    assert _is_too_quiet(SILENCE_RMS + 0.01, online=False, silent=False) is False


def test_온라인은_작아도_경고하지_않는다():
    """온라인(Gemini)은 자체 게인 처리가 있어 이 임계값과 무관하다."""
    from local_backend import SILENCE_RMS
    from ws_server import _is_too_quiet

    assert _is_too_quiet(SILENCE_RMS - 0.001, online=True, silent=False) is False


def test_완전_무음은_작음경고가_아니다():
    """무음(신호 없음)은 별도의 무음 경고가 우선 — 이중 경고를 막는다."""
    from ws_server import _is_too_quiet

    assert _is_too_quiet(0.0, online=False, silent=True) is False


# ── 입력 게인(소프트웨어 증폭) ──────────────────────────────────
# 실제 문제: 컴퓨터 소리 볼륨이 낮아 STT 임계값에 못 미쳐 전사가 안 됐다.
# 시스템 볼륨을 못 올리는 상황에서 앱이 신호를 증폭해 임계값을 넘긴다.


def test_게인이_신호를_증폭한다():
    cap = AudioCapture()
    cap.set_gain(2.0)
    chunk = _chunk(0.25)
    out = cap._apply_gain(chunk)
    rms_in = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
    rms_out = float(np.sqrt(np.mean(out.astype(np.float32) ** 2)))
    assert rms_out == pytest.approx(rms_in * 2, rel=0.02)


def test_게인은_int16_범위로_클리핑된다():
    """증폭이 최대치를 넘어도 오버플로우(랩어라운드)가 나면 안 된다."""
    cap = AudioCapture()
    cap.set_gain(8.0)
    out = cap._apply_gain(_chunk(0.5))  # 0.5 * 8 = 4.0 → 클리핑
    assert out.max() <= 32767
    assert out.min() >= -32768


def test_게인은_허용_범위로_클램프된다():
    from audio_input import MAX_GAIN, MIN_GAIN

    cap = AudioCapture()
    assert cap.set_gain(100) == MAX_GAIN   # 상한
    assert cap.set_gain(0.1) == MIN_GAIN   # 하한
    assert cap.set_gain(3.0) == 3.0        # 범위 내


def test_게인_1이면_원본을_그대로_반환():
    """기본(1.0)일 때 불필요한 복사·연산을 하지 않는다."""
    cap = AudioCapture()  # 기본 게인 1.0
    chunk = _chunk(0.3)
    assert cap._apply_gain(chunk) is chunk
