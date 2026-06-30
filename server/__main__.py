"""패키지 실행 진입점 — `python -m server` 로 서버 기동.

`python server/ws_server.py` 와 동일하게 동작하되, 패키지 형태 실행도 지원한다.
(server 디렉터리를 import 경로에 넣어 모듈 간 절대 임포트를 유지)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import uvicorn  # noqa: E402

from config import Settings  # noqa: E402

if __name__ == "__main__":
    cfg = Settings.load()
    uvicorn.run("ws_server:app", host=cfg.ws_host, port=cfg.ws_port, reload=False)
