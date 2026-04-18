#!/usr/bin/env python3
"""
gui_main.py
-----------
AudioDesc GUI — wxPython Desktop Application Entry Point
100% Screen-Reader Accessible (NVDA, JAWS, VoiceOver, Orca)

Usage:
    python gui_main.py           # Launch GUI
    python gui_main.py --check   # Dependency check then GUI

Architecture:
    gui/
        app.py              — wx.App subclass, theme & accessibility setup
        main_window.py      — Top-level frame, menu bar, toolbar, status bar
        panels/
            project_panel.py    — Project list & management
            pipeline_panel.py   — Step-by-step pipeline (upload→describe→audio→dub→export)
            description_panel.py— Description editor & table
            player_panel.py     — Audio/video playback engine
            export_panel.py     — Export options
            batch_panel.py      — Batch queue management
            settings_panel.py   — Global settings & TTS config
        dialogs/
            project_dialog.py   — Create/edit project dialog
            tts_dialog.py       — TTS configuration dialog
            description_dialog.py — Edit single description
            preview_dialog.py   — Segment preview dialog
            cost_dialog.py      — API cost report dialog
            validation_dialog.py— Validation report dialog
            about_dialog.py     — About / version info

Accessibility notes:
    - Every control has wx.AcceleratorTable shortcut or explicit Help text
    - All labels use SetName() for screen-reader name override
    - ListCtrl columns have descriptive headers
    - Status bar announces key state changes
    - Dialogs close with Escape; all buttons focusable
    - No visual-only widgets (no custom drawn panels without fallback text)
    - wx.ACCESSIBLE role set on compound widgets
"""

import os
import sys
from pathlib import Path

# ── Ensure project root is on sys.path ────────────────────────────────────────
# gui_main.py lives inside audiodesc_gui/ which itself sits inside the
# audiodesc/ project root.  Walk up until we find the .env file so the
# launcher works no matter how deep the gui/ subfolder is placed.

def _find_project_root() -> Path:
    """Walk up from this file until we find .env or core/ — that's the root."""
    candidate = Path(__file__).resolve().parent
    for _ in range(5):  # max 5 levels up
        if (candidate / ".env").exists() or (candidate / "core").is_dir():
            return candidate
        candidate = candidate.parent
    # Fallback: directory containing gui_main.py
    return Path(__file__).resolve().parent

ROOT = _find_project_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Load .env ─────────────────────────────────────────────────────────────────
def _load_env():
    # Try root/.env first, then current working directory
    for env_file in [ROOT / ".env", Path.cwd() / ".env"]:
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            break  # stop after first found .env

_load_env()

# ── wx import with friendly error ─────────────────────────────────────────────
try:
    import wx
    import wx.adv
    import wx.lib.scrolledpanel as scrolled
except ImportError:
    print(
        "\n[ERROR] wxPython is not installed.\n"
        "Install it with:\n"
        "    pip install wxPython\n"
        "On Linux you may also need:\n"
        "    pip install wxPython --pre  (or use a wheel from extras.wxpython.org)\n"
    )
    sys.exit(1)

from gui.app import AudioDescApp


def main():
    app = AudioDescApp()
    app.MainLoop()


if __name__ == "__main__":
    main()
