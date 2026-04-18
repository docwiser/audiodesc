# AudioDesc GUI — Installation & Usage Guide

## Overview

AudioDesc GUI is a **100% screen-reader accessible** desktop application built with
**wxPython** that wraps the entire AudioDesc pipeline in a native desktop UI.

It is compatible with:
- **NVDA** (Windows)
- **JAWS** (Windows)
- **VoiceOver** (macOS)
- **Orca** (Linux/GNOME)

---

## Prerequisites

1. **Python 3.10+** (3.11 recommended)
2. **ffmpeg** with `ffplay` included (required for audio/video playback)
3. **wxPython 4.2+** (see install instructions below)
4. All other AudioDesc dependencies (see `requirements.txt`)

---

## Install ffmpeg

**Ubuntu/Debian:**
```bash
sudo apt update && sudo apt install ffmpeg -y
```

**macOS (Homebrew):**
```bash
brew install ffmpeg
```

**Windows:**
Download from https://ffmpeg.org/download.html and add `bin/` folder to PATH.

---

## Install wxPython

wxPython provides native screen-reader accessible GUI widgets on all platforms.

### Windows / macOS (simple):
```bash
pip install wxPython
```

### Ubuntu/Debian Linux:
wxPython on Linux requires pre-built wheels. The easiest method:

```bash
# For Ubuntu 22.04 (Jammy):
pip install wxPython --pre \
  --find-links https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-22.04/

# For Ubuntu 24.04 (Noble):
pip install wxPython --pre \
  --find-links https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-24.04/
```

Alternatively, build from source (takes 20–40 minutes):
```bash
sudo apt install python3-dev libgtk-3-dev libwebkit2gtk-4.0-dev \
                 libgstreamer1.0-dev gstreamer1.0-gtk3 -y
pip install wxPython
```

Or install the system package:
```bash
sudo apt install python3-wxgtk4.0 -y
```

---

## Install all Python dependencies

```bash
# From the audiodesc/ root directory:
pip install -r requirements_gui.txt
```

---

## Configure API Keys

Create `.env` in the `audiodesc/` folder:
```
GEMINI_API_KEY=your_gemini_api_key_here
ELEVENLABS_API_KEY=optional_elevenlabs_key
OPENAI_API_KEY=optional_openai_key
```

Or set them in the **Settings** tab of the GUI.

---

## Launch the GUI

```bash
# From the audiodesc/ root directory:
python gui_main.py
```

---

## Application Layout

```
┌─────────────────────────────────────────────────────────┐
│ Menu: File | Pipeline | Tools | Help                     │
│ Toolbar: New | Open | 1:Upload | 2:Describe | 3:Audio... │
├─────────────────────────────────────────────────────────┤
│ Notebook tabs:                                           │
│  [Projects] [Pipeline] [Descriptions] [Player] ...      │
├─────────────────────────────────────────────────────────┤
│                    Active panel                          │
│                    content here                          │
├─────────────────────────────────────────────────────────┤
│ Status: Project: My Film | Stage: described | Ready      │
└─────────────────────────────────────────────────────────┘
```

---

## Screen Reader Usage

### Navigation
| Key          | Action                              |
|--------------|-------------------------------------|
| `Ctrl+1`–`6` | Switch notebook tabs                |
| `Tab`        | Move between controls               |
| `F5`–`F9`    | Run pipeline steps 1–5 (via menu)   |
| `Ctrl+N`     | New project                         |
| `Ctrl+O`     | Open project                        |
| `Ctrl+Q`     | Quit                                |
| `F1`         | About                               |

### Player Controls
| Key          | Action                              |
|--------------|-------------------------------------|
| `Space`      | Play / Pause                        |
| `←` / `→`   | Seek ±5 seconds                     |
| `↑` / `↓`   | Volume ±5%                          |

### Descriptions List
| Key          | Action                              |
|--------------|-------------------------------------|
| `Enter`      | Open description text editor        |
| `Delete`     | (in project list) Delete project    |

---

## Accessibility Design Notes

