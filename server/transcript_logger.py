"""전사/번역 로깅 (선택) — 사후 검토용.

LOG_TRANSCRIPTS=1 일 때만 활성화. data/logs/ 에 세션별 JSONL 파일로 한 줄씩 기록:
  {"t": "2026-06-27T12:00:00", "lang": "ko", "text": "..."}

민감 자료이므로 data/logs/ 는 .gitignore 로 제외돼 있다.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "logs"


class TranscriptLogger:
    def __init__(self, path: Path) -> None:
        self._path = path

    @staticmethod
    def maybe_create() -> "TranscriptLogger | None":
        """환경변수가 켜져 있을 때만 로거 생성."""
        if os.getenv("LOG_TRANSCRIPTS", "").strip().lower() not in ("1", "true", "yes"):
            return None
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return TranscriptLogger(LOG_DIR / f"sermon-{stamp}.jsonl")

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
        except Exception as exc:  # noqa: BLE001
            print(f"[log] 기록 실패(무시): {exc}")

    @property
    def path(self) -> Path:
        return self._path
