"""
gui/panels/settings_panel.py
-----------------------------
Global settings panel.

Sections:
  - Gemini API key
  - ElevenLabs / OpenAI API keys
  - Default Gemini model
  - Default TTS engine
  - Default export directory
  - Environment check link
"""

import wx
import os
from pathlib import Path


class SettingsPanel(wx.Panel):
    def __init__(self, parent, main_window):
        super().__init__(parent)
        self.main_window = main_window
        self._build_ui()
        self._load_current_values()

    def _build_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        hdr = wx.StaticText(self, label="Settings")
        hdr.SetFont(hdr.GetFont().Bold().Scaled(1.2))
        sizer.Add(hdr, 0, wx.ALL, 8)

        # ── API Keys ──────────────────────────────────────────────────────────
        api_box = wx.StaticBox(self, label="API Keys")
        api_sizer = wx.StaticBoxSizer(api_box, wx.VERTICAL)
        g = wx.FlexGridSizer(rows=0, cols=3, vgap=8, hgap=8)
        g.AddGrowableCol(1)

        # Gemini
        g.Add(wx.StaticText(self, label="&Gemini API Key:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.gemini_key = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.gemini_key.SetName("Gemini API Key")
        self.gemini_key.SetHelpText("Your Google Gemini API key (kept in .env file)")
        g.Add(self.gemini_key, 1, wx.EXPAND)
        g.Add(wx.StaticText(self, label=""), 0)  # spacer

        # ElevenLabs
        g.Add(wx.StaticText(self, label="&ElevenLabs API Key:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.el_key = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.el_key.SetName("ElevenLabs API Key")
        g.Add(self.el_key, 1, wx.EXPAND)
        g.Add(wx.StaticText(self, label="(optional)"), 0, wx.ALIGN_CENTER_VERTICAL)

        # OpenAI
        g.Add(wx.StaticText(self, label="&OpenAI API Key:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.oai_key = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.oai_key.SetName("OpenAI API Key")
        g.Add(self.oai_key, 1, wx.EXPAND)
        g.Add(wx.StaticText(self, label="(optional)"), 0, wx.ALIGN_CENTER_VERTICAL)

        api_sizer.Add(g, 0, wx.EXPAND | wx.ALL, 8)

        save_key_btn = wx.Button(self, label="&Save API Keys to .env")
        save_key_btn.SetHelpText("Save all API keys to the .env file in the project root")
        api_sizer.Add(save_key_btn, 0, wx.ALL, 4)
        sizer.Add(api_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # ── Defaults ──────────────────────────────────────────────────────────
        def_box = wx.StaticBox(self, label="Pipeline Defaults")
        def_sizer = wx.StaticBoxSizer(def_box, wx.VERTICAL)
        g2 = wx.FlexGridSizer(rows=0, cols=2, vgap=8, hgap=8)
        g2.AddGrowableCol(1)

        g2.Add(wx.StaticText(self, label="Default Gemini &model:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.default_model = wx.ComboBox(
            self,
            choices=["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite", "gemini-2.0-flash"],
            style=wx.CB_READONLY,
        )
        self.default_model.SetValue("gemini-2.5-flash")
        self.default_model.SetName("Default Gemini model")
        g2.Add(self.default_model, 1, wx.EXPAND)

        g2.Add(wx.StaticText(self, label="Default &TTS engine:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.default_tts = wx.ComboBox(
            self,
            choices=["edge", "gtts", "elevenlabs", "openai"],
            style=wx.CB_READONLY,
        )
        self.default_tts.SetValue("edge")
        self.default_tts.SetName("Default TTS engine")
        g2.Add(self.default_tts, 1, wx.EXPAND)

        def_sizer.Add(g2, 0, wx.EXPAND | wx.ALL, 8)
        sizer.Add(def_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Tools ─────────────────────────────────────────────────────────────
        tools_box = wx.StaticBox(self, label="Tools")
        tools_sizer = wx.StaticBoxSizer(tools_box, wx.HORIZONTAL)
        btn_env   = wx.Button(self, label="&Check Environment")
        btn_about = wx.Button(self, label="&About AudioDesc")
        btn_env.SetHelpText("Check all required dependencies are installed")
        btn_about.SetHelpText("Show version and about information")
        tools_sizer.Add(btn_env,   0, wx.ALL, 4)
        tools_sizer.Add(btn_about, 0, wx.ALL, 4)
        sizer.Add(tools_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Status ────────────────────────────────────────────────────────────
        self.status_lbl = wx.StaticText(self, label="")
        sizer.Add(self.status_lbl, 0, wx.ALL, 8)

        self.SetSizer(sizer)

        # Events
        save_key_btn.Bind(wx.EVT_BUTTON, self._on_save_keys)
        btn_env.Bind(wx.EVT_BUTTON,      self._on_check_env)
        btn_about.Bind(wx.EVT_BUTTON,    self._on_about)

    def _load_current_values(self):
        self.gemini_key.SetValue(os.environ.get("GEMINI_API_KEY", ""))
        self.el_key.SetValue(os.environ.get("ELEVENLABS_API_KEY", ""))
        self.oai_key.SetValue(os.environ.get("OPENAI_API_KEY", ""))

    def _on_save_keys(self, event):
        # Find project root the same way gui_main.py does
        candidate = Path(__file__).resolve().parent
        root = candidate
        for _ in range(6):
            if (candidate / ".env").exists() or (candidate / "core").is_dir():
                root = candidate
                break
            candidate = candidate.parent
        env_file = root / ".env"

        lines = []
        if env_file.exists():
            with open(env_file) as f:
                lines = [l for l in f.readlines()
                         if not l.startswith("GEMINI_API_KEY")
                         and not l.startswith("ELEVENLABS_API_KEY")
                         and not l.startswith("OPENAI_API_KEY")]

        keys = {
            "GEMINI_API_KEY":      self.gemini_key.GetValue().strip(),
            "ELEVENLABS_API_KEY":  self.el_key.GetValue().strip(),
            "OPENAI_API_KEY":      self.oai_key.GetValue().strip(),
        }
        for k, v in keys.items():
            if v:
                lines.append(f"{k}={v}\n")
                os.environ[k] = v

        with open(env_file, "w") as f:
            f.writelines(lines)

        self.status_lbl.SetLabel(f"Keys saved to {env_file}")
        wx.MessageBox(f"API keys saved to:\n{env_file}", "Saved", wx.OK | wx.ICON_INFORMATION)

    def _on_check_env(self, event):
        from gui.dialogs.env_check_dialog import EnvCheckDialog
        dlg = EnvCheckDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def _on_about(self, event):
        from gui.dialogs.about_dialog import AboutDialog
        dlg = AboutDialog(self)
        dlg.ShowModal()
        dlg.Destroy()
