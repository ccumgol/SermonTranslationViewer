#!/usr/bin/env bash
# 실행 중인 설교 자막 서버를 안전하게 종료한다.
#
# start.sh(sermon) 로 띄운 서버가 터미널을 닫아 '고아 프로세스'로 백그라운드에
# 남으면 Ctrl+C 로 끌 수 없다(터미널이 없으므로). 이 스크립트가 포트를 잡고 있는
# 서버 프로세스를 찾아 정상 종료(안 죽으면 강제 종료)한다.
#
# 사용법:
#   ./stop.sh
set -uo pipefail

# 스크립트가 있는 폴더로 이동 (어디서 실행하든 동작)
cd "$(dirname "$0")"

# 포트는 .env 의 WS_PORT 사용(없으면 8000) — start.sh 와 동일 규칙
PORT="$(grep -E '^WS_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d ' ')"
PORT="${PORT:-8000}"

if ! command -v lsof >/dev/null 2>&1; then
  echo "❌ lsof 가 없어 포트로 서버를 찾을 수 없습니다. 수동으로 종료하세요."
  exit 1
fi

PIDS="$(lsof -ti:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
if [ -z "${PIDS}" ]; then
  echo "ℹ️  포트 ${PORT} 에서 실행 중인 서버가 없습니다."
  exit 0
fi

echo "포트 ${PORT} 서버 종료 중… (PID: ${PIDS//$'\n'/ })"
# shellcheck disable=SC2086
kill ${PIDS} 2>/dev/null || true

# 포트가 풀릴 때까지 최대 ~5초 대기(정상 종료 우선)
for _ in $(seq 1 10); do
  lsof -ti:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1 || break
  sleep 0.5
done

STILL="$(lsof -ti:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "${STILL}" ]; then
  echo "정상 종료가 안 돼 강제 종료합니다."
  # shellcheck disable=SC2086
  kill -9 ${STILL} 2>/dev/null || true
  sleep 0.5
fi

echo "✅ 종료 완료."
