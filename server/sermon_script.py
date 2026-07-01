"""설교 원고 기반 전사 보정.

원고를 미리 입력하면, 그 안의 고유명사·희귀어를 뽑아 STT 전사 결과를
"발음 유사도"로 원고 단어 쪽으로 교정한다.

  예) 원고에 "히브리어" 가 있으면, STT 가 "티브리어" 로 잘못 들어도
      한 음절 차이이므로 "히브리어" 로 자동 교정 → 이후 번역도 Hebrew 로 정확.

STT context 에 단어를 직접 넣으면 모델이 그 목록을 그대로 출력(환각)하므로,
여기서는 안전하게 "전사 후 후처리 교정"만 한다. 보수적으로 한 음절 차이만 교정해
정상 전사를 훼손하지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 교정 대상으로 삼을 최소 음절 수 (짧은 흔한 단어를 건드리지 않기 위해 3음절+).
MIN_TERM_LEN = 3
# 이 편집거리 이하일 때만 교정 (1 = 한 음절/자음 차이).
MAX_EDIT = 1

# 뒤에 붙는 흔한 조사 (교정 전 분리했다가 다시 붙인다). 긴 것부터.
_PARTICLES = [
    "으로부터", "에게서", "이라고", "라고", "에게", "에서", "부터", "까지",
    "처럼", "으로", "께서", "한테", "이나", "나마", "라도", "밖에",
    "을", "를", "이", "가", "은", "는", "에", "의", "로", "와", "과",
    "도", "만", "께", "야", "아", "여",
]


def _lev(a: str, b: str) -> int:
    """음절(문자) 단위 편집거리."""
    la, lb = len(a), len(b)
    if abs(la - lb) > MAX_EDIT:
        return 99
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i]
        ai = a[i - 1]
        for j in range(1, lb + 1):
            cost = 0 if ai == b[j - 1] else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[lb]


def _split_particle(word: str) -> tuple[str, str]:
    """단어 끝의 흔한 조사를 분리 → (핵심, 조사)."""
    for p in _PARTICLES:
        if len(word) > len(p) + 1 and word.endswith(p):
            return word[: -len(p)], p
    return word, ""


@dataclass
class ScriptCorrector:
    """설교 원고에서 뽑은 용어로 전사를 보정."""

    terms: set[str] = field(default_factory=set)

    def set_script(self, text: str) -> int:
        """원고에서 한글 단어를 용어로 추출. 조사를 벗긴 어간도 함께 넣는다.

        예) "아브라함과" → {"아브라함과", "아브라함"} 둘 다 용어로.
        3음절 미만 어간은 오검출 위험이 커 제외한다. 추출 수 반환.
        """
        words = re.findall(r"[가-힣]{%d,}" % MIN_TERM_LEN, text or "")
        terms: set[str] = set()
        for w in words:
            terms.add(w)
            stem, particle = _split_particle(w)
            if particle and len(stem) >= MIN_TERM_LEN:
                terms.add(stem)
        self.terms = terms
        return len(self.terms)

    def clear(self) -> None:
        self.terms = set()

    def _closest(self, word: str) -> str | None:
        """원고 용어 중 편집거리 MAX_EDIT 이내의 가장 가까운 단어(정확히 같지 않은)."""
        if len(word) < MIN_TERM_LEN or word in self.terms:
            return None
        best, best_d = None, 99
        for t in self.terms:
            if abs(len(t) - len(word)) > MAX_EDIT:
                continue
            d = _lev(word, t)
            if d < best_d:
                best, best_d = t, d
        return best if best and 0 < best_d <= MAX_EDIT else None

    def correct(self, text: str) -> str:
        """전사 텍스트의 각 단어를 원고 용어 쪽으로 보정."""
        if not self.terms or not text:
            return text
        out = []
        for token in text.split(" "):
            m = re.match(r"^([가-힣]+)(.*)$", token)
            if not m:
                out.append(token)
                continue
            hangul, tail = m.group(1), m.group(2)  # tail = 구두점 등
            core, particle = _split_particle(hangul)
            fixed = self._closest(core)
            if fixed:
                out.append(fixed + particle + tail)
            else:
                out.append(token)
        return " ".join(out)

    @property
    def is_empty(self) -> bool:
        return not self.terms
