"""자막 안정화 엔진 (시간 기반 줄바꿈 + 하단 고정용 tail 유지).

Gemini Live 의 전사 텍스트는 작은 "조각(delta)" 으로 들어온다.
설교처럼 쉼 없이 이어 말하면 문장 확정(turn_complete) 경계가 잘 잡히지 않으므로,
줄바꿈은 "조각이 들어온 시각의 실제 간격" 으로 판단한다.

  - 직전 조각 이후 PAUSE_NEWLINE_SEC 이상 멈췄다가 새 조각이 오면 → 줄바꿈
  - 화면이 무한정 길어지지 않도록 최근 줄/글자수만 유지(tail)
    (송출 화면은 하단 고정 + 위쪽 잘라내기로, 항상 최신 자막이 보인다)

순수 로직만 담당하며 새 상태를 만들어 반환(불변 원칙)한다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

# 화면에 유지할 최대 글자수 (tail 기준). 송출 화면 CSS 가 화면 높이만큼만 보여준다.
MAX_DISPLAY_CHARS = 1200
# 유지할 최대 줄 수 (검정 풀스크린을 채울 만큼 넉넉히)
MAX_LINES = 16
# 조각이 이 시간(초) 이상 끊겼다가 다시 오면 줄을 바꾼다.
PAUSE_NEWLINE_SEC = 2.0


@dataclass(frozen=True)
class SubtitleState:
    """현재 화면에 표시할 자막 상태 (불변). 줄바꿈은 '\n' 으로 표현."""

    text: str = ""
    is_final: bool = False


@dataclass
class RollingTranscript:
    """조각을 누적하되, 시간 간격으로 줄을 나누고 최근 분량만 유지한다."""

    text: str = ""
    _last_at: float = 0.0  # 마지막 조각 수신 시각(monotonic)

    @staticmethod
    def _now() -> float:
        return time.monotonic()

    def add_delta(self, delta: str, is_final: bool) -> SubtitleState:
        now = self._now()
        # 직전 조각 이후 충분히 멈췄으면 새 줄에서 이어간다.
        if self.text and self._last_at and (now - self._last_at) >= PAUSE_NEWLINE_SEC:
            if not self.text.endswith("\n"):
                self.text = self.text.rstrip() + "\n"
        self._last_at = now
        self.text = self._trim(self.text + delta)
        return SubtitleState(text=self.text, is_final=is_final)

    def reset(self) -> SubtitleState:
        """화면 리셋 — 누적 상태를 비운다."""
        self.text = ""
        self._last_at = 0.0
        return SubtitleState(text="", is_final=True)

    @staticmethod
    def _trim(text: str) -> str:
        lines = text.split("\n")
        if len(lines) > MAX_LINES:
            lines = lines[-MAX_LINES:]
        trimmed = "\n".join(lines)
        if len(trimmed) > MAX_DISPLAY_CHARS:
            trimmed = trimmed[-MAX_DISPLAY_CHARS:]
        return trimmed


class SubtitleEngine:
    """송출 자막(영어)을 위한 rolling 누적기."""

    def __init__(self) -> None:
        self._roller = RollingTranscript()

    def add(self, delta: str, is_final: bool) -> SubtitleState:
        return self._roller.add_delta(delta, is_final)

    def reset(self) -> SubtitleState:
        return self._roller.reset()
