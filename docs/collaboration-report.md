# 협력 보고서 (Collaboration Report)

> **여러 AI Agent / 개발자가 이 프로젝트를 동시에 작업할 때 상태를 공유하는 문서입니다.**
> 영문: [collaboration-report.en.md](collaboration-report.en.md)
> 관련: [analysis-report.md](analysis-report.md) (진단·제안) · [handover.md](handover.md) (설계 배경) · [setup-guide.md](setup-guide.md) (운영)

**최근 갱신**: 2026-07-26 · 갱신자: Claude (Agent C, Opus 4.8) · 기준 커밋: `978f0fb` + 미커밋 작업분

---

## 0. 이 문서 사용 규칙 (중요)

작업을 시작·완료할 때 **이 문서를 먼저 읽고, 끝나면 갱신**해 주세요. 목적은 **중복 작업과
충돌 방지**입니다.

1. **착수 전**: 4장(작업 보드)에서 그 항목이 `🔴 미착수` 인지 확인하고, `🟡 진행중`으로 바꾸고
   본인 이름(Agent 명)과 날짜를 적습니다.
2. **완료 후**: `🟢 완료`로 바꾸고 **검증 방법과 결과**를 5장에 한 줄 남깁니다.
   (주장만 쓰지 말고 "무엇으로 확인했는지" 적어주세요)
3. **파일 충돌 주의**: 5장 "파일별 점유 현황"에서 다른 Agent가 만지는 파일과 겹치면
   먼저 6장 "인계 메모"에 남기고 조율합니다.
4. **커밋 정책 (2026-07-08 변경)**: Agent 가 작업 완료 후 **직접 커밋·푸시합니다.**
   - 논리적 단위로 나눠 커밋하고(성격이 섞이면 분리), 메시지에 **원인·조치·검증**을 담습니다.
   - ⚠️ **푸시 전 민감정보 점검 필수**: `git diff --name-only origin/main..HEAD` 로
     `.env`·토큰·`data/` 가 포함되지 않았는지 확인. (3.2 사고 참고)
   - 협업 중이므로 푸시 실패 시 `git pull --rebase` 후 재시도합니다.
   - **이력 재작성(force push, filter-repo)은 사용자 승인 필요** — 다른 Agent 작업을 깨뜨릴 수 있음.
   - (이전 방침은 "사용자가 커밋"이었으나 자동화로 전환됨)
5. **착수할 때 "복구 정보"를 먼저 쓴다** (⚠️ 가장 중요 — 아래 0.1 참고).
   사용량 만료·크래시는 예고 없이 오므로, **끝난 뒤 쓰는 기록은 남지 않습니다.**

---

## 0.1 중단(사용량 만료·크래시·강제 종료) 대응 규칙 ★필수

Agent 작업은 **토큰/사용량 소진, 세션 만료, 크래시**로 언제든 중간에 끊길 수 있습니다.
그 경우 "완료 후 갱신" 규칙만 있으면 보드에 `🟡 진행중` 만 남아, 다른 Agent 가
**"누가 하는 중이니 손대지 말자"** 고 오해해 작업이 정지합니다.

### 규칙 A — 착수 즉시 3줄을 먼저 기록 (선행 기록)
작업을 시작하면 **코드를 만지기 전에** 8장(진행 중 작업 로그)에 다음을 씁니다.
```
- [시작 2026-07-08 14:30 / Agent B] H-3 명령 rate limit
  계획: ws_server.py 의 _handle_command 앞에 쿨다운 검사 추가 / 기준 2초
  다음 단계: 쿨다운 상수 결정 → 구현 → 재현 테스트(연타) → 문서 갱신
```
중단돼도 **이 기록이 남아** 다음 Agent 가 이어받을 수 있습니다.

### 규칙 B — 긴 작업은 단계마다 한 줄 갱신
30분 이상 걸릴 작업은 단계가 끝날 때마다 `다음 단계:` 줄만 고칩니다.
(마지막으로 갱신된 지점이 곧 **중단 지점**입니다)

### 규칙 C — 이어받는 Agent 의 판정 절차
`🟡 진행중` 인데 담당자가 응답 없거나 오래됐다고 판단되면 **아래 근거로 직접 확인**하세요.
추측하지 말고 실제 상태를 보고 판단합니다.

```bash
# 1) 미커밋 변경 = 진행 중이던 흔적 (무엇을 만지고 있었는지)
git status --short
git diff                     # 어디까지 고쳤는지

# 2) 파일 수정 시각 = 마지막 활동 시점 (중단 시각 추정)
ls -lt server/*.py web/**/*.html docs/*.md | head

# 3) 남은 잔여물 확인
git stash list               # 중단 전 stash 했을 수 있음
git branch --no-merged main  # 미병합 작업 브랜치

# 4) 코드가 실제로 동작하는 상태인지 (반쯤 고친 상태일 수 있음)
python3 -m py_compile server/*.py
GEMINI_API_KEY=test python3 -m pytest tests/ -q
```

**판정 기준 (제안)**
| 상황 | 판정 | 조치 |
|---|---|---|
| 미커밋 변경 있음 + 파일 수정이 **수 시간 이상 전** | 중단됨 | 8장 로그를 읽고 이어받기. 상태를 `🟡 진행중(인계: 본인)` 으로 갱신 |
| 미커밋 변경 없음 + 보드만 `🟡` | **착수 직후 중단** | 그 항목은 사실상 미착수 → `🔴` 로 되돌리고 새로 시작 |
| 테스트/컴파일 실패 | **반쯤 고친 상태** | 먼저 그 부분을 완성하거나 되돌린 뒤 진행 (사용자에게 보고) |
| 판단이 애매함 | — | **사용자에게 확인** (임의로 되돌리지 말 것) |

### 규칙 D — 되돌리기는 사용자 승인 후
중단된 작업의 미커밋 변경을 **버리는 것(`git checkout --`, `git stash drop`)은 사용자 승인
없이 하지 않습니다.** 다른 Agent 의 미완성 작업일 수 있고, 커밋 전이라 복구가 불가능합니다.

### 규칙 E — 사용자가 할 수 있는 최소 조치
Agent 가 갑자기 멈췄을 때 사용자는 다음 한 줄만 남겨도 충분합니다.
```
- [중단 2026-07-08 15:10] Agent B 사용량 만료로 중단. 위 항목 이어받을 Agent 필요.
```

---

## 1. 참여자 및 역할 기록

| 참여자 | 담당·기여 | 최근 작업일 |
|---|---|---|
| **사용자 (소유자)** | 요구사항 정의·우선순위 결정, 실기기 테스트, 결제·API 키 관리, 방향 승인 | 계속 |
| **Agent A** (분석 담당) | 코드베이스 정밀 분석 → [analysis-report.md](analysis-report.md) 작성(보안 CRITICAL 2건 등 발견) | 2026-07-07 |
| **Agent B / Claude** (구현 담당) | 초기 전체 구현 + 문서화, 분석 결과 검증 및 **보안 1단계 하드닝** 구현 | 2026-07-08 |
| **Agent C / Claude** (Opus 4.8) | 운영자 화면 사용성 수정: 전사영역 스크롤 + 입력볼륨 부족 경고(오프라인 STT 임계값 미달 진단) | 2026-07-26 |

> 협업 방식: **Agent A 가 진단 → 사용자가 우선순위 결정 → Agent B 가 구현·검증**
> 이 흐름이 잘 작동했습니다(분석의 CRITICAL 2건이 실제 취약점으로 재현·확인됨).

---

## 2. 프로젝트 현재 상태 요약

| 항목 | 상태 |
|---|---|
| 기능 완성도 | **운영 가능**. 온/오프라인 2-track, 다국어 1~3개, 모바일 자막·QR, 원고 교정 등 |
| 테스트 | **72개 통과** — 단위 20 + WS·인증 11 + 남용방지 8 + 스타일 10 + 정보노출 16 + VAD재조합 7 |
| 문서 | README·setup-guide·troubleshooting·handover·analysis (한/영) |
| 보안 | **C-1·C-2·H-1·H-3·H-4·M-1·M-2·M-3·M-5·L-1 완료**. 남은 항목: H-2(HTTPS/WSS) — 외부 노출 시에만 필요 |
| 배포 | 로컬 LAN 전제. main 은 안정, 기능은 브랜치에서 작업 후 병합 |

---

## 3. 최근 완료된 작업 (2026-07-08, 보안 1단계)

Agent A 의 분석에서 지적된 CRITICAL 항목을 **재현 → 수정 → 재검증**했습니다.

### 수정 전 실제 재현된 취약점
```
✅ 접속 성공 (Origin=evil.example.com 인데도 거부되지 않음)
⚠️  토큰 없이 방송 종료 실행됨 → active = False
```
> 즉 "신뢰된 LAN" 전제만으로는 방어되지 않음이 실증됨. Agent A 의 진단이 정확했습니다.

