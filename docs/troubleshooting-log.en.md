# Development Troubleshooting Log (Educational)

This document records the actual errors hit while building `translateViewer` and
how they were solved. Each case follows **Symptom → Cause → Fix → Lesson**. Use it
as a learning resource for anyone building a real-time speech/translation system
for the first time.

---

## 1. Authentication / account issues

### 1-1. Organization account refuses API key creation
- **Symptom**: Creating an API key returns *"API keys are not allowed. Use
  Application Default Credentials (ADC) instead."*
- **Cause**: A Google Workspace (organization) account has a **security policy that
  blocks API-key creation**.
- **Fix**: Create the key with a **personal Google account** that has no such policy.
- **Lesson**: Org accounts are often locked down. Start personal projects with a
  personal account to avoid workaround work.

### 1-2. ADC/Vertex workaround — but the model isn't there
- **Symptom**: To keep the org account, we considered the ADC (Vertex AI) path, but
  `gemini-3.5-live-translate-preview` wasn't available on Vertex.
- **Cause**: At the time, this model was **Gemini Developer API (AI Studio,
  API-key) only**.
- **Fix**: Commit to the personal account + API key path.
- **Lesson**: A "workaround path" doesn't always offer the same model. **Verify
  model availability first**, then choose the auth method.

### 1-3. Browser automation flagged as "suspicious" when creating project/key
- **Symptom**: Automated project/key creation returns *"The request is suspicious.
  Please try again."*
- **Cause**: Google's **bot detection** blocks automated creation requests.
- **Fix**: Create projects/keys **manually**. (Automation only for read/verify.)
- **Lesson**: Security-sensitive creation is bot-blocked. Don't try to bypass it;
  do it by hand.

---

## 2. Model / API configuration

### 2-1. Session connects, but sending audio throws `1007 invalid argument`
- **Symptom**: Right after `session connected`, `1007 None. Request contains an
  invalid argument.` repeats every 2 s; no subtitles.
- **Cause**: The target language code was passed as **`en-US` (with region
  suffix)**. This model rejects region-suffixed codes.
- **Fix**: Use **short codes** (`en`, `ja`, `es`, …). Chinese allows both `zh` and `zh-CN`.
- **How verified**: Stream silent PCM while connection-testing several codes →
  build a pass/reject table to confirm.
- **Lesson**: Connection validates setup; **the real invalid-argument shows up on
  the first data send**. A trivial format like a code value can block everything —
  **measure, don't guess**.

### 2-2. Can't output multiple languages from one session
- **Symptom**: One session outputs only one language.
- **Cause**: By design, session = one target language.
- **Fix**: Run a **separate session per language** and **fan-out** one audio stream
  to all of them.
- **Lesson**: Simultaneous multi-language = simultaneous sessions = **N× cost and
  concurrency**. Surface the cost to the user.

---

## 3. Billing

### 3-1. `1011 prepayment credits are depleted`
- **Symptom**: Key and model are fine, but `Your prepayment credits are depleted`.
- **Cause**: The prepaid billing project ran **out of credits**.
- **Fix**: Top up credits (or switch to postpaid). **The user must enter payment
  details themselves.**
- **Lesson**: Reaching the billing stage means auth/permission are already fine.
  Distinguishing error layers (auth vs permission vs billing) speeds up diagnosis.

---

## 4. Environment / running

### 4-1. `ModuleNotFoundError: No module named 'sounddevice'`
- **Symptom**: `python3 server/audio_input.py` can't find the module.
- **Cause**: Ran with system Python **without activating the virtualenv (.venv)**.
- **Fix**: `source .venv/bin/activate` first. (`./start.sh` does this automatically.)
- **Lesson**: Deps live only inside the venv. A launch script that forces activation
  prevents this mistake.

### 4-2. Audio device index treated as a string
- **Symptom**: `AUDIO_INPUT_DEVICE=2` selected the wrong device.
- **Cause**: `.env` values are always strings → sounddevice looked for a device
  *named* "2".
- **Fix**: Parse to `int` (index) when numeric, else `str` (name) — `_parse_device`.
- **Lesson**: External input (.env) is always a string. **Normalize types at the
  boundary.**

### 4-3. Server keeps running after you "close" it, and the port collides (orphan process)
- **Symptom**: `sermon` fails every time with `[Errno 48] address already in use`.
  Closing the browser tab or the terminal doesn't stop the server; it keeps holding port 8000.
