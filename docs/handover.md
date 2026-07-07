# 프로젝트 인수인계 보고서 (translateViewer)

> 영문: [handover.en.md](handover.en.md)
> 함께 볼 문서: [README.md](../README.md) · [setup-guide.md](setup-guide.md) · [troubleshooting-log.md](troubleshooting-log.md)

이 문서는 후임 개발자가 이 프로젝트의 **의도·구조·결정 이유·함정**을 빠르게 이해하고
개발을 이어갈 수 있도록 작성한 종합 인수인계 문서입니다.

---

## 1. 한 줄 요약 / 기획 의도

**한국어 설교 음성을 실시간으로 여러 언어 자막으로 번역해 프로젝터·OBS·교인 폰에 송출하는 시스템.**

- 배경: 교회에 외국인·다국어 교인이 늘면서, 설교를 실시간으로 통역·자막화할 필요가 생김.
- 목표: ① 실시간성(수 초 지연) ② **정확도**(설교는 단어 하나가 신학적 의미를 바꿈)
  ③ 운영 편의(비개발자 봉사자가 화면에서 조작) ④ **비용/오프라인 대비**.
- 핵심 철학: **"실시간 AI 번역 하나에 모든 신뢰를 걸지 않는다."** 원고 기반 보정 +
  실시간 보완, 온라인/오프라인 이중화로 안정성을 확보.

---

## 2. 큰 그림 아키텍처

```
[믹서/마이크] → 오디오 캡처(16kHz mono PCM) → fan-out(복제)
                                               │
                        ┌──────────────────────┴───────────────────────┐
                        ▼                                               ▼
                [온라인: GeminiBackend]                        [오프라인: LocalBackend]
        언어마다 Gemini Live 세션(음성→번역)          공유 STT(Qwen3-ASR, 한국어) 1회
        각 세션이 자막 텍스트 반환                     → 언어별 TranslateGemma 번역 N회
                        └──────────────────────┬───────────────────────┘
                                               ▼
                            자막 안정화(RollingTranscript) + 원고/용어집 교정
                                               ▼
                        WebSocket 브로드캐스트(FastAPI) → 화면들
                     송출(/)  ·  운영자(/operator)  ·  모바일(/m)  ·  QR(/qr-view)
```

- **온라인**과 **오프라인**은 `TranslationBackend` 인터페이스로 추상화되어 있고,
  운영자 화면에서 **실시간 전환** 가능(같은 오디오 파이프라인·UI 공유).
- 오디오는 하나인데 여러 언어 세션에 뿌려야 하므로 **fan-out**(오디오 복제)이 핵심.

---

## 3. 파일별 역할 (server/)

| 파일 | 역할 | 알아둘 점 |
|---|---|---|
| `ws_server.py` | **엔트리포인트**. FastAPI + WebSocket 허브 + 상태(AppState) + 워커 관리 + 명령 처리 + 각종 엔드포인트 | 가장 큼. 대부분의 오케스트레이션이 여기 있음 |
| `config.py` | `.env` 로드, 오디오 장치 파싱, 백엔드/토큰 선택 | 로컬 모드는 API 키 없어도 동작(키를 선택적으로 읽음) |
| `audio_input.py` | `AudioCapture`(캡처+장치전환), `AudioFanout`(복제), `queue_chunks` | 콜백은 PortAudio 스레드 → 루프 스레드에서 drop-oldest 로 큐 적재 |
| `translation_backend.py` | `TranslationBackend`/`TranslationSession` 프로토콜 + `GeminiBackend` | 세션 인터페이스: `run/set_target_language/stop` |
| `live_session.py` | Gemini Live 세션 래퍼. **15분 세션 재개**, 런타임 언어 변경, 용어집 system_instruction | preview 모델 SDK 필드명에 의존 → 스펙 변화 시 여기부터 확인 |
| `local_backend.py` | 오프라인: `KoreanSTT`(VAD 전사) + `LocalSession`(언어별 번역) + `LocalBackend` | 여러 개선(문장 단위·예열·전용 executor·원고/용어집)이 이 파일에 집약 |
| `subtitle_engine.py` | `RollingTranscript`(조각 누적, 시간 기반 줄바꿈, tail 유지) | 순수 로직 → 테스트 있음 |
| `glossary.py` | 용어집 로드/치환(fix)/번역힌트(term) | STT context 대신 **후처리 치환** 방식(환각 방지) |
| `sermon_script.py` | 설교 원고에서 용어 추출 + **발음 유사도 전사 교정** | 음절 편집거리 1 이내 보수적 교정 |
| `languages.py` | 지원 언어 단일 정의(코드/라벨/영어이름) | ws_server·local_backend 가 공유(중복 방지) |
| `transcript_logger.py` | 선택적 전사/번역 JSONL 로깅 | `LOG_TRANSCRIPTS=1` 일 때만 |
| `__main__.py` | `python -m server` 진입점 | start.sh 가 사용 |

