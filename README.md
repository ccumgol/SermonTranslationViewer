# 설교 실시간 다국어 자막 시스템 (translateViewer)

한국어 설교 음성을 실시간으로 여러 언어 자막으로 번역해 프로젝터/OBS 화면에
송출하는 시스템입니다. **온라인(Gemini)** 과 **오프라인(로컬 모델)** 두 가지
번역 백엔드를 운영자 화면에서 즉시 전환할 수 있습니다.

> 📖 English: [README.en.md](README.en.md)
> 🛠 설치·운영 매뉴얼: [docs/setup-guide.md](docs/setup-guide.md)
> 🎓 개발 중 만난 에러와 해결 과정(교육용): [docs/troubleshooting-log.md](docs/troubleshooting-log.md)

## 핵심 기능

- **다국어 동시 출력**: 목표 언어 1~3개를 동시에, 화면을 행으로 나눠 표시 (행별 글자색 지정)
- **온라인/오프라인 2-track**: 운영자 화면 배지 클릭으로 실시간 전환 (인터넷 끊기면 폴백)
- **15분 세션 제한 무중단 우회**(온라인): 설교는 30~45분이므로 세션 재개 자동 처리
- **운영자 대시보드**: 오디오 소스 전환, 자막 스타일, 리셋, 송출 종료/재개를 예배 중 화면에서 제어
- **OBS/프로젝터 송출**: 검정 풀스크린 또는 그린스크린(크로마키) 배경

## 두 가지 번역 백엔드

| | 온라인 (gemini) | 오프라인 (local) |
|---|---|---|
| 엔진 | `gemini-3.5-live-translate-preview` (음성→번역 단일 모델) | Qwen3-ASR(STT) + TranslateGemma(MT) |
| 정확도 | 최고 (노이즈에도 강함) | 양호 (조용한 환경·또렷한 발화에서 좋음) |
| 지연 | 1~3초 | 2~4초 (발화 후 멈추면 전사) |
| 비용 | 약 $0.037/분 × 언어 수 | **0 (인터넷 불필요)** |
| 요구 | API 키 + 인터넷 | Apple Silicon Mac + 로컬 모델 |

오프라인 구조: **STT 한국어 전사 1회(공유) → 언어별 번역 N회** 라 다국어에 효율적입니다.

## 빠른 시작 (온라인)

```bash
# 1) 가상환경 + 의존성
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2) 환경설정 (API 키 입력)
cp .env.example .env
#   → .env 를 열어 GEMINI_API_KEY 입력 (발급: https://aistudio.google.com/apikey)

# 3) 오디오 입력 장치 확인
python server/audio_input.py --list
#   → .env 의 AUDIO_INPUT_DEVICE 에 인덱스/이름 입력 (예: 2)

# 4) 실행
./start.sh          # 또는  python server/ws_server.py
```

- 송출 자막 화면: <http://localhost:8000/>  (OBS 브라우저 소스로 사용)
- 운영자 대시보드: <http://localhost:8000/operator>

## 오프라인(로컬) 모드 추가 설치

```bash
pip install -r requirements-offline.txt   # mlx-qwen3-asr
brew install ollama ffmpeg                 # 이미 있으면 생략
ollama pull translategemma:12b             # 번역 모델 (~8GB)

BACKEND=local ./start.sh                    # 오프라인으로 시작
```
> Apple Silicon(M1 이상) 필요. 실행 후 운영자 화면 배지를 클릭하면 온라인↔오프라인 전환됩니다.

## 운영자 대시보드 기능

예배 중 터미널·`.env` 를 건드릴 필요 없이 모든 조작을 화면에서 합니다.

| 기능 | 설명 |
|---|---|
| **백엔드 토글** | 상단 배지 클릭 → 온라인↔오프라인 실시간 전환 (언어 구성 유지) |
| **번역 언어** | 슬롯 3개로 1~3개 언어 선택, 각 언어 글자색 지정 |
| **오디오 입력 소스** | 드롭다운으로 입력 장치 즉석 변경 (**세션 끊김 없음**) + 🔄 목록 새로고침 |
| **🖥 송출 창 열기** | 메뉴/주소창 없는 별도 창. 더블클릭으로 전체화면 |
| **↺ 화면 리셋** | 누적 자막 즉시 비움 |
| **⏹ 송출 종료 / ▶ 재개** | 송출 화면만 비움(번역은 계속, 운영자 화면엔 표시) |
| **스타일** | 폰트 크기 · 배경색(검정/그린스크린) · 안여백 실시간 조절 |

> 송출 화면을 새로 열거나 OBS 를 재시작해도, 서버가 현재 상태(스타일·언어·송출상태)를
> 자동 동기화합니다.

## 개인정보 / 민감정보 관리

| 항목 | 위치 | 보호 방식 |
|---|---|---|
| Gemini API 키 | `.env` | `.gitignore` 로 git 제외, 코드 하드코딩 금지 |
| 설교 원고·로그·용어집 | `data/` | git 제외 (`.gitkeep` 만 포함) |
| Claude 로컬 설정 | `.claude/` | git 제외 |

## 구조

```
server/
  config.py             환경설정(.env) + 오디오 장치/백엔드 선택
  audio_input.py        입력 캡처 + 장치 실시간 전환 + 여러 세션용 fan-out
  translation_backend.py 번역 백엔드 추상화 + GeminiBackend(온라인)
  live_session.py       Gemini Live + 15분 세션 재개
  local_backend.py      오프라인: Qwen3-ASR(VAD 전사) + TranslateGemma
  subtitle_engine.py    자막 누적 + rolling 표시
  ws_server.py          FastAPI WebSocket + 화면 라우팅 + 제어 (엔트리포인트)
web/
  subtitle-overlay/     송출용 풀스크린 자막 (다국어 행·색상)
  operator/             운영자 대시보드
data/                   원고·로그·용어집 (git 제외)
```

## 실행 명령 요약

| 목적 | 명령 |
|---|---|
| 온라인 시작 | `./start.sh` (또는 `sermon`) |
| 오프라인 시작 | `BACKEND=local ./start.sh` |
| 종료 | `Ctrl+C` |
| 실행 중 전환 | 운영자 화면 백엔드 배지 클릭 |