### 적용한 수정
| ID | 조치 | 파일 |
|---|---|---|
| **C-1** | WebSocket **Origin 검증** 후 accept, 불일치 시 `4403` close. 같은 호스트(Host 헤더)·localhost 허용, 비브라우저(Origin 없음) 허용, `ALLOWED_ORIGINS` 로 추가 허용 | `server/ws_server.py` |
| **C-2** | LAN 노출 시 **토큰 자동 생성**(`secrets.token_urlsafe(18)`) → "인증 없음" 상태 제거. 콘솔에 접속 URL 출력, `data/runtime/operator_url.txt`(권한 600)에 기록 → `start.sh` 가 그 URL 로 브라우저 오픈 | `server/config.py`, `server/ws_server.py`, `start.sh` |
| **H-1** | `hmac.compare_digest` 상수시간 비교 + **인증 실패 5회 시 연결 종료** + 실패당 0.5초 지연 | `server/ws_server.py` |

### 수정 후 검증 결과 (실제 실행)
```
C-1 외부 Origin 접속 : ✅ 차단됨 (InvalidStatus)
C-2 토큰 없이 명령   : ✅ 거부됨 (auth_error)
정상 운영자(토큰 O)  : ✅ 정상 동작 (active=False)     ← 기능 회귀 없음
H-1 브루트포스       : ✅ 연결 종료됨 (ConnectionClosedError)
모바일 자막(LAN IP)  : ✅ 정상 (192.168.1.190 접속 확인)
단위 테스트          : ✅ 20 passed
```

### 설계 판단 (다른 Agent 가 알아야 할 것)
1. **기동 거부(fail-fast) 대신 토큰 자동 생성**을 택함 — 예배 직전 서버가 안 뜨는 위험이 더 큼.
   운영자 체감은 이전과 동일(`start.sh` 가 토큰 URL 로 자동 오픈).
2. **Origin 허용 기준 = "브라우저가 접속한 Host 와 동일"** — 그래서 폰이 LAN IP 로 여는 `/m` 이
   그대로 동작함. 프록시·다른 도메인은 `ALLOWED_ORIGINS` 로.
3. `WS_HOST=127.0.0.1`(로컬 전용)은 **토큰을 만들지 않음** — 노출이 없어 불필요한 마찰 방지.
4. 토큰 파일은 이후 **저장소 밖**($TMPDIR)으로 이동함(3.2 사고 후 개선).

### 커밋 상태
보안 1단계는 커밋 `a3f4fe0` 으로 반영됨(사용자 커밋). 이후 후속 작업은
`a8ae88d`(토큰 파일 사고 수정) · `de0f376`(보안 테스트) · `5c52954`(협력 보고서)로 푸시됨.
`docs/analysis-report.md`, `.en.md` 는 Agent A 산출물이라 Agent B 가 수정하지 않음.

---

### 3.1 WS·인증 통합 테스트 (2026-07-08, Agent B)

보안 로직이 들어갔으므로 **회귀 방지 테스트**를 추가했습니다.

- 신규 파일: `tests/test_ws_security.py` (11개)
  - Origin: 외부 차단 / 같은 호스트 허용 / **모바일 LAN IP 허용** / Origin 없음 허용 / `ALLOWED_ORIGINS`
  - 인증: 토큰 없음·틀림 거부 / 정상 토큰 동작 / **실패 누적 시 연결 종료**
  - 토큰 자동생성: LAN 노출 시 생성 / 로컬 전용은 미생성
- 격리 방법: `lifespan` 이 오디오 장치·모델을 열기 때문에 **`pipeline` 을 모킹**해
  실제 하드웨어·외부 API 를 건드리지 않고 기동(다음 Agent 가 테스트 추가할 때 같은 패턴 사용).
- **실효성 검증(뮤테이션 테스트)**: 보안 코드를 일부러 무력화해 테스트가 실제로 잡는지 확인
  ```
  Origin 검증 무력화 → 1 failed  (정상: 취약점을 잡음)
  토큰 검사 무력화   → 3 failed  (정상)
  복원 후            → 31 passed, 코드 원상복구 diff 확인
  ```
  → "통과만 하는 무의미한 테스트"가 아님을 확인했습니다.
- 의존성: `httpx` 추가 설치 필요(`fastapi.testclient` 요구). `requirements-dev.txt` 반영.

---

### 3.2 ⚠️ 사고 기록: 토큰 파일이 공개 저장소에 커밋됨 (2026-07-08, 해결)

**같은 실수를 반복하지 않기 위해 남깁니다.**

- **무슨 일**: C-2 구현 시 운영자 토큰이 담긴 URL 을 `data/runtime/operator_url.txt` 에
  저장했는데, 이 파일이 커밋 `a3f4fe0` 에 포함되어 **PUBLIC 저장소에 푸시**되었습니다.
- **왜 막히지 않았나 (근본 원인 2개)**
  1. `.gitignore` 에 `data/runtime/   # 주석` 형태로 썼는데, **gitignore 는 줄 끝 인라인
     주석을 패턴의 일부로 해석**합니다. → 규칙이 전혀 작동하지 않았음.
     (`git check-ignore -v <파일>` 로 확인 가능)
  2. 그 사이 파일이 이미 `git add` 되어 **추적 상태**가 되었고, 추적 중인 파일은
     `.gitignore` 로 막을 수 없습니다.
- **실질적 위험도**: **낮음.** 자동생성 토큰은 **매 기동마다 새로 생성**되므로 노출된 값은
  이미 무효입니다(커밋된 값 ≠ 현재 값 확인). 고정 `OPERATOR_TOKEN` 을 쓰고 있었다면
  **즉시 교체가 필요한 심각한 사고**였습니다.
- **조치**
  1. `git rm --cached` 로 추적 중단(파일은 디스크에 유지 — 실행에 필요).
  2. `.gitignore` 주석을 **위 줄로 분리**해 규칙이 실제로 작동하도록 수정.
  3. **근본 해결**: 토큰 파일 위치를 저장소 밖(`$TMPDIR/translateviewer/`)으로 이동
     → **git 에 들어갈 경로 자체를 없앰**. `start.sh` 도 새 경로를 읽도록 수정.
- **교훈 / 다른 Agent 가 지킬 것**
  - 비밀정보를 파일로 남길 때는 **저장소 밖**에 두세요(`tempfile.gettempdir()`).
  - `.gitignore` 에 **인라인 주석을 쓰지 마세요**. 추가 후 반드시
    `git check-ignore -v <파일>` 로 실제 무시되는지 확인하세요.
  - 커밋 전 `git status` 에 예상치 못한 파일이 있는지 확인하세요.

---

### 3.3 남용 방지 상한 H-3 / H-4 (2026-07-08, Agent B)

기준값은 사용자 승인 후 적용.

| 항목 | 값 | 동작 |
|---|---|---|
| 명령 쿨다운 | **2초** (set_backend 는 **10초**) | 연타 시 `command_throttled` 브로드캐스트, 명령 무시 |
| 쿨다운 대상 | set_languages·set_backend·set_broadcast·set_device·set_script | reset·list_devices 등 무해한 명령은 제외(운영 편의) |
| 원고 최대 | **10만 자** | 초과분은 잘라서 적용 + `script_truncated` 알림 |
| 동시 연결 | **100** | 상한 도달 시 `4429` 로 거부 |
| 메시지 크기 | **512KB** | uvicorn `ws_max_size` (두 엔트리포인트 모두) |

- 모두 env 로 조정 가능(`COMMAND_COOLDOWN_SEC` 등, `.env.example` 참고).
- 운영자 화면에 throttle·truncate 안내 메시지 추가(한/영).
- 테스트 `tests/test_ws_limits.py` 8개. **뮤테이션 검증**: 쿨다운·원고상한·연결상한을
  각각 무력화하면 정확히 1건씩 실패 → 실효성 확인. 전체 **39 passed**.
- 실서버 확인: 명령 연타 시 `1차 script_state → 2차 command_throttled(retry_after=2.0)`.

**테스트 작성 시 주의(실제로 겪은 함정)**: 응답을 보내지 않는 명령(`set_device` 는
`state.capture is None` 이면 조용히 return)으로 `receive_json()` 을 기다리면 **테스트가 무한
대기**합니다. 응답이 보장되는 명령을 쓰거나, 응답 대신 **서버 상태·결과로 판정**하세요.

---

### 3.4 M-2 스타일 검증 + 모바일 언어 유지 (2026-07-08, Agent B)

**M-2 `set_style` 화이트리스트 검증** — 기존에는 임의 키가 그대로 상태에 병합되고
색상 길이도 무제한이어서, 쓰레기 값이 모든 클라이언트(송출 화면 포함)로 전파될 수 있었다.

| 항목 | 허용 범위 |
|---|---|
| `fontSize` | 숫자, 1~20 으로 클램프 |
| `padding` | 숫자, 0~30 |
| `maxLines` | 정수, 0~10 |
| `region` | `full`/`bottom`/`top` 만 |
| `bgColor` | `#RGB` 또는 `#RRGGBB` 형식만 |
| 그 외 키 | **제거** |

- bool 이 int 하위형인 파이썬 특성 때문에 `True` 가 숫자로 통과하지 않도록 명시적으로 배제.
- 언어 색상(`_sanitize_languages`)도 같은 형식 검증(`_is_hex_color`)을 쓰도록 강화
  (기존은 `#` 로 시작하는지만 확인).
