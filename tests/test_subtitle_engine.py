"""RollingTranscript / SubtitleEngine 단위 테스트."""

import subtitle_engine as se
from subtitle_engine import RollingTranscript, SubtitleEngine


def test_accumulates_deltas():
    r = RollingTranscript()
    r.add_delta("하나님은 ", False)
    state = r.add_delta("우리를 사랑하십니다", True)
    assert state.text == "하나님은 우리를 사랑하십니다"


def test_pause_inserts_newline(monkeypatch):
    r = RollingTranscript()
    # 시간 흐름을 직접 제어
    t = {"now": 100.0}
    monkeypatch.setattr(RollingTranscript, "_now", staticmethod(lambda: t["now"]))
    r.add_delta("첫 문장.", True)
    t["now"] += se.PAUSE_NEWLINE_SEC + 0.1   # 충분히 쉼
    r.add_delta("두 번째.", True)
    assert "\n" in r.text
    assert r.text.split("\n")[-1].strip() == "두 번째."


def test_no_newline_without_pause(monkeypatch):
    r = RollingTranscript()
    t = {"now": 0.0}
    monkeypatch.setattr(RollingTranscript, "_now", staticmethod(lambda: t["now"]))
    r.add_delta("이어서 ", False)
    t["now"] += 0.1
    r.add_delta("계속 말합니다", False)
    assert "\n" not in r.text


def test_trim_keeps_recent_within_limits():
    r = RollingTranscript()
    for i in range(se.MAX_LINES + 5):
        r.text += f"줄{i}\n"
    trimmed = r._trim(r.text)
    assert trimmed.count("\n") <= se.MAX_LINES
    # 최신 줄이 남아야 함
    assert f"줄{se.MAX_LINES + 4}" in trimmed


def test_reset_clears():
    r = RollingTranscript()
    r.add_delta("내용", True)
    state = r.reset()
    assert state.text == ""
    assert r.text == ""


def test_engine_wraps_roller():
    e = SubtitleEngine()
    e.add("안녕 ", False)
    s = e.add("하세요", True)
    assert "안녕" in s.text
    assert e.reset().text == ""
