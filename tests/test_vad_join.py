"""VAD 문장 재조합 로직 테스트.

강제 분할(8초 상한)로 문장 중간이 잘리면 조각 단위로 번역돼 문맥이 끊긴다.
그 조각을 문장이 끝날 때까지 모아 한 번에 번역하는 규칙을 검증한다.

STT 모델을 띄우지 않고 규칙만 검증하기 위해, `finalize` 내부의 판정식을 그대로
반영한 순수 함수로 재현해 테스트한다(실제 코드와 동일한 조건식).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("GEMINI_API_KEY", "test")


def should_flush(pending: list[str], forced: bool, max_join: int) -> bool:
    """local_backend.finalize 의 방출 판정과 동일한 규칙."""
    from local_backend import _SENTENCE_ENDINGS

    joined = " ".join(pending)
    ends_sentence = joined.rstrip().endswith(tuple(_SENTENCE_ENDINGS))
    return (
        max_join <= 0
        or not forced
        or ends_sentence
        or len(pending) >= max_join
    )


# ── 재조합이 일어나는 경우 ─────────────────────────────────────


def test_문장_중간_조각은_보류된다():
    """강제 분할 + 문장 미완성 + 상한 미달 → 다음 조각과 합치기 위해 보류."""
    assert should_flush(["오늘 우리는 하나님의"], forced=True, max_join=2) is False


def test_상한에_도달하면_보류하지_않고_내보낸다():
    """무한 대기를 막는 안전장치(자막이 과도하게 늦어지지 않게)."""
    assert should_flush(
        ["오늘 우리는", "하나님의 사랑을"], forced=True, max_join=2
    ) is True


# ── 즉시 내보내는 경우 ─────────────────────────────────────────


def test_침묵으로_끊긴_구간은_즉시_내보낸다():
    """forced=False = 문장이 끝났을 가능성이 높음 → 기다리지 않는다."""
    assert should_flush(["오늘 우리는 예배합니다"], forced=False, max_join=2) is True


def test_문장부호로_끝나면_즉시_내보낸다():
    for ending in ["다.", "까?", "라!", "…"]:
        assert should_flush([f"문장이 끝났{ending}"], forced=True, max_join=2) is True


def test_재조합_비활성화면_항상_즉시_내보낸다():
    """STT_MAX_JOIN_SEGMENTS=0 으로 예전 동작(조각 단위 번역)으로 되돌릴 수 있다."""
    assert should_flush(["미완성 조각"], forced=True, max_join=0) is True


# ── 설정값 ─────────────────────────────────────────────────────


def test_기본_설정이_합리적이다():
    import local_backend

    # 기본은 재조합 켜짐, 다만 지연이 과하지 않게 작은 값
    assert local_backend.MAX_JOIN_SEGMENTS >= 1
    assert local_backend.MAX_JOIN_SEGMENTS <= 4
    # 문장 끝 판정에 한국어·영어 마침표가 모두 포함돼야 한다
    for ch in ".?!":
        assert ch in local_backend._SENTENCE_ENDINGS


def test_환경변수로_재조합을_끌_수_있다(monkeypatch):
    """운영 중 지연이 문제면 끌 수 있어야 한다."""
    monkeypatch.setenv("STT_MAX_JOIN_SEGMENTS", "0")
    import importlib

    import local_backend

    importlib.reload(local_backend)
    try:
        assert local_backend.MAX_JOIN_SEGMENTS == 0
    finally:
        monkeypatch.delenv("STT_MAX_JOIN_SEGMENTS", raising=False)
        importlib.reload(local_backend)   # 다른 테스트에 영향 없게 복원