- 실서버 확인: 악성 입력
  `{evil:"<script>", bgColor:"#zzz…3000자", fontSize:99999, region:"diagonal", maxLines:9999}`
  → 결과 `{fontSize:20, bgColor:"#000000", padding:4, region:"full", maxLines:10}` (전부 차단/클램프)
- 테스트 `tests/test_style_validation.py` 10개. **뮤테이션 검증**: 검증 함수를 통째로
  무력화하면 7건, 색상 검증만 무력화하면 2건 실패 → 실효성 확인. 전체 **49 passed**.

**7.2 모바일 언어 선택 유지** — 폰에서 고른 언어를 `localStorage` 에 저장해 재접속·새로고침
시 자동 복원. 첫 방문에 자동 선택된 언어도 저장한다. 사생활 보호 모드 등에서 저장이
실패해도 동작에 지장이 없도록 `try/catch` 로 감쌌다.

---

### 3.5 정보 노출·엔드포인트 보호 M-1 / M-3 / L-1 (2026-07-08, Agent B)

**M-1 init 정보 분리** — 예전에는 인증 없는 연결(교인 폰·송출 화면)에도 장치 목록·백엔드·
원고 용어 개수까지 보내, 주소만 아는 사람에게 내부 구성이 노출됐다.

| 구분 | 내용 |
|---|---|
| 공용 `init` (인증 불필요) | `style`, `output_enabled`, `layout`, `languages` — 화면 동작에 필요한 값만 |
| `operator_init` (인증 후 1회) | `devices`, `current_device`, `backend`, `broadcasting`, `script_terms`, `default_colors`, `max_languages` |

- 운영자 화면은 `init` 수신 직후 무해한 명령(`list_devices`)을 보내 **인증을 트리거**하고,
  그 응답으로 `operator_init` 을 받아 기존과 동일하게 동작한다.
- ⚠️ **주의(다른 Agent 용)**: 인증 성공 시 `operator_init` 이 **먼저** 오므로, 명령 응답을
  기다리는 테스트/코드는 이 메시지를 건너뛰어야 한다. 기존 테스트 3건이 이 때문에 깨져
  헬퍼(`_send`/`_cmd`)가 `operator_init` 을 스킵하도록 수정했다.

**M-3 `/qr.svg` 길이 상한** — 512자(`MAX_QR_TEXT_CHARS`) 초과 시 400. 상한이 없으면 임의
텍스트로 QR 을 대량 생성시켜 CPU 를 소모시킬 수 있다(오픈프록시 악용).

**L-1 보안 헤더** — 모든 HTTP 응답에 `X-Frame-Options: SAMEORIGIN`,
`X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
(특히 Referrer-Policy 는 **토큰이 담긴 URL** 이 외부로 새는 것을 막는다)

**실서버 검증**
```
L-1 헤더        : x-frame-options: SAMEORIGIN / nosniff / no-referrer  ✅
M-3 QR          : 정상 26자 → 200 · 과대 600자 → 400  ✅
M-1 인증 전 init: 노출 필드 없음, 공용 필드 4개만  ✅
M-1 인증 후     : operator_init 수신(devices 6개)  ✅
```
테스트 `tests/test_info_exposure.py` 11개. **뮤테이션 검증**: M-1 무력화 1건, M-3 무력화
2건, L-1 무력화 4건 실패 → 실효성 확인. 전체 **60 passed**.

---

### 3.6 M-5 락파일 · 모바일 접근성 · VAD 재조합 (2026-07-08, Agent B)

**M-5 의존성 고정 + 취약점 스캔 — 실제 취약점을 발견해 해결했습니다.**
```
pip-audit → Found 3 known vulnerabilities in 1 package
  pyasn1 0.6.3  PYSEC-2026-3455 / 3456 / 3457  (fix: 0.6.4)
