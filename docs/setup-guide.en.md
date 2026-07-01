# Setup & Operation Manual

> 한국어: [setup-guide.md](setup-guide.md) · Dev troubleshooting: [troubleshooting-log.en.md](troubleshooting-log.en.md)

This app produces live subtitles via **online (Gemini)** or **offline (local models)**,
switchable on screen during operation.

---

## 1. Prerequisites

| Item | Notes |
|---|---|
| Computer | macOS / Windows / Linux (Python 3.10+). **Offline mode needs Apple Silicon Mac** |
| Audio interface | Mixer AUX/REC OUT → USB audio interface |
| Internet | Online mode only (wired recommended). Not needed offline |
| Gemini API key | Online mode only. https://aistudio.google.com/apikey |

> **Recommended**: take a clean AUX bus of the **preacher's mic only**. A main mix with
> congregation mics/music lowers accuracy.

---

## 2. Install

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```
`sounddevice` needs PortAudio — macOS: `brew install portaudio`, Ubuntu: `sudo apt install libportaudio2`.

---

## 3. API key (online mode only)

Skip to sections 5–6 if you only use offline mode.

- **Use a personal Google account.** The model `gemini-3.5-live-translate-preview` is
  API-key (AI Studio) only, and organization accounts block API keys.
- **Enable billing** (Tier 1 / paid) on the project in AI Studio → Billing.
- Create the key (AI Studio → API keys → Create), then:
  ```bash
  cp .env.example .env
  ```
  Set `GEMINI_API_KEY=...` in `.env` (git-ignored, never share).

---

## 4. Check audio input

```bash
python server/audio_input.py --list
python server/audio_input.py --monitor --device "Device Name"
```
Put the index (or name) into `AUDIO_INPUT_DEVICE` in `.env` (e.g. `2`).

---

## 5. Run

```bash
./start.sh                 # mac/linux (auto venv + server)
start.bat  or  start.ps1   # Windows
```
- Automatically **opens the operator screen** in your browser (`OPEN_BROWSER=0 ./start.sh` to disable).
- Startup backend comes from `.env` `BACKEND=gemini|local` (switchable on screen).
- Stop: `Ctrl+C`.

| Screen | URL | Use |
|---|---|---|
| Subtitle output | http://localhost:8000/ | Projector / OBS browser source |
| Operator | http://localhost:8000/operator | All control & monitoring |
| Mobile | http://localhost:8000/m | Attendees pick their language on phones |

---

## 6. Operator dashboard

Everything is controlled here during the service. Top-right **EN/한글** button switches UI language.

- **6-1. Start / stop broadcast** — turns the translation pipeline on/off. Stopping
  **actually halts online cost/compute** (languages kept). Use before/after service.
  (`AUTO_START=0` in `.env` starts stopped, at zero cost.)
- **6-2. Backend toggle** — click the top badge to switch online↔offline live (languages
  kept; offline load ~10s). One-click **fallback when internet drops**.
- **6-3. Audio source** — dropdown switches device instantly **without dropping the session**.
- **6-4. Languages (1–3)** — up to 3 targets, each with a text color; screen splits into rows.
  **N languages = N× cost** (online).
- **6-5. Sermon script (recommended)** — paste the script and Apply. Proper nouns are
  extracted to **auto-correct transcription** (e.g. wrong "Tebrew"→"Hebrew" so the
  translation is right too). Corrected before translation in local mode; persists across restarts.
- **6-6. Style & output region** — font size / background / padding, plus **region**
  (full / bottom band / top band) and **max lines** (0/1/2/3). Single-language + bottom
  band lets you put video behind and subtitles only at the bottom; a green background +
  OBS Color Key composites just the text.
- **6-7. Screen control** — 🖥 open output window (click/F for fullscreen), ↺ reset,
  ⏹ hide output / ▶ show (translation keeps running).
- **6-8. Mobile URL / QR** — detects LAN IP (works offline) and shows a QR. Click the QR
  or 🔍 to open a **separate window** with a big QR you can keep up for latecomers.
- **6-9. Usage badge** — shows elapsed time / estimated cost (online) and warns after 5 min idle.

> Opening a fresh output screen or restarting OBS auto-syncs current state.

---

## 7. OBS / projector

- **OBS**: Browser source → `http://localhost:8000/`. Set background green + a **Color Key**
  filter to composite only the text.
