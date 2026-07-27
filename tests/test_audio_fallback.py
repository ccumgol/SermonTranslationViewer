"""입력 장치를 못 열어도 서버가 살아남는지 검증.

실제로 겪은 문제: `.env` 의 `AUDIO_INPUT_DEVICE` 장치(Vocaster)가 연결돼 있지
않아 `AudioCapture` 진입에서 예외가 났고, `lifespan` 이 그 예외를 확인하지 않아
**파이프라인만 조용히 죽었다.** 서버는 200 OK 로 응답하고 운영자 화면도 정상으로
보이는데 자막만 영원히 안 나오는 상태 — 예배 직전 USB 를 안 꽂으면 그대로 발생한다.

캡처 객체가 살아 있어야 운영자가 장치를 꽂고 '목록 새로고침 → 선택'으로 복구할 수
있다(사용자 제안). 이 파일은 그 전제조건을 지킨다.
"""

from __future__ import annotations

import asyncio

import pytest

from audio_input import AudioCapture


class _FakeStream:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture
def stream_factory(monkeypatch):
    """`sd.InputStream` 을 가로채, 장치별로 성공/실패를 지정할 수 있게 한다."""
    calls: list = []

    def make(fail_devices: set | None = None):
        fail = fail_devices or set()

        def fake_input_stream(*, device=None, **kwargs):
            calls.append(device)
            if device in fail:
                raise ValueError(f"No input device matching '{device}'")
            return _FakeStream()

        import audio_input

        monkeypatch.setattr(audio_input.sd, "InputStream", fake_input_stream)
        return calls

    return make


def _enter(cap: AudioCapture) -> AudioCapture:
    async def run():
        return await cap.__aenter__()

    return asyncio.run(run())


# ── 기동 시 장치 실패 ────────────────────────────────────────────


def test_지정_장치가_없으면_기본_장치로_대체된다(stream_factory):
    """케이블이 빠져 있어도 예배가 멈추면 안 된다."""
    calls = stream_factory(fail_devices={"Vocaster Two USB"})
    cap = AudioCapture("Vocaster Two USB")
    _enter(cap)

    assert calls == ["Vocaster Two USB", None], "지정 장치 실패 후 기본 장치를 시도해야 함"
    assert cap.current_device is None, "기본 장치로 열렸어야 함"


def test_대체되면_사용자에게_알릴_오류메시지가_남는다(stream_factory):
    """조용히 대체하면 '왜 다른 마이크 소리가 나지?' 를 알 수 없다."""
    stream_factory(fail_devices={"Vocaster Two USB"})
    cap = AudioCapture("Vocaster Two USB")
    _enter(cap)

    assert cap.error, "대체 사실이 error 로 노출돼야 함"
    assert "Vocaster Two USB" in cap.error, "어떤 장치가 실패했는지 알려야 함"


def test_모든_장치_실패해도_예외를_던지지_않는다(stream_factory):
    """여기서 예외가 나가면 파이프라인 전체가 죽어 자막이 영영 안 나온다."""
    stream_factory(fail_devices={"Vocaster Two USB", None})
    cap = AudioCapture("Vocaster Two USB")
    _enter(cap)  # 예외가 나면 이 지점에서 테스트 실패

    assert cap.error, "실패 사실은 남아야 함"


def test_모든_장치_실패해도_캡처_객체는_살아있다(stream_factory):
    """운영자가 장치를 꽂고 '새로고침 → 선택'으로 복구할 수 있어야 한다."""
    stream_factory(fail_devices={"Vocaster Two USB", None})
    cap = AudioCapture("Vocaster Two USB")
    _enter(cap)

    assert cap.pop_level() == 0.0, "레벨 조회가 죽지 않아야 함"


def test_정상_장치는_대체하지_않는다(stream_factory):
    calls = stream_factory(fail_devices=set())
    cap = AudioCapture("BlackHole 2ch")
    _enter(cap)

    assert calls == ["BlackHole 2ch"], "성공했으면 기본 장치를 시도하면 안 됨"
    assert cap.error is None


def test_장치_미지정_기동은_그대로_동작한다(stream_factory):
    """AUDIO_INPUT_DEVICE 를 비워둔 기본 설정의 회귀 방지."""
    calls = stream_factory(fail_devices=set())
    cap = AudioCapture(None)
    _enter(cap)

    assert calls == [None]
    assert cap.error is None


# ── 복구: 나중에 장치를 꽂고 교체 ────────────────────────────────


def test_실패_후에도_장치_교체로_복구된다(stream_factory):
    """사용자 제안의 핵심 — 꽂은 다음 대시보드에서 고르면 살아나야 한다."""
    stream_factory(fail_devices={"Vocaster Two USB", None})
    cap = AudioCapture("Vocaster Two USB")
    _enter(cap)
    assert cap.error

    # USB 를 꽂았다고 가정하고 다시 목록에서 선택
    stream_factory(fail_devices=set())
    cap.set_device("Vocaster Two USB")

    assert cap.current_device == "Vocaster Two USB"
    assert cap.error is None, "복구되면 오류 표시가 사라져야 함"


def test_교체_실패는_예외로_알린다(stream_factory):
    """운영자가 고른 장치가 실패하면 화면에 오류를 띄워야 하므로 예외는 전파한다."""
    stream_factory(fail_devices={"없는장치"})
    cap = AudioCapture(None)
    _enter(cap)

    with pytest.raises(Exception):
        cap.set_device("없는장치")