→ pyasn1 0.6.4 로 업그레이드 후 재스캔: No known vulnerabilities found ✅
→ 업그레이드 후 전체 테스트 통과(회귀 없음)
```
- `requirements.lock` 생성(73개 고정) — 운영 환경은 이걸로 설치하면 검증된 조합 재현.
- `requirements.txt` 에 락파일 사용법·`pip-audit` 실행법 주석 추가.
- `pyasn1>=0.6.4` 하한 명시(간접 의존성이지만 취약점이 있었으므로).

**모바일 접근성(`/m`)** — 시니어 교인 배려.
- 상단에 **`A−` / `A+`**(글자 크기 3단계: 1 / 1.3 / 1.6배), **`◐`**(고대비: 흰 배경·검은 글씨)
- 선택은 `localStorage` 에 저장돼 재접속 시 유지. CSS 변수(`--scale`)로 구현해 기존
  vw 기반 반응형을 깨지 않는다.

**VAD 문장 재조합** — 강제 분할(8초 상한)로 문장 중간이 잘리면 조각 단위로 번역돼 문맥이
끊기고 오역(주어/목적어 뒤바뀜 등)이 생겼다. 이제 **문장이 끝날 때까지 모아 한 번에 번역**한다.
- 즉시 내보내는 조건(자막 지연 방지): 문장부호로 끝남 / 침묵으로 끊김(문장 끝 가능성) /
  모은 조각이 `STT_MAX_JOIN_SEGMENTS`(기본 2) 도달
- **한국어 화면 표시는 조각이 나오는 대로 즉시** 갱신해 반응성을 유지한다(번역만 모음).
- 지연이 문제면 `STT_MAX_JOIN_SEGMENTS=0` 으로 예전 동작으로 되돌릴 수 있다.
- 테스트 `tests/test_vad_join.py` 7개(판정 규칙). 전체 **67 passed**.

**부수 발견(환경)**: USB 재연결로 오디오 장치 **인덱스가 2→4 로 바뀌어** 로컬 백엔드가
기동하지 못했다. `.env` 를 **장치 이름**(`AUDIO_INPUT_DEVICE=Vocaster Two USB`)으로 바꿔
해결. 인덱스는 재연결 시 변동되므로 **이름 지정을 권장**한다.

---

### 3.7 ⚠️ 회귀 기록: 화면이 캐시돼 기능이 사라져 보인 문제 (2026-07-08, 해결)

**증상**: 운영자 화면에서 **오디오 입력 장치를 선택할 수 없고**, 온라인/오프라인 **백엔드
전환 옵션이 사라짐**(배지가 `…`, "운영자 토큰이 필요합니다" 경고 표시).

**원인 추적**
1. 서버는 정상이었다 — 직접 WebSocket 으로 확인: `operator_init`(devices=6) 정상 도착.
2. 서버가 내보내는 HTML 도 정상 — `operator_init` 핸들러 포함 확인.
3. **캐시 헤더 확인 결과 `Cache-Control` 이 없었다.** FastAPI `FileResponse` 는
   `ETag`/`Last-Modified` 를 붙이므로, 브라우저가 **304 로 옛 JS 를 재사용**했다.
   옛 JS 에는 `operator_init` 핸들러가 없어 장치 목록·백엔드 배지가 채워지지 않았다.
   → M-1(init 분리) 변경이 **캐시된 화면에서만** 회귀를 일으킨 것.

**조치**
- 화면 HTML(`/`, `/operator`, `/m`, `/qr-view`)에 `Cache-Control: no-store, must-revalidate`
  적용 + `ETag`/`Last-Modified` 제거 → 조건부 요청으로 304 를 받지 않는다.
- QR·아이콘은 그대로 캐시 허용(불필요한 재다운로드 방지).
- 구현 함정: Starlette `MutableHeaders` 에는 **`pop()` 이 없어** 500 이 났다 → `del` 사용.
- 테스트 5개 추가(`test_info_exposure.py`): 화면 4개의 no-store·검증자 제거 + QR 캐시 허용.

**교훈**: 프런트엔드를 고쳤는데 "기능이 사라졌다"는 증상이면 **캐시를 먼저 의심**하고
`curl -sI` 로 캐시 헤더를 확인하라. 사용자에게 강제 새로고침을 요구하는 대신
**서버에서 캐시를 막는 것**이 근본 해결이다.

---

### 3.8 ⚠️ 진짜 원인: 자동 토큰이 재시작마다 바뀌어 인증 실패 (2026-07-08, 해결)

3.7 에서 캐시를 고쳤는데도 **장치 선택 불가·백엔드 토글 사라짐**이 계속됐다. 재진단 결과
**원인은 캐시가 아니라 토큰**이었다.

**진단 과정(추측 없이 좁혀감)**
1. 서버를 WebSocket 으로 직접 확인 → `operator_init`(devices=6, backend=local) **정상 도착**.
2. 브라우저(자동화)로 최신 토큰 URL 접속 → **정상 동작**(장치 6개, 배지 표시).
3. 사용자 스크린샷 2장의 토큰이 서로 달랐음(`a8gBuEv8…` → `E1sBjShyz…`)
   → **서버 재시작마다 토큰이 새로 생성**되어, 열어둔 탭의 옛 토큰이 무효가 된 것.
4. 옛 토큰으로 재현 → `auth_error` → `operator_init` 미수신 → 장치 목록 빈 채로 남음.
   **사용자 증상과 정확히 일치.**

**조치**
- 자동 생성 토큰을 **파일에 저장해 재시작 후 재사용**(`$TMPDIR/translateviewer/operator_token`,
  권한 600). 이제 열어둔 탭·북마크가 계속 유효하다. 검증: 재시작 전후 토큰 동일 확인.
- 토큰이 무효일 때 **빨간 배너로 원인·조치를 크게 안내**(예전엔 작은 경고라 알아채기 어려웠음).

**교훈**: "고쳤는데 그대로"라는 보고를 받으면 **내 수정이 원인이었다고 단정하지 말고**
증상을 처음부터 다시 재현하라. 3.7(캐시)도 실재한 문제였지만 **이번 증상의 원인은 아니었다.**

### 3.9 요청 기능: 시스템 오디오 · 전사 자동 저장 (2026-07-08)

- **컴퓨터 소리 입력**: 이미 가능했다(BlackHole 등 가상 장치). 다만 운영자가 알아보기
  어려워, 장치 목록에 **🔊 컴퓨터 소리** 표시를 추가했다(`system_audio` 플래그).
  유튜브 영상 등으로 테스트할 때 유용.
- **전사 자동 저장**: `LOG_TRANSCRIPTS` 기본값을 **켜짐**으로 바꿨다(전사 품질 점검이
  번역보다 중요하다는 사용자 판단 반영). 두 형식을 동시에 남긴다.
  - `data/logs/sermon-<시각>.txt` — `[10:56:21] (한국어) …` 사람이 읽는 형식
  - `data/logs/sermon-<시각>.jsonl` — 기계 판독용
  기동 시 콘솔에 경로 출력. 끄려면 `LOG_TRANSCRIPTS=0`.

---

### 3.10 입력 레벨 게이지 추가 — "BlackHole 골랐는데 전사가 안 됨" (2026-07-26, 해결)

**증상(사용자 보고)**: 운영자 화면은 정상이고 BlackHole 2ch 도 선택되는데 전사가 전혀
안 됨. "입력 신호가 없는 것 같다."

**진단**: 추측하지 않고 직접 측정했다. BlackHole 에서 3초간 캡처 →
`콜백 29회, 최대 RMS = 0.000000`. 스트림은 정상으로 열렸고 콜백도 도는데 **샘플이 전부 0**.
`system_profiler` 로 확인하니 macOS 기본 출력이 여전히 내장 스피커였다.

**원인**: 코드 문제가 아니다. BlackHole 은 '출력 → 입력' 루프백 장치라서,
**macOS [시스템 설정 → 사운드 → 출력]을 BlackHole 로 바꾸지 않으면** 아무 소리도
흘러들어오지 않는다. 장치를 고르는 것만으로는 부족하다.

**진짜 문제는 관측 불가능성**: 화면상으로는 모든 것이 정상으로 보여서, 신호가 0 이라는
사실을 확인할 방법이 없었다. 사용자가 게이지를 요청한 것도 같은 이유다.

**구현**:
| 계층 | 내용 |
|------|------|
| `audio_input.py` | 오디오 콜백에서 청크 RMS 를 피크로 누적, `pop_level()` 로 소비·초기화. `rms_to_dbfs()` 는 -60dB 바닥. 장치 교체 시 피크 리셋(이전 장치 신호 잔존 방지) |
| `ws_server.py` | `Hub._operators` 로 **운영자 인증 연결만** 추적. `_level_heartbeat()` 가 0.2초마다 `{"type":"level", dbfs, silent}` 를 그쪽에만 push (교인 폰 수십 대에 초당 5회는 낭비) |
| `operator/index.html` | 색 눈금 막대 + dB 수치. 4초 이상 무음이면 **선택 장치 종류별 안내**(🔊 컴퓨터 소리 → macOS 출력 변경 안내 / 마이크 → 전원·연결 확인) |

**설계 판단 두 가지**
- **평균이 아니라 피크**: 평균을 내면 짧은 말소리가 무음 구간에 묻혀 막대가 거의 안 움직인다.
- **막대에 그라디언트를 주지 않는다**: 처음엔 막대 자체에 초록→빨강 그라디언트를 줬는데,
  막대가 짧아질 때 색이 압축돼 **초록-노랑-빨강이 3번 반복**됐다(실제 스크린샷으로 확인).
  색 눈금은 '레벨 척도'라 막대 길이와 무관하게 고정돼야 한다 → 그라디언트를 컨테이너에 깔고
  **미도달 구간을 마스크로 덮는** 방식으로 변경.

**검증**(브라우저 실측)
- Vocaster 선택 → `-24 dB`, 막대 59% (실제 주변음)
- BlackHole 선택 → `무음`, 막대 0%, 경고 문구 정확히 출력
- 표시 매핑: -60dB→0% / -30dB→50% / -3dB→95%(빨강 구간)
- 테스트 85개 통과 (레벨 11 + 운영자 전용 전송 2 신규)

**다른 Agent 주의**: `Hub` 에 `_operators` 집합이 생겼다. `unregister()` 는 두 집합에서
모두 제거해야 하며(누락 시 끊긴 소켓에 계속 전송), 자주 갱신되는 운영자 전용 정보는
`broadcast()` 대신 `send_operators()` 를 쓸 것.

### 3.11 전사/번역 영역 무한 확장 수정 + 오프라인 전사 안 됨 진단 (2026-07-26, Agent C)

**문제 2 — 운영자 화면 전사/번역 영역이 무한 세로 확장(완료)**
- 원인: 서버 `RollingTranscript` 는 16줄/1200자 tail 을 유지하나, `operator/index.html` 의
  `.source`·`.target-line` CSS 에 `max-height`/`overflow` 가 없어 카드가 화면 밖까지 늘어남
  → 대시보드 상단이 밀려 최신 멘트를 보려면 스크롤을 내려야 했음.
- 수정: 두 영역에 `max-height`(source 7.5em=150px / target 6em=126px) + `overflow-y:auto`
  + `overscroll-behavior:contain`. 새 자막 수신 시(`case "source"`/`"subtitle"`)
  `scrollTop=scrollHeight` 로 **항상 최신이 보이도록 자동 하단 스크롤**.
- 검증(브라우저 실측, file://): 16줄 주입 시 `maxHeight=150px, overflowY=auto,
  isOverflowing=true, scrolledToBottom=true`. target-line 도 `maxHeight=126px` 동일 확인.

**문제 1 — 오프라인 전환 후 BlackHole 전사 안 됨(원인 확정 + 관측성 경고 추가, 완료)**
- 실측: `/health` → `backend=local, audio_device=6`(BlackHole), 스크린샷 입력레벨 **-42dB**.
- 핵심 진단: VAD 침묵 임계값 `SILENCE_RMS=0.015` = **-36.5dBFS**. 신호 -42dB 가 이보다
  낮아 전부 '침묵' 판정 → 발화 구간이 안 잡혀 `transcribe()` 미호출.
- **사용자 확인으로 원인 확정**: 시스템 **볼륨을 100%로 올리자 전사가 시작됨.** 전환 버그가
  아니라 **입력 볼륨이 STT 임계값 미달**이었음. 온라인(Gemini)은 자체 게인 처리로 작은 소리도
  전사하지만 오프라인 STT 는 임계값 미달 신호를 통째로 버림 → "온라인은 되고 오프라인은 안 됨".
- 전환 로직은 코드상 정상(`switch_backend`→`GeminiBackend.aclose`→`LocalBackend` 재생성→fanout
  유지→KoreanSTT 재시작). 수정 불필요.
- **관측성 개선(재발 방지)**: 게이지 바닥 -60dB 와 STT 임계값 -36.5dB 사이 '죽은 구간'
  (막대는 초록인데 전사 안 됨)에 **`too_quiet` 경고 추가**. 서버가 오프라인일 때만
  `_is_too_quiet(rms, online, silent)` 로 판정해 level 메시지에 실어 보내고, 운영자 화면은
  3초 지속 시 "소리가 너무 작아 전사되지 않습니다. 볼륨을 높이세요"(한/영) 표시. 무음(-60dB↓)
  경고가 우선. 3.10 의 관측가능성 철학과 동일 — "화면상 정상인데 안 되는" 상황을 없앰.
- 검증: 서버 테스트 4개 추가(`test_audio_level.py`, 임계값 경계/온라인/무음 분기 커버, **89 passed**).
  클라이언트 상태머신 브라우저 시뮬레이션(quiet 3초/silent 4초/우선순위/복구) 확인, 콘솔 오류 없음.
- 파일: `server/ws_server.py`(`_is_too_quiet` + level 메시지 `too_quiet`),
  `web/operator/index.html`(경고 상태머신 silent|quiet|none + i18n), `tests/test_audio_level.py`.
- 미채택(현 시점 불필요): `STT_SILENCE_RMS` 하향은 노이즈 오탐 트레이드오프가 있어 보류.
  볼륨을 올리는 운영 방식 + 경고로 충분. 반복되면 env 로 조정 가능.

### 3.12 반복 포트충돌 방지 + 토큰 안내 메시지 명확화 (2026-07-26, Agent C)

**배경**: 사용자가 `sermon`(start.sh)을 기존 서버 종료 없이 반복 실행 → 매번 `[Errno 48]
address already in use` 로 조용히 실패(세 번 연속 실패 로그 확인). 게다가 실패한 각 기동이
"🔐 운영자 토큰이 자동 생성되었습니다"를 출력하며 매번 다른 토큰을 보여줘, 토큰이 계속
바뀌는 것처럼 오해를 유발함.

**진단(실측)**:
- 8000 을 LISTEN 하는 실제 서버는 `PID 60004`(11:10 기동) 하나뿐. 반복 실행한 프로세스들은
  포트 충돌로 즉시 종료됨(`ps` 로 확인 — 죽은 PID 들).
- 토큰 재사용 로직(`config._load_or_create_token`)은 **정상 작동 중**: 토큰 파일값이
  `I21T0zGQ8C…` 로 스크린샷 운영자 URL·현재 서버 사용값과 **일치**(실측). 즉 재사용됨.
- 문제는 `token_autogenerated` 플래그가 재사용/신규를 구분하지 않아 **메시지가 항상 "자동
  생성"** 으로 떴던 것(오해의 근원). 로그의 토큰 불일치는 파일 확립 전 초기 현상이었음.

**수정**:
1. **start.sh 포트 선점검**(사용자 선택: 물어보고 자동 종료): 시작 전 `lsof -ti:PORT -sTCP:LISTEN`
   로 점유 확인 → 있으면 "종료하고 새로 시작할까요? [y/N]" → 동의 시 `kill`(안 죽으면 최대 5초
   대기 후 `kill -9`) 후 진행, 거부 시 기존 URL 안내하고 `exit 0`. `lsof` 없으면 검사 생략.
2. **토큰 메시지 분기**: `_load_or_create_token → (token, reused)` 튜플, `Settings.token_reused`
   추가. ws_server 가 재사용이면 "저장된 운영자 토큰을 재사용합니다", 신규면 "자동 생성되었
   습니다"로 구분 출력.

**검증**:
- start.sh 거부(N) 경로 실측: 8000 의 기존 서버(60004) 감지 → 안내 → "취소" → `exit 0`,
  **기존 서버 유지됨**(N 이라 안 죽음) 확인. `bash -n` 문법 OK.
- 토큰 재사용 테스트 3개 추가(`test_parsing.py`): 신규 생성·저장 / 재시작 시 같은 값 재사용
  (열어둔 탭 안 깨짐 회귀 방지) / 짧은 파일 무시. **92 passed**. `py_compile` OK.
- 파일: `start.sh`, `server/config.py`, `server/ws_server.py`, `tests/test_parsing.py`.

**교훈(인계메모 보강)**: 6장 "서버 재기동 시 포트 확인" 함정을 **코드로 예방**함. 앞으로
`sermon` 재실행 시 기존 서버가 있으면 안내·종료를 물어보므로 무의미한 실패가 사라진다.

**부가 진단 — 유령(고아) 서버가 반복 충돌의 근본 원인 (사용자 질문 규명)**
"브라우저 탭을 닫으면 서버가 종료되나? 현재 서버는 언제부터 돌았나?"를 실측으로 규명:
- **탭 닫기 ≠ 서버 종료**: 운영자 화면은 WebSocket 클라이언트일 뿐이고 서버(uvicorn)는
  독립 프로세스다. 탭을 닫으면 연결만 끊기고(`hub.unregister`) 서버는 계속 돈다.
  서버를 끄려면 그 프로세스에 `Ctrl+C`/`kill` 해야 한다.
- 현재 8000 을 잡은 서버 `PID 60004` 는 **오늘 11:10:14 기동**, 부모가 **PPID=1**
  (원래 터미널이 이미 종료된 **고아 프로세스**)라 터미널 없이 백그라운드에서 계속 돈다.
  → "터미널/탭을 닫았는데도 서버가 안 꺼진다"의 실체.
- 이 서버는 `sermon`(=`python -m server`)이 아니라 **`python server/ws_server.py` 직접
  실행**으로 떴다(`ps` command 로 확인 — README 의 대체 실행법 또는 다른 경로).
- 오늘 서버 기동 이력(전사로그 파일명): **10:54:42(서버 A) → 11:10:15(서버 B=현재 60004)**.
  사용자의 첫 `sermon` 충돌(10:59경)은 이미 떠 있던 **서버 A** 때문 → "처음부터 충돌"이 맞다.
- **결론**: 정리되지 않은 유령 서버가 포트를 선점 → 이후 모든 기동이 실패했다. 3.12 의
  start.sh 포트 선점검이 정확히 이 문제를 해결한다. 운영 시 **서버를 띄운 터미널을 열어두고
  종료 때 그 창에서 `Ctrl+C`** 로 끝내면 고아화를 막을 수 있다.

### 3.13 코드 품질 1단계: print → logging 전환 (2026-07-26, Agent C)

사용자 선택(코드 품질 / LAN 전용→H-2 보류)에 따라 **순수 리팩터링**(기능 변화 0)으로 진행.
2단계 중 **1단계 완료**.

**변경**:
- 신규 `server/logging_setup.py`: `setup_logging()` — 루트 로거 1회 설정(중복 무시),
  포맷 `%(asctime)s %(levelname)-7s [%(name)s] %(message)s`, `LOG_LEVEL` env 로 조정.
- 각 모듈이 `logging.getLogger("server"/"local"/"live"/"audio"/"config"/"transcript")` 사용.
  기존 `[server]` 등 태그는 **로거 이름**이 대신한다.
- `print(...)` → `log.info/warning`(레벨 구분): 운영 정보=info, 실패·⚠경고=warning.
  총 **34개 전환**(ws_server 18·local 7·audio 2·live 4·config 1·transcript 1·원고상한 1).
- **의도적으로 print 유지**: ① 서버 시작 시 **운영자 토큰 URL 배너**(사용자 대면 안내)
  ② `audio_input.py` 의 CLI 진단 도구(`--list`/`--monitor`) 출력.
- 진입점(`__main__.py`·`ws_server.py __main__`)과 `lifespan` 에서 `setup_logging()` 호출
  (어떤 실행 경로든 로깅 보장). `audio_input` 의 미사용 `import sys` 제거.

**검증**:
- 실제 출력 확인: `18:10:09 INFO [server] 파이프라인 시작 …` 형식 정상.
  `LOG_LEVEL=WARNING` 시 info 억제·warning만 출력 확인(레벨 필터 동작).
- `py_compile` OK, **92 passed**(기능 회귀 없음), 남은 print 는 위 의도분만 잔존.

**다음(2단계)**: `ws_server.py`(1000줄+) 모듈 분리 — 별도 진행(회귀 위험 커서 신중히).

### 3.14 후속 개선 4건: stop.sh · 무발화 자동종료 · 입력 게인 · WS 재연결 (2026-07-27, Agent C)

사용자 선택으로 오늘 이슈에서 파생된 후속 4건을 **각 독립 커밋**으로 진행(순수 개선).

1) **stop.sh**(커밋 45e1c2e) — 터미널을 닫아 고아 프로세스로 남은 서버를 `lsof -sTCP:LISTEN`
   으로 찾아 안전 종료(정상 종료 후 안 죽으면 최대 5초 대기→강제). README 실행 요약 반영.
2) **무발화 자동 방송 종료**(커밋 71b1286) — `IDLE_STOP_MIN`(기본 0=off). 무발화 N분 초과 +
   방송중이면 자동 종료해 온라인 비용 방지. `_should_auto_stop()` 판정, `reconfig_lock` 하
   재판정(그사이 발화 시 오종료 방지), 재시작 시 `last_speech_at` 리셋. 운영자 `auto_stopped`
   안내(한/영), `.env.example` 문서화.
3) **입력 게인 슬라이더**(커밋 e82895a) — 낮은 신호를 앱에서 1~8배 증폭(int16 클리핑으로
   오버플로우 방지, 게이지·전사 동일 반영). too_quiet 경고의 완결편. `set_gain` 명령
   (쿨다운 제외 — 슬라이더 드래그), `gain_state`/`operator_init` 로 상태 동기화.
4) **WS 재연결/연결상태 강화**(이 커밋) — 끊김 시 재시도 횟수 표시("재연결 시도 중 (N)"),
   5회+ 면 "서버 응답 없음 — 서버 실행 확인" 안내. 완만한 백오프(1.5초씩↑, 최대 6초).

**검증**: 각 단계 `py_compile` + `pytest`(최종 **98 passed**, 게인·무발화 순수 함수로
+8개 테스트) + 브라우저 file:// 로 슬라이더·문구·콘솔무오류 확인. stop.sh 는 `bash -n` +
'서버 없음' 경로(실 kill 은 사용자 서버 보호로 미실행).

### 3.15 오디오 장치 없이도 서버 유지 + 대시보드에서 복구 (2026-07-27, Agent B)

**발견 경위**: 사용자가 "OBS 브라우저 소스가 제대로 작동하는지 확인해달라"고 요청 →
검증 과정에서 발견. `.env` 의 `AUDIO_INPUT_DEVICE=Vocaster Two USB` 가 미연결이라
`AudioCapture.__aenter__` 에서 `ValueError: No input device matching …` 발생.
`lifespan` 이 `create_task(pipeline(...))` 결과를 확인하지 않아 **예외가 로그 없이
사라지고** 파이프라인만 조용히 죽었다.

**증상이 위험한 이유**: 서버는 `200 OK`, `/health` 는 `status: ok`(단 `backend: null`),
운영자 화면도 정상 표시 — **자막만 영원히 안 나온다.** 예배 직전 USB 를 안 꽂거나
케이블이 빠지면 그대로 발생하며, 화면상 단서가 전혀 없다. 3.10(레벨 게이지)·3.11
(too_quiet)과 같은 **관측 불가능성** 문제.

**사용자 제안(채택·구현)**: "대시보드가 현재 장치를 검색하고, 중간에 장치를 꽂으면
'목록 새로고침'으로 복구해 쓰면 되지 않나?" → 방향이 맞다. 다만 당시엔
`state.capture is None` 이라 `_switch_device` 가 **응답조차 없이 return** 해 장치를 골라도
아무 일도 일어나지 않았다. 그래서 **캡처 객체를 살려두는 것**을 전제조건으로 먼저 구현.

**구현**
| 파일 | 변경 |
|---|---|
| `audio_input.py` | `__aenter__` 가 실패해도 예외를 올리지 않는다. 지정 장치 실패 → **기본 장치로 폴백** → 그것도 실패하면 `error` 만 기록하고 객체 유지. `_open_stream` 성공 시 `error` 자동 해제(복구 반영). `error` 프로퍼티 신설 |
| `ws_server.py` | `task.add_done_callback(_log_pipeline_failure)` — 파이프라인 예외를 **반드시 로깅**. `operator_init`·`device_list`·`device_state` 에 `device_error` 실어 보냄 |
| `operator/index.html` | 빨간 `device-warn` 배너(레벨 경고보다 강한 색 — 기동 실패가 더 급함). 장치 교체 성공 시 자동 해제 |

**설계 판단**: `set_device` 의 예외는 **그대로 전파**한다(기존 `device_error` 경로가
운영자에게 실패를 알려야 하므로). 폴백은 기동 시점(`__aenter__`)에만 적용 — 운영자가
명시적으로 고른 장치를 말없이 다른 것으로 바꾸면 더 혼란스럽다.

**검증**(실측)
- TDD: `tests/test_audio_fallback.py` 8개 먼저 작성 → 전부 RED(문제 재현) → 구현 → GREEN
- 실제 기동(없는 장치 지정): `/health` 가 `backend: gemini`(과거엔 `null`) — **파이프라인 생존**.
  로그에 `⚠ 지정한 입력 장치를 열 수 없습니다 … 기본 입력 장치로 대체했습니다` 출력
- 브라우저 실측: 배너 표시 확인(문구에 실패 장치명 포함), 장치 목록 6개 정상,
  BlackHole 선택 → `입력 장치를 전환했습니다 → [1]` + **배너 자동 해제**
- 전체 **106 passed**

**부수 확인 — OBS 브라우저 소스(사용자 원 질문)**: 실제 OBS 32.2.0 으로 끝까지 검증.
기존 "예배" 장면의 브라우저 소스(URL `http://localhost:8000/`, 1920x1080, 투명 배경 CSS)
설정이 올바름(속성은 열람만 하고 취소 — 사용자 설정 미변경). 한국어 TTS 를 BlackHole
루프백으로 흘려 STT→번역→표시 전 경로 통과, **OBS 미리보기에 자막 렌더링 확인**
("God loves us. Today, we will share that love together."). 서버 재시작 시 브라우저 소스가
**자동 재연결**되는 것도 확인(3.14 재연결 로직 실동작).
⚠️ **주의**: 브라우저 소스의 **'로컬 파일' 체크는 켜면 안 된다** — Origin 이 `null` 이 되어
WS 가 차단된다(실측 403). URL 방식이면 Origin 이 동일 출처라 통과.

