"""_parse_device(config) 와 _sanitize_languages(ws_server) 단위 테스트."""

import os

from config import _parse_device


def test_parse_device_numeric_to_int():
    assert _parse_device("2") == 2
    assert _parse_device(" 5 ") == 5


def test_parse_device_name_stays_string():
    assert _parse_device("Vocaster Two USB") == "Vocaster Two USB"


def test_parse_device_empty_is_none():
    assert _parse_device("") is None
    assert _parse_device("   ") is None


def test_sanitize_languages():
    # ws_server 는 무거운 import 가 있으므로 필요한 시점에 import
    os.environ.setdefault("GEMINI_API_KEY", "test")
    from ws_server import _sanitize_languages, MAX_LANGUAGES

    # 유효 코드만, 중복 제거, 최대 3개
    out = _sanitize_languages(
        [
            {"code": "en", "color": "#fff"},
            {"code": "en", "color": "#000"},   # 중복 → 제거
            {"code": "xx"},                      # 무효 코드 → 제거
            {"code": "ja"},
            {"code": "zh-CN"},
            {"code": "fr"},                      # 4번째 → 잘림
        ]
    )
    codes = [x["code"] for x in out]
    assert codes == ["en", "ja", "zh-CN"]
    assert len(out) <= MAX_LANGUAGES
    # 색 누락 시 기본색 보정
    assert all(x["color"].startswith("#") for x in out)


def test_sanitize_languages_empty_defaults_to_en():
    os.environ.setdefault("GEMINI_API_KEY", "test")
    from ws_server import _sanitize_languages

    out = _sanitize_languages([])
    assert out == [{"code": "en", "color": out[0]["color"]}]
