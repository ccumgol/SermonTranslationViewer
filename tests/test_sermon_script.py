"""ScriptCorrector 단위 테스트."""

from sermon_script import ScriptCorrector

SCRIPT = (
    "오늘 본문은 히브리어 원문으로 보겠습니다. "
    "아브라함과 이삭과 야곱의 하나님, 다메섹으로 가는 길에서 엘리에셀을 만났다."
)


def make():
    sc = ScriptCorrector()
    sc.set_script(SCRIPT)
    return sc


def test_extracts_terms():
    sc = make()
    # 조사 벗긴 어간도 포함
    assert "히브리어" in sc.terms
    assert "아브라함" in sc.terms   # "아브라함과" 에서 어간
    assert "다메섹" in sc.terms      # "다메섹으로" 에서 어간


def test_corrects_single_syllable_error():
    sc = make()
    assert sc.correct("티브리어 원문을") == "히브리어 원문을"
    assert sc.correct("아브라암과 함께") == "아브라함과 함께"
    assert sc.correct("다베섹으로 갔다") == "다메섹으로 갔다"


def test_leaves_correct_and_unrelated_untouched():
    sc = make()
    assert sc.correct("엘리에셀을 불렀다") == "엘리에셀을 불렀다"
    assert sc.correct("완전히 다른 평범한 문장입니다") == "완전히 다른 평범한 문장입니다"
    assert sc.correct("우리 교회는 오늘") == "우리 교회는 오늘"


def test_empty_script_is_noop():
    sc = ScriptCorrector()
    assert sc.is_empty
    assert sc.correct("티브리어") == "티브리어"


def test_two_syllable_words_not_touched():
    # 짧은 단어는 오검출 위험이 커서 교정 대상에서 제외(3음절+만)
    sc = ScriptCorrector()
    sc.set_script("이삭 야곱")   # 2음절
    assert sc.correct("이색") == "이색"   # 교정 안 함