### 3.16 코드 품질 2단계: ws_server.py 모듈 분리 완료 (2026-07-27, Agent C, 브랜치)

사용자 요청(완전 분리)으로 브랜치 `refactor/ws-server-split` 에서 진행. 순수 리팩터링(기능 0).
**1020줄+ 단일 파일 → 7개 모듈**(관심사별), ws_server 는 460줄로 축소.

분리 결과(단방향 의존, 순환 없음):
```
constants.py(71)     설정 상수
hub.py(68)           WebSocket 브로드캐스트 허브
validation.py(73)    입력 검증 순수 함수
app_state.py(158)    AppState·LangWorker·전역 state
orchestration.py(281) 백엔드전환·파이프라인·하트비트
commands.py(163)     운영자 명령 처리
ws_server.py(460)    FastAPI app·lifespan·HTTP 라우트·ws_endpoint (엔트리)
```

방식·안전장치:
- 단계별(constants→hub→validation→app_state→orchestration→commands) 커밋, **각 단계 106 passed**.
- ws_server 가 re-export(+`__all__`)로 기존 `from ws_server import …` 호환 → 대부분 테스트 무수정.
- **화이트박스 테스트(monkeypatch)만** 대상 모듈 조정: 연결상한→hub, 무발화→orchestration,
  쿨다운·원고상한→commands (re-export 는 값 바인딩이라 monkeypatch 로는 못 바꾼다).
