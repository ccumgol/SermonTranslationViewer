# Collaboration Report

> **Shared status document for multiple AI agents / developers working on this project concurrently.**
> 한국어: [collaboration-report.md](collaboration-report.md)
> Related: [analysis-report.en.md](analysis-report.en.md) (findings) · [handover.en.md](handover.en.md) (design background) · [setup-guide.en.md](setup-guide.en.md) (operations)

**Last updated**: 2026-07-08 · By: Claude (Opus 4.8) · Baseline: commit `8a1b795` + uncommitted work

---

## 0. How to use this document (important)

**Read this before starting work, and update it when you finish.** The goal is to
**prevent duplicated effort and conflicts**.

1. **Before starting**: check that the item is `🔴 Not started` in section 4 (Work Board),
   flip it to `🟡 In progress`, and add your name (agent) and date.
2. **After finishing**: flip to `🟢 Done` and add one line in section 5 describing **how you
   verified it**. (Don't just claim it works — state what you ran.)
3. **File conflicts**: check "File ownership" in section 5. If you'll touch a file another
   agent is working on, leave a note in section 6 first.
4. **Commit policy (changed 2026-07-08)**: agents **commit and push directly** when work is done.
   - Commit in logical units (split mixed concerns); messages state **cause, action, verification**.
   - ⚠️ **Check for secrets before pushing**: run `git diff --name-only origin/main..HEAD` and
     confirm no `.env`, tokens, or `data/` files are included. (See incident §3.2)
   - On push rejection, `git pull --rebase` and retry (concurrent agents).
   - **History rewrites (force push, filter-repo) require user approval** — they can break
     other agents' work.
   - (The previous policy was "the user commits"; now automated.)
5. **Write "recovery info" when you START** (⚠️ most important — see 0.1 below).
   Usage limits and crashes arrive without warning, so **notes written only at the end never get written.**

---

## 0.1 Interruption protocol (usage limits, crashes, forced exit) ★required

Agent work can stop mid-task at any time due to **token/usage exhaustion, session expiry, or
crashes**. With only an "update when done" rule, the board is left showing `🟡 In progress`,
and another agent assumes **"someone is on it, don't touch"** — so the work stalls.

### Rule A — Write 3 lines the moment you start (write-ahead)
When you start, **before touching code**, add this to section 8 (Live Work Log):
```
- [START 2026-07-08 14:30 / Agent B] H-3 command rate limit
  Plan: add a cooldown check at the top of _handle_command in ws_server.py / 2s threshold
  Next step: confirm cooldown value → implement → spam repro test → update docs
```
Even if you're cut off, **this note survives** so the next agent can pick it up.

### Rule B — Update one line per step for long tasks
For anything over ~30 minutes, update just the `Next step:` line as each step completes.
(The last update marks **where it stopped**.)

### Rule C — How the next agent decides
If an item is `🟡 In progress` but the owner seems gone or stale, **verify with evidence** —
don't guess:

```bash
# 1) Uncommitted changes = traces of work in progress (what was being touched)
git status --short
git diff                     # how far it got

# 2) File mtimes = last activity (estimate when it stopped)
ls -lt server/*.py web/**/*.html docs/*.md | head

# 3) Leftovers
git stash list               # may have stashed before stopping
git branch --no-merged main  # unmerged work branches

# 4) Is the code actually in a working state? (may be half-edited)
python3 -m py_compile server/*.py
GEMINI_API_KEY=test python3 -m pytest tests/ -q
```

**Suggested decision table**
| Situation | Verdict | Action |
|---|---|---|
| Uncommitted changes + mtime **hours old** | Interrupted | Read section 8, take over. Mark `🟡 In progress (took over: you)` |
| No uncommitted changes + board says `🟡` | **Stopped right after starting** | Effectively not started → reset to `🔴` and start fresh |
| Tests/compile fail | **Half-edited state** | Finish or revert that part first (report to the user) |
| Ambiguous | — | **Ask the user** (don't revert on your own) |

### Rule D — Discarding work requires user approval
**Never discard another agent's uncommitted work** (`git checkout --`, `git stash drop`)
without user approval. It may be unfinished work and, being uncommitted, is unrecoverable.

### Rule E — Minimum the user can do
If an agent stops abruptly, one line from the user is enough:
```
- [INTERRUPTED 2026-07-08 15:10] Agent B stopped (usage limit). Item above needs a new owner.
```

---

## 1. Participants and roles

| Participant | Responsibility / contribution | Last active |
|---|---|---|
| **User (owner)** | Requirements & prioritization, real-device testing, billing & API keys, direction approval | Ongoing |
| **Agent A** (analysis) | In-depth codebase analysis → [analysis-report.en.md](analysis-report.en.md) (found 2 CRITICAL security issues) | 2026-07-07 |
| **Agent B / Claude** (implementation) | Initial full implementation + documentation; verified analysis findings and implemented **security hardening phase 1** | 2026-07-08 |

> Working model: **Agent A diagnoses → user prioritizes → Agent B implements & verifies.**
> This worked well (both CRITICAL findings were reproduced as real vulnerabilities).

---

## 2. Current project state

| Area | State |
|---|---|
| Features | **Production-usable**: online/offline dual track, 1–3 languages, mobile subtitles & QR, script correction |
| Tests | **72 passing** — 20 unit + 11 WS/auth + 8 abuse-limit + 10 style + 16 info-exposure + 7 VAD-join |
| Docs | README · setup-guide · troubleshooting · handover · analysis (KO/EN) |
| Security | **C-1·C-2·H-1·H-3·H-4·M-1·M-2·M-3·M-5·L-1 done**. Remaining: H-2 (HTTPS/WSS) — only needed if exposed publicly |
| Deployment | LAN-only assumption. `main` is stable; features go on branches then merge |

---

## 3. Recently completed (2026-07-08, security phase 1)

CRITICAL findings from Agent A's analysis were **reproduced → fixed → re-verified**.

### Vulnerabilities actually reproduced before the fix
```
✅ Connected (Origin=evil.example.com was NOT rejected)
⚠️  Broadcast stopped WITHOUT a token → active = False
```
> This proved the "trusted LAN" assumption alone does not protect the server.
> Agent A's diagnosis was accurate.

### Fixes applied
| ID | Change | Files |
|---|---|---|
| **C-1** | Validate **WebSocket Origin** before accept; close `4403` on mismatch. Allows same host (Host header) & localhost, allows non-browser clients (no Origin), extra allowlist via `ALLOWED_ORIGINS` | `server/ws_server.py` |
| **C-2** | **Auto-generate token** (`secrets.token_urlsafe(18)`) when exposed on LAN → the "no auth" state no longer exists. Prints the access URL and writes `data/runtime/operator_url.txt` (mode 600); `start.sh` opens that URL | `server/config.py`, `server/ws_server.py`, `start.sh` |
| **H-1** | `hmac.compare_digest` constant-time compare + **close connection after 5 auth failures** + 0.5s delay per failure | `server/ws_server.py` |

### Verification after the fix (actually executed)
```
C-1 external Origin   : ✅ blocked (InvalidStatus)
C-2 command w/o token : ✅ rejected (auth_error)
Legit operator (token): ✅ works (active=False)      ← no functional regression
H-1 brute force       : ✅ connection closed (ConnectionClosedError)
Mobile subtitles (LAN): ✅ works (verified via 192.168.1.190)
Unit tests            : ✅ 20 passed
```

### Design decisions other agents should know
1. Chose **token auto-generation over fail-fast startup** — a server that refuses to start
   right before a service is the bigger risk. Operator experience is unchanged
   (`start.sh` opens the tokenized URL automatically).
2. **Origin rule = "same as the Host the browser connected to"** — so phones opening `/m`
   via the LAN IP keep working. Use `ALLOWED_ORIGINS` for proxies/other domains.
3. `WS_HOST=127.0.0.1` (local-only) **does not generate a token** — no exposure, no friction.
4. The token file was later moved **outside the repo** ($TMPDIR) — see incident §3.2.

### Commit status
Security phase 1 landed in commit `a3f4fe0` (committed by the user). Follow-up work was pushed as
`a8ae88d` (token-file incident fix) · `de0f376` (security tests) · `5c52954` (collaboration report).
`docs/analysis-report.md/.en.md` are Agent A's output and were not modified by Agent B.

---

### 3.1 WS/auth integration tests (2026-07-08, Agent B)

Added **regression tests** now that security logic has landed.

- New file: `tests/test_ws_security.py` (11 tests)
  - Origin: external blocked / same host allowed / **mobile LAN IP allowed** / no-Origin allowed / `ALLOWED_ORIGINS`
  - Auth: missing & wrong token rejected / valid token works / **connection closed after repeated failures**
  - Token auto-gen: created when exposed on LAN / not created for local-only
- Isolation: `lifespan` opens audio devices/models, so **`pipeline` is mocked** to avoid touching
  real hardware or external APIs (reuse this pattern when adding tests).
- **Effectiveness verified (mutation testing)** — security code was deliberately disabled to confirm the tests catch it:
  ```
  Origin check disabled → 1 failed  (good: catches the hole)
  Token check disabled  → 3 failed  (good)
  After restore         → 31 passed, code restored (diff verified)
  ```
  → Confirms these aren't vacuous always-pass tests.
- Dependency: `httpx` required by `fastapi.testclient`; added to `requirements-dev.txt`.

---

### 3.2 ⚠️ Incident: token file committed to a PUBLIC repo (2026-07-08, resolved)

**Recorded so nobody repeats it.**

- **What happened**: while implementing C-2, the operator URL containing the token was written to
  `data/runtime/operator_url.txt`; that file landed in commit `a3f4fe0` and was **pushed to the
  PUBLIC repository**.
- **Why it wasn't prevented (2 root causes)**
  1. `.gitignore` had `data/runtime/   # comment` — **gitignore treats a trailing inline comment
     as part of the pattern**, so the rule never matched. (Verify with `git check-ignore -v <file>`.)
  2. Meanwhile the file had already been `git add`ed, and **tracked files cannot be excluded**
     by `.gitignore`.
- **Actual risk: low.** Auto-generated tokens are **regenerated on every startup**, so the leaked
  value was already invalid (verified: committed value ≠ current value). Had a fixed
  `OPERATOR_TOKEN` been in use, this would have been a **serious incident requiring rotation**.
- **Actions taken**
  1. `git rm --cached` to untrack (file kept on disk — needed at runtime).
  2. Moved the `.gitignore` comment to **its own line** so the rule actually works.
  3. **Root fix**: moved the token file outside the repo (`$TMPDIR/translateviewer/`) →
     **there is no in-repo path to commit**. `start.sh` updated to read the new location.
- **Lessons / rules for other agents**
  - Store secrets **outside the repository** (`tempfile.gettempdir()`).
  - **Never use inline comments in `.gitignore`**; after adding a rule, confirm with
    `git check-ignore -v <file>`.
  - Check `git status` for unexpected files before committing.

---

### 3.3 Abuse limits H-3 / H-4 (2026-07-08, Agent B)

Thresholds applied after user approval.

| Item | Value | Behavior |
|---|---|---|
| Command cooldown | **2s** (set_backend **10s**) | Broadcasts `command_throttled`, ignores the command |
| Cooldown scope | set_languages·set_backend·set_broadcast·set_device·set_script | Harmless ones (reset, list_devices) excluded |
| Max script | **100,000 chars** | Truncated + `script_truncated` notice |
| Max connections | **100** | New connections closed with `4429` |
| Max message | **512KB** | uvicorn `ws_max_size` (both entrypoints) |

- All tunable via env (`COMMAND_COOLDOWN_SEC`, etc. — see `.env.example`).
- Operator UI shows throttle/truncate notices (KO/EN).
- Tests: `tests/test_ws_limits.py` (8). **Mutation-verified**: disabling the cooldown,
  script cap, or connection cap each caused exactly 1 failure. Total **39 passed**.
- Real-server check: spamming a command gives `script_state → command_throttled(retry_after=2.0)`.

**Testing pitfall (hit for real)**: waiting on `receive_json()` after a command that may send
no response (`set_device` returns silently when `state.capture is None`) makes the test **hang
forever**. Use a command that always responds, or assert on **server state/results** instead.

---

### 3.4 M-2 style validation + mobile language persistence (2026-07-08, Agent B)

**M-2 `set_style` whitelist validation** — previously arbitrary keys were merged into state and
color length was unbounded, so junk values could propagate to every client (including the output screen).

| Field | Allowed |
|---|---|
| `fontSize` | number, clamped 1–20 |
| `padding` | number, 0–30 |
| `maxLines` | int, 0–10 |
| `region` | only `full`/`bottom`/`top` |
| `bgColor` | only `#RGB` or `#RRGGBB` |
| any other key | **dropped** |

- Explicitly rejects `bool` (since `bool` is a subclass of `int` in Python).
- Language colors (`_sanitize_languages`) now use the same `_is_hex_color` check
  (previously only checked a leading `#`).
- Real-server check: malicious input
  `{evil:"<script>", bgColor:"#zzz…3000 chars", fontSize:99999, region:"diagonal", maxLines:9999}`
  → result `{fontSize:20, bgColor:"#000000", padding:4, region:"full", maxLines:10}` (all blocked/clamped)
- Tests: `tests/test_style_validation.py` (10). **Mutation-verified**: disabling the whole
  validator fails 7, disabling only the color check fails 2. Total **49 passed**.

**7.2 Mobile language persistence** — the chosen language is saved in `localStorage` and restored
on reconnect/refresh (the auto-selected language on first visit is saved too). Wrapped in
`try/catch` so private-browsing storage failures don't break anything.

---

### 3.5 Info exposure & endpoint hardening M-1 / M-3 / L-1 (2026-07-08, Agent B)

**M-1 init split** — previously unauthenticated connections (attendee phones, output screen)
also received the device list, backend name, and script term count, exposing internals to anyone
who knows the URL.

| Payload | Contents |
|---|---|
| public `init` (no auth) | `style`, `output_enabled`, `layout`, `languages` — only what screens need |
| `operator_init` (after auth, once) | `devices`, `current_device`, `backend`, `broadcasting`, `script_terms`, `default_colors`, `max_languages` |

- The operator screen sends a harmless command (`list_devices`) right after `init` to **trigger
  auth**, then receives `operator_init` and behaves exactly as before.
- ⚠️ **Note for other agents**: on first successful auth, `operator_init` arrives **first**, so
  code/tests waiting for a command reply must skip it. Three existing tests broke for this
  reason; their helpers (`_send`/`_cmd`) now skip `operator_init`.

**M-3 `/qr.svg` length cap** — over 512 chars (`MAX_QR_TEXT_CHARS`) returns 400. Without a cap,
arbitrary text could be used to mass-generate QR codes and burn CPU (open-proxy abuse).

**L-1 security headers** — every HTTP response gets `X-Frame-Options: SAMEORIGIN`,
`X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`
(the last one prevents **tokenized URLs** from leaking outward).

**Real-server verification**
```
L-1 headers   : x-frame-options: SAMEORIGIN / nosniff / no-referrer  ✅
M-3 QR        : 26 chars → 200 · 600 chars → 400  ✅
M-1 pre-auth  : no leaked fields, only 4 public fields  ✅
M-1 post-auth : operator_init received (6 devices)  ✅
```
Tests: `tests/test_info_exposure.py` (11). **Mutation-verified**: disabling M-1 fails 1, M-3
fails 2, L-1 fails 4. Total **60 passed**.

---

### 3.6 M-5 lockfile · mobile accessibility · VAD re-assembly (2026-07-08, Agent B)

**M-5 dependency pinning + vulnerability scan — found and fixed real CVEs.**
```
pip-audit → Found 3 known vulnerabilities in 1 package
  pyasn1 0.6.3  PYSEC-2026-3455 / 3456 / 3457  (fix: 0.6.4)
→ upgraded to 0.6.4, rescan: No known vulnerabilities found ✅
→ full test suite still passes (no regression)
```
- Created `requirements.lock` (73 pinned) — use it in production for a reproducible set.
- Documented lockfile usage and `pip-audit` in `requirements.txt`.
- Pinned `pyasn1>=0.6.4` (indirect dependency, but it had the CVEs).

**Mobile accessibility (`/m`)** — for senior attendees.
- Top bar: **`A−` / `A+`** (3 text sizes: 1 / 1.3 / 1.6×), **`◐`** (high contrast: white bg, black text)
- Choices persist in `localStorage`. Implemented via a CSS variable (`--scale`) so the existing
  vw-based responsive sizing still works.

**VAD sentence re-assembly** — when the 8-second force-cut split a sentence, fragments were
translated separately, breaking context and causing mistranslations. Now fragments are
**joined until the sentence ends** and translated once.
- Flush immediately (to avoid subtitle lag) when: ends with sentence punctuation / the cut came
  from silence (likely a sentence end) / `STT_MAX_JOIN_SEGMENTS` (default 2) reached.
- **The Korean display still updates per fragment** for responsiveness — only translation waits.
- Set `STT_MAX_JOIN_SEGMENTS=0` to restore the old behavior if latency matters more.
- Tests: `tests/test_vad_join.py` (7, the flush rules). Total **67 passed**.

**Environment note**: after a USB re-plug the audio device **index changed 2→4**, so the local
backend failed to start. Fixed by setting `.env` to the device **name**
(`AUDIO_INPUT_DEVICE=Vocaster Two USB`). Prefer names — indices shift on re-connect.

---

### 3.7 ⚠️ Regression: cached screens made features look missing (2026-07-08, fixed)

**Symptom**: on the operator screen the **audio device could not be selected** and the
**online/offline backend toggle was gone** (badge showed `…` with an "operator token required" warning).

**Root cause**
1. The server was fine — verified directly over WebSocket: `operator_init` (devices=6) arrived.
2. The served HTML was fine — it contained the `operator_init` handler.
3. **No `Cache-Control` header.** FastAPI's `FileResponse` sets `ETag`/`Last-Modified`, so the
   browser **reused the old JS via 304**. The old JS had no `operator_init` handler, so the
   device list and backend badge never got filled.
   → The M-1 (init split) change regressed **only on cached pages**.

**Fix**
- HTML screens (`/`, `/operator`, `/m`, `/qr-view`) now send
  `Cache-Control: no-store, must-revalidate` and drop `ETag`/`Last-Modified`.
- QR/icons still cacheable (avoid needless re-downloads).
- Implementation pitfall: Starlette's `MutableHeaders` has **no `pop()`** → caused a 500; use `del`.
- Added 5 tests (`test_info_exposure.py`): no-store + validator removal on 4 screens, QR cacheable.

**Lesson**: if a frontend change makes features "disappear", **suspect caching first** and check
headers with `curl -sI`. Fixing it **server-side** beats asking users to hard-refresh.

---

### 3.8 ⚠️ Real cause: auto token changed on every restart (2026-07-08, fixed)

After the §3.7 cache fix, the **device selector stayed empty and the backend toggle was still
missing**. Re-diagnosis showed the cause was **not caching but the token**.

**How it was narrowed down (no guessing)**
1. Checked the server directly over WebSocket → `operator_init` (devices=6, backend=local) arrived fine.
2. Opened the latest tokenized URL in a real browser → **worked** (6 devices, badge shown).
3. The two user screenshots had **different tokens** (`a8gBuEv8…` → `E1sBjShyz…`)
   → the token was **regenerated on every restart**, invalidating already-open tabs.
4. Reproduced with an old token → `auth_error` → no `operator_init` → empty device list.
   **Exactly the reported symptom.**

**Fix**
- Persist the auto-generated token (`$TMPDIR/translateviewer/operator_token`, mode 600) and
  reuse it across restarts, so open tabs/bookmarks stay valid. Verified: same token before/after restart.
- Show a **large red banner** explaining the cause and the fix when the token is invalid
  (previously only a small warning that was easy to miss).

**Lesson**: when told "still broken after your fix", don't assume your change caused it —
**reproduce the symptom from scratch**. §3.7 (caching) was a real issue, but not the cause here.

### 3.9 Requested features: system audio · automatic transcript saving (2026-07-08)

- **System sound input**: already possible via virtual devices (BlackHole etc.), but hard to
  recognize — the device list now marks them **🔊 system audio** (`system_audio` flag).
  Useful for testing with YouTube videos.
- **Automatic transcript saving**: `LOG_TRANSCRIPTS` now defaults to **on** (the user judged
  transcription quality more critical than translation). Two formats are written:
  - `data/logs/sermon-<time>.txt` — human-readable `[10:56:21] (한국어) …`
  - `data/logs/sermon-<time>.jsonl` — machine-readable
  The path is printed at startup. Disable with `LOG_TRANSCRIPTS=0`.

---

### 3.10 Input level meter — "BlackHole selected but nothing transcribes" (2026-07-26, resolved)

**Symptom (user)**: operator screen looked fine, BlackHole 2ch was selectable, but nothing
was transcribed. "There seems to be no input signal."

**Diagnosis**: measured instead of guessing. Captured 3s from BlackHole →
`29 callbacks, peak RMS = 0.000000`. The stream opened and callbacks fired, but **every
sample was zero**. `system_profiler` showed the macOS default output was still the speakers.

**Cause**: not a code bug. BlackHole is an output→input loopback device, so unless
**macOS System Settings → Sound → Output** is switched to BlackHole, no audio ever flows in.
Selecting the input device is not enough.

**The real problem was unobservability**: everything looked correct on screen, so there was
no way to see that the signal was zero. That is exactly why the user asked for a meter.

**Implementation**
| Layer | What |
|-------|------|
| `audio_input.py` | Accumulate per-chunk RMS as a peak in the audio callback; `pop_level()` consumes and resets. `rms_to_dbfs()` floors at -60dB. Peak resets on device switch so the old device's signal can't look live |
| `ws_server.py` | `Hub._operators` tracks **authenticated operator sockets only**. `_level_heartbeat()` pushes `{"type":"level", dbfs, silent}` every 0.2s to those sockets only (5×/s to dozens of phones would be waste) |
| `operator/index.html` | Colour-scaled bar + dB readout. After 4s of silence, a hint **tailored to the selected device** (🔊 computer audio → change the macOS output; mic → check power/connection) |

**Two design calls**
- **Peak, not average**: averaging buries short speech in the surrounding silence and the bar
  barely moves.
- **No gradient on the bar itself**: the first version put the green→red gradient on the bar,
  and when the bar shrank the colours compressed so **green-yellow-red repeated three times**
  (caught in a screenshot). A colour scale must stay fixed regardless of bar length, so the
  gradient now lives on the container and an **overlay masks the not-yet-reached portion**.

**Verification** (measured in-browser)
- Vocaster → `-24 dB`, bar 59% (real room noise)
- BlackHole → `silent`, bar 0%, correct warning text
- Mapping: -60dB→0% / -30dB→50% / -3dB→95% (red zone)
- 85 tests pass (11 new level tests + 2 operator-only delivery tests)

**Note for other Agents**: `Hub` now has an `_operators` set. `unregister()` must remove from
both sets (otherwise we keep sending to dead sockets), and frequently-updating operator-only
data should use `send_operators()` rather than `broadcast()`.

## 4. Work Board

Status: 🔴 Not started · 🟡 In progress · 🟢 Done · ⚪ Deferred (intentional)

### 4.1 Security (analysis-report §6)
| ID | Item | Status | Owner | Notes |
|---|---|---|---|---|
| C-1 | WS Origin validation | 🟢 Done | Agent B | 2026-07-08, verified by repro test |
| C-2 | Token auto-gen / enforced auth | 🟢 Done | Agent B | Auto-generation approach |
| H-1 | Constant-time compare + failure limit | 🟢 Done | Agent B | Close after 5 failures |
| H-2 | Token in URL → HTTPS/WSS · sessionStorage | 🔴 Not started | — | Pair with UX 7.1 |
| H-3 | Rate limit on operator commands | 🟢 Done | Agent B | 2026-07-08 · 2s (backend 10s), mutation-verified |
| H-4 | WS message size / connection caps | 🟢 Done | Agent B | 2026-07-08 · script 100k chars · 100 conns · 512KB msg |
| M-1 | Send internal info in `init` only after auth | 🟢 Done | Agent B | 2026-07-08 · split public init / operator_init |
| M-2 | Whitelist-validate `set_style` | 🟢 Done | Agent B | 2026-07-08 · keys/types/ranges/color format, mutation-verified |
| M-3 | `/qr.svg` length limit | 🟢 Done | Agent B | 2026-07-08 · 512-char cap (400 over) |
| M-5 | Dependency lockfile + pip-audit | 🟢 Done | Agent B | 2026-07-08 · **found & fixed 3 real CVEs** (pyasn1) |
| L-1 | Security headers middleware | 🟢 Done | Agent B | X-Frame-Options·nosniff·Referrer-Policy |
| L-2–3 | Endpoint exposure · script length | ⚪ Deferred | — | Script length covered by H-4; /health acceptable on LAN |

### 4.2 Usability (analysis-report §7)
| Priority | Item | Status | Owner |
|---|---|---|---|
| High | Token input UX (sessionStorage / QR) | 🔴 Not started | — |
| High | Auto-stop broadcast on idle (`IDLE_STOP_MIN`) | ⚪ Deferred | — (risk of stopping mid-service → awaiting user decision) |
| High | Persist mobile language choice (localStorage) | 🟢 Done | Agent B (2026-07-08) |
| Medium | First-run onboarding (3-step mini guide) | 🔴 Not started | — |
| Medium | Stronger WS connection-state badge | 🔴 Not started | — |
| Medium | Mobile accessibility (font size / contrast) | 🟢 Done | Agent B (2026-07-08) |
| Low | Presets / show original text toggle | 🔴 Not started | — |

### 4.3 Quality & tech debt (analysis-report §8)
| Item | Status | Notes |
|---|---|---|
| **WS/auth integration tests** | 🟢 Done | Agent B, 2026-07-08 · `tests/test_ws_security.py` (11). **Mutation-tested** for effectiveness |
| Split `ws_server.py` (689 lines) | 🔴 Not started | auth / commands / routing |
| `print` → `logging` | 🔴 Not started | |
| Defensive handling of preview SDK fields | 🔴 Not started | Session-resumption regression risk |

### 4.4 Feature improvements (handover §9)
| Item | Status | Notes |
|---|---|---|
| VAD sentence re-assembly (accuracy↑) | 🟢 Done | Agent B · 2026-07-08, STT_MAX_JOIN_SEGMENTS=2 (0 disables) |
| i18n locale file split | 🔴 Not started | When 3+ UI languages |
| Logs → SQLite + review UI | 🔴 Not started | Currently JSONL |
| STT acceleration (draft model) | 🔴 Not started | |

---

## 5. File ownership (conflict avoidance)

Recently modified files and **cautions**. Leave a note in section 6 before touching these.

| File | Last modified by | Caution |
|---|---|---|
| `server/ws_server.py` | Agent B (security) | **Highest conflict risk** (689 lines, most features pass through). Overlaps with the module-split task |
| `server/config.py` | Agent B (token auto-gen) | `Settings` is a frozen dataclass — adding a field means updating `load()` too |
| `start.sh` | Agent B (tokenized URL) | Reads `data/runtime/operator_url.txt` |
| `.env.example` / `README.md` | Agent B | When behavior changes, **update docs too** (avoid doc/code drift) |
| `docs/analysis-report*.md` | Agent A | Agent B does not modify these (respecting ownership) |
| `web/operator/index.html` | (earlier) Agent B | Uses an i18n dictionary + `tmsg` pattern — new strings need both ko/en entries |

---

## 6. Handover notes / for the next agent

### Good next tasks (recommended order)
1. ~~WS/auth integration tests~~ → **Done** (2026-07-08). Reuse the `client` fixture
   (mocked `pipeline`) in `tests/test_ws_security.py` for new tests.
2. ~~H-3 / H-4~~ → **Done** (2026-07-08). All caps tunable via env.
3. **Token UX (H-2 + 7.1)** — store the token in `sessionStorage` with a one-time input UI.
   Not urgent right now because `start.sh` already opens the tokenized URL.
4. **M-2 whitelist-validate `set_style`** — fairly independent, low conflict risk, easy to test.

### Project conventions to follow
- **Measure, don't guess**: verify model specs / SDK fields with a small script (past issues
  like `en-US` → `1007` and the streaming-STT collapse were all caught by measurement).
- **Preserve online/offline symmetry**: put new features behind `TranslationBackend` when possible.
- **Update docs in the same change**: if behavior changes, fix README / setup-guide wording.
- **Tests must pass**: `GEMINI_API_KEY=test python -m pytest tests/ -q`
- **Check the port on restart**: if an old process holds 8000, **the old build answers** and it
  looks like your change didn't apply (this actually happened). Run
  `lsof -ti:8000 | xargs kill -9` before starting.

### Open questions (need user decision)
- Add **auto-stop on idle**? (cost savings ↔ risk of stopping mid-service)
- Any plan to **expose this server publicly** (ngrok etc.)? If yes, H-2 (HTTPS/WSS) becomes mandatory.
- Do the **`ws_server.py` module split** now, or after features stabilize?

---

## 7. Change log (this document)

| Date | By | Change |
|---|---|---|
| 2026-07-08 | Claude (Agent B) | Created. Recorded security phase 1, work board, file ownership, handover notes |
| 2026-07-08 | Claude (Agent B) | **Added interruption protocol (0.1) + Live Work Log (§8)** — closes the gap where usage limits/crashes leave no record |
| 2026-07-08 | Claude (Agent B) | **Real fix (§3.8)**: auto token regenerated on every restart → persisted & reused, plus auth banner |
| 2026-07-08 | Claude (Agent B) | **Requested features (§3.9)**: system-audio device tagging, transcript saving on by default |
| 2026-07-08 | Claude (Agent B) | **Regression fix (§3.7)**: cached HTML hid device select & backend toggle → no-store, 5 tests (72 total) |
| 2026-07-08 | Claude (Agent B) | **M-5 · mobile accessibility · VAD re-assembly done** (§3.6) — 3 pyasn1 CVEs fixed, lockfile, a11y UI, sentence joining + 7 tests (67 total) |
| 2026-07-08 | Claude (Agent B) | **M-1·M-3·L-1 done** (§3.5) — init split, QR cap, security headers, 11 tests (60 total) |
| 2026-07-08 | Claude (Agent B) | **M-2 & mobile language persistence done** (§3.4) — style whitelist + localStorage, 10 tests (49 total) |
| 2026-07-08 | Claude (Agent B) | **H-3 & H-4 done** (§3.3) — cooldown + script/connection/message caps + 8 tests (mutation-verified), 39 passing |
| 2026-07-08 | Claude (Agent B) | **Commit policy changed**: agents now commit/push directly (secret check required before push) |
| 2026-07-08 | Claude (Agent B) | **Incident §3.2**: token file was committed to the public repo → untracked, gitignore fixed, token file moved outside the repo |
| 2026-07-08 | Claude (Agent B) | **Added 11 WS/auth integration tests** (§3.1) — mutation-tested. 31 total passing. Updated §2, board 4.3, handover notes |

---

## 8. Live Work Log ★interruption-safe

> **Rule A**: when you start, write 3 lines here (start / plan / next step) **before touching code**.
> **Rule B**: update the `Next step:` line as steps complete — the last update marks where it stopped.
> When done, delete the entry, set the board item to `🟢 Done`, and summarize in section 3.

### Currently in progress
```
(none — no active work)
```

### Template (copy this)
```
- [START 2026-07-08 14:30 / Agent B] H-3 operator command rate limit
  Plan: add per-command cooldown (2s) at the entry of _handle_command in ws_server.py
  Next step: confirm threshold with user → implement → spam repro test → update README
```

### Interrupted / handed over
> Record confirmed interruptions here (Rules C & E). The agent taking over appends here too.

```
(none)
```
