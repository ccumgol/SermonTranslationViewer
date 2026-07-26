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
| Tests | **31 passing** — 20 unit (pure logic) + 11 WS/auth integration (security regression guard) |
| Docs | README · setup-guide · troubleshooting · handover · analysis (KO/EN) |
| Security | **Phase 1 hardening done** (C-1, C-2, H-1). H-2–H-4 and M/L items not started |
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

## 4. Work Board

Status: 🔴 Not started · 🟡 In progress · 🟢 Done · ⚪ Deferred (intentional)

### 4.1 Security (analysis-report §6)
| ID | Item | Status | Owner | Notes |
|---|---|---|---|---|
| C-1 | WS Origin validation | 🟢 Done | Agent B | 2026-07-08, verified by repro test |
| C-2 | Token auto-gen / enforced auth | 🟢 Done | Agent B | Auto-generation approach |
| H-1 | Constant-time compare + failure limit | 🟢 Done | Agent B | Close after 5 failures |
| H-2 | Token in URL → HTTPS/WSS · sessionStorage | 🔴 Not started | — | Pair with UX 7.1 |
| H-3 | Rate limit on operator commands | 🔴 Not started | — | Prevent `set_backend`/`set_languages` spam |
| H-4 | WS message size / connection caps | 🔴 Not started | — | Includes script length cap |
| M-1 | Send internal info in `init` only after auth | 🔴 Not started | — | Device names etc. |
| M-2 | Whitelist-validate `set_style` | 🔴 Not started | — | Pydantic |
| M-3 | `/qr.svg` length + rate limit | 🔴 Not started | — | Open-proxy potential |
| M-5 | Dependency lockfile + pip-audit | 🔴 Not started | — | |
| L-1–3 | Security headers · endpoint exposure · script length | 🔴 Not started | — | |

### 4.2 Usability (analysis-report §7)
| Priority | Item | Status | Owner |
|---|---|---|---|
| High | Token input UX (sessionStorage / QR) | 🔴 Not started | — |
| High | Auto-stop broadcast on idle (`IDLE_STOP_MIN`) | ⚪ Deferred | — (risk of stopping mid-service → awaiting user decision) |
| High | Persist mobile language choice (localStorage) | 🔴 Not started | — |
| Medium | First-run onboarding (3-step mini guide) | 🔴 Not started | — |
| Medium | Stronger WS connection-state badge | 🔴 Not started | — |
| Medium | Mobile accessibility (font size / contrast) | 🔴 Not started | — |
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
| VAD sentence re-assembly (accuracy↑) | 🔴 Not started | Gather force-cut fragments until sentence end |
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
2. **H-3 / H-4** — command cooldown, WS size/connection caps, script length cap. These change
   behavior, so agree thresholds with the user first. **Good time now that tests exist.**
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
