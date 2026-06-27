# Sermon Real-Time Multilingual Subtitle System (translateViewer)

Translates a Korean sermon into multiple languages in real time and projects the
subtitles to a screen / OBS. It offers **two translation backends** — **online
(Gemini)** and **offline (local models)** — switchable instantly from the
operator dashboard.

> 📖 한국어: [README.md](README.md)
> 🛠 Setup & operation manual: [docs/setup-guide.en.md](docs/setup-guide.en.md)
> 🎓 Errors hit during development & how they were solved (educational): [docs/troubleshooting-log.en.md](docs/troubleshooting-log.en.md)

## Key features

- **Simultaneous multi-language output**: 1–3 target languages at once, screen split into rows (per-row text color).
- **Online/offline 2-track**: switch live by clicking the badge on the operator dashboard (fallback when the internet drops).
- **Seamless 15-minute session-limit bypass** (online): sermons run 30–45 min, so session resumption is handled automatically.
- **Operator dashboard**: change audio source, subtitle style, reset, stop/resume output — all from the screen during service.
- **OBS / projector output**: solid black fullscreen or green-screen (chroma key) background.

## The two backends

| | Online (gemini) | Offline (local) |
|---|---|---|
| Engine | `gemini-3.5-live-translate-preview` (single speech→translation model) | Qwen3-ASR (STT) + TranslateGemma (MT) |
| Accuracy | Best (robust to noise) | Good (best with quiet room & clear speech) |
| Latency | 1–3 s | 2–4 s (transcribes after a pause) |
| Cost | ~$0.037/min × #languages | **0 (no internet)** |
| Requires | API key + internet | Apple Silicon Mac + local models |

Offline design: **one shared Korean STT → N per-language translations**, which is efficient for multiple languages.

## Quick start (online)

```bash
# 1) Virtualenv + deps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2) Configure (enter API key)
cp .env.example .env
#   → edit .env, set GEMINI_API_KEY (get one at https://aistudio.google.com/apikey)

# 3) Find your audio input device
python server/audio_input.py --list
#   → put the index/name into AUDIO_INPUT_DEVICE in .env (e.g. 2)

# 4) Run
./start.sh          # or  python server/ws_server.py
```

- Subtitle output screen: <http://localhost:8000/> (use as an OBS browser source)
- Operator dashboard: <http://localhost:8000/operator>

## Offline (local) mode — extra install

```bash
pip install -r requirements-offline.txt   # mlx-qwen3-asr
brew install ollama ffmpeg                 # skip if already installed
ollama pull translategemma:12b             # translation model (~8GB)

BACKEND=local ./start.sh                    # start in offline mode
```
> Requires Apple Silicon (M1+). After launch, click the dashboard badge to toggle online↔offline.

## Operator dashboard

Everything is controlled from the screen during the service — no need to touch the
terminal or `.env`.

| Control | What it does |
|---|---|
| **Backend toggle** | Click the top badge → switch online↔offline live (keeps language setup) |
| **Target languages** | 3 slots for 1–3 languages, each with its own text color |
| **Audio input source** | Switch device instantly from a dropdown (**no session drop**) + 🔄 refresh list |
| **🖥 Open output window** | Separate window with no menu/address bar; double-click for fullscreen |
| **↺ Reset screen** | Clear accumulated subtitles immediately |
| **⏹ Stop / ▶ Resume output** | Blank only the output screen (translation keeps running) |
| **Style** | Font size · background color (black / green screen) · padding, live |

> Opening a fresh output screen or restarting OBS auto-syncs the current state
> (style, languages, output on/off).

## Privacy / sensitive data

| Item | Location | Protection |
|---|---|---|
| Gemini API key | `.env` | git-ignored, never hardcoded |
| Sermon scripts / logs / glossary | `data/` | git-ignored (only `.gitkeep` tracked) |
| Claude local settings | `.claude/` | git-ignored |

## Structure

```
server/
  config.py             config (.env) + audio device / backend selection
  audio_input.py        capture + live device switch + fan-out for sessions
  translation_backend.py backend abstraction + GeminiBackend (online)
  live_session.py       Gemini Live + 15-min session resumption
  local_backend.py      offline: Qwen3-ASR (VAD transcribe) + TranslateGemma
  subtitle_engine.py    subtitle accumulation + rolling display
  ws_server.py          FastAPI WebSocket + routing + control (entrypoint)
web/
  subtitle-overlay/     fullscreen output (multi-language rows & colors)
  operator/             operator dashboard
data/                   scripts / logs / glossary (git-ignored)
```

## Command cheat sheet

| Goal | Command |
|---|---|
| Start online | `./start.sh` (or `sermon`) |
| Start offline | `BACKEND=local ./start.sh` |
| Stop | `Ctrl+C` |
| Switch at runtime | Click the backend badge on the operator dashboard |
