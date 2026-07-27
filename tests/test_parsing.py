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


# ── 자동 운영자 토큰: 재시작해도 유지되어야 열어둔 탭이 안 깨진다 ──
# monkeypatch 로 토큰 파일을 임시 경로로 돌려 실제 $TMPDIR 파일은 건드리지 않는다.


def test_토큰_없으면_새로_생성하고_저장한다(monkeypatch, tmp_path):
    import config

    monkeypatch.setattr(config, "_TOKEN_FILE", tmp_path / "operator_token")
    token, reused = config._load_or_create_token()
    assert reused is False           # 새로 만든 것
    assert len(token) >= 16
    assert (tmp_path / "operator_token").read_text().strip() == token  # 저장됨


def test_토큰_파일있으면_같은값_재사용한다(monkeypatch, tmp_path):
    import config

    monkeypatch.setattr(config, "_TOKEN_FILE", tmp_path / "operator_token")
    first, first_reused = config._load_or_create_token()
    second, second_reused = config._load_or_create_token()
    assert first_reused is False     # 1회차: 신규
    assert second_reused is True     # 2회차: 재사용
    assert second == first, "재시작해도 토큰이 유지돼야 열어둔 운영자 탭이 안 깨진다"


def test_짧은_토큰파일은_무시하고_새로_만든다(monkeypatch, tmp_path):
    """손상되거나 너무 짧은(≥16자 미만) 파일은 재사용하지 않는다."""
    import config

    tf = tmp_path / "operator_token"
    tf.write_text("short")
    monkeypatch.setattr(config, "_TOKEN_FILE", tf)
    token, reused = config._load_or_create_token()
    assert reused is False
    assert len(token) >= 16


# ── 무발화 자동 방송 종료 판정 ──────────────────────────────────


def test_무발화_자동종료_판정(monkeypatch):
    os.environ.setdefault("GEMINI_API_KEY", "test")
    import ws_server

    monkeypatch.setattr(ws_server, "IDLE_STOP_MIN", 10.0)   # 10분 설정
    assert ws_server._should_auto_stop(9 * 60, broadcasting=True) is False    # 아직 미달
    assert ws_server._should_auto_stop(10 * 60, broadcasting=True) is True    # 도달 + 방송중
    assert ws_server._should_auto_stop(20 * 60, broadcasting=False) is False  # 방송중 아님


def test_무발화_자동종료_기본은_비활성(monkeypatch):
    os.environ.setdefault("GEMINI_API_KEY", "test")
    import ws_server

    monkeypatch.setattr(ws_server, "IDLE_STOP_MIN", 0.0)    # 기본값 = 끔
    assert ws_server._should_auto_stop(999 * 60, broadcasting=True) is False
