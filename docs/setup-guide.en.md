# Setup & Operation Guide

> 한국어: [setup-guide.md](setup-guide.md)

## 1. Prerequisites

| Item | Notes |
|---|---|
| Computer | macOS / Windows / Linux (Python 3.10+). Offline mode needs Apple Silicon. |
| Audio interface | Mixer AUX/REC OUT → USB audio interface |
| Wired internet | For online mode; more stable than Wi-Fi during service |
| Gemini API key | https://aistudio.google.com/apikey (online mode only) |

> **Recommended**: take a **clean bus of the preacher's mic only** from the mixer
> (a separate AUX). A main mix with congregation mics / music lowers accuracy.

## 2. Install

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`sounddevice` needs PortAudio:
- macOS: `brew install portaudio`
- Ubuntu: `sudo apt install libportaudio2`

## 3. API key (sensitive) — online mode

> Use a **personal Google account**. Organization accounts often block API keys.
> The model `gemini-3.5-live-translate-preview` is API-key (AI Studio) only.

```bash
cp .env.example .env
```
Open `.env` and set `GEMINI_API_KEY`. This file is git-ignored — never share it.
Billing (paid tier) must be enabled on the project; enter card details yourself.

> Tip: creating a brand-new GCP project via browser automation gets blocked as a
> "suspicious request". Create projects/keys manually.

## 4. Check the audio device

```bash
python server/audio_input.py --list
python server/audio_input.py --monitor --device "USB Audio CODEC"
```
Put the index (or name) into `AUDIO_INPUT_DEVICE` in `.env`. Numeric = device index,
text = device name.

## 5. Run

```bash
./start.sh                  # online (or: python server/ws_server.py)
BACKEND=local ./start.sh    # offline (needs offline install, see 6.5)
```

| Screen | URL | Use |
|---|---|---|
| Subtitle output | http://localhost:8000/ | Projector fullscreen / OBS browser source |
| Operator | http://localhost:8000/operator | Monitor + control |

### OBS
1. Add Source → **Browser**, URL `http://localhost:8000/`.
2. For chroma key, set background color to green in the operator panel, then add a
   **Color Key** filter on the browser source.

## 6. Operator dashboard

Everything is controlled on screen during the service.

- **6-1. Audio source**: pick a device from the dropdown → switches instantly,
  **without dropping the session**. 🔄 refresh after plugging in a new interface.
- **6-2. Output control**: ↺ Reset (clear subtitles), ⏹ Stop / ▶ Resume (blank only
  the output screen; translation keeps running).
- **6-3. Style**: font size / background color / padding, applied live.
- **6-4. Languages (1–3)**: pick up to 3 targets, each with its own text color; the
  output splits into rows. N languages = N× cost/compute.
- **6-5. Backend toggle**: click the top badge to switch online(Gemini)↔offline
  (local) live. Switching to offline takes ~10 s to load models. Great as an
  internet-drop fallback.

> Opening a fresh output screen or restarting OBS auto-syncs current state.

## 6.5 Offline (local) install — optional

Runs with no internet and no API cost. Requires **Apple Silicon Mac (M1+)**.

```bash
pip install -r requirements-offline.txt   # mlx-qwen3-asr
brew install ollama ffmpeg                 # skip if present
ollama pull translategemma:12b             # ~8GB
BACKEND=local ./start.sh
```

Pipeline: **Qwen3-ASR** (Korean STT; cuts utterances by silence and transcribes
each) + **TranslateGemma** (translation via Ollama). One Korean transcript →
multiple language translations.

Tuning (`.env`, optional):
- `STT_SILENCE_RMS` — silence threshold. If speech isn't detected, lower it (0.008);
  if noise triggers it, raise it (0.025).
- `STT_MIN_SILENCE_SEC` — pause length that ends an utterance (default 0.7 s).
- `MT_MODEL` — `translategemma:12b` (accurate) / `translategemma:4b` (fast).
- `STT_MODEL` — `Qwen/Qwen3-ASR-0.6B` (fast, recommended) / `Qwen/Qwen3-ASR-1.7B`.

Operation tip: local mode is most accurate with **short, clear sentences and a brief
pause at the end of each**. Run-on/complex sentences and disfluencies hurt quality —
coach the speaker to break it up.

## 7. Pre-service checklist

- [ ] Mixer AUX → interface → computer input level OK (`--monitor`)
- [ ] Wireless mic battery
- [ ] Wired internet (online mode)
- [ ] Operator shows "connected"
- [ ] Test speech produces subtitles within 1–3 s
- [ ] **Run 15+ minutes** (online): session resumption works seamlessly

## 8. When things go wrong

| Symptom | Action |
|---|---|
| No subtitles | Check operator connection status → check server console log |
| Subtitles freeze | Server auto-reconnects (2 s); restart if persistent |
| Wrong source | Switch via the **audio source** dropdown (no session drop) |
| Bad translations | Check input audio quality (other sounds mixed in?) |
| Messy subtitles | **↺ Reset** on the operator screen |
| **Internet down** | Click the badge → **fall back to offline** (if local mode installed) |
| (local) no subtitles | Check input device + lower `STT_SILENCE_RMS` (0.008) |
| (local) repeats junk | Check input device/channel; speak short, clear sentences |
| Last resort | **⏹ Stop output** — subtitles off, audio continues; service unaffected |

## 9. Cost

- **Online (Gemini)**: ~**$0.037/min × #languages**. A 40-min sermon, 1 language ≈
  under $1.5; 3 languages ≈ $4.5. Billing: [AI Studio billing](https://ai.google.dev/gemini-api/docs/billing).
- **Offline (local)**: **$0** (electricity/hardware only). No internet needed.

For more, see [troubleshooting-log.en.md](troubleshooting-log.en.md).
