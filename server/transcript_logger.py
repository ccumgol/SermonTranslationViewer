"""전사/번역 로깅 (선택) — 사후 검토용.

기본 활성화(LOG_TRANSCRIPTS=0 으로 끌 수 있음). 전사 품질 점검이 번역보다
중요하므로 기본으로 남긴다. data/logs/ 에 세션별로 두 형식으로 저장한다.

  sermon-<시각>.jsonl : 기계 판독용 (한 줄 = {t, lang, text})
  sermon-<시각>.txt   : 사람이 바로 읽는 형식 (한국어 전사 + 언어별 번역)

민감 자료이므로 data/logs/ 는 .gitignore 로 제외돼 있다.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

log = logging.getLogger("transcript")

LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "logs"


class TranscriptLogger:
    def __init__(self, path: Path) -> None:
        self._path = path

    @staticmethod
    def maybe_create() -> "TranscriptLogger | None":
        """기본 활성화. LOG_TRANSCRIPTS=0/false/no 로 끌 수 있다."""
        if os.getenv("LOG_TRANSCRIPTS", "1").strip().lower() in ("0", "false", "no"):
            return None
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return TranscriptLogger(LOG_DIR / f"sermon-{stamp}.jsonl")

    @property
    def text_path(self) -> Path:
        """사람이 읽는 형식(.txt) 경로 — 전사 점검용."""
        return self._path.with_suffix(".txt")

    def log(self, lang: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        line = json.dumps(
            {"t": datetime.now().isoformat(timespec="seconds"), "lang": lang, "text": text},
            ensure_ascii=False,
        )
        try:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            # 사람이 바로 읽을 수 있는 형식도 함께 남긴다(전사 점검이 주목적).
            stamp = datetime.now().strftime("%H:%M:%S")
            label = "한국어" if lang == "ko" else lang
            with self.text_path.open("a", encoding="utf-8") as f:
                f.write(f"[{stamp}] ({label}) {text}\n")
        except Exception as exc:  # noqa: BLE001
            log.warning("기록 실패(무시): %s", exc)

    @property
    def path(self) -> Path:
        return self._path
