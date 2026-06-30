"""Glossary 단위 테스트."""

from glossary import Glossary


def _make(tmp_path, body):
    p = tmp_path / "glossary.txt"
    p.write_text(body, encoding="utf-8")
    return Glossary.load(p)


def test_corrections_applied(tmp_path):
    g = _make(tmp_path, "fix: 아브라마 => 아브람\nfix: 카라사대 => 가라사대\n")
    assert g.correct("아브라마에게 카라사대") == "아브람에게 가라사대"


def test_term_hint_only_present_terms(tmp_path):
    g = _make(tmp_path, "term: 아브람 = Abram\nterm: 여호와 = Jehovah\n")
    assert g.hint_for("아브람아 두려워 말라") == "아브람→Abram"
    assert g.hint_for("관계없는 문장") == ""


def test_comments_and_blank_lines_ignored(tmp_path):
    g = _make(tmp_path, "# 주석\n\n  \nterm: 다메섹 = Damascus\n")
    assert len(g.terms) == 1
    assert g.terms[0] == ("다메섹", "Damascus")


def test_missing_file_is_empty(tmp_path):
    g = Glossary.load(tmp_path / "none.txt")
    assert g.is_empty
    assert g.correct("그대로") == "그대로"
    assert g.hint_for("그대로") == ""