### web/
- `subtitle-overlay/` — 송출 화면(언어별 행, 영역/줄수 제한, 전체화면, PWA). 배경색 단색(그린스크린 가능).
- `operator/` — 운영자 대시보드(모든 제어 + i18n 한/영). 가장 복잡한 프런트.
- `mobile/` — 교인 폰용(`/m`). 언어 선택 후 해당 언어 자막만.
- `qr-view/` — QR 큰 화면(`/qr-view`, 별도 창).

### data/ (git 제외)
- `sermons/current_script.txt`(원고), `logs/*.jsonl`(로그), `glossary/glossary.txt`(용어집).
  `glossary.example.txt` 만 저장소에 포함.

---

## 4. 핵심 설계 결정과 이유 (변곡점)

후임이 "왜 이렇게 했나"를 이해하는 게 가장 중요합니다.

1. **온라인 엔진: Gemini Live Translate 전용 모델**
   - `gemini-3.5-live-translate-preview` 는 음성→번역을 **한 모델**로 처리(STT+MT 분리보다 단순·정확).
   - 입력 16kHz mono 16-bit PCM little-endian, 100ms 청크(공식 문서 스펙).

2. **15분 세션 제한 → 세션 재개(가장 중요한 온라인 설계)**
   - 오디오 단독 세션은 15분에 강제 종료. 설교는 30~45분 → **session_resumption 핸들 + go_away
     처리로 무중단 재연결**. 없으면 설교 중간에 자막이 죽음. `live_session.py` 참고.

3. **텍스트만 수신(오디오 출력 OFF)**
   - `response_modalities=["TEXT"]` + input/output transcription. 번역 음성을 안 받아
     **출력 토큰 비용(입력의 ~6배) 절감 + 지연 감소**.

4. **언어 코드는 짧은 코드만** (`en` O, `en-US` ❌)
   - `translation_config.target_language_code` 에 지역 접미사(`en-US`)를 주면 **`1007 invalid
     argument`**. 실측으로 확정: `en/ja/zh/zh-CN/es/vi/fr/ru` OK, `en-US` 거부.

5. **개인 계정 + API 키(인증 경로 확정)**
   - 조직(Workspace) 계정은 API 키 발급 금지 정책. Vertex AI 엔 이 preview 모델이 없음.
     → **개인 Gmail + API 키(Tier1 결제)** 로 확정. (조직/Vertex 로는 이 전용 모델 못 씀)

6. **다국어 = 세션 N개 + 오디오 fan-out**
   - 한 세션 = 한 목표 언어. 동시 다국어는 **언어당 세션**을 띄우고 오디오를 복제해 공급.
     → **비용·연산 N배**(사용자에게 명시). 화면은 언어 수만큼 행으로 분할.

7. **온라인/오프라인 2-track(백엔드 추상화)**
   - `TranslationBackend` 인터페이스로 분리 → 오디오/자막/웹 UI 는 그대로 재사용.
     운영 중 토글 가능. **인터넷 장애 시 오프라인 폴백**이 교회엔 큰 가치.

