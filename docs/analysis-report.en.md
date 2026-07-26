# Project Analysis Report (translateViewer)

> Korean: [analysis-report.md](analysis-report.md)
> Related: [README.en.md](../README.en.md) · [handover.en.md](handover.en.md) · [setup-guide.en.md](setup-guide.en.md) · [troubleshooting-log.en.md](troubleshooting-log.en.md)

Date: 2026-07-07 · Target commit: `main` (8a1b795)

This document is a **comprehensive analysis of the current codebase and existing docs**, evaluating
the project's state and proposing improvements — with a focus on **security** and **user experience**,
ordered by priority. Design rationale for handover lives in [handover.en.md](handover.en.md); this report
focuses on **assessment and recommendations**.

---

## 0. At a Glance (Summary)

| Area | Rating | Basis |
|---|---|---|
| **Design / intent** | ★★★★★ | Clear 4-axis goals (latency/accuracy/ops/cost); online+offline redundancy for reliability |
| **Code structure** | ★★★★☆ | Good module split, backend abstraction, immutable config. Responsibility concentrated in `ws_server.py` (689 lines) |
| **Documentation** | ★★★★★ | README/handover/setup/troubleshooting in KO+EN. Well above typical for a project this size |
| **Testing** | ★★★☆☆ | 20 pure-logic unit tests. WebSocket/command/auth paths untested |
| **Security** | ★★☆☆☆ | **2 CRITICAL** (WS Origin unchecked, no default token). Real risk even under LAN assumption |
| **User experience** | ★★★★☆ | Excellent operator dashboard, QR, PWA. Token-entry UX and cost auto-guard can improve |

**Bottom line**: Feature and documentation maturity are high, but a **structural vulnerability in the
WebSocket auth path** means the "trusted LAN" assumption alone does not protect the system. Address
C-1 and C-2 in Section 6 (Security) first.

---

## 1. Overview

**A system that translates Korean sermon audio into multi-language subtitles in real time, broadcasting
to projector, OBS, and congregants' phones.**

- Stack: Python 3 / FastAPI + WebSocket / (online) Gemini Live Translate / (offline) Qwen3-ASR + TranslateGemma (Ollama)
- Size: ~1,977 lines of server code (12 modules), ~1,050 lines of web frontend (4 screens), 20 unit tests
- Core philosophy: *"Don't put all trust in a single real-time AI translation"* — script correction, glossary, online/offline redundancy

Four screens: overlay (`/`) · operator (`/operator`) · mobile (`/m`) · large QR (`/qr-view`).

---

## 2. Architecture Assessment

```
[mixer/mic] → audio capture (16kHz mono) → fan-out (duplicate)
                                            │
                  ┌─────────────────────────┴──────────────────────┐
             [online GeminiBackend]                       [offline LocalBackend]
        one Gemini Live session per lang        shared STT once → per-lang MT xN
                  └─────────────────────────┬──────────────────────┘
                        subtitle stabilization + script/glossary correction
                                            ▼
                        WebSocket broadcast (FastAPI) → 4 screens
```

**Strengths**
- **Backend abstraction** (`TranslationBackend`/`TranslationSession` protocols): online/offline share audio, subtitles, and UI, with runtime switching — the key extensibility/maintainability win.
- **Audio fan-out** cleanly solves "1 audio → N language sessions."
- **Separation of concerns**: pure logic (`subtitle_engine`, `glossary`, `sermon_script`, `languages`) is decoupled from I/O and testable.
- **Immutable config** (`@dataclass(frozen=True) Settings`) prevents config tampering.
- **Reconfig concurrency control**: `reconfig_lock` prevents race conditions (ghost workers) during lang/backend/device reconfig.

**Structural risks**
- `ws_server.py` (689 lines) handles routing, state, worker orchestration, command handling, and auth all at once (approaching the 800-line ceiling in the global guidelines). → Split auth/command handling into separate modules.
- Dependence on preview SDK field names (`live_session.py`) — fragile across model/SDK changes (also noted in handover).

---

## 3. Codebase Structure & Quality

| Module | Lines | Assessment |
|---|---|---|
| `ws_server.py` | 689 | Orchestration hub. Recommend splitting (Sec. 6, 9) |
| `local_backend.py` | 325 | VAD transcription, warmup, dedicated executor. Good |
| `audio_input.py` | 219 | Capture, fan-out, drop-oldest queue. Good |
| `live_session.py` | 206 | 15-min session resumption core. Watch SDK dependence |
| `sermon_script.py` | 116 | Phonetic-similarity correction. Pure logic, tested |
| `config.py` | 87 | Immutable, fail-fast. Good |
| `subtitle_engine.py`·`glossary.py`·`transcript_logger.py`·`languages.py` | 30–83 each | Small, cohesive. Exemplary |

**Overall**: Largely follows the global coding rules (small files, immutability, explicit error handling). Rich Korean comments aid handover.

**Room for improvement**
- Broad `except Exception` (`# noqa: BLE001`) — intentional, but narrowing some to specific exceptions would aid debugging.
- `print()`-based logging — promote to the `logging` module with log levels/file output (also aligns with global rules).
- Some missing type hints (`# noqa: ANN001`) — strengthen types/schemas at boundaries like command payloads.

