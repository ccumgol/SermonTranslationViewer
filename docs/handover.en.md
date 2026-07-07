# Project Handover Report (translateViewer)

> 한국어: [handover.md](handover.md)
> See also: [README.en.md](../README.en.md) · [setup-guide.en.md](setup-guide.en.md) · [troubleshooting-log.en.md](troubleshooting-log.en.md)

This document helps a successor quickly understand the project's **intent, structure,
decision rationale, and pitfalls**, and continue development.

---

## 1. One-line summary / intent

**A system that translates a Korean sermon into multiple languages in real time and sends
subtitles to a projector, OBS, and attendees' phones.**

- Background: churches with growing multilingual/foreign attendance need live sermon
  interpretation/subtitles.
- Goals: (1) real-time (a few seconds latency) (2) **accuracy** (in a sermon one wrong word
  changes theological meaning) (3) operability (non-developer volunteers operate on screen)
  (4) **cost / offline resilience**.
- Core philosophy: **"Don't bet everything on a single real-time AI translation."**
  Script-based correction + real-time fill-in, and online/offline duality for reliability.

---

## 2. Big-picture architecture

```
[Mixer/Mic] → Audio capture (16kHz mono PCM) → fan-out (duplicate)
                                                 │
                        ┌────────────────────────┴────────────────────────┐
                        ▼                                                  ▼
                [Online: GeminiBackend]                          [Offline: LocalBackend]
        A Gemini Live session per language               One shared Korean STT (Qwen3-ASR)
        (speech → translation)                           → per-language TranslateGemma MT
                        └────────────────────────┬────────────────────────┘
                                                 ▼
                        Subtitle stabilization (RollingTranscript) + script/glossary fix
                                                 ▼
                            WebSocket broadcast (FastAPI) → screens
                     output (/) · operator (/operator) · mobile (/m) · QR (/qr-view)
```

- Online and offline are abstracted behind a `TranslationBackend` interface, **switchable
  live** from the operator screen (sharing the same audio pipeline and UI).
- Since there is one audio stream fed to multiple language sessions, **fan-out** (audio
  duplication) is central.

---

## 3. File responsibilities (server/)

| File | Role | Notes |
|---|---|---|
| `ws_server.py` | **Entrypoint**. FastAPI + WebSocket hub + AppState + worker mgmt + commands + endpoints | Largest; most orchestration lives here |
| `config.py` | Loads `.env`, parses audio device, backend/token selection | Local mode works without an API key (key read optionally) |
| `audio_input.py` | `AudioCapture` (capture + device switch), `AudioFanout`, `queue_chunks` | Callback runs on PortAudio thread → enqueue on loop thread, drop-oldest |
| `translation_backend.py` | `TranslationBackend`/`TranslationSession` protocols + `GeminiBackend` | Session interface: `run/set_target_language/stop` |
| `live_session.py` | Gemini Live wrapper. **15-min session resumption**, runtime language change, glossary system_instruction | Depends on preview SDK field names → check here first if spec changes |
| `local_backend.py` | Offline: `KoreanSTT` (VAD transcribe) + `LocalSession` (per-language MT) + `LocalBackend` | Many improvements concentrated here |
| `subtitle_engine.py` | `RollingTranscript` (accumulate deltas, time-based newline, tail) | Pure logic → tested |
| `glossary.py` | Glossary load / fix (correction) / term (translation hint) | Post-processing, not STT context (avoids hallucination) |
| `sermon_script.py` | Extract terms from the script + **phonetic transcription correction** | Conservative: syllable edit distance ≤ 1 |
| `languages.py` | Single source of supported languages (code/label/English name) | Shared by ws_server & local_backend |
| `transcript_logger.py` | Optional transcript/translation JSONL logging | Only when `LOG_TRANSCRIPTS=1` |
| `__main__.py` | `python -m server` entrypoint | Used by start.sh |

