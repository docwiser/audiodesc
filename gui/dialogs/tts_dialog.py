"""
gui/dialogs/tts_dialog.py
--------------------------
TTS Configuration Dialog.

Accessibility improvements over v1:
  - Engine selection uses wx.RadioBox (single Tab stop, arrow-key navigation)
    instead of a ComboBox + separate Notebook tab switch.
  - Each engine's options are in a wx.Panel that shows/hides based on the
    radio selection — so NVDA always reads visible options in correct context.
  - Every TextCtrl has an explicit StaticText label in the same sizer row.
  - wx.StaticBox groups logically related fields (fieldset equivalent).
  - SetName on each control mirrors the visible label for screen readers that
    don't honour adjacent-label heuristics.
  - Tab order follows top-to-bottom left-to-right reading order.
  - Preview button announces result via status StaticText (live region).
"""

import wx
import threading


EDGE_VOICES = [
    "en-US-AriaNeural",   "en-US-GuyNeural",   "en-US-JennyNeural",
    "en-US-EricNeural",   "en-GB-SoniaNeural", "en-GB-RyanNeural",
    "en-AU-NatashaNeural","en-AU-WilliamNeural","en-CA-ClaraNeural",
    "en-IN-NeerjaNeural", "fr-FR-DeniseNeural", "de-DE-KatjaNeural",
    "es-ES-ElviraNeural",
]

EL_VOICE_IDS = {
    "Rachel (calm female)":   "21m00Tcm4TlvDq8ikWAM",
    "Adam (deep male)":       "pNInz6obpgDQGcFmaJgB",
    "Bella (soft female)":    "EXAVITQu4vr4xnSDxMaL",
    "Arnold (authoritative)": "VR6AewLTigWG4xSOukaG",
}

OPENAI_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

PREVIEW_TEXT = (
    "The young woman looks up, expression thoughtful. "
    "She glances toward the window, then turns back."
)

ENGINES     = ["edge", "gtts", "elevenlabs", "openai"]
ENGINE_LBLS = [
    "Edge TTS (Microsoft — free, no key needed)",
    "gTTS (Google — free, needs internet)",
    "ElevenLabs (premium, requires API key)",
    "OpenAI TTS (premium, requires API key)",
]


