@echo off
REM 설교 실시간 자막 서버 실행 (Windows). 온라인 모드 지원.
REM (오프라인 로컬 모드는 Apple Silicon Mac 전용)
cd /d "%~dp0"

if not exist ".venv" (
  echo [!] .venv 가 없습니다. 먼저:
  echo     python -m venv .venv ^&^& .venv\Scripts\activate ^&^& pip install -r requirements.txt
  exit /b 1
)
if not exist ".env" (
  echo [!] .env 가 없습니다. copy .env.example .env 후 GEMINI_API_KEY 를 채우세요.
  exit /b 1
)

call ".venv\Scripts\activate.bat"

echo 🎤 설교 실시간 자막 서버 시작...
echo    송출 화면:   http://localhost:8000/
echo    운영자 화면: http://localhost:8000/operator
echo    셀폰 자막:   http://(이PC의IP):8000/m
echo    (종료: Ctrl+C)
echo.

python -m server