---

## 4. Test Status

- `test_subtitle_engine`(6) · `test_sermon_script`(5) · `test_parsing`(5) · `test_glossary`(4) = **20 total**, all pure logic.
- Run: `GEMINI_API_KEY=test python -m pytest tests/ -q`

**Gaps**
- **WebSocket command path, auth logic, `_sanitize_languages`/`_handle_command` untested** — a blind spot directly tied to security.
- Add integration tests with FastAPI `TestClient`/`websockets` for commands/auth/validation (low cost, high value).

---

## 5. What's Done Well (Strengths to Keep)

1. **Documentation quality**: 4 KO+EN docs; the troubleshooting log is especially educational.
2. **Online/offline redundancy**: real mitigation for internet outages and cost risk.
3. **Accuracy design**: script phonetic correction + glossary post-processing (avoiding STT-context hallucination) — decisions reflecting domain understanding.
4. **Operational care**: usage/cost badge, idle warning, `/health`, auto browser open, Windows scripts.
5. **Secret hygiene**: API key/token loaded only via `os.getenv`, `.env` confirmed git-excluded, no secrets in logs.
6. **XSS defense**: all dynamic text rendered via `textContent` (confirmed safe in the security review).
7. **Path-traversal defense**: static asset endpoint blocks `..` via `resolve()` + parent comparison.

---

## 6. Security Analysis & Recommendations ★KEY

> From `security-reviewer` deep analysis + direct code review. Dependency CVE scan (`pip-audit`) came back clean.
> This is a **realistic assessment accounting for the "trusted LAN" assumption** — but the two CRITICAL items below break that assumption itself.

### 🔴 CRITICAL

#### C-1. WebSocket Origin unchecked → CSWSH (Cross-Site WebSocket Hijacking)
- Location: [ws_server.py:635-682](../server/ws_server.py:635) — the `/ws` handler never checks the `Origin` header before `ws.accept()`.
- Risk: WebSocket handshakes are **not** subject to the browser's Same-Origin Policy, so **any external website** can open `new WebSocket("ws://<church-LAN-IP>:8000/ws")` via JS. If the operator's PC is on the church LAN and merely visits an unrelated page (ad, phishing), that page can connect and send commands in the background.
- Impact: With no token set (the default), **all operator commands** (stop broadcast, switch language/backend to incur cost, etc.) can be executed remotely. Even with a token set, **read access** (live transcription/translation, device names) is eavesdroppable.
- Recommendation: Compare the `Origin` header against a whitelist (own host / LAN IP) before `ws.accept()`, closing with `4403` on mismatch. **Low cost, high impact — do this first.**

#### C-2. No default OPERATOR_TOKEN and not enforced → default config effectively has no auth
- Location: [config.py:73](../server/config.py:73) · [ws_server.py:430-435](../server/ws_server.py:430) (warning only) · [ws_server.py:669-670](../server/ws_server.py:669) (`if token and ...` — the check is skipped entirely when the token is empty)
- Risk: `.env.example` defaults to `WS_HOST=0.0.0.0` with a blank token. If the deployer doesn't set one, **anyone on the same LAN (including guest Wi-Fi)** can use `/operator` to stop the broadcast, tamper with the script, etc.
- Recommendation: If `WS_HOST=0.0.0.0` with a blank token, **refuse to start (fail-fast)** or auto-generate a temporary token via `secrets.token_urlsafe(24)` printed once to the console. Do not leave "no token" as the default.

### 🟠 HIGH

| ID | Issue | Location | Recommendation |
|---|---|---|---|
| **H-1** | Non-constant-time token compare + **unlimited brute force** (thousands/sec on one WS) | [ws_server.py:670](../server/ws_server.py:670) | `hmac.compare_digest` + auth-failure count → close/backoff |
| **H-2** | Token in **URL query (`?token=`)** + **plaintext `ws://`** → history & packet-sniffing exposure | [operator/index.html:300-303](../web/operator/index.html:300) | Document HTTPS/WSS (mkcert) for real use; consider `sessionStorage` prompt for the token |
| **H-3** | No rate limiting → repeated `set_backend`/`set_languages` cause session-restart storms + Gemini cost spikes | [ws_server.py:563-601](../server/ws_server.py:563) | 2–3s cooldown / token bucket on operator commands |
| **H-4** | WS message size / connection count unbounded (`set_script`/`set_style` length unlimited) | [ws_server.py:661-663](../server/ws_server.py:661) | `uvicorn(ws_max_size=…)`, script length cap, `Hub` max connections |

### 🟡 MEDIUM

