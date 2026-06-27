# 설교 실시간 다국어 자막 시스템 (translateViewer)

교회 믹서로 들어온 한국어 설교 음성을 **Gemini Live Translate** 로 실시간 영어
번역하여, 프로젝터/OBS 화면에 자막으로 송출하는 시스템입니다.

## 핵심 설계 (공식 문서 검증 반영)

- 모델: `gemini-3.5-live-translate-preview` (실시간 음성 번역 전용)
- 입력 오디오: **16kHz / mono / 16-bit PCM little-endian**, 100ms 청크
- **15분 세션 제한 무중단 우회**: 설교는 30~45분이므로 세션 재개
  (session resumption) + `go_away` 처리를 기본 탑재 → [server/live_session.py](server/live_session.py)
- **자막만 수신**(번역 음성 오디오 OFF): 출력 토큰 비용(입력의 ~6배) 절감 + 지연 감소
- 비용 감각: 약 **$0.037/분** → 40분 설교 1회 ≈ $1.5 미만

## 개인정보 / 민감정보 관리

| 항목 | 위치 | 보호 방식 |
|---|---|---|
| Gemini API 키 | `.env` | `.gitignore` 로 git 제외. 코드에 하드코딩 금지 |
| 설교 원고 | `data/sermons/` | git 제외 |
| 전사/번역 로그 | `data/logs/` | git 제외 |
| 용어집(인명 등) | `data/glossary/` | git 제외 |

`.env.example` 만 저장소에 포함되며, 실제 키가 담긴 `.env` 는 절대 커밋되지 않습니다.

## 빠른 시작

```bash
# 1) 가상환경 + 의존성
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2) 환경설정 (API 키 입력)
cp .env.example .env
#   → .env 를 열어 GEMINI_API_KEY 입력
#   → API 키 발급: https://aistudio.google.com/apikey

# 3) 오디오 입력 장치 확인 (믹서 연결)
python server/audio_input.py --list      # 장치 목록에서 인터페이스 찾기
python server/audio_input.py --monitor --device "장치이름"   # 레벨 점검
#   → .env 의 AUDIO_INPUT_DEVICE 에 장치 이름/인덱스 입력

# 4) 서버 실행
python server/ws_server.py
```

- 송출 자막 화면: <http://localhost:8000/>  (OBS 브라우저 소스로 이 주소 사용)
- 운영자 대시보드: <http://localhost:8000/operator>

## 운영자 대시보드 기능

예배 중 터미널·`.env` 를 건드릴 필요 없이 모든 조작을 화면에서 한다.

| 기능 | 설명 |
|---|---|
| **오디오 입력 소스 전환** | 드롭다운으로 입력 장치를 즉석 변경. **세션이 끊기지 않음**(입력 스트림만 교체). 무선 마이크 장애 시 내장 마이크로 1클릭 전환 |
| **🔄 목록 새로고침** | 예배 중 USB 인터페이스를 새로 연결해도 장치 목록 갱신 |
| **↺ 화면 리셋** | 누적된 자막(한/영)을 즉시 비움 |
| **⏹ 송출 종료 / ▶ 재개** | 송출 화면만 비움(번역은 계속 동작, 운영자 화면엔 계속 표시) |
| **스타일** | 폰트 크기·글자색·배경색·배경 투명도를 실시간 조절 → 송출 화면 즉시 반영 |
| **자동 줄바꿈** | 문장이 끝나고 일정 시간(기본 2초) 쉬면 다음 문장을 새 줄에서 시작 |

> 송출 화면(OBS 브라우저 소스 포함)을 새로 열어도, 서버가 현재 스타일·송출상태·
> 마지막 자막을 자동 전송하므로 항상 같은 상태로 동기화된다.

자세한 설치/운영은 [docs/setup-guide.md](docs/setup-guide.md) 참고.

## 구조

```
server/
  config.py           환경설정 로드 (.env), 오디오 장치 파싱
  audio_input.py      믹서 입력 → 16kHz mono PCM 캡처 + 장치 실시간 전환
  live_session.py     Gemini Live + 15분 세션 재개 (★핵심)
  subtitle_engine.py  조각 누적 + rolling 표시 + 인터벌 줄바꿈
  ws_server.py        FastAPI WebSocket + 화면 라우팅 + 송출 제어 (엔트리포인트)
web/
  subtitle-overlay/   송출용 풀스크린 자막 (스타일/리셋/송출토글 반영)
  operator/           운영자 대시보드 (모니터링 + 송출 제어)
data/                 원고·로그·용어집 (git 제외)
```

## 로드맵

- [x] Phase 1: 오디오 → 실시간 번역 자막 MVP (세션 재개 포함)
- [x] Phase 2: WebSocket 자막 송출 + 운영자 화면
- [ ] Phase 3: 용어집 주입, SQLite 로그, 원고 매칭(원고 있는 주 한정)