### web/
- `subtitle-overlay/` — output screen (per-language rows, region/line limit, fullscreen, PWA). Solid background (green-screen capable).
- `operator/` — operator dashboard (all controls + KO/EN i18n). Most complex frontend.
- `mobile/` — attendee phones (`/m`); pick a language, see only that one.
- `qr-view/` — large QR (`/qr-view`, separate window).

### data/ (git-ignored)
- `sermons/current_script.txt`, `logs/*.jsonl`, `glossary/glossary.txt`.
  Only `glossary.example.txt` is committed.

---

## 4. Key design decisions & rationale (inflection points)

Understanding "why it's built this way" matters most.

1. **Online engine: Gemini Live Translate dedicated model**
   - `gemini-3.5-live-translate-preview` does speech→translation in **one model** (simpler,
     more accurate than separate STT+MT). Input: 16kHz mono 16-bit PCM LE, 100ms chunks.

2. **15-min session limit → session resumption (most important online design)**
   - Audio-only sessions terminate at 15 min; sermons run 30–45 min → **resumption handle +
     go_away handling for seamless reconnect**. Without it, subtitles die mid-sermon.

3. **Text-only output (audio output OFF)**
   - `response_modalities=["TEXT"]` + input/output transcription. Not receiving translated
     audio **cuts output-token cost (~6× input) and latency**.

4. **Short language codes only** (`en` OK, `en-US` ❌)
   - Region-suffixed codes in `translation_config.target_language_code` cause **`1007 invalid
     argument`**. Verified empirically: `en/ja/zh/zh-CN/es/vi/fr/ru` OK, `en-US` rejected.

5. **Personal account + API key (auth path)**
   - Org (Workspace) accounts block API keys; Vertex AI lacks this preview model.
     → **Personal Gmail + API key (Tier-1 billing)**. Org/Vertex cannot use this model.

6. **Multi-language = N sessions + audio fan-out**
   - One session = one target language. Concurrent languages spin up **one session each**,
     fed the duplicated audio → **N× cost/compute** (surfaced to the user). Screen splits into rows.

7. **Online/offline 2-track (backend abstraction)**
   - Separated via `TranslationBackend` → audio/subtitle/web UI reused. Live toggle.
     **Offline fallback on internet failure** is a big win for churches.

8. **Offline stack: Qwen3-ASR (STT) + TranslateGemma (MT)**
   - Chosen via research: Qwen3-ASR is CJK-specialized (strong Korean), Apple Silicon MLX
     native; TranslateGemma is translation-dedicated (55 languages), served locally via Ollama.
     Both offline & free. Offline design is **one STT (shared) → per-language MT**, efficient for many languages.

9. **Offline STT: streaming → VAD-windowed transcribe (decisive pivot)**
   - Qwen3-ASR **streaming mode collapses accuracy** (drops audio, filler hallucinations);
     whole-file transcription is near-perfect. → **Cut utterances by silence (VAD) and run
     full `transcribe()` per segment** for whole-file-grade accuracy.

10. **Sentence/utterance-level translation + model warmup**
    - Calling heavy MT per word backs up the queue → **one call per utterance**. Warm up the
      MT at startup + `keep_alive` to kill the first-sentence cold delay.

11. **Model sizes decided by measurement**
    - STT: 1.7B not more accurate than 0.6B and slower → **keep 0.6B**.
    - MT: 12B accurate but 2× slower → after speed complaints, **default to 4b** (quality sufficient).

12. **Subtitle rendering: rolling + bottom-anchor + region**
    - Accumulate deltas into sentences, keep the previous one (rolling). Screen is
      **bottom-anchored, clipping the top** so the newest is always visible. Single language
      supports **bottom/top bands + line limits** for OBS compositing.