- **Cause**: The server (uvicorn) is a **process independent of the browser**. ① A browser tab
  is just a connected client — closing it doesn't stop the server. ② If the terminal that
  launched the server closes, the process is adopted by the system (PID 1) and keeps running in
  the background as an **orphan process**. This ghost server holds the port, so every later
  restart collides.
- **Fix**: `start.sh` now checks for a listener before starting
  (`lsof -ti:PORT -sTCP:LISTEN`) and, if found, asks "kill and restart?" before proceeding.
  Manual cleanup: `lsof -ti:8000 -sTCP:LISTEN | xargs kill`.
- **How verified**: `ps -o ppid= -p <PID>` shows parent `1` (orphan); transcript-log filenames
  reveal the real startup history (e.g. a 10:54 server → an 11:10 server).
- **Lesson**: Server and client (browser) have **different lifetimes**. Stop the server at the
  process. Keeping the launching terminal open and ending with `Ctrl+C` prevents orphaning; a
  restart script should **check port ownership first**.

### 4-4. The auto operator token looks like it changes every restart
- **Symptom**: Each restart prints *"🔐 operator token auto-generated"* with a **different
  value**, making already-open operator tabs/bookmarks seem invalidated.
- **Cause**: The token is actually saved to a temp file and **reused**, but the message said
  "auto-generated" even on reuse — misleading. (During the earlier port-collision failures
  (4-3), the file wasn't established yet, so it really did differ each time — compounding the
  confusion.)
- **Fix**: Distinguish reuse vs new: print *"reusing saved operator token"* vs *"auto-generated"*.
- **How verified**: token file value = the running server's value = the URL token on screen all
  **matched** → reuse works correctly.
- **Lesson**: Saying "created" for an action that changes nothing (reuse) misleads users.
  **Log messages must reflect what actually happened.**

---

## 5. UI / subtitle rendering

### 5-1. Subtitles flicker too briefly
- **Symptom**: Only the latest tiny fragment flickers, not the accumulated sentence.
- **Cause**: Transcription arrives as **deltas**, but the screen was replaced
  wholesale by each delta.
- **Fix**: **Accumulate** deltas into sentences and keep the previous sentence too
  (rolling).
- **Lesson**: Streaming text is incremental. Design the accumulate/replace policy
  explicitly.

### 5-2. Subtitles clipped in half top and bottom
- **Symptom**: When split into rows, text is cut in half at row boundaries.
- **Cause**: Rows used `justify-content: center`, so overflow was clipped on **both
  sides**.
- **Fix**: Anchor text to the **bottom of the row** (`position:absolute; bottom:0`)
  so only the top clips.
- **Lesson**: For "always show the latest" UIs, **bottom-anchor + top-clip** is the
  standard pattern.

### 5-3. Browser menu/address bar leaks onto the output screen
- **Symptom**: Tabs/address bar visible on the projector.
- **Fix**: Open a separate popup window + **fullscreen toggle** (Fullscreen API,
  double-click).
- **Lesson**: Cleanest output = OBS browser source or true fullscreen.

### 5-4. Operator screen's transcript/translation area grows off-screen
- **Symptom**: The Korean-transcript and translation cards grow taller without bound as speech
  accumulates, pushing the top of the dashboard out of view (the window grows instead of scrolling).
- **Cause**: The server caps the transcript at the last 16 lines (tail), but the screen CSS
  (`.source`/`.target-line`) had no `max-height`/`overflow`, so the card grew past the viewport.
- **Fix**: Give both areas `max-height` + `overflow-y:auto`, and on each new subtitle set
  `scrollTop=scrollHeight` to **auto-scroll to the bottom so the latest is always visible**.
- **Lesson**: For "ever-accumulating" areas, pair **height cap + scroll + auto-reveal-latest**.
  Even if the server limits the data, the display must limit it again or the screen grows forever.

---

## 6. Offline (local) backend — the richest learning section

### 6-1. `RuntimeError: Event loop is closed` traceback on shutdown
- **Symptom**: After `Ctrl+C`, a traceback prints despite a clean shutdown.
- **Cause**: STT inference ran via `asyncio.to_thread` (default thread pool); after
  the loop closed, that pool touched the closed loop.
- **Fix**: Run STT inference on a **dedicated `ThreadPoolExecutor`** and clean up
  the task/pool explicitly in `aclose()` on shutdown.
- **Lesson**: Leaving blocking work in the default pool causes shutdown races.
  **Manage lifecycles yourself.**