8. **오프라인 스택: Qwen3-ASR(STT) + TranslateGemma(MT)**
   - 리서치로 선정: Qwen3-ASR 은 CJK 특화(한국어 강함), Apple Silicon MLX 네이티브.
     TranslateGemma 는 번역 전용(55개 언어), Ollama 로 로컬 서빙. 둘 다 오프라인·무료.
   - 오프라인 구조는 **STT 1회(공유) → 언어별 MT** 라 다국어에 더 효율적.

9. **오프라인 STT: 스트리밍 → VAD 발화구간 전사(결정적 전환)**
   - Qwen3-ASR **스트리밍 모드는 정확도가 붕괴**(오디오 누락, "이미.어" 같은 필러 환각).
     전체파일 전사는 거의 완벽. → **침묵(VAD)으로 발화 구간을 잘라 그 구간을 `transcribe()`
     로 통째 처리**해 전체파일급 정확도 확보. `local_backend.py` 의 KoreanSTT 참고.

10. **번역은 문장/발화 단위 + 모델 예열**
    - 단어 조각마다 무거운 MT 를 호출하면 큐가 밀림 → **발화 단위 1회 호출**. 시작 시 더미
      번역으로 **예열(warmup)** + `keep_alive` 로 첫 문장 콜드 지연 제거.

11. **모델 크기는 측정으로 결정**
    - STT: 1.7B 가 0.6B 보다 더 정확하지도 않고 느림 → **0.6B 유지**.
    - MT: 12B 는 정확하나 2배 느림 → 속도 불만 후 **4b 를 기본값**으로(품질 충분).

12. **자막 렌더링: rolling + 하단 고정 + 영역 제한**
    - 조각을 누적해 문장을 만들고 직전 문장을 유지(rolling). 화면은 **하단 절대고정 + 위쪽만
      잘라내기**로 항상 최신이 보이게. 단일 언어는 **하단/상단 밴드 + 줄 수 제한**으로 OBS 합성 대응.

13. **고유명사 정확도: 원고 교정 + 용어집(둘 다 후처리)**
    - STT context 에 단어 목록을 직접 주면 **그 목록을 토해내는 환각** 발생 → 폐기.
      대신 **전사 후 후처리**: ① 설교 원고에서 용어 추출 → 발음 유사도로 교정
      ("티브리어"→"히브리어"), ② 용어집 `fix:` 로 확정 치환. 전사가 맞으면 번역도 자동으로 맞음.

---

## 5. 기능 추가 연대기 (요약)

대략 이 순서로 진화했습니다(git 로그와 대응):

1. MVP: 오디오 → Gemini Live → 콘솔 자막, 15분 세션 재개.
2. WebSocket 자막 송출 + 운영자 화면.
3. 자막 안정화(조각 누적, 시간 기반 줄바꿈), 하단 고정으로 잘림 해결.
4. 다국어(1~3개) 동시 출력 + 행별 색상 + fan-out.
5. 오디오 소스 실시간 전환, 운영자 화면에서 언어/스타일/리셋/송출토글.
6. 오프라인 백엔드(Qwen3-ASR + TranslateGemma) 추가 + 백엔드 추상화 + 런타임 토글.
7. 오프라인 품질/속도: VAD 전사, 문장 단위 번역, 예열, 4b 기본, 종료 정리(executor).
8. 운영 편의: 비용/사용량 배지, 방송 시작/종료, 전사 로깅, 보안 토큰, /health, 패키지 실행, Windows 스크립트, 자동 브라우저 열기.
9. 송출 화면: 검정 풀스크린/그린스크린, 전체화면·PWA, 출력 영역/줄수 제한.
10. 정확도: 용어집 배선(로컬+Gemini), 번역 문맥(직전 문장), **설교 원고 교정**.
11. UI: 한/영 i18n 전환.
12. 모바일: `/m` 페이지, **모바일 주소/QR 추출**(LAN IP 검출 + 로컬 QR 생성), QR 별도 창.

---

## 6. 발생했던 주요 에러와 해결 (핵심만)

전체는 [troubleshooting-log.md](troubleshooting-log.md) 참고. 특히 기억할 것:

