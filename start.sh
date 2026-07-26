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

# 포트가 이미 사용 중이면(기존 서버가 살아있으면) 새 서버는 'address already in
# use' 로 조용히 실패한다(자주 겪는 함정). 미리 감지해 물어보고, 동의 시 기존 서버를
# 종료한 뒤 진행한다. lsof 가 없으면 이 검사는 건너뛴다.
if command -v lsof >/dev/null 2>&1; then
  EXISTING_PID="$(lsof -ti:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
  if [ -n "${EXISTING_PID}" ]; then
    echo "⚠ 포트 ${PORT} 에서 이미 서버가 실행 중입니다 (PID: ${EXISTING_PID//$'\n'/ })."
    echo "   그대로 새로 시작하면 포트 충돌로 실패합니다."
    printf "   기존 서버를 종료하고 새로 시작할까요? [y/N] "
    read -r ANS || ANS=""
    case "${ANS}" in
      [yY] | [yY][eE][sS])
        echo "   기존 서버 종료 중…"
        # shellcheck disable=SC2086
        kill ${EXISTING_PID} 2>/dev/null || true
        for _ in $(seq 1 10); do   # 포트가 풀릴 때까지 최대 ~5초 대기
          lsof -ti:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1 || break
          sleep 0.5
        done
        STILL="$(lsof -ti:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
        if [ -n "${STILL}" ]; then
          echo "   정상 종료가 안 돼 강제 종료합니다."
          # shellcheck disable=SC2086
          kill -9 ${STILL} 2>/dev/null || true
          sleep 0.5
        fi
        echo "   완료. 새 서버를 시작합니다."
        ;;
      *)
        echo "   취소했습니다. 기존 서버를 그대로 사용하세요: ${OP_URL}"
        exit 0
        ;;
    esac
  fi
fi

echo "🎤 설교 실시간 자막 서버 시작…"
echo "   송출 화면:   http://localhost:${PORT}/"
echo "   운영자 화면: ${OP_URL}"
echo "   셀폰 자막:   http://(이PC의IP):${PORT}/m"
echo "   (종료: Ctrl+C)"
echo

# 이전 실행의 URL 파일을 지워, 새 토큰이 기록될 때까지 기다리게 한다
# (토큰이 담기므로 저장소 밖 임시 디렉터리에 둔다 — 실수로 커밋되는 것을 방지)
URL_FILE="${TMPDIR:-/tmp}/translateviewer/operator_url.txt"
rm -f "${URL_FILE}"

# 서버가 뜨면 운영자 화면을 자동으로 연다 (OPEN_BROWSER=0 이면 끔)
# 운영자 토큰이 자동 생성되므로, 서버가 남긴 URL(토큰 포함)을 읽어서 연다.
if [ "${OPEN_BROWSER:-1}" != "0" ]; then
  (
    for _ in $(seq 1 40); do
      if curl -s -o /dev/null "http://localhost:${PORT}/health"; then break; fi
      sleep 0.5
    done
    for _ in $(seq 1 10); do
      [ -f "${URL_FILE}" ] && break
      sleep 0.3
    done
    TARGET="$(cat "${URL_FILE}" 2>/dev/null || echo "${OP_URL}")"
    if command -v open >/dev/null 2>&1; then open "${TARGET}"          # macOS
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "${TARGET}"  # Linux
    fi
  ) &
fi

# 서버 실행 (python3, 패키지 형식)
exec python3 -m server