- **M-1** Unauthenticated `init` broadcast leaks device names, backend, term count ([ws_server.py:640-660](../server/ws_server.py:640)) → send operator-only fields after auth.
- **M-2** `set_style` merges arbitrary keys into state; `color` length unbounded ([ws_server.py:572-576](../server/ws_server.py:572)) → Pydantic whitelist validation.
- **M-3** `/qr.svg?text=` unbounded length/rate/unauthenticated → arbitrary-QR open proxy & DoS potential ([ws_server.py:538-547](../server/ws_server.py:538)) → length cap + rate limit.
- **M-5** Dependencies pinned only with lower bounds (`>=`), no lockfile (`requirements*.txt`) → `pip freeze` lockfile + CI `pip-audit`.

### 🟢 LOW
- **L-1** No security headers (`X-Frame-Options`, `nosniff`) → add middleware. **L-2** `/health`·`/lan-info` unauthenticated info exposure (document: don't port-forward). **L-3** Script file write length unvalidated.

### Recommended order
1. **C-1** WS Origin check → 2. **C-2** token auto-gen/fail-fast → 3. **H-1** constant-time compare + failure limit → 4. **H-3/H-4** command cooldown + size/connection caps → 5. MEDIUM/LOW.

---

## 7. User Experience Analysis & Recommendations ★KEY

Overall, **care for non-developer volunteers is excellent** (all controls in the operator dashboard during
service, QR/PWA, auto browser). Below are improvements on top of that.

### 7.1 Operator / Volunteer

| Priority | Proposal | Rationale |
|---|---|---|
| High | **Improve token-entry UX** | Token currently appended as URL `?token=` ([operator/index.html:300](../web/operator/index.html:300)). Typing a long URL each time invites mistakes. → Enter once, store in `sessionStorage`; offer a "token-embedded QR/bookmark" (solves alongside security H-2) |
| High | **Idle auto-stop broadcast (opt-in)** | Currently warning only ([ws_server.py:405](../server/ws_server.py:405)). Forgetting to stop keeps online cost accruing. → `IDLE_STOP_MIN` option to auto-stop after N idle minutes (default off, to avoid mid-service false stops) |
| Medium | **Onboarding / first-run guide** | The setup guide is great but text-heavy. → A 3-step mini walkthrough on first operator load (device → language → start) |
| Medium | **Consistent error feedback** | `backend_error`/`device_error`/`auth_error` exist (good), but disconnect/reconnect state is weak → add a WS connection-status badge |
| Low | **Preset save** | Save/restore favorite language/color/style combos as presets |

### 7.2 Congregant (Mobile)

| Priority | Proposal | Rationale |
|---|---|---|
| High | **Persist language choice** | Store selected language in `localStorage` → auto-restore on reconnect/refresh (currently likely re-selected each time) |
| Medium | **Accessibility (font size / contrast)** | Text-size control and high-contrast mode on phones — care for senior congregants |
| Medium | **Connection/latency indicator** | "Live/disconnected" so users can tell a stalled feed from simple silence |
| Low | **Source-text toggle** | Show Korean source alongside translation for study/verification |

### 7.3 Extensibility (also noted in existing docs)
- **i18n locale split**: UI localization is currently a KO/EN dictionary. For 3+ languages, split into locale JSON.
- **Log enhancement**: JSONL → SQLite + review UI, per-session stats.
- **VAD sentence reassembly**: gather force-split fragments to the sentence end before translating (higher accuracy).

---

## 8. Technical Debt & Maintenance Risks

| Risk | Severity | Response |
|---|---|---|
| Preview SDK field-name dependence (session resumption) | Medium | Pin SDK version + defensive field access, regression tests |
| `ws_server.py` over-responsibility (689 lines) | Medium | Split auth/command/routing modules |
| No WS/auth path tests | Medium | `TestClient` integration tests (alongside security fixes) |
| No dependency lockfile | Low | Lockfile + periodic `pip-audit` |
| `print` logging | Low | Migrate to `logging` |

---

## 9. Prioritized Roadmap

**Phase 1 — Security hardening (immediate)**
1. C-1 WebSocket Origin check
2. C-2 token auto-generation or fail-fast
3. H-1 `hmac.compare_digest` + auth-failure rate limit

**Phase 2 — Robustness & UX (short term)**
4. H-3/H-4 command cooldown, WS size/connection caps, script/style length validation (Pydantic)
5. Token-entry UX (`sessionStorage`) + idle auto-stop option
6. Persist mobile language choice (`localStorage`)

**Phase 3 — Quality & extension (mid term)**
7. Add WS/auth integration tests, split `ws_server.py`
8. Security-header middleware, dependency lockfile + CI `pip-audit`
9. i18n locale split, log-to-SQLite, VAD sentence reassembly

---

## 10. Conclusion

translateViewer is a mature project with **clear domain understanding, excellent documentation, and a solid
design featuring online/offline redundancy**. Its code structure, accuracy design, and care for non-developer
operators are especially exemplary.

However, a **structural vulnerability in the WebSocket auth path (C-1, C-2)** means the "trusted LAN"
assumption alone does not defend it. These are **fixable at low implementation cost**, so they should be
prioritized. After security hardening and a few UX improvements, the system reaches a level fit for confident
use in real worship settings.

> The proposals here complement Section 9 "Future Work" in [handover.en.md](handover.en.md).
> For detailed reproductions/fix code on security items, spinning them off into separate issues is recommended.