| 증상 | 원인 | 해결 |
|---|---|---|
| `1007 invalid argument`(오디오 전송 시) | 언어 코드 `en-US` | 짧은 코드(`en`) 사용 |
| `1011 credits depleted` | 선불 크레딧 소진 | 충전/후불 |
| 조직계정 API 키 거부 / Vertex 에 모델 없음 | 정책·미지원 | 개인계정 + API 키 |
| 봇 탐지 "suspicious" | 자동화로 프로젝트/키 생성 | 사람이 수동 생성 |
| `ModuleNotFoundError: sounddevice` | venv 미활성화 | `source .venv/bin/activate`(start.sh 가 처리) |
| 자막 위아래 반쪽 잘림 | 행 세로 가운데 정렬 | 하단 절대고정 + 위쪽만 클리핑 |
| 종료 시 `Event loop is closed` | STT 를 기본 스레드풀(to_thread)로 | **전용 ThreadPoolExecutor** + `aclose()` |
| STT 가 성경 용어 목록 토함 | STT context 에 긴 목록 주입 | context 제거, **후처리 교정**으로 전환 |
| 라이브 전사 붕괴(필러 환각) | Qwen3-ASR 스트리밍 모드 | **VAD 발화구간 전사** |
| 첫 문장 ~18초 지연 | 로컬 MT 콜드 로딩 | 시작 시 **예열** + keep_alive |
| 문장 중간 마침표 | 숨 멈춤/8초 강제분할 지점에 마침표 | 강제분할 마침표 제거 + 침묵기준 0.9초↑ |
| git push 거부 | 원격이 앞섬 | `git pull --rebase` |

**디버깅 원칙(교훈)**: 추측 말고 **작은 재현 스크립트로 실측**, 에러를 **계층(인증/권한/결제/데이터)으로 구분**,
학습 시점 이후 스펙은 **공식 문서로 검증**.

---

## 7. WebSocket 프로토콜 (요약)

- **클라이언트 → 서버 명령**(운영자, 토큰 필요 시 `token` 포함):
  `reset`, `set_output{enabled}`, `set_style{style}`, `set_languages{languages:[{code,color}]}`,
  `set_broadcast{active}`, `set_backend{backend}`, `set_device{device}`, `list_devices`,
  `set_script{text}`.
- **서버 → 클라이언트 메시지**:
  `init`(전체 상태 동기화), `source`(한국어), `subtitle{lang,text}`, `layout`, `reset`,
  `output_state`, `broadcast_state`, `backend_state`, `backend_error`, `auth_error`,
  `device_state/list/error`, `style`, `usage`, `script_state`.
- HTTP 엔드포인트: `/`, `/operator`, `/m`, `/qr-view`, `/qr.svg?text=`, `/lan-info`,
  `/manifest.webmanifest`, `/health`.

---

## 8. 환경변수 총람 (`.env`)

| 변수 | 기본 | 설명 |
|---|---|---|
| `GEMINI_API_KEY` | — | 온라인 키(로컬 전용이면 불필요) |
| `GEMINI_MODEL` | gemini-3.5-live-translate-preview | 온라인 모델 |
| `BACKEND` | gemini | 시작 백엔드(gemini/local) |
| `TARGET_LANGUAGE` | en | 시작 목표 언어(짧은 코드) |
| `AUDIO_INPUT_DEVICE` | (기본입력) | 숫자=인덱스, 문자=이름 |
| `WS_HOST` / `WS_PORT` | 0.0.0.0 / 8000 | 서버 바인딩 |
| `OPERATOR_TOKEN` | (없음) | 운영자 명령 보호 토큰 |
| `AUTO_START` | 1 | 0이면 방송 종료 상태로 시작 |
| `OPEN_BROWSER` | 1 | start.sh 자동 브라우저 열기 |
| `LOG_TRANSCRIPTS` | (off) | 1이면 data/logs 에 JSONL |
| `COST_PER_MIN` / `IDLE_WARN_MIN` | 0.037 / 5 | 사용량 배지 |
| `MT_MODEL` | translategemma:4b | 오프라인 번역 모델 |
| `STT_MODEL` | Qwen/Qwen3-ASR-0.6B | 오프라인 STT 모델 |
| `STT_MIN_SILENCE_SEC` | 0.9 | 발화 끊는 침묵(↑면 문장 단위·지연↑) |
| `STT_MAX_SEGMENT_SEC` | 8 | 강제 분할 상한 |
| `STT_SILENCE_RMS` | 0.015 | 침묵 음량 임계값 |