13. **Proper-noun accuracy: script correction + glossary (both post-processing)**
    - Injecting a word list into STT context caused **the model to regurgitate that list** →
      dropped. Instead **post-process**: (1) extract terms from the sermon script → phonetic
      correction ("Tebrew"→"Hebrew"), (2) glossary `fix:` for exact replacement. Correct
      transcription → correct translation automatically.

---

## 5. Feature timeline (summary)

Roughly evolved in this order (matches git log):

1. MVP: audio → Gemini Live → console subtitles, 15-min resumption.
2. WebSocket output + operator screen.
3. Subtitle stabilization (accumulate, time-based newline), bottom-anchor fixes clipping.
4. Multi-language (1–3) output + per-row colors + fan-out.
5. Live audio-source switch; operator controls language/style/reset/output toggle.
6. Offline backend (Qwen3-ASR + TranslateGemma) + backend abstraction + runtime toggle.
7. Offline quality/speed: VAD transcribe, sentence-level MT, warmup, 4b default, clean shutdown (executor).
8. Ops: cost/usage badge, start/stop broadcast, transcript logging, security token, /health, package run, Windows scripts, auto-open browser.
9. Output screen: black fullscreen/green-screen, fullscreen·PWA, region/line limit.
10. Accuracy: glossary wiring (local+Gemini), translation context (prev sentence), **sermon-script correction**.
11. UI: KO/EN i18n toggle.
12. Mobile: `/m` page, **mobile URL/QR extraction** (LAN IP detect + local QR), QR separate window.

---

## 6. Major errors & fixes (essentials)

Full list in [troubleshooting-log.en.md](troubleshooting-log.en.md). Remember especially:

| Symptom | Cause | Fix |
|---|---|---|
| `1007 invalid argument` (on audio send) | code `en-US` | use short code (`en`) |
| `1011 credits depleted` | prepaid credits out | top up / postpaid |
| org account API-key refusal / model absent on Vertex | policy / unsupported | personal account + API key |
| bot detection "suspicious" | automated project/key creation | create manually |
| `ModuleNotFoundError: sounddevice` | venv not active | `source .venv/bin/activate` (start.sh handles) |
| subtitles clipped top & bottom | rows vertically centered | bottom-anchor + top-only clip |
| `Event loop is closed` on exit | STT on default thread pool | **dedicated ThreadPoolExecutor** + `aclose()` |
| STT emits list of Bible terms | long list in STT context | remove context, use **post-correction** |
| live transcription collapses (filler) | Qwen3-ASR streaming mode | **VAD-windowed transcribe** |
| first sentence ~18s late | local MT cold load | **warmup** at start + keep_alive |
| mid-sentence periods | period added at breath/8s force-cut | strip force-cut period + silence 0.9s |
| git push rejected | remote ahead | `git pull --rebase` |

**Debugging principles (lessons)**: measure with a small repro instead of guessing;
separate error layers (auth/permission/billing/data); verify post-cutoff specs against official docs.

---

## 7. WebSocket protocol (summary)

- **Client → server commands** (operator; include `token` if required):
  `reset`, `set_output{enabled}`, `set_style{style}`, `set_languages{languages:[{code,color}]}`,
  `set_broadcast{active}`, `set_backend{backend}`, `set_device{device}`, `list_devices`, `set_script{text}`.
- **Server → client messages**:
  `init` (full state sync), `source` (Korean), `subtitle{lang,text}`, `layout`, `reset`,
  `output_state`, `broadcast_state`, `backend_state`, `backend_error`, `auth_error`,
  `device_state/list/error`, `style`, `usage`, `script_state`.
- HTTP endpoints: `/`, `/operator`, `/m`, `/qr-view`, `/qr.svg?text=`, `/lan-info`,
  `/manifest.webmanifest`, `/health`.

---

## 8. Environment variables (`.env`)

