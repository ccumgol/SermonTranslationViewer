# 설교 실시간 자막 서버 실행 (Windows PowerShell). 온라인 모드 지원.
# (오프라인 로컬 모드는 Apple Silicon Mac 전용)
Set-Location -Path $PSScriptRoot

if (-not (Test-Path ".venv")) {
  Write-Host "[!] .venv 가 없습니다. 먼저:" -ForegroundColor Yellow
  Write-Host "    python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt"
  exit 1
}
if (-not (Test-Path ".env")) {
  Write-Host "[!] .env 가 없습니다. copy .env.example .env 후 GEMINI_API_KEY 를 채우세요." -ForegroundColor Yellow
  exit 1
}

. .\.venv\Scripts\Activate.ps1

Write-Host "🎤 설교 실시간 자막 서버 시작..."
Write-Host "   송출 화면:   http://localhost:8000/"
Write-Host "   운영자 화면: http://localhost:8000/operator"
Write-Host "   셀폰 자막:   http://(이PC의IP):8000/m"
Write-Host "   (종료: Ctrl+C)"
Write-Host ""

python -m server