---

## 9. 알려진 한계와 향후 과제

**한계**
- 오프라인 다국어는 언어당 MT 호출 → 언어가 늘수록 느려짐(GPU 공유).
- 온라인(Gemini) 은 자기 번역을 서버가 만들어 주므로, 원고 교정은 **표시(한국어)만** 바로잡고
  Gemini 의 번역 자체는 못 고침(로컬은 번역 전 교정이라 둘 다 고쳐짐).
- 무발화 시 **자동 일시정지 없음**(경고만) — 예배 중 자동 중단은 위험해 의도적으로 보류.
- VAD 가 문장 중간을 자르면 번역 문맥이 끊길 수 있음(직전 문장 문맥으로 일부 완화).
- i18n 은 사전 방식 → 언어 3개 이상이면 **로케일 파일 분리** 권장.
- 15분 세션 재개는 preview SDK 필드명에 의존 → 모델/ SDK 변경 시 깨질 수 있음.

**향후 과제(우선순위 제안)**
1. **VAD 문장 재조합**: 강제 분할된 조각을 문장 끝까지 모아 한 번에 번역(정확도↑).
2. **비용 자동 가드**: 무발화 N분 후 자동 방송 종료(옵션).
3. **UI 다국어 확장**: 로케일 JSON + 플레이스홀더/복수 처리.
4. **STT 가속**: draft-model(speculative decoding) 로 전사 속도↑.
5. **로그 고도화**: SQLite + 사후 검토 UI, 세션별 통계.
6. **Gemini 번역 보정**: system_instruction 강화 또는 출력 후처리 치환.

---

## 10. 개발·운영 노트

- **저장소**: https://github.com/ccumgol/SermonTranslationViewer (main 브랜치가 안정).
  기능은 브랜치에서 작업 후 `--no-ff` 병합. `.env`·`data/`·`.claude/` 는 git 제외.
- **테스트**: `GEMINI_API_KEY=test python -m pytest tests/ -q` (순수 로직 20+개).
  실제 모델·오디오는 자동화 어려움 → 라이브 확인 필요.
- **실행**: `./start.sh`(자동 브라우저) / `python -m server` / Windows `start.bat`·`start.ps1`.
- **리소스**: 오프라인은 MLX(Metal GPU) + Ollama(12B/4B) 로 RAM·GPU 를 크게 씀. 24GB 에서
  4b 권장. 안 쓸 땐 방송 종료·`ollama stop` 으로 메모리 반환.
- **Antigravity IDE 크래시**: 이 프로젝트를 IDE로 열면 `.venv`(수천 파일) 인덱싱 + 로컬 모델
  리소스 압박으로 공유 백엔드 서버가 죽어 **모든 창이 리로드**를 요구할 수 있음. 해결:
  IDE 설정에서 `.venv/`·`data/`·`__pycache__` 를 **인덱싱/워처에서 제외**.

---

## 11. 후임을 위한 조언

- **먼저 읽을 것**: 이 문서 → `ws_server.py`(오케스트레이션) → `local_backend.py`(오프라인 핵심)
  → `live_session.py`(온라인 핵심) → 웹 `operator/index.html`.
- **손대기 전 실측**: 특히 모델 스펙(코드값·필드명)은 작은 스크립트로 확인 후 반영.
- **온라인/오프라인 대칭성**을 깨지 않게: 새 기능은 가능하면 `TranslationBackend` 뒤에서 처리.
- **정확도 우선**: 설교 특성상 오역 위험이 크다. 원고 교정·용어집을 적극 활용/개선.
- **비용 감각**: 온라인은 언어 수 × 분 단위 과금. 방송 종료·자동 가드로 낭비 방지.
- **되돌릴 수 있게**: 큰 변경은 브랜치 + 테스트. main(동작본) 보호.
