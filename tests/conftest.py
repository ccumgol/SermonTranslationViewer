"""테스트 공통 설정 — server 모듈을 import 경로에 추가."""

import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent / "server"
sys.path.insert(0, str(SERVER))