class TTSConfigDialog(wx.Dialog):
    def __init__(self, parent, project: dict):
        super().__init__(
            parent,
            title="Configure TTS Voice and Engine",
            size=(580, 620),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.SetName("TTS Configuration Dialog")
        self.SetHelpText(
            "Configure the text-to-speech engine and voice settings. "
            "Press Escape to cancel. Press Tab to move between fields."
        )
        self.project = project
        self.current = project.get("tts_config", {})
        self._engine_panels = {}
        self._build_ui()
        self._load_current()
        self.Centre(wx.BOTH)

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = wx.BoxSizer(wx.VERTICAL)

        # ── Engine radio group ────────────────────────────────────────────────
        self.engine_radio = wx.RadioBox(
            self,
            label="TTS Engine — use arrow keys to switch",
            choices=ENGINE_LBLS,
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        self.engine_radio.SetName(
            "TTS engine selector. "
            "Use Up and Down arrow keys to switch engines. "
            "Options below update automatically."
        )
        self.engine_radio.SetHelpText(
            "Choose the text-to-speech engine. "
            "Edge TTS is free and works without any API key. "
            "ElevenLabs and OpenAI require API keys set in Settings."
        )
        tips = [
            "Microsoft Edge TTS: free neural voices, no API key required",
            "Google gTTS: free, requires internet connection",
            "ElevenLabs: high-quality voices, requires ElevenLabs API key in Settings",
            "OpenAI TTS: high-quality voices, requires OpenAI API key in Settings",
        ]
        for i, tip in enumerate(tips):
            self.engine_radio.SetItemHelpText(i, tip)
        root.Add(self.engine_radio, 0, wx.EXPAND | wx.ALL, 10)

        # ── Engine options area ───────────────────────────────────────────────
        opts_box   = wx.StaticBox(self, label="Engine Options")
        opts_sizer = wx.StaticBoxSizer(opts_box, wx.VERTICAL)

        self.opts_panel = wx.Panel(self)
        self.opts_sizer = wx.BoxSizer(wx.VERTICAL)
        self.opts_panel.SetSizer(self.opts_sizer)

        # Build all engine panels (initially all hidden)
        self._build_edge_panel()
        self._build_gtts_panel()
        self._build_el_panel()
        self._build_oai_panel()

        opts_sizer.Add(self.opts_panel, 1, wx.EXPAND | wx.ALL, 4)
        root.Add(opts_sizer, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # ── Normalize ─────────────────────────────────────────────────────────
        norm_box   = wx.StaticBox(self, label="Audio Processing")
        norm_sizer = wx.StaticBoxSizer(norm_box, wx.VERTICAL)
        self.chk_normalize = wx.CheckBox(
            self, label="&Normalize clip loudness to -16 LUFS (recommended)"
        )
        self.chk_normalize.SetValue(True)
        self.chk_normalize.SetName(
            "Normalize clip loudness checkbox. "
            "When checked, all generated clips are loudness-normalized to -16 LUFS."
        )
        self.chk_normalize.SetHelpText(
            "When enabled, each generated audio clip is normalized to -16 LUFS "
            "for consistent volume across all descriptions."
        )
        norm_sizer.Add(self.chk_normalize, 0, wx.ALL, 8)
        root.Add(norm_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # ── Preview ───────────────────────────────────────────────────────────
        prev_box   = wx.StaticBox(self, label="Voice Preview")
        prev_sizer = wx.StaticBoxSizer(prev_box, wx.HORIZONTAL)
        self.btn_preview = wx.Button(self, label="🔊 &Preview Voice")
        self.btn_preview.SetHelpText(
            "Synthesize a short sample sentence using the current settings "
            "and play it through your audio output device."
        )
        self.preview_status = wx.StaticText(self, label="Press Preview to hear the selected voice.")
        self.preview_status.SetName("Preview status")
        prev_sizer.Add(self.btn_preview,    0, wx.ALL, 6)
        prev_sizer.Add(self.preview_status, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        root.Add(prev_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # ── Dialog buttons ────────────────────────────────────────────────────
        root.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        btn_sizer = wx.StdDialogButtonSizer()
        self.btn_ok     = wx.Button(self, wx.ID_OK, "&Save Configuration")
        self.btn_cancel = wx.Button(self, wx.ID_CANCEL, "&Cancel")
        self.btn_ok.SetDefault()
        self.btn_ok.SetHelpText("Save TTS configuration to the project and close.")
        self.btn_cancel.SetHelpText("Discard changes and close the dialog. (Escape)")
        btn_sizer.AddButton(self.btn_ok)
        btn_sizer.AddButton(self.btn_cancel)
        btn_sizer.Realize()
        root.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(root)

        # ── Events ────────────────────────────────────────────────────────────
        self.engine_radio.Bind(wx.EVT_RADIOBOX, self._on_engine_change)
        self.btn_preview.Bind(wx.EVT_BUTTON,    self._on_preview)
        self.btn_ok.Bind(wx.EVT_BUTTON,         self._on_save)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

    def _on_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
        else:
            event.Skip()

    # ── Engine sub-panels ─────────────────────────────────────────────────────

    def _add_engine_panel(self, engine_idx: int, panel: wx.Panel):
        panel.Hide()
        self.opts_sizer.Add(panel, 1, wx.EXPAND)
        self._engine_panels[engine_idx] = panel

    def _build_edge_panel(self):
        p = wx.Panel(self.opts_panel)
        p.SetName("Edge TTS options")
        g = wx.FlexGridSizer(rows=0, cols=2, vgap=10, hgap=8)
        g.AddGrowableCol(1)

        lbl_v = wx.StaticText(p, label="&Voice name:")
        lbl_v.SetName("Edge TTS voice label")
        self.edge_voice = wx.ComboBox(p, choices=EDGE_VOICES, style=wx.CB_DROPDOWN)
        self.edge_voice.SetName("Edge TTS voice selector or text entry. e.g. en-US-AriaNeural")
        self.edge_voice.SetHelpText(
            "Select from the list or type a voice name. "
            "Format: Language-Region-VoiceNeural. "
            "e.g. en-US-AriaNeural, en-GB-SoniaNeural."
        )

        lbl_r = wx.StaticText(p, label="Speech &rate:")
        lbl_r.SetName("Speech rate label")
        self.edge_rate = wx.TextCtrl(p, value="+0%")
        self.edge_rate.SetName("Speech rate modifier. e.g. plus 0 percent normal, minus 10 percent slower")
        self.edge_rate.SetHelpText("+0%=normal speed. Use negative values to slow down, positive to speed up. e.g. -10%, +15%")

        lbl_p = wx.StaticText(p, label="&Pitch:")
        lbl_p.SetName("Pitch label")
        self.edge_pitch = wx.TextCtrl(p, value="+0Hz")
        self.edge_pitch.SetName("Pitch modifier in Hertz. e.g. plus 0 Hz for no change")
        self.edge_pitch.SetHelpText("Pitch adjustment in Hz. +0Hz=natural, -20Hz=lower, +20Hz=higher.")

        for lbl, ctrl in [(lbl_v, self.edge_voice), (lbl_r, self.edge_rate), (lbl_p, self.edge_pitch)]:
            g.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
            g.Add(ctrl, 1, wx.EXPAND)

        s = wx.BoxSizer(wx.VERTICAL)
        s.Add(g, 0, wx.EXPAND | wx.ALL, 8)
        p.SetSizer(s)
        self._add_engine_panel(0, p)

    def _build_gtts_panel(self):
        p = wx.Panel(self.opts_panel)
        p.SetName("Google TTS options")
        g = wx.FlexGridSizer(rows=0, cols=2, vgap=10, hgap=8)
        g.AddGrowableCol(1)

        lbl_l = wx.StaticText(p, label="&Language code:")
        lbl_l.SetName("gTTS language code label")
        self.gtts_lang = wx.TextCtrl(p, value="en")
        self.gtts_lang.SetName("gTTS language code. e.g. en for English, fr for French")
        self.gtts_lang.SetHelpText("BCP-47 language code: en, fr, de, es, hi, ja, zh-TW, etc.")

        g.Add(lbl_l,         0, wx.ALIGN_CENTER_VERTICAL)
        g.Add(self.gtts_lang,1, wx.EXPAND)

        self.gtts_slow = wx.CheckBox(p, label="Use &slow speech (for clarity)")
        self.gtts_slow.SetName("gTTS slow speech mode checkbox")
        self.gtts_slow.SetHelpText("When checked, gTTS speaks more slowly. Useful for clarity.")
        g.Add(wx.StaticText(p, label=""), 0)
        g.Add(self.gtts_slow, 1)

        s = wx.BoxSizer(wx.VERTICAL)
        s.Add(g, 0, wx.EXPAND | wx.ALL, 8)
        p.SetSizer(s)
        self._add_engine_panel(1, p)

    def _build_el_panel(self):
        p = wx.Panel(self.opts_panel)
        p.SetName("ElevenLabs TTS options")
        g = wx.FlexGridSizer(rows=0, cols=2, vgap=10, hgap=8)
        g.AddGrowableCol(1)

        lbl_v = wx.StaticText(p, label="&Voice preset:")
        lbl_v.SetName("ElevenLabs voice preset label")
        self.el_voice_combo = wx.ComboBox(p, choices=list(EL_VOICE_IDS.keys()), style=wx.CB_READONLY)
        self.el_voice_combo.SetName("ElevenLabs voice preset selector")
        self.el_voice_combo.SetHelpText("Select a preset voice. The voice ID field below auto-fills.")

        lbl_id = wx.StaticText(p, label="Voice &ID (override):")
        lbl_id.SetName("ElevenLabs custom voice ID label")
        self.el_voice_id = wx.TextCtrl(p)
        self.el_voice_id.SetName("ElevenLabs custom voice ID. Paste a voice ID from elevenlabs.io to override the preset.")
        self.el_voice_id.SetHelpText("Paste a custom voice ID from elevenlabs.io/voice-library to use any voice.")

        lbl_m = wx.StaticText(p, label="&Model:")
        lbl_m.SetName("ElevenLabs model label")
        self.el_model = wx.ComboBox(
            p,
            choices=["eleven_multilingual_v2", "eleven_monolingual_v1", "eleven_turbo_v2"],
            style=wx.CB_READONLY,
        )
        self.el_model.SetValue("eleven_multilingual_v2")
        self.el_model.SetName("ElevenLabs model selector")
        self.el_model.SetHelpText("eleven_multilingual_v2 supports 29 languages. eleven_turbo_v2 is fastest.")

        for lbl, ctrl in [(lbl_v, self.el_voice_combo), (lbl_id, self.el_voice_id), (lbl_m, self.el_model)]:
            g.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
            g.Add(ctrl, 1, wx.EXPAND)

        s = wx.BoxSizer(wx.VERTICAL)
        s.Add(g, 0, wx.EXPAND | wx.ALL, 8)
        p.SetSizer(s)
        self.el_voice_combo.Bind(wx.EVT_COMBOBOX, self._on_el_voice_select)
        self._add_engine_panel(2, p)

    def _build_oai_panel(self):
        p = wx.Panel(self.opts_panel)
        p.SetName("OpenAI TTS options")
        g = wx.FlexGridSizer(rows=0, cols=2, vgap=10, hgap=8)
        g.AddGrowableCol(1)

        lbl_v = wx.StaticText(p, label="&Voice:")
        lbl_v.SetName("OpenAI voice label")
        self.oai_voice = wx.ComboBox(p, choices=OPENAI_VOICES, style=wx.CB_READONLY)
        self.oai_voice.SetValue("nova")
        self.oai_voice.SetName("OpenAI voice selector")
        self.oai_voice.SetHelpText("nova and shimmer are female; onyx, echo, fable, alloy are male or neutral.")

        lbl_m = wx.StaticText(p, label="&Model:")
        lbl_m.SetName("OpenAI TTS model label")
        self.oai_model = wx.ComboBox(p, choices=["tts-1", "tts-1-hd"], style=wx.CB_READONLY)
        self.oai_model.SetValue("tts-1")
        self.oai_model.SetName("OpenAI TTS model selector. tts-1-hd is higher quality but slower.")
        self.oai_model.SetHelpText("tts-1: fast and cheap. tts-1-hd: higher quality, slower, more expensive.")

        lbl_r = wx.StaticText(p, label="Speech &rate:")
        lbl_r.SetName("OpenAI speech rate label")
        self.oai_rate = wx.TextCtrl(p, value="+0%")
        self.oai_rate.SetName("OpenAI speech rate modifier. e.g. plus 0 percent for normal speed")
        self.oai_rate.SetHelpText("Rate modifier: +0%=normal. Use -10% to slow down, +15% to speed up.")

        for lbl, ctrl in [(lbl_v, self.oai_voice), (lbl_m, self.oai_model), (lbl_r, self.oai_rate)]:
            g.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
            g.Add(ctrl, 1, wx.EXPAND)

        s = wx.BoxSizer(wx.VERTICAL)
        s.Add(g, 0, wx.EXPAND | wx.ALL, 8)
        p.SetSizer(s)
        self._add_engine_panel(3, p)

    # ── Engine switching ──────────────────────────────────────────────────────

    def _show_engine(self, idx: int):
        for i, panel in self._engine_panels.items():
            if i == idx:
                panel.Show()
            else:
                panel.Hide()
        self.opts_panel.Layout()
        self.opts_sizer.Layout()

    def _on_engine_change(self, event):
        self._show_engine(event.GetInt())

    # ── Load saved config ─────────────────────────────────────────────────────

    def _load_current(self):
        c = self.current
        engine = c.get("engine", "edge")
        idx    = ENGINES.index(engine) if engine in ENGINES else 0
        self.engine_radio.SetSelection(idx)
        self._show_engine(idx)

        self.edge_voice.SetValue(c.get("voice", "en-US-AriaNeural"))
        self.edge_rate.SetValue(c.get("rate", "+0%"))
        self.edge_pitch.SetValue(c.get("pitch", "+0Hz"))
        self.gtts_lang.SetValue(c.get("gtts_lang", "en"))
        self.gtts_slow.SetValue(c.get("gtts_slow", False))
        self.el_model.SetValue(c.get("elevenlabs_model", "eleven_multilingual_v2"))
        self.el_voice_id.SetValue(c.get("elevenlabs_voice_id", ""))
        self.oai_voice.SetValue(c.get("openai_voice", "nova"))
        self.oai_model.SetValue(c.get("openai_model", "tts-1"))
        self.oai_rate.SetValue(c.get("rate", "+0%"))
        self.chk_normalize.SetValue(c.get("normalize_clips", True))

    def _on_el_voice_select(self, event):
        name = self.el_voice_combo.GetValue()
        vid  = EL_VOICE_IDS.get(name, "")
        if vid:
            self.el_voice_id.SetValue(vid)

    # ── Preview ───────────────────────────────────────────────────────────────

    def _on_preview(self, event):
        config = self._build_config()
        self.preview_status.SetLabel("Generating preview audio, please wait…")
        self.btn_preview.Enable(False)

        def _do():
            from tts.tts_manager import preview_voice
            try:
                ok  = preview_voice(config, sample_text=PREVIEW_TEXT)
                msg = "Preview played successfully." if ok else "Preview failed or ffplay not installed."
            except Exception as e:
                msg = f"Preview error: {e}"
            wx.CallAfter(self.preview_status.SetLabel, msg)
            wx.CallAfter(self.btn_preview.Enable, True)

        threading.Thread(target=_do, daemon=True).start()

    # ── Build config dict ─────────────────────────────────────────────────────

    def _build_config(self) -> dict:
        idx    = max(0, self.engine_radio.GetSelection())
        engine = ENGINES[idx] if idx < len(ENGINES) else "edge"

        config = {
            "engine":          engine,
            "normalize_clips": self.chk_normalize.GetValue(),
        }
        if engine == "edge":
            config["voice"] = self.edge_voice.GetValue()
            config["rate"]  = self.edge_rate.GetValue()
            config["pitch"] = self.edge_pitch.GetValue()
        elif engine == "gtts":
            config["gtts_lang"] = self.gtts_lang.GetValue()
            config["gtts_slow"] = self.gtts_slow.GetValue()
        elif engine == "elevenlabs":
            vid = self.el_voice_id.GetValue().strip()
            config["elevenlabs_voice_id"] = vid or list(EL_VOICE_IDS.values())[0]
            config["elevenlabs_model"]    = self.el_model.GetValue()
            config["elevenlabs_stability"]  = 0.5
            config["elevenlabs_similarity"] = 0.75
        elif engine == "openai":
            config["openai_voice"] = self.oai_voice.GetValue()
            config["openai_model"] = self.oai_model.GetValue()
            config["rate"]         = self.oai_rate.GetValue()
        return config

    # ── Save ──────────────────────────────────────────────────────────────────

    def _on_save(self, event):
        config = self._build_config()
        try:
            from db import database as db
            db.update_project(self.project["id"], {"tts_config": config})
            self.project["tts_config"] = config
            self.EndModal(wx.ID_OK)
        except Exception as e:
            wx.MessageBox(f"Failed to save TTS config:\n{e}", "Error", wx.OK | wx.ICON_ERROR)
