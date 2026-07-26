"""중앙 로깅 설정 — `print` 대신 표준 `logging` 을 쓴다.

각 모듈은 `logging.getLogger("server"/"local"/"live"/"audio"/...)` 로 로거를 얻고,
진입점(`python -m server` / `python server/ws_server.py`)에서 `setup_logging()` 을
한 번 호출한다.

- 레벨은 `LOG_LEVEL` 환경변수로 조정 가능(기본 INFO). 예: `LOG_LEVEL=DEBUG`.
- 로거 이름이 예전의 `[server]` 같은 태그 역할을 대신한다(포맷에 `%(name)s`).
- 사용자에게 보여주는 시작 배너 등 일부 CLI 출력은 의도적으로 `print` 를 유지한다.
"""

from __future__ import annotations

import logging
import os

_CONFIGURED = False


def setup_logging(level: int | str | None = None) -> None:
    """루트 로거를 한 번 설정한다(중복 호출은 무시)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    if level is None:
        level = os.getenv("LOG_LEVEL", "INFO").upper()
    if isinstance(level, str):
        level = getattr(logging, level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    _CONFIGURED = True