- ruff 도입해 이동으로 unused 된 import 18개 정리(re-export 는 `__all__` 로 보호).
- 실제 import 로드로 **순환 없음 확인**, py_compile OK, 최종 **106 passed**.

★다른 Agent 참고: 서버 심볼은 이제 각 모듈에 있다. `from ws_server import X` 는 re-export 로
계속 되지만, **monkeypatch·직접 참조는 실제 모듈**(hub/app_state/orchestration/commands 등)을
대상으로 해야 한다.

## 4. 작업 보드 (Work Board)

상태: 🔴 미착수 · 🟡 진행중 · 🟢 완료 · ⚪ 보류(의도적)

### 4.1 보안 (analysis-report 6장)
| ID | 항목 | 상태 | 담당 | 비고 |
|---|---|---|---|---|
| C-1 | WS Origin 검증 | 🟢 완료 | Agent B | 2026-07-08, 재현 테스트로 검증 |
| C-2 | 토큰 자동생성/인증 강제 | 🟢 완료 | Agent B | 자동생성 방식 채택 |
| H-1 | 상수시간 비교 + 실패 제한 | 🟢 완료 | Agent B | 5회 초과 시 연결 종료 |
| H-2 | 토큰 URL 노출 → HTTPS/WSS·sessionStorage | 🔴 미착수 | — | UX 7.1 과 함께 처리 권장 |
| H-3 | 운영 명령 rate limit(쿨다운) | 🟢 완료 | Agent B | 2026-07-08 · 2초(백엔드 10초), 뮤테이션 검증 |
| H-4 | WS 메시지 크기·연결 수 상한 | 🟢 완료 | Agent B | 2026-07-08 · 원고 10만자·연결 100·메시지 512KB |
| M-1 | init 내부정보를 인증 후 전송 | 🟢 완료 | Agent B | 2026-07-08 · 공용 init/operator_init 분리 |
| M-2 | `set_style` 화이트리스트 검증 | 🟢 완료 | Agent B | 2026-07-08 · 허용 키·타입·범위·색상형식, 뮤테이션 검증 |
| M-3 | `/qr.svg` 길이 제한 | 🟢 완료 | Agent B | 2026-07-08 · 512자 상한(초과 400) |
| M-5 | 의존성 락파일 + pip-audit | 🟢 완료 | Agent B | 2026-07-08 · **실제 취약점 3건 발견·해결**(pyasn1) |
| L-1 | 보안 헤더 미들웨어 | 🟢 완료 | Agent B | X-Frame-Options·nosniff·Referrer-Policy |
| L-2~3 | 엔드포인트 노출·원고 길이 | ⚪ 보류 | — | 원고 길이는 H-4 로 처리됨. /health 는 LAN 전제상 허용 |