- **Projector directly**: move the output window to the projector display, then click for
  fullscreen (removes address/title bar). Or **install the page as a PWA** for a title-bar-only window.

---

## 8. Offline (local) mode install

No internet / no API cost. **Apple Silicon Mac (M1+)** required.

```bash
pip install -r requirements-offline.txt     # mlx-qwen3-asr
brew install ollama ffmpeg                    # skip if present
ollama pull translategemma:4b                 # translation model (fast, default, ~3GB)
#   for higher accuracy: ollama pull translategemma:12b

BACKEND=local ./start.sh
```

Pipeline: **Qwen3-ASR** (Korean STT, cuts utterances by silence) + **TranslateGemma** (Ollama).

Tuning (`.env`, optional):
| Var | Meaning |
|---|---|
| `MT_MODEL` | `translategemma:4b` (fast, default) / `12b` (accurate, slower) |
| `STT_MODEL` | `Qwen/Qwen3-ASR-0.6B` (fast, recommended) / `1.7B` |
| `STT_MIN_SILENCE_SEC` | Pause that ends an utterance (default 0.9). Raise (1.2–1.5) to reduce mid-sentence periods |
| `STT_MAX_SEGMENT_SEC` | Force-cut for run-on speech (default 8s) |
| `STT_SILENCE_RMS` | Silence threshold. Lower (0.008) if speech missed; raise (0.025) if noise triggers |

**Tip**: local is most accurate with short, clear sentences and a brief pause at the end.
Pin stubborn misrecognitions with a `fix:` rule in `data/glossary/glossary.txt`
(e.g. `fix: 티브리어 => 히브리어`).

---

## 9. Security (LAN exposure)

Default `WS_HOST=0.0.0.0` allows phones/PCs on the LAN (needed for mobile subtitles), but
`/operator` commands have **no auth by default** — anyone on the network could change settings.

- Set **`OPERATOR_TOKEN=<long random>`** in `.env` → control only via `…/operator?token=…`
- Or `WS_HOST=127.0.0.1` for this PC only
- Output (`/`) and mobile (`/m`) are read-only and safe to share

---

## 10. Pre-service checklist

- [ ] Input level OK (`--monitor`); wireless mic battery; wired internet (if online)
- [ ] `./start.sh` → operator shows "connected", correct backend badge
- [ ] Paste sermon script + Apply (if available)
- [ ] Test speech → subtitles within 1–3s
- [ ] Press **▶ Start broadcast** (or AUTO_START)
- [ ] **📱 Get QR** for attendees if needed

---

## 11. Troubleshooting

| Symptom | Action |
|---|---|
| No subtitles | Check "connected" → did you press **Start broadcast** → check server log |
| Subtitles freeze | Auto-reconnect (2s); restart if persistent |
| Wrong source | Switch via **audio source** dropdown (no session drop) |
| Proper nouns wrong | Paste the **sermon script** · glossary `fix:` rules |
| Internet down | **Click badge → offline fallback** (if installed) |
| Mid-sentence periods (local) | Raise `STT_MIN_SILENCE_SEC=1.2` |
| (local) no subtitles | Check device + `STT_SILENCE_RMS=0.008` |
| Phone can't open QR | Check Wi-Fi client isolation (guest network) |
| Last resort | **Hide output** or **Stop broadcast** — audio keeps going |

---

## 12. Cost

- **Online (Gemini)**: ~**$0.037/min × #languages**. 40-min sermon: 1 lang ≈ under $1.5, 3 langs ≈ $4.5.
  Don't forget **Stop broadcast** after service.
- **Offline (local)**: **$0** (electricity/hardware only). No internet.
