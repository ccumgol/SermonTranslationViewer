"""set_style 화이트리스트 검증(M-2) 테스트.

기존에는 임의 키가 그대로 상태에 병합되고 색상 길이도 무제한이어서, 쓰레기 값이
모든 클라이언트(송출 화면 포함)로 전파될 수 있었다.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("GEMINI_API_KEY", "test")


@pytest.fixture
def sanitize():
    from ws_server import _sanitize_style

    return _sanitize_style


# ── 허용되지 않는 입력은 제거 ───────────────────────────────────


def test_알_수_없는_키는_제거된다(sanitize):
    out = sanitize({"evil": "<script>", "fontSize": 5})
    assert "evil" not in out
    assert out["fontSize"] == 5.0


def test_딕셔너리가_아니면_빈_결과(sanitize):
    assert sanitize("문자열") == {}
    assert sanitize(None) == {}
    assert sanitize([1, 2, 3]) == {}


def test_잘못된_타입은_무시된다(sanitize):
    out = sanitize({"fontSize": "크게", "padding": None, "maxLines": "둘"})
    assert out == {}


def test_불리언은_숫자로_취급하지_않는다(sanitize):
    """파이썬에서 bool 은 int 의 하위형이라 실수로 통과할 수 있다."""
    assert sanitize({"fontSize": True, "maxLines": False}) == {}


# ── 색상 형식 검증 ──────────────────────────────────────────────


def test_유효한_색상만_통과한다(sanitize):
    assert sanitize({"bgColor": "#000000"})["bgColor"] == "#000000"
    assert sanitize({"bgColor": "#0f0"})["bgColor"] == "#0f0"


def test_잘못된_색상은_거부된다(sanitize):
    for bad in ["#12345", "#gggggg", "red", "#" + "a" * 5000, "", "#0000001"]:
        assert "bgColor" not in sanitize({"bgColor": bad}), f"거부되어야 함: {bad[:20]}"


# ── 범위 제한 ───────────────────────────────────────────────────


def test_폰트_크기는_범위로_제한된다(sanitize):
    assert sanitize({"fontSize": 9999})["fontSize"] <= 20.0
    assert sanitize({"fontSize": -5})["fontSize"] >= 1.0


def test_안여백과_줄수도_범위로_제한된다(sanitize):
    assert sanitize({"padding": 99999})["padding"] <= 30.0
    assert sanitize({"padding": -3})["padding"] >= 0.0
    assert sanitize({"maxLines": 500})["maxLines"] <= 10
    assert sanitize({"maxLines": -2})["maxLines"] >= 0


def test_region_은_정해진_값만_허용(sanitize):
    assert sanitize({"region": "bottom"})["region"] == "bottom"
    assert "region" not in sanitize({"region": "diagonal"})


# ── 언어 색상도 같은 검증을 쓴다 ────────────────────────────────


def test_언어_색상도_형식_검증된다():
    """_sanitize_languages 가 잘못된 색상을 기본색으로 대체하는지."""
    from ws_server import _sanitize_languages

    out = _sanitize_languages([{"code": "en", "color": "not-a-color"}])
    assert out[0]["color"].startswith("#")
    assert len(out[0]["color"]) in (4, 7)
