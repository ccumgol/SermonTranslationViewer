"""운영자 명령 입력 검증 — ws_server.py 에서 분리(모듈 분리 2단계).

스타일·언어 목록을 화이트리스트로 검증하는 순수 함수 모음. 상태·네트워크에
의존하지 않아 단위 테스트가 쉽다.
"""

from __future__ import annotations

from constants import DEFAULT_COLORS, MAX_LANGUAGES, _HEX_COLOR_RE
from languages import VALID_CODES


def _is_hex_color(value: object) -> bool:
    """#RGB / #RRGGBB 형식인지 검사 (임의 길이 문자열이 상태에 들어가는 것을 막는다)."""
    return (
        isinstance(value, str)
        and _HEX_COLOR_RE.fullmatch(value) is not None
    )


def _sanitize_style(raw: object) -> dict:
    """set_style 입력을 화이트리스트로 검증 (M-2).

    기존에는 임의 키를 그대로 상태에 병합하고 색상 길이도 무제한이어서,
    쓰레기 값이 모든 클라이언트로 전파될 수 있었다. 허용된 키·타입·범위만 통과시킨다.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict = {}

    size = raw.get("fontSize")
    if isinstance(size, (int, float)) and not isinstance(size, bool):
        out["fontSize"] = min(max(float(size), 1.0), 20.0)

    pad = raw.get("padding")
    if isinstance(pad, (int, float)) and not isinstance(pad, bool):
        out["padding"] = min(max(float(pad), 0.0), 30.0)

    if _is_hex_color(raw.get("bgColor")):
        out["bgColor"] = raw["bgColor"]

    region = raw.get("region")
    if region in ("full", "bottom", "top"):
        out["region"] = region

    lines = raw.get("maxLines")
    if isinstance(lines, int) and not isinstance(lines, bool):
        out["maxLines"] = min(max(lines, 0), 10)

    return out


def _sanitize_languages(raw: object) -> list[dict]:
    """입력 언어 목록을 검증·정리. 최대 3개, 코드 중복 제거, 색 기본값 보정."""
    cleaned: list[dict] = []
    seen: set[str] = set()
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            code = entry.get("code")
            if code not in VALID_CODES or code in seen:
                continue
            color = entry.get("color")
            if not _is_hex_color(color):
                color = DEFAULT_COLORS[len(cleaned) % len(DEFAULT_COLORS)]
            cleaned.append({"code": code, "color": color})
            seen.add(code)
            if len(cleaned) >= MAX_LANGUAGES:
                break
    if not cleaned:  # 최소 1개 보장
        cleaned.append({"code": "en", "color": DEFAULT_COLORS[0]})
    return cleaned