### 4.2 사용자 편의성 (analysis-report 7장)
| 우선 | 항목 | 상태 | 담당 |
|---|---|---|---|
| 높음 | 토큰 입력 UX(sessionStorage) | 🟢 완료 | Agent C (2026-07-27) · URL>저장값 우선, auth_error prompt |
| 높음 | 무발화 자동 방송 종료 옵션(`IDLE_STOP_MIN`) | 🟢 완료 | Agent C (2026-07-27) · 기본 off, reconfig_lock 재판정 |
| 높음 | 입력 게인 슬라이더(소프트웨어 증폭 1~8배) | 🟢 완료 | Agent C (2026-07-27) · too_quiet 완결편 |
| 낮음 | stop.sh 서버 종료 스크립트(고아 프로세스) | 🟢 완료 | Agent C (2026-07-27) |
| 높음 | 모바일 언어 선택 유지(localStorage) | 🟢 완료 | Agent B (2026-07-08) |
| 중간 | 첫 실행 온보딩(3단계 미니 안내) | 🔴 미착수 | — |
| 중간 | WS 연결 상태 배지 강화 | 🟢 완료 | Agent C (2026-07-27) · 재시도 횟수·서버다운 안내·백오프 |
| 중간 | 모바일 접근성(글꼴·대비) | 🟢 완료 | Agent B (2026-07-08) |
| 낮음 | 프리셋 저장 / 원문 병기 토글 | 🔴 미착수 | — |
| 높음 | 오디오 장치 미연결 시 서버 생존 + 대시보드 복구 | 🟢 완료 | Agent B (2026-07-27) · 폴백+배너, 사용자 제안 채택 |
| 높음 | 전사/번역 영역 무한확장 → 창 크기 맞춤 스크롤 | 🟢 완료 | Agent C (2026-07-26) |
| 높음 | 입력볼륨 부족(STT 임계값 미달) 게이지 경고 | 🟢 완료 | Agent C (2026-07-26) |
| 중간 | 반복 포트충돌 방지(start.sh 선점검·물어보고 종료) | 🟢 완료 | Agent C (2026-07-26) |
| 낮음 | 토큰 안내 메시지 재사용/신규 구분 | 🟢 완료 | Agent C (2026-07-26) |

### 4.3 품질·기술부채 (analysis-report 8장)
| 항목 | 상태 | 비고 |
|---|---|---|
| WS/인증 **통합 테스트** | 🟢 완료 | Agent B, 2026-07-08 · `tests/test_ws_security.py` 11개. **뮤테이션 테스트로 실효성 검증**(보안 코드 무력화 시 실패 확인) |
| `ws_server.py` 모듈 분리(1020줄+→7모듈) | 🟢 완료 | Agent C (2026-07-27) · constants/hub/validation/app_state/orchestration/commands, ws_server 460줄, 106 passed |
| `print` → `logging` 전환 | 🟢 완료 | Agent C (2026-07-26) · logging_setup + 34개 전환, LOG_LEVEL env, 92 passed |
| preview SDK 필드 방어적 처리 | 🔴 미착수 | 세션 재개 회귀 위험 |

### 4.4 기능 개선 (handover 9장)
| 항목 | 상태 | 비고 |
|---|---|---|
| VAD 문장 재조합(정확도↑) | 🟢 완료 | Agent B · 2026-07-08, STT_MAX_JOIN_SEGMENTS=2 (0이면 끔) |
| i18n 로케일 파일 분리 | 🔴 미착수 | 언어 3개 이상일 때 |
| 로그 SQLite + 검토 UI | 🔴 미착수 | 현재 JSONL |
| STT 가속(draft model) | 🔴 미착수 | |

---

## 5. 파일별 점유 현황 (충돌 방지)

최근 수정된 파일과 **주의점**입니다. 같은 파일을 만질 때는 6장에 메모를 남기세요.

| 파일 | 최근 수정 | 주의 |
|---|---|---|
| `server/ws_server.py` | Agent B (보안) | **가장 충돌 위험 높음**(689줄, 대부분 기능이 지나감). 모듈 분리 작업과 겹치기 쉬움 |
| `server/config.py` | Agent B (토큰 자동생성) | `Settings` 는 frozen dataclass — 필드 추가 시 `load()` 도 함께 |
| `start.sh` | Agent B (토큰 URL 오픈) | `data/runtime/operator_url.txt` 를 읽음 |
| `.env.example` / `README.md` | Agent B | 동작 변경 시 **문서도 같이** 갱신(사실 불일치 주의) |
| `docs/analysis-report*.md` | Agent A | Agent B 는 수정하지 않음(소유 존중) |
| `web/operator/index.html` | (이전) Agent B | i18n 사전 + tmsg 패턴 사용 — 새 문구는 ko/en 양쪽에 추가 필요 |

---

## 6. 인계 메모 / 다음 Agent 에게

### 바로 이어서 하기 좋은 작업 (권장 순서)
1. ~~WS/인증 통합 테스트~~ → **완료**(2026-07-08). 새 테스트는 `tests/test_ws_security.py` 의
   `client` 픽스처(pipeline 모킹) 패턴을 재사용하세요.
2. ~~H-3/H-4~~ → **완료**(2026-07-08). 상한값은 모두 env 로 조정 가능.
3. **토큰 UX(H-2 + 7.1)** — 토큰을 URL 대신 `sessionStorage` 에 저장하고, 최초 1회 입력 UI.
   지금은 `start.sh` 가 토큰 URL 을 자동으로 열어주므로 **급하지는 않음**.
4. **M-2 `set_style` 화이트리스트 검증** — 비교적 독립적이라 충돌 위험이 낮고 테스트도 쉬움.

### 작업 시 지켜야 할 이 프로젝트의 관례
- **추측 말고 실측**: 모델 스펙·SDK 필드는 작은 스크립트로 확인 후 반영(과거 `en-US` → `1007`,
  스트리밍 STT 붕괴 등 모두 실측으로 잡았음).
- **온라인/오프라인 대칭성 유지**: 새 기능은 가능하면 `TranslationBackend` 뒤에서.
- **문서 동시 갱신**: 동작을 바꾸면 README·setup-guide 의 해당 문구도 고칠 것.
- **테스트 필수 통과**: `GEMINI_API_KEY=test python -m pytest tests/ -q`
- **서버 재기동 시 포트 확인**: 옛 프로세스가 8000 을 잡고 있으면 **구버전이 응답**해
  수정이 반영되지 않은 것처럼 보입니다(이번에 실제로 겪음).
  `lsof -ti:8000 | xargs kill -9` 후 기동하세요.

### 열린 질문 (사용자 결정 필요)
- 무발화 **자동 방송 종료**를 넣을지? (비용 절감 ↔ 예배 중 오종료 위험)
- 이 서버를 **외부(ngrok 등)에 노출**할 계획이 있는지? 있다면 H-2(HTTPS/WSS)가 필수가 됨.
- `ws_server.py` **모듈 분리**를 지금 할지, 기능 안정화 후로 미룰지?

---

## 7. 변경 이력 (이 문서)

| 날짜 | 갱신자 | 내용 |
|---|---|---|
| 2026-07-27 | Claude (Agent C) | **운영자 대시보드 1920x1080 배치**(3.18) — 2열 그리드(.full 제거)+여백 조밀화. 최악 케이스도 overflow 0, 한 화면 |
| 2026-07-27 | Claude (Agent C) | **토큰 입력 UX 완료**(3.17) — URL>sessionStorage 우선순위·저장, auth_error prompt 입력. 재방문·토큰없는 주소도 동작 |
| 2026-07-27 | Claude (Agent C) | **코드품질 2단계: ws_server 모듈 분리 완료**(3.16) — 1020줄+→7모듈(constants/hub/validation/app_state/orchestration/commands), ws_server 460줄. 브랜치 작업 후 병합, 각 단계 106 passed, ruff 도입 |
| 2026-07-27 | Claude (Agent C) | **후속 개선 4건**(3.14) — stop.sh(고아서버 종료)·무발화 자동종료(IDLE_STOP_MIN)·입력 게인 슬라이더(1~8배)·WS 재연결/연결상태 강화. 각 독립 커밋, 98 passed |
| 2026-07-26 | Claude (Agent C) | **코드 품질 1단계**(3.13) — print→logging 전환(logging_setup, 34개, LOG_LEVEL env). 토큰배너·CLI 출력은 print 유지. 92 passed. 2단계(모듈분리) 대기 |
| 2026-07-26 | Claude (Agent C) | **오류보고서(troubleshooting-log) 4건 추가**(한/영) — 4-3 고아서버 포트충돌, 4-4 토큰 재사용 오해, 5-4 전사영역 무한확장, 6-7 오프라인 볼륨부족(게이지↔STT 임계값 사각지대) |
| 2026-07-26 | Claude (Agent C) | **부가 진단**(3.12) — 유령(고아 PPID=1) 서버가 8000 을 선점해 반복 충돌한 것이 근본 원인임을 실측 규명. 탭 닫기≠서버종료, 현재 서버 11:10 기동·`ws_server.py` 직접 실행 등. (문서만 갱신) |
| 2026-07-26 | Claude (Agent C) | **포트충돌 방지·토큰 메시지 완료**(3.12) — start.sh 선점검(물어보고 종료), 토큰 안내 재사용/신규 구분. 토큰 재사용 테스트 3개(92 passed). 재사용 로직은 정상이었고 메시지가 오해의 근원이었음을 실측 확인 |
| 2026-07-26 | Claude (Agent C) | **운영자 화면 사용성 2건 완료**(3.11) — 전사/번역 영역 무한확장→스크롤, 오프라인 입력볼륨 부족 `too_quiet` 경고(원인=STT 임계값 미달, 볼륨100%로 확정). 테스트 4개 추가(89 passed) |
| 2026-07-08 | Claude (Agent B) | 문서 생성. 보안 1단계 완료 반영, 작업 보드·점유 현황·인계 메모 정리 |
| 2026-07-08 | Claude (Agent B) | **중단 대응 규칙(0.1) + 진행 중 작업 로그(8장) 추가** — 사용량 만료·크래시로 기록이 남지 않는 공백 해결 |
| 2026-07-08 | Claude (Agent B) | **진짜 원인 해결(3.8)**: 자동 토큰이 재시작마다 바뀌어 인증 실패 → 토큰 파일 저장·재사용, 인증 실패 배너 |
| 2026-07-08 | Claude (Agent B) | **요청 기능(3.9)**: 시스템 오디오 장치 표시, 전사 자동 저장 기본 ON(.txt/.jsonl) |
| 2026-07-08 | Claude (Agent B) | **회귀 수정(3.7)**: 화면 HTML 캐시로 장치 선택·백엔드 토글이 사라져 보인 문제 → no-store 적용, 테스트 5개(총 72) |
| 2026-07-08 | Claude (Agent B) | **M-5·모바일 접근성·VAD 재조합 완료**(3.6) — pyasn1 취약점 3건 해결, 락파일, 접근성 UI, 문장 재조합 + 테스트 7개(총 67) |
| 2026-07-08 | Claude (Agent B) | **M-1·M-3·L-1 완료**(3.5) — init 정보분리·QR 길이제한·보안헤더, 테스트 11개(총 60) |
| 2026-07-08 | Claude (Agent B) | **M-2·모바일 언어 유지 완료**(3.4) — 스타일 화이트리스트 검증 + localStorage, 테스트 10개 추가(총 49) |
| 2026-07-08 | Claude (Agent B) | **H-3·H-4 완료**(3.3) — 쿨다운·원고/연결/메시지 상한 + 테스트 8개(뮤테이션 검증), 총 39 passed |
| 2026-07-08 | Claude (Agent B) | **커밋 정책 변경**: Agent 가 직접 커밋·푸시(푸시 전 민감정보 점검 필수) |
| 2026-07-08 | Claude (Agent B) | **WS·인증 통합 테스트 11개 추가**(3.1) — 뮤테이션 테스트로 실효성 검증. 총 31개 통과. 보드 4.3·2장·인계 메모 갱신 |