### 6-2. STT outputs a list of Bible terms verbatim (hallucination)
- **Symptom**: Regardless of speech, it kept showing *"Jehovah God Jesus Christ …"*.
- **Cause**: To boost accuracy, the STT `context` was given a **long proper-noun
  list**, and the model regurgitated that list as the transcript.
- **Fix**: Default context = **empty string**. If needed, only a few key terms, short.
- **Lesson**: ASR context/hotword features **hallucinate when overused**. Use sparingly.

### 6-3. Real-time streaming STT accuracy is terrible
- **Symptom**: Live output was just **filler fragments** like `hamyeon.imi.eo.imi…`.
- **Cause**: Qwen3-ASR's **streaming mode** dropped/garbled audio (whole-file
  transcription was near-perfect).
- **Fix**: Drop streaming; use **VAD (silence detection) to cut utterances** and run
  full `transcribe()` on each segment → whole-file-grade accuracy.
- **How verified**: Run the same audio through (a) streaming and (b) VAD-segmented,
  compare directly.
- **Lesson**: "Real-time = streaming" isn't always right. Accepting a small delay to
  transcribe **per utterance** can yield far better subtitle quality.

### 6-4. First-sentence translation lags ~18 s
- **Symptom**: Only the first translation is very slow.
- **Cause**: **Cold load** of the local translation model (Ollama).
- **Fix**: **Warm up** with a dummy translation at startup + `keep_alive` to stay warm.
- **Lesson**: Local LLMs are slow on the first call. Preload into memory.

### 6-5. Per-word translation calls pile up latency
- **Symptom**: Translation falls further behind the longer you speak.
- **Cause**: Calling the heavy translation model **per transcription fragment** →
  queue backup.
- **Fix**: Batch by **sentence/utterance** (far fewer calls). After VAD, one call per
  utterance.
- **Lesson**: For heavy post-processing, **call frequency = latency**. Group by
  meaning units.

### 6-6. A bigger STT model wasn't better
- **Symptom**: Bumping to 1.7B for accuracy was **slower and not more accurate**.
- **Fix**: Keep 0.6B (warm: ~3.7 s for 9 s of audio). Make model size env-swappable.
- **Lesson**: "Bigger = better" is false. **Measure** cost vs benefit.

### 6-7. Gauge shows signal, but offline transcription produces nothing (input too quiet)
- **Symptom**: Input that worked online (Gemini) produces **no transcription at all** offline.
  The input-level bar is green (-42 dB) as if signal is arriving, yet transcription is empty.
- **Cause**: The input is below the offline STT's VAD **silence threshold**
  (`SILENCE_RMS=0.015` ≈ **-36.5 dBFS**), so **everything is discarded as "silence"** — no
  utterance segment forms and `transcribe()` is never called. Online (Gemini) transcribes quiet
  audio thanks to its own gain/noise handling, hence "online works, offline doesn't." Also, the
  gauge floor (-60 dB) and the STT threshold (-36.5 dB) differ, creating a **blind spot where
  the bar is green but nothing transcribes** (-60 to -36.5 dB).
- **Fix**: ① Raise system/mixer **volume** above the threshold. ② When offline hits this dead
  zone, show a gauge warning: *"Audio is too quiet to transcribe. Raise the volume"* (`too_quiet`).
  You may lower `STT_SILENCE_RMS`, but that trades off against noise false-positives.
- **How verified**: Raising system volume to 100% started transcription immediately.
- **Lesson**: **"Signal is visible ≠ it's processed."** When the display (gauge) and the actual
  decision (STT threshold) use different criteria, users can't find the cause. **Observability**
  (surfacing *why* it isn't working) is the key to debugging.

---

## 7. Git / collaboration

### 7-1. Push rejected (non-fast-forward)
- **Symptom**: `git push` says *"Updates were rejected … use 'git pull' before
  pushing."*
- **Cause**: The remote had a commit the local branch lacked (a README edited via
  the web UI).
- **Fix**: `git pull --rebase origin main`, then push. (Identical change auto-skips.)
- **Lesson**: Editing the remote via another path (web UI) diverges history. Make
  **pull --rebase before push** a habit.

---

## Appendix: general debugging principles used

1. **Measure, don't guess**: For value/format issues, confirm with a small repro script.
2. **Separate error layers**: auth / permission / billing / data (invalid argument).
3. **Verify with official docs**: Always check models/specs newer than your knowledge
   cutoff against official docs/forums.
4. **Isolate secrets**: API keys, logs, scripts go behind `.gitignore` from day one.
5. **Stay reversible**: Do big changes on a **branch**; always protect the working
   version (main).