| Var | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | — | Online key (not needed if local-only) |
| `GEMINI_MODEL` | gemini-3.5-live-translate-preview | Online model |
| `BACKEND` | gemini | Startup backend (gemini/local) |
| `TARGET_LANGUAGE` | en | Startup target (short code) |
| `AUDIO_INPUT_DEVICE` | (default input) | number=index, text=name |
| `WS_HOST` / `WS_PORT` | 0.0.0.0 / 8000 | Server binding |
| `OPERATOR_TOKEN` | (none) | Operator command auth token |
| `AUTO_START` | 1 | 0 = start with broadcast stopped |
| `OPEN_BROWSER` | 1 | start.sh auto-open browser |
| `LOG_TRANSCRIPTS` | (off) | 1 = JSONL in data/logs |
| `COST_PER_MIN` / `IDLE_WARN_MIN` | 0.037 / 5 | Usage badge |
| `MT_MODEL` | translategemma:4b | Offline MT model |
| `STT_MODEL` | Qwen/Qwen3-ASR-0.6B | Offline STT model |
| `STT_MIN_SILENCE_SEC` | 0.9 | Utterance-ending pause (higher = sentence-level, more latency) |
| `STT_MAX_SEGMENT_SEC` | 8 | Force-cut cap |
| `STT_SILENCE_RMS` | 0.015 | Silence RMS threshold |

---

## 9. Known limitations & future work

**Limitations**
- Offline multi-language calls MT per language → slows as languages grow (shared GPU).
- Online (Gemini) produces its own translation server-side, so script correction only fixes
  the **displayed Korean**, not Gemini's translation (local corrects before translating, fixing both).
- **No auto-pause** on idle (warning only) — auto-stopping mid-service is risky, intentionally deferred.
- VAD cutting mid-sentence can break translation context (partly mitigated by prev-sentence context).
- i18n is dictionary-based → 3+ languages warrant **per-locale files**.
- 15-min resumption depends on preview SDK field names → may break if the model/SDK changes.

**Future work (suggested priority)**
1. **VAD sentence re-assembly**: gather force-cut fragments until a real sentence end, translate once.
2. **Cost auto-guard**: auto-stop broadcast after N idle minutes (optional).
3. **UI i18n scaling**: locale JSON + placeholders/plurals.
4. **STT acceleration**: draft-model (speculative decoding).
5. **Logging upgrade**: SQLite + review UI, per-session stats.
6. **Gemini translation correction**: stronger system_instruction or output post-processing.

---

## 10. Dev / ops notes

- **Repo**: https://github.com/ccumgol/SermonTranslationViewer (main is stable). Work on
  branches, merge `--no-ff`. `.env`, `data/`, `.claude/` are git-ignored.
- **Tests**: `GEMINI_API_KEY=test python -m pytest tests/ -q` (20+ pure-logic tests). Real
  models/audio are hard to automate → live checks needed.
- **Run**: `./start.sh` (auto-browser) / `python -m server` / Windows `start.bat`·`start.ps1`.
- **Resources**: offline uses MLX (Metal GPU) + Ollama (12B/4B), heavy on RAM/GPU. Prefer 4b on
  24GB; stop broadcast / `ollama stop` to release memory.
- **Antigravity IDE crashes**: opening this project in the IDE can crash the shared backend
  server (indexing `.venv` thousands of files + local-model resource pressure), making **all
  windows** demand reload. Fix: exclude `.venv/`, `data/`, `__pycache__` from indexing/watchers.

---

## 11. Advice for the successor

- **Read first**: this doc → `ws_server.py` (orchestration) → `local_backend.py` (offline core)
  → `live_session.py` (online core) → `operator/index.html`.
- **Measure before touching**: verify model specs (code values, field names) with a small script.
- **Preserve online/offline symmetry**: implement new features behind `TranslationBackend` when possible.
- **Accuracy first**: sermons carry high mistranslation risk — lean on script correction & glossary.
- **Cost awareness**: online bills per language × minute. Use stop-broadcast / auto-guards.
- **Stay reversible**: big changes on branches + tests; protect main (the working version).