---

## 8. 진행 중 작업 로그 (Live Work Log) ★중단 대비

> **규칙 A**: 작업을 시작하면 **코드를 만지기 전에** 여기에 3줄(시작·계획·다음 단계)을 씁니다.
> **규칙 B**: 단계가 끝나면 `다음 단계:` 줄을 갱신합니다. 마지막 갱신 지점이 곧 중단 지점입니다.
> 완료되면 이 항목을 지우고 4장 보드를 `🟢 완료` 로 바꾸고 3장에 결과를 요약합니다.

### 현재 진행 중
```
(진행 중 작업 없음 — 송출 제어 OBS URL 복사 버튼 완료. 3.19 참고)
```

### 3.19 송출 제어에 OBS 브라우저 소스 URL 복사 버튼 (2026-08-13, Agent C)
OBS '브라우저' 소스로 자막을 넣는 것은 원래 가능했으나(URL 직접 입력) 봉사자가 주소를
정확히 치는 마찰이 있었다. 사용자 선택(A안: 복사 편의)으로 버튼 추가.
- 송출 제어에 **"📋 OBS URL 복사"** 버튼. 클릭 → 송출화면(/) URL(`http://localhost:PORT/`)을
  클립보드 복사(clipboard API, 실패 시 `execCommand` 폴백) + 안내 메시지.
- `/lan-info` 로 LAN IP 를 받아 "다른 PC 의 OBS 면 `http://<IP>:PORT/`" 도 함께 안내.
- 안내에 권장 설정(폭 1920·높이 1080, 배경 그린스크린+OBS 크로마키) 포함. i18n 한/영.
- 값은 location·서버 lan-info 유래라 `textContent` 로만 렌더(XSS 안전).
- OBS WebSocket 자동 제어(C안)는 환경 의존·복잡으로 미채택. 파일: `web/operator/index.html`.
- 검증: 버튼·메시지 렌더·샘플 메시지 구성·콘솔 무오류. 실제 복사는 실서버(localhost)에서 동작.

### 3.18 운영자 대시보드 1920x1080 한 화면 배치 (2026-07-27, Agent C)
운영자 카드가 세로로 8개 쌓여 1080 을 넘겨 스크롤이 필요했다. 1920 폭을 활용해 2열로 배치.
- **2열 그리드**: 카드 대부분에서 `.full` 제거(상태바·송출제어만 전체폭 유지) →
  오디오|모바일, 언어|원고, 전사|번역 이 나란히. `align-items:start` 로 높이 다른 카드 정렬.
- **여백 조밀화**: body padding 24→12/18, grid gap 16→10, card padding 16→11,
  h1·label 여백 축소, `.source`/`.target-line` max-height·폰트 소폭↓, 원고 textarea rows 4→2.
- **검증(1920x1080 실측)**: 빈 상태 마지막카드 bottom 644px, **최악 케이스**(한국어 전사 가득 +
  번역 3언어 가득)에서도 `overflow 0`(한 화면). 스크린샷으로 배치·가독성 확인.
- 파일: `web/operator/index.html`(운영자 화면만). 송출 자막(/)·모바일(/m)은 미변경.
- **재배치 최종(2026-08-13, 요청 테이블 구조)**: 상태바(full) / **오디오(왼) · 모바일+원고(오른 `.col`)** /
  번역 언어(full) / 송출 제어(full) / 전사·번역. 번역 언어를 전체폭으로 내리고 왼쪽 열은 오디오 단독.
  오른쪽 `.col` 에 모바일 자막주소 위 설교 원고를 이어 붙임. 1920x1080 에서 `overflow 0` 확인.

### 3.17 토큰 입력 UX 개선 (2026-07-27, Agent C)
운영자 토큰이 URL `?token=` 로만 전달돼, 매번 긴 주소가 필요하고 토큰 없는 주소로
접속하면 인증이 안 됐다. 개선:
- **URL > sessionStorage 우선순위**: URL 에 토큰이 있으면 쓰고 sessionStorage 에 저장,
  없으면 저장된 값을 쓴다. → start.sh 가 연 URL 로 최초 접속하면 저장되어, 이후
  `/operator`(토큰 없는 주소)·재방문에서도 동작.
- **auth_error 시 prompt**: 토큰이 없거나 틀리면 한 번 입력받아 저장(URL 편집·재접속 없이
  이어서 조작). 새로 입력하면 다음에 또 틀릴 때 다시 묻는다(연타 시 반복 억제).
- 사생활 보호 모드 등 저장 실패는 `try/catch` 로 무해 처리(URL 토큰으로 계속 동작).
- i18n `tokenPrompt`(한/영). 검증: 브라우저에서 URL우선·저장값재사용·저장 동작, 콘솔 무오류.
- 파일: `web/operator/index.html`. (H-2 의 sessionStorage 부분 반영; HTTPS/WSS 는 LAN 전용이라 보류)

### 다음 세션 착수 예정 — 코드 품질 2단계: ws_server.py 모듈 분리 ★인계
```
- ws_server.py(1000줄+)를 분리. 순수 리팩터링(기능 변화 0), 92 테스트 항상 통과.
- 분리안(계층 순서, 순환 import 주의):
    hub.py         : Hub (독립)
    app_state.py   : AppState·LangWorker·state 싱글턴 (LangWorker 가 hub.broadcast 호출 → hub import)
    validation.py  : _is_hex_color / _sanitize_style / _sanitize_languages (거의 독립)
    orchestration.py: _build_backend/switch_backend/set_broadcast/apply_languages/pipeline/
                      _usage_heartbeat/_level_heartbeat/_is_too_quiet (state·hub 참조)
    commands.py    : _cooldown_remaining/_handle_command/_set_script/_switch_device
  ws_server.py 는 app·lifespan·HTTP 라우트·ws_endpoint 만 남긴다.
- ★호환: 기존 테스트가 `from ws_server import Hub, _sanitize_languages, _is_too_quiet,
  _public_init ...` 를 import 하므로, ws_server.py 에서 분리 대상들을 **re-export** 해야
  테스트가 안 깨진다. (또는 테스트 import 경로 수정)
- 착수 시 규칙 A대로 이 로그를 '진행 중'으로 옮기고, 단계마다 pytest -q 로 회귀 확인.
```

### 작성 예시 (복사해서 쓰세요)
```
- [시작 2026-07-08 14:30 / Agent B] H-3 운영 명령 rate limit
  계획: ws_server.py 의 _handle_command 진입부에 명령별 쿨다운(2초) 검사 추가
  다음 단계: 쿨다운 기준값 사용자 확인 → 구현 → 연타 재현 테스트 → README 갱신
```

### 중단·인계 기록 (Interrupted / Handed over)
> 중단이 확인되면 여기에 남깁니다(규칙 C·E). 이어받은 Agent 도 여기에 이어서 적습니다.

```
(없음)
```
