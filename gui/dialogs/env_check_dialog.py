"""
gui/dialogs/env_check_dialog.py
gui/dialogs/about_dialog.py
"""

import wx
import subprocess
import importlib
import os
import sys


class EnvCheckDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(
            parent,
            title="Environment Check",
            size=(620, 520),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._build_ui()
        self._run_checks()

    def _build_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        hdr = wx.StaticText(self, label="AudioDesc Environment Check")
        hdr.SetFont(hdr.GetFont().Bold().Scaled(1.1))
        sizer.Add(hdr, 0, wx.ALL, 10)

        self.check_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_HRULES)
        self.check_list.SetName("Environment checks")
        self.check_list.InsertColumn(0, "Check",   width=200)
        self.check_list.InsertColumn(1, "Status",  width=220)
        self.check_list.InsertColumn(2, "Note",    width=180)
        sizer.Add(self.check_list, 1, wx.EXPAND | wx.ALL, 8)

        self.result_lbl = wx.StaticText(self, label="")
        self.result_lbl.SetFont(self.result_lbl.GetFont().Bold())
        sizer.Add(self.result_lbl, 0, wx.LEFT | wx.BOTTOM, 8)

        sizer.Add(wx.Button(self, wx.ID_CANCEL, label="&Close"), 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        self.SetSizer(sizer)

    def _run_checks(self):
        checks = []
        hard_fail = False

        # Python version
        major, minor = sys.version_info[:2]
        ok = major >= 3 and minor >= 10
        checks.append(("Python version", f"{major}.{minor}", "3.10+ required" if not ok else "OK", ok))

        # CLI tools
        for tool in ["ffmpeg", "ffprobe", "ffplay"]:
            try:
                subprocess.run([tool, "-version"], capture_output=True, timeout=5)
                checks.append((tool, "Found", "", True))
            except (FileNotFoundError, subprocess.TimeoutExpired):
                checks.append((tool, "NOT FOUND", "Install ffmpeg", False))
                hard_fail = True

        # Python packages
        packages = [
            ("google.genai",  "google-genai",  True),
            ("edge_tts",      "edge-tts",       True),
            ("gtts",          "gTTS",           True),
            ("moviepy",       "moviepy",        True),
            ("pydub",         "pydub",          False),
            ("rich",          "rich",           True),
            ("questionary",   "questionary",    True),
            ("pydantic",      "pydantic",       True),
            ("elevenlabs",    "elevenlabs",     False),
            ("openai",        "openai",         False),
            ("wx",            "wxPython",       True),
        ]
        for module, pip_name, required in packages:
            try:
                importlib.import_module(module)
                checks.append((pip_name, "Installed", "", True))
            except ImportError:
                status = "NOT installed" if required else "Not installed (optional)"
                note   = f"pip install {pip_name}" if required else "Optional"
                checks.append((pip_name, status, note, not required))
                if required:
                    hard_fail = True

        # API keys
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if api_key:
            masked = api_key[:8] + "…"
            checks.append(("GEMINI_API_KEY", masked, "Set", True))
        else:
            checks.append(("GEMINI_API_KEY", "NOT SET", "Set in .env or Settings tab", False))
            hard_fail = True

        el_key = os.environ.get("ELEVENLABS_API_KEY", "")
        checks.append(("ELEVENLABS_API_KEY", "Set" if el_key else "Not set (optional)", "Optional", bool(el_key) or True))

        # Populate list
        green  = wx.Colour(180, 255, 180)
        red    = wx.Colour(255, 180, 180)
        yellow = wx.Colour(255, 255, 180)

        for name, status, note, ok in checks:
            idx = self.check_list.InsertItem(self.check_list.GetItemCount(), name)
            self.check_list.SetItem(idx, 1, status)
            self.check_list.SetItem(idx, 2, note)
            if ok is True:
                self.check_list.SetItemBackgroundColour(idx, green)
            elif ok is False:
                self.check_list.SetItemBackgroundColour(idx, red)
            else:
                self.check_list.SetItemBackgroundColour(idx, yellow)

        if hard_fail:
            self.result_lbl.SetLabel("❌ Some required checks FAILED. See notes above.")
            self.result_lbl.SetForegroundColour(wx.Colour(180, 0, 0))
        else:
            self.result_lbl.SetLabel("✅ All required checks passed!")
            self.result_lbl.SetForegroundColour(wx.Colour(0, 130, 0))


class AboutDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(
            parent,
            title="About AudioDesc",
            size=(500, 360),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        self._build_ui()

    def _build_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(self, label="AudioDesc")
        title.SetFont(wx.Font(18, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        sizer.Add(title, 0, wx.ALL | wx.ALIGN_CENTER, 12)

        subtitle = wx.StaticText(self, label="AI-Powered Audio Description Generator")
        sizer.Add(subtitle, 0, wx.ALIGN_CENTER | wx.BOTTOM, 6)

        info_text = (
            "AudioDesc generates professional, timestamped audio descriptions\n"
            "for video content using Google Gemini AI, making videos accessible\n"
            "for blind and visually impaired audiences.\n\n"
            "Pipeline:\n"
            "  1. Upload video → Gemini Files API\n"
            "  2. AI analysis → structured audio description JSON\n"
            "  3. Text-to-speech synthesis (Edge/ElevenLabs/OpenAI/gTTS)\n"
            "  4. Two-pass ffmpeg dubbing with volume ducking\n"
            "  5. Export (VTT, SRT, JSON, MP3, MP4)\n\n"
            "GUI: wxPython — 100% screen-reader accessible\n"
            "Playback engine: ffplay (bundled with ffmpeg)\n\n"
            "Standards: MIB India, Netflix, ITC, DCMP\n"
            "License: MIT"
        )
        info_lbl = wx.StaticText(self, label=info_text)
        sizer.Add(info_lbl, 0, wx.ALL, 12)

        sizer.Add(wx.Button(self, wx.ID_OK, label="&OK"), 0, wx.ALL | wx.ALIGN_CENTER, 10)
        self.SetSizer(sizer)
