# AudioDesc — Installation Guide

## Prerequisites

- Python **3.10+** (3.11 recommended)
- `ffmpeg` installed on your system (required for audio/video processing)

### Install ffmpeg

**Ubuntu/Debian:**
```bash
sudo apt update && sudo apt install ffmpeg -y
```

**macOS (Homebrew):**
```bash
brew install ffmpeg
```

**Windows:**
Download from https://ffmpeg.org/download.html and add to PATH.

---

## 1. Clone / Download the project

```bash
# If using git:
git clone <repo-url>
cd audiodesc

# Or just place the folder wherever you like
cd audiodesc
```

---

## 2. Create a Virtual Environment (recommended)

```bash
python -m venv venv

# Activate:
# Linux/macOS:
source venv/bin/activate

# Windows (cmd):
venv\Scripts\activate.bat

# Windows (PowerShell):
venv\Scripts\Activate.ps1
```

---

## 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

> **Note:** If you encounter issues with `moviepy` on some systems, try:
> ```bash
> pip install moviepy==1.0.3
> ```

---

## 4. Configure Your Gemini API Key

### Option A — `.env` file (recommended)

Create a file named `.env` in the `audiodesc/` folder:

```
GEMINI_API_KEY=your_actual_api_key_here
```

Get your free API key at: https://aistudio.google.com/app/apikey

### Option B — Environment Variable

```bash
# Linux/macOS:
export GEMINI_API_KEY=your_actual_api_key_here

# Windows (cmd):
set GEMINI_API_KEY=your_actual_api_key_here
```

### Option C — Enter it at runtime

The app will prompt you for the API key if it's not found.

---

## 5. Verify Installation

```bash
python main.py --check
```

Expected output:
```
✅ Python version: OK
✅ ffmpeg: found
✅ google-genai: OK
✅ edge-tts: OK
✅ gTTS: OK
✅ moviepy: OK
✅ GEMINI_API_KEY: set
All checks passed. You're ready to go!
```

---

## 6. Launch the App

```bash
python main.py
```

---

## Project Folder Structure (auto-created on first run)

```
audiodesc/
├── main.py                  # Entry point / main menu
├── requirements.txt
├── install.md
├── .env                     # Your API key (create this!)
│
├── core/                    # Core pipeline logic
│   ├── project_manager.py   # Create/open/list projects
│   ├── gemini_uploader.py   # Upload video to Gemini Files API
│   ├── description_generator.py  # AI description generation
│   ├── pipeline.py          # Step-by-step pipeline runner
│   └── video_dubber.py      # Final video dubbing / mixing
│
├── tts/                     # TTS engines
│   ├── tts_manager.py       # Unified TTS interface
│   ├── gtts_engine.py       # Google TTS
│   └── edge_engine.py       # Microsoft Edge TTS
│
├── export/                  # Export handlers
│   ├── subtitle_exporter.py # VTT / SRT / JSON export
│   └── export_manager.py    # Zip packaging, export menu
│
├── db/                      # Local JSON database
│   └── database.py          # CRUD operations for projects
│
├── prompts/                 # AI prompts and instructions
│   ├── prompt.txt           # Main generation prompt
│   └── instructions.txt     # System instructions
│
├── data/                    # Auto-created runtime data
│   ├── projects.json        # Project database
│   └── projects/            # Per-project folders
│       └── {project_id}/
│           ├── uploads/     # Original video file
│           ├── audio/       # Generated audio clips
│           └── exports/     # Final export files
```

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'edge_tts'`**
```bash
pip install edge-tts
```

**`OSError: [Errno 2] No such file or directory: 'ffmpeg'`**
Install ffmpeg (see Prerequisites above) and ensure it's in your PATH.

**`google.auth.exceptions.DefaultCredentialsError`**
Make sure your `GEMINI_API_KEY` is set correctly in `.env` or environment.

**`MoviePy: ffmpeg binary not found`**
```bash
pip install imageio[ffmpeg]
python -c "import imageio; imageio.plugins.ffmpeg.download()"
```

---

## TTS Voices Quick Reference

### Edge TTS (Recommended — High Quality)
- `en-US-AriaNeural` — US English Female (warm, expressive)
- `en-US-GuyNeural` — US English Male (clear, authoritative)  
- `en-GB-SoniaNeural` — British English Female
- `en-AU-NatashaNeural` — Australian English Female

List all voices:
```bash
python -m edge_tts --list-voices
```

### Google TTS
- Language codes: `en`, `en-uk`, `en-au`, `fr`, `de`, `es`, etc.
- Speed: normal or slow

---

## License

MIT — Free to use, modify, and distribute.