- **All controls have `SetName()`** — screen readers announce the widget role + name
- **All controls have `SetHelpText()`** — press `F1` or hover for tooltip text
- **No visual-only widgets** — no custom drawn items without fallback text
- **ListCtrl in report mode** — all columns keyboard navigable; row contents read as cells
- **Background threads** — pipeline steps run async so UI never freezes on screen reader
- **Status bar** — announces current project name, stage, and last action
- **Progress gauge** — labeled with `SetName()` and accompanied by a text label
- **Dialogs** — close with `Escape`, all buttons focusable, logical tab order
- **Play/Pause** — button label changes to "Pause" when playing (not just icon change)
- **Time display** — announced as `StaticText`, updated every 500ms during playback

---

## Pipeline Steps (from the Pipeline tab)

1. **Step 1 — Upload Video**: Browse to your video file. It's copied to the project
   folder and uploaded to the Gemini Files API for AI analysis.

2. **Step 2 — Generate Descriptions**: Choose a Gemini model and optional extra
   instructions. The AI analyzes the video and generates timed audio descriptions
   as structured JSON.

3. **Step 3 — Generate Audio**: Configure your TTS engine (Edge/ElevenLabs/OpenAI/gTTS),
   then synthesize all descriptions as MP3 clips. Optional loudness normalization.

4. **Step 4 — Dub Video**: Two-pass ffmpeg mix — all clips positioned by `adelay`,
   merged into one combined track, then mixed into video with volume ducking.
   Live progress bar during dubbing.

5. **Step 5 — Export**: Choose from: dubbed video, VTT, SRT, JSON, MP3 AD track,
   individual clips, CSV, plain text scripts, or a ZIP of everything.

---

## Player Features

The **Player tab** uses `ffplay` (included with ffmpeg) as the playback engine:

- Load original video, dubbed video, or any audio/video file
- Seek to any position (slider + time display)
- Volume control (0–150%)
- Speed control (0.5x to 2.0x)
- Description clip list — double-click any clip to play it
- Preview in context — mixes ±2s of original video audio with the description clip

---

## Troubleshooting

**`No module named 'wx'`**
→ Install wxPython (see above)

**`ffplay not found` in player**
→ Install ffmpeg (must include ffplay)

**`ModuleNotFoundError: No module named 'edge_tts'`**
→ `pip install edge-tts`

**Gray/missing descriptions panel after generation**
→ Click the **Reload** button in the Descriptions tab, or switch away and back

**TTS preview fails silently**
→ Check that ffplay is installed; see Tools → Check Environment

---

## File Structure

```
audiodesc/
├── gui_main.py              ← Launch GUI from here
├── gui/
│   ├── app.py               ← wx.App bootstrap
│   ├── main_window.py       ← Main frame, menu, toolbar, status bar
│   ├── panels/
│   │   ├── project_panel.py     ← Project list & management
│   │   ├── pipeline_panel.py    ← Step-by-step pipeline
│   │   ├── description_panel.py ← Description editor & table
│   │   ├── player_panel.py      ← Audio/video player
│   │   ├── batch_panel.py       ← Batch queue
│   │   ├── settings_panel.py    ← API keys & defaults
│   │   └── export_panel.py      ← Export dialog
│   └── dialogs/
│       ├── project_dialog.py        ← Create project
│       ├── describe_dialog.py       ← AI generation options
│       ├── tts_dialog.py            ← TTS configuration + preview
│       ├── description_dialog.py    ← Edit text / volume / timing
│       ├── preview_dialog.py        ← Segment preview in context
│       ├── validation_dialog.py     ← Validation report
│       ├── cost_dialog.py           ← API cost report
│       ├── env_check_dialog.py      ← Environment check
│       └── about_dialog.py          ← About AudioDesc
├── core/            ← Pipeline logic (unchanged)
├── tts/             ← TTS engines (unchanged)
├── export/          ← Export handlers (unchanged)
├── db/              ← Database (unchanged)
└── prompts/         ← AI prompts (unchanged)
```

---

## License

MIT — Free to use, modify, and distribute.
