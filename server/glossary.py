"""용어집(glossary) — 고유명사 인식·번역 품질 보정.

STT context 에 단어 목록을 직접 주면 그 단어를 환각 출력하는 부작용이 있으므로,
안전하게 두 단계로 적용한다.
  1) STT 전사 후 "치환"(자주 틀리는 표기 → 올바른 표기)
  2) 번역 프롬프트에 "권장 표기 힌트"(한국어 → 목표어 고유명사)

파일 형식 (data/glossary/glossary.txt, UTF-8):
  # 주석
  fix: 아브라마 => 아브람          # STT 전사 후 치환
  term: 아브람 = Abram             # 번역 시 권장 표기
  term: 여호와 = Jehovah / LORD

term 의 목표 표기는 자유 텍스트(슬래시로 대안 표기 가능).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_GLOSSARY_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "glossary" / "glossary.txt"
)


@dataclass
class Glossary:
    corrections: list[tuple[str, str]] = field(default_factory=list)  # (틀림, 올바름)
    terms: list[tuple[str, str]] = field(default_factory=list)        # (한국어, 표기힌트)

    @staticmethod
    def load(path: str | os.PathLike | None = None) -> "Glossary":
        p = Path(path) if path else DEFAULT_GLOSSARY_PATH
        g = Glossary()
        if not p.exists():
            return g
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("fix:"):
                body = line[4:].strip()
                if "=>" in body:
                    wrong, right = body.split("=>", 1)
                    if wrong.strip() and right.strip():
                        g.corrections.append((wrong.strip(), right.strip()))
            elif line.startswith("term:"):
                body = line[5:].strip()
                if "=" in body:
                    ko, hint = body.split("=", 1)
                    if ko.strip() and hint.strip():
                        g.terms.append((ko.strip(), hint.strip()))
        return g

    def correct(self, text: str) -> str:
        """STT 전사 결과에 치환 규칙을 적용."""
        for wrong, right in self.corrections:
            if wrong in text:
                text = text.replace(wrong, right)
        return text

    def hint_for(self, text: str) -> str:
        """주어진 한국어에 등장하는 용어만 골라 번역 힌트 문자열을 만든다.

        전체 용어집을 매번 넣으면 프롬프트가 비대해지므로, 실제 등장 용어만.
        """
        present = [(ko, hint) for ko, hint in self.terms if ko in text]
        if not present:
            return ""
        return ", ".join(f"{ko}→{hint}" for ko, hint in present)

    @property
    def is_empty(self) -> bool:
        return not self.corrections and not self.terms
