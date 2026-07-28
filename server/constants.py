"""서버 전역에서 공유하는 설정 상수 — ws_server.py 에서 분리(모듈 분리 2단계).

환경변수·경로·상한·기본 스타일 등을 모은다. 순환 import 를 만들지 않도록
다른 서버 모듈에 의존하지 않는다(언어 정의 languages 만 참조).
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from languages import LANGUAGES

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
# 기동 시 운영자 접속 URL(토큰 포함)을 남기는 위치 — start.sh 가 읽는다(git 제외).
# ⚠️ 저장소 안에 두면 실수로 커밋되어 토큰이 공개될 수 있다(실제로 한 번 발생).
#    그래서 저장소 밖(OS 임시 디렉터리)에 저장한다 — git 에 들어갈 경로 자체가 없다.
RUNTIME_DIR = Path(tempfile.gettempdir()) / "translateviewer"
OPERATOR_URL_FILE = RUNTIME_DIR / "operator_url.txt"
# 설교 원고 저장 위치(재시작 후에도 유지). data/ 는 git 제외.
SCRIPT_PATH = Path(__file__).resolve().parent.parent / "data" / "sermons" / "current_script.txt"

# 온라인(Gemini) 분당 단가(USD, 입력+출력 전사 기준) — 예상 비용 표시용
COST_PER_MIN = float(os.getenv("COST_PER_MIN", "0.037"))
# 입력 레벨 게이지 전송 주기(초). 5회/초면 말소리 움직임이 자연스럽게 보인다.
LEVEL_PUSH_SEC = float(os.getenv("LEVEL_PUSH_SEC", "0.2"))
# 무발화 이 시간(분) 이상이면 "끄는 걸 잊지 않았나요?" 경고
IDLE_WARN_MIN = float(os.getenv("IDLE_WARN_MIN", "5"))
# 무발화 이 시간(분) 이상이면 방송을 '자동 종료'해 온라인 비용을 막는다.
# 0=비활성(기본). 예배 중 오종료를 막기 위해 기본은 꺼두고, 켤 때도 넉넉히 잡는다.
IDLE_STOP_MIN = float(os.getenv("IDLE_STOP_MIN", "0"))
# 한 WebSocket 연결에서 허용하는 인증 실패 횟수(초과 시 연결 종료 — 브루트포스 차단)
MAX_AUTH_FAILURES = 5

# ── 남용 방지 상한 (H-3 / H-4) ─────────────────────────────────
# 운영 명령 연타로 세션 재시작 스톰·과금 급증이 생기는 것을 막는 쿨다운(초).
COMMAND_COOLDOWN_SEC = float(os.getenv("COMMAND_COOLDOWN_SEC", "2"))
# 백엔드 전환은 모델 로딩이 있어 더 길게 잡는다.
BACKEND_COOLDOWN_SEC = float(os.getenv("BACKEND_COOLDOWN_SEC", "10"))
# 쿨다운을 적용할 명령(무해한 reset·list_devices 등은 제외)
_COOLDOWN_COMMANDS = {
    "set_languages", "set_backend", "set_broadcast", "set_device", "set_script",
}
# 설교 원고 최대 길이(자). 일반 설교 원고는 1~2만 자 수준.
MAX_SCRIPT_CHARS = int(os.getenv("MAX_SCRIPT_CHARS", "100000"))
# 색상 형식(#RGB / #RRGGBB) — 임의 문자열이 스타일 상태에 들어가는 것을 막는다
_HEX_COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")
# 동시 WebSocket 연결 상한(교인 폰 다수 접속 고려)
MAX_WS_CLIENTS = int(os.getenv("MAX_WS_CLIENTS", "100"))
# QR 텍스트 최대 길이(M-3) — 임의 QR 생성 오픈프록시·DoS 방지. URL 용도로 충분.
MAX_QR_TEXT_CHARS = int(os.getenv("MAX_QR_TEXT_CHARS", "512"))
# WebSocket 메시지 크기 상한(바이트) — 원고 10만 자(UTF-8 최대 3바이트) + 여유
WS_MAX_MESSAGE_BYTES = int(os.getenv("WS_MAX_MESSAGE_BYTES", str(512 * 1024)))

# 송출 화면 공유 스타일 (글자색은 언어별로 따로 지정하므로 여기엔 없음)
DEFAULT_STYLE: dict = {
    "fontSize": 4.0,       # vw 단위 글자 크기
    "bgColor": "#000000",  # 화면 전체 배경색 (검정 / 그린스크린 등)
    "padding": 4.0,        # 화면 테두리에서의 안여백 (vw)
    "region": "full",      # 자막 영역: full(전체) / bottom(하단 밴드) / top(상단 밴드)
    "maxLines": 0,         # 언어별 최대 줄 수 (0=제한없음). 예: 2 → 항상 2줄
}

# 언어 정의는 languages.py 단일 출처 사용
LABELS: dict[str, str] = {item["code"]: item["label"] for item in LANGUAGES}

# 언어 슬롯별 기본 글자색 (1번/2번/3번)
DEFAULT_COLORS = ["#ffffff", "#ffd54a", "#5ad1ff"]
MAX_LANGUAGES = 3
