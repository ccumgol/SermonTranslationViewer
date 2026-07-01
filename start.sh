#!/usr/bin/env bash
# 설교 실시간 자막 서버 실행 단축 스크립트.
# 가상환경 활성화 + 서버 실행을 한 번에 처리한다.
#
# 사용법:
#   ./start.sh
set -euo pipefail

# 스크립트가 있는 폴더로 이동 (어디서 실행하든 동작)
cd "$(dirname "$0")"

# 가상환경이 없으면 안내 후 종료
if [ ! -d ".venv" ]; then
  echo "❌ .venv 가 없습니다. 먼저 아래로 환경을 만드세요:"
  echo "   python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

# .env 확인
if [ ! -f ".env" ]; then
  echo "❌ .env 가 없습니다. cp .env.example .env 로 만들고 GEMINI_API_KEY 를 채우세요."
  exit 1
fi

# 가상환경 활성화
source .venv/bin/activate

# 포트는 .env 의 WS_PORT 사용(없으면 8000)
PORT="$(grep -E '^WS_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d ' ')"
PORT="${PORT:-8000}"
OP_URL="http://localhost:${PORT}/operator"

echo "🎤 설교 실시간 자막 서버 시작…"
echo "   송출 화면:   http://localhost:${PORT}/"
echo "   운영자 화면: ${OP_URL}"
echo "   셀폰 자막:   http://(이PC의IP):${PORT}/m"
echo "   (종료: Ctrl+C)"
echo

# 서버가 뜨면 운영자 화면을 자동으로 연다 (OPEN_BROWSER=0 이면 끔)
if [ "${OPEN_BROWSER:-1}" != "0" ]; then
  (
    for _ in $(seq 1 40); do
      if curl -s -o /dev/null "http://localhost:${PORT}/health"; then break; fi
      sleep 0.5
    done
    if command -v open >/dev/null 2>&1; then open "${OP_URL}"          # macOS
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "${OP_URL}"  # Linux
    fi
  ) &
fi

# 서버 실행 (python3, 패키지 형식)
exec python3 -m server
