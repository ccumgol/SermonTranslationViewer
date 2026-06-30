"""지원 언어 단일 정의 (UI 라벨 + 번역 프롬프트용 영어 이름).

ws_server(드롭다운/검증)와 local_backend(번역 프롬프트)가 이 한 곳을 공유해
시간이 지나도 어긋나지 않게 한다.
"""

from __future__ import annotations

# code: BCP-47 단축 코드 (Gemini/번역 공용)
# label: 운영자 화면 드롭다운 표시
# name : 번역 프롬프트에 넣을 영어 언어명
_LANGUAGES: list[dict] = [
    {"code": "en", "label": "English 영어", "name": "English"},
    {"code": "ja", "label": "日本語 일본어", "name": "Japanese"},
    {"code": "zh-CN", "label": "中文 중국어", "name": "Chinese (Simplified)"},
    {"code": "es", "label": "Español 스페인어", "name": "Spanish"},
    {"code": "vi", "label": "Tiếng Việt 베트남어", "name": "Vietnamese"},
    {"code": "fr", "label": "Français 프랑스어", "name": "French"},
    {"code": "ru", "label": "Русский 러시아어", "name": "Russian"},
    {"code": "ko", "label": "한국어", "name": "Korean"},
]

# 운영자 화면에 보낼 목록 (code/label 만)
LANGUAGES: list[dict] = [
    {"code": item["code"], "label": item["label"]} for item in _LANGUAGES
]
# code → 영어 이름 (번역 프롬프트용)
LANGUAGE_NAMES: dict[str, str] = {item["code"]: item["name"] for item in _LANGUAGES}
# 유효 코드 집합
VALID_CODES: set[str] = {item["code"] for item in _LANGUAGES}
