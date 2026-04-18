"""
gui/dialogs/settings_dialog.py
--------------------------------
Application Settings Dialog.

Replaces the old settings tab/panel with a proper modal dialog.
Opened via File > Settings (Ctrl+,) or the Settings button on the home screen.

Sections:
  - API Keys (Gemini required, ElevenLabs + OpenAI optional)
  - Pipeline Defaults (model, TTS engine)
  - Tools (Check Environment, About)

Accessibility:
  - Each StaticBox group maps to a logical fieldset
  - Every TextCtrl has an explicit StaticText label in the same FlexGridSizer row
  - Password fields labelled "hidden characters" in SetName so NVDA announces it
  - Buttons have full SetHelpText descriptions
  - Tab order: API keys → Defaults → Save → Tools → Close
  - Escape closes (standard dialog behaviour)
"""

import wx
import os
from pathlib import Path


class SettingsDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(
            parent,
            title="AudioDesc Settings",
            size=(560, 500),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.SetName("AudioDesc Settings Dialog")
        self.SetHelpText(
            "Configure API keys and pipeline defaults. "
            "Press Tab to move between fields. Press Escape to close."
        )
        self._build_ui()
        self._load_current_values()
        self.Centre(wx.BOTH)

    def _build_ui(self):
        root = wx.BoxSizer(wx.VERTICAL)

        # ── API Keys ──────────────────────────────────────────────────────────
        api_box   = wx.StaticBox(self, label="API Keys")
        api_sizer = wx.StaticBoxSizer(api_box, wx.VERTICAL)

        # Explanation
        note = wx.StaticText(
            self,
            label="Keys are stored in the .env file in your project root.\n"
                  "Gemini is required. ElevenLabs and OpenAI are optional.",
        )
        note.SetName("API key explanation")
        api_sizer.Add(note, 0, wx.ALL, 8)

        g = wx.FlexGridSizer(rows=0, cols=3, vgap=10, hgap=8)
        g.AddGrowableCol(1)

        # ── Gemini ────────────────────────────────────────────────────────────
        lbl_g = wx.StaticText(self, label="&Gemini API Key:")
        lbl_g.SetName("Gemini API Key label")
        self.gemini_key = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.gemini_key.SetName(
            "Gemini API Key, required, hidden characters. "
            "Get your key from aistudio.google.com"
        )
        self.gemini_key.SetHelpText(
            "Your Google Gemini API key (required). "
            "Get one free at aistudio.google.com. "
            "Stored in .env as GEMINI_API_KEY."
        )
        req_lbl = wx.StaticText(self, label="Required")
        req_lbl.SetForegroundColour(wx.Colour(180, 0, 0))
        g.Add(lbl_g,           0, wx.ALIGN_CENTER_VERTICAL)
        g.Add(self.gemini_key, 1, wx.EXPAND)
        g.Add(req_lbl,         0, wx.ALIGN_CENTER_VERTICAL)

        # ── ElevenLabs ────────────────────────────────────────────────────────
        lbl_el = wx.StaticText(self, label="&ElevenLabs API Key:")
        lbl_el.SetName("ElevenLabs API Key label")
        self.el_key = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.el_key.SetName(
            "ElevenLabs API Key, optional, hidden characters. "
            "Required only if you use ElevenLabs TTS engine."
        )
        self.el_key.SetHelpText(
            "ElevenLabs API key (optional). Only needed if you use ElevenLabs TTS. "
            "Get one at elevenlabs.io. Stored as ELEVENLABS_API_KEY."
        )
        g.Add(lbl_el,       0, wx.ALIGN_CENTER_VERTICAL)
        g.Add(self.el_key,  1, wx.EXPAND)
        g.Add(wx.StaticText(self, label="Optional"), 0, wx.ALIGN_CENTER_VERTICAL)

        # ── OpenAI ────────────────────────────────────────────────────────────
        lbl_oai = wx.StaticText(self, label="&OpenAI API Key:")
        lbl_oai.SetName("OpenAI API Key label")
        self.oai_key = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.oai_key.SetName(
            "OpenAI API Key, optional, hidden characters. "
            "Required only if you use OpenAI TTS engine."
        )
        self.oai_key.SetHelpText(
            "OpenAI API key (optional). Only needed if you use OpenAI TTS. "
            "Get one at platform.openai.com. Stored as OPENAI_API_KEY."
        )
        g.Add(lbl_oai,       0, wx.ALIGN_CENTER_VERTICAL)
        g.Add(self.oai_key,  1, wx.EXPAND)
        g.Add(wx.StaticText(self, label="Optional"), 0, wx.ALIGN_CENTER_VERTICAL)

        api_sizer.Add(g, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Save button inside the API Keys group
        self.btn_save_keys = wx.Button(self, label="&Save API Keys to .env File")
        self.btn_save_keys.SetHelpText(
            "Save all API keys to the .env file in your project root directory. "
            "The file will be created if it does not exist."
        )
        api_sizer.Add(self.btn_save_keys, 0, wx.ALL, 8)
        root.Add(api_sizer, 0, wx.EXPAND | wx.ALL, 10)

        # ── Pipeline defaults ─────────────────────────────────────────────────
        def_box   = wx.StaticBox(self, label="Pipeline Defaults")
        def_sizer = wx.StaticBoxSizer(def_box, wx.VERTICAL)
        g2 = wx.FlexGridSizer(rows=0, cols=2, vgap=10, hgap=8)
        g2.AddGrowableCol(1)

        lbl_model = wx.StaticText(self, label="Default Gemini &model:")
        lbl_model.SetName("Default Gemini model label")
        self.default_model = wx.ComboBox(
            self,
            choices=["gemini-2.5-flash", "gemini-2.5-pro",
                     "gemini-2.5-flash-lite", "gemini-2.0-flash"],
            style=wx.CB_READONLY,
        )
        self.default_model.SetValue("gemini-2.5-flash")
        self.default_model.SetName(
            "Default Gemini model selector. "
            "gemini-2.5-flash is recommended for speed and cost."
        )
        self.default_model.SetHelpText(
            "The Gemini model used for description generation by default. "
            "Can be changed per-project in the Pipeline section."
        )
        g2.Add(lbl_model,          0, wx.ALIGN_CENTER_VERTICAL)
        g2.Add(self.default_model, 1, wx.EXPAND)

        lbl_tts = wx.StaticText(self, label="Default &TTS engine:")
        lbl_tts.SetName("Default TTS engine label")
        self.default_tts = wx.ComboBox(
            self,
            choices=["edge", "gtts", "elevenlabs", "openai"],
            style=wx.CB_READONLY,
        )
        self.default_tts.SetValue("edge")
        self.default_tts.SetName(
            "Default TTS engine selector. "
            "edge is free. elevenlabs and openai require API keys."
        )
        self.default_tts.SetHelpText(
            "The text-to-speech engine used by default. "
            "edge (Microsoft Edge TTS): free, no key needed. "
            "gtts (Google): free, requires internet. "
            "elevenlabs: high quality, requires API key. "
            "openai: high quality, requires API key."
        )
        g2.Add(lbl_tts,          0, wx.ALIGN_CENTER_VERTICAL)
        g2.Add(self.default_tts, 1, wx.EXPAND)

        def_sizer.Add(g2, 0, wx.EXPAND | wx.ALL, 8)
        root.Add(def_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # ── Tools ─────────────────────────────────────────────────────────────
        tools_box   = wx.StaticBox(self, label="Tools and Information")
        tools_sizer = wx.StaticBoxSizer(tools_box, wx.HORIZONTAL)

        btn_env   = wx.Button(self, label="&Check Environment")
        btn_about = wx.Button(self, label="&About AudioDesc")
        btn_env.SetHelpText(
            "Check that all required tools are installed: "
            "ffmpeg, ffprobe, ffplay, Python packages, and API keys."
        )
        btn_about.SetHelpText("Show version information and pipeline overview.")
        tools_sizer.Add(btn_env,   0, wx.ALL, 6)
        tools_sizer.Add(btn_about, 0, wx.ALL, 6)
        root.Add(tools_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # ── Status ────────────────────────────────────────────────────────────
        self.status_lbl = wx.StaticText(self, label="")
        self.status_lbl.SetName("Settings status message")
        root.Add(self.status_lbl, 0, wx.LEFT | wx.BOTTOM, 10)

        # ── Dialog buttons ────────────────────────────────────────────────────
        btn_sizer = wx.StdDialogButtonSizer()
        self.btn_close = wx.Button(self, wx.ID_CLOSE, label="&Close")
        self.btn_close.SetHelpText("Close the settings dialog. (Escape)")
        btn_sizer.AddButton(self.btn_close)
        btn_sizer.Realize()
        root.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 10)

        self.SetSizer(root)
        root.Fit(self)

        # ── Events ────────────────────────────────────────────────────────────
        self.btn_save_keys.Bind(wx.EVT_BUTTON, self._on_save_keys)
        btn_env.Bind(wx.EVT_BUTTON,   self._on_check_env)
        btn_about.Bind(wx.EVT_BUTTON, self._on_about)
        self.btn_close.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

    def _on_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CLOSE)
        else:
            event.Skip()

    def _load_current_values(self):
        self.gemini_key.SetValue(os.environ.get("GEMINI_API_KEY", ""))
        self.el_key.SetValue(os.environ.get("ELEVENLABS_API_KEY", ""))
        self.oai_key.SetValue(os.environ.get("OPENAI_API_KEY", ""))

    def _find_root(self) -> Path:
        candidate = Path(__file__).resolve().parent
        root = candidate
        for _ in range(6):
            if (candidate / ".env").exists() or (candidate / "core").is_dir():
                root = candidate
                break
            candidate = candidate.parent
        return root

    def _on_save_keys(self, event):
        env_file = self._find_root() / ".env"

        # Read existing lines, stripping the keys we're about to rewrite
        lines = []
        strip_keys = {"GEMINI_API_KEY", "ELEVENLABS_API_KEY", "OPENAI_API_KEY"}
        if env_file.exists():
            with open(env_file) as f:
                lines = [
                    ln for ln in f.readlines()
                    if not any(ln.startswith(k) for k in strip_keys)
                ]

        keys = {
            "GEMINI_API_KEY":     self.gemini_key.GetValue().strip(),
            "ELEVENLABS_API_KEY": self.el_key.GetValue().strip(),
            "OPENAI_API_KEY":     self.oai_key.GetValue().strip(),
        }
        for k, v in keys.items():
            if v:
                lines.append(f"{k}={v}\n")
                os.environ[k] = v

        env_file.parent.mkdir(parents=True, exist_ok=True)
        with open(env_file, "w") as f:
            f.writelines(lines)

        msg = f"API keys saved to:\n{env_file}"
        self.status_lbl.SetLabel(f"Saved to {env_file}")
        wx.MessageBox(msg, "Keys Saved", wx.OK | wx.ICON_INFORMATION)

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
