"""
gui/dialogs/description_dialog.py
-----------------------------------
Dialogs for editing individual descriptions.

DescriptionEditDialog — edit description text
DescriptionVolDialog  — edit volume, timing, priority, notes
"""

import wx


class DescriptionEditDialog(wx.Dialog):
    """Edit the text of a single description."""

    def __init__(self, parent, desc: dict, project: dict):
        super().__init__(
            parent,
            title=f"Edit Description — {desc.get('id', '')}",
            size=(560, 400),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.desc    = desc
        self.project = project
        self._new_text = None
        self._build_ui()

    def _build_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Info
        info_lines = [
            f"Time: {self.desc.get('startTime','')} → {self.desc.get('endTime','')}",
            f"Gap: {self.desc.get('durationSeconds',0):.2f}s  |  "
            f"Est. speech: {self.desc.get('estimatedSpeechDurationSeconds',0):.2f}s",
            f"Priority: {self.desc.get('priority','')}  |  "
            f"Audio context: {self.desc.get('audioContext','')}",
        ]
        for line in info_lines:
            lbl = wx.StaticText(self, label=line)
            sizer.Add(lbl, 0, wx.LEFT | wx.TOP, 10)

        # Word count hint
        text = self.desc.get("descriptionText", "")
        words = len(text.split())
        gap = self.desc.get("durationSeconds", 5)
        hint = f"Approximate word budget: {int(gap * 2.2)}–{int(gap * 2.5)} words  (current: {words})"
        hint_lbl = wx.StaticText(self, label=hint)
        hint_lbl.SetForegroundColour(wx.Colour(100, 100, 160))
        sizer.Add(hint_lbl, 0, wx.LEFT | wx.TOP, 10)

        sizer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.ALL, 6)

        sizer.Add(wx.StaticText(self, label="&Description text:"), 0, wx.LEFT, 10)
        self.text_ctrl = wx.TextCtrl(
            self,
            value=text,
            style=wx.TE_MULTILINE | wx.TE_WORDWRAP,
            size=(-1, 140),
        )
        self.text_ctrl.SetName("Description text editor")
        self.text_ctrl.SetHelpText(
            "Edit the audio description text. "
            "Write in present tense, active voice, no filler phrases."
        )
        self.text_ctrl.Bind(wx.EVT_TEXT, self._on_text_change)
        sizer.Add(self.text_ctrl, 1, wx.EXPAND | wx.ALL, 8)

        # Live word count
        self.word_count_lbl = wx.StaticText(self, label=f"Words: {words}")
        self.word_count_lbl.SetName("Word count")
        sizer.Add(self.word_count_lbl, 0, wx.LEFT, 10)

        sizer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.ALL, 6)

        btn_sizer = wx.StdDialogButtonSizer()
        btn_ok     = wx.Button(self, wx.ID_OK, "&Save Changes")
        btn_cancel = wx.Button(self, wx.ID_CANCEL, "&Cancel")
        btn_ok.SetDefault()
        btn_sizer.AddButton(btn_ok)
        btn_sizer.AddButton(btn_cancel)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(sizer)
        self.text_ctrl.SetFocus()
        self.text_ctrl.SetInsertionPointEnd()

    def _on_text_change(self, event):
        words = len(self.text_ctrl.GetValue().split())
        self.word_count_lbl.SetLabel(f"Words: {words}")

    def get_text(self) -> str:
        return self.text_ctrl.GetValue().strip()


class DescriptionVolDialog(wx.Dialog):
    """Edit volume, timing, rate, priority, notes for a description."""

    def __init__(self, parent, desc: dict, project: dict):
        super().__init__(
            parent,
            title=f"Edit Volume & Timing — {desc.get('id', '')}",
            size=(480, 500),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        self.desc    = desc
        self.project = project
        self._build_ui()

    def _build_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        g = wx.FlexGridSizer(rows=0, cols=2, vgap=10, hgap=10)
        g.AddGrowableCol(1)

        def add_row(label, widget):
            g.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            g.Add(widget, 1, wx.EXPAND)

        # Video volume
        self.vol_spin = wx.SpinCtrl(self, min=0, max=100,
                                    value=str(int(self.desc.get("videoVolumePercent", 70))))
        self.vol_spin.SetName("Video volume percent")
        self.vol_spin.SetHelpText("Volume of video audio during this description (0=muted, 100=full)")
        add_row("Video &volume %:", self.vol_spin)

        # Description volume
        self.desc_vol_spin = wx.SpinCtrl(self, min=0, max=100,
                                          value=str(int(self.desc.get("descriptionVolumePercent", 100))))
        self.desc_vol_spin.SetName("Description volume")
        add_row("Description &volume %:", self.desc_vol_spin)

        # Fade in
        self.fade_in_spin = wx.SpinCtrl(self, min=0, max=2000,
                                         value=str(self.desc.get("fadeInMs", 300)))
        self.fade_in_spin.SetName("Fade in milliseconds")
        add_row("&Fade in (ms):", self.fade_in_spin)

        # Fade out
        self.fade_out_spin = wx.SpinCtrl(self, min=0, max=2000,
                                          value=str(self.desc.get("fadeOutMs", 400)))
        self.fade_out_spin.SetName("Fade out milliseconds")
        add_row("Fade &out (ms):", self.fade_out_spin)

        # Speech rate
        self.rate_ctrl = wx.TextCtrl(self, value=self.desc.get("speechRateModifier", "+0%"))
        self.rate_ctrl.SetName("Speech rate modifier")
        self.rate_ctrl.SetHelpText("Rate: +0%=normal, -10%=slower, +15%=faster. Range: -20% to +15%")
        add_row("Speech &rate:", self.rate_ctrl)

        # Priority
        self.priority_combo = wx.ComboBox(
            self, choices=["critical", "high", "medium", "low"],
            style=wx.CB_READONLY, value=self.desc.get("priority", "medium")
        )
        self.priority_combo.SetName("Priority")
        add_row("&Priority:", self.priority_combo)

        # Audio context
        self.ctx_combo = wx.ComboBox(
            self,
            choices=["silence", "soft_music", "loud_music", "ambient", "near_dialogue", "over_dialogue"],
            style=wx.CB_READONLY,
            value=self.desc.get("audioContext", "soft_music"),
        )
        self.ctx_combo.SetName("Audio context")
        add_row("Audio &context:", self.ctx_combo)

        sizer.Add(g, 0, wx.EXPAND | wx.ALL, 10)

        # Notes
        sizer.Add(wx.StaticText(self, label="&Notes:"), 0, wx.LEFT, 10)
        self.notes_ctrl = wx.TextCtrl(self, value=self.desc.get("notes", ""),
                                       style=wx.TE_MULTILINE, size=(-1, 60))
        self.notes_ctrl.SetName("Production notes")
        sizer.Add(self.notes_ctrl, 0, wx.EXPAND | wx.ALL, 8)

        sizer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        btn_sizer = wx.StdDialogButtonSizer()
        btn_ok     = wx.Button(self, wx.ID_OK, "&Save")
        btn_cancel = wx.Button(self, wx.ID_CANCEL, "&Cancel")
        btn_ok.SetDefault()
        btn_sizer.AddButton(btn_ok)
        btn_sizer.AddButton(btn_cancel)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(sizer)
        btn_ok.Bind(wx.EVT_BUTTON, self._on_save)

    def _on_save(self, event):
        try:
            import json
            from db import database as db

            project_id = self.project["id"]
            p = db.get_project(project_id)
            desc_data = p.get("descriptions_data", {})
            descs = desc_data.get("descriptions", [])
            target = next((d for d in descs if d["id"] == self.desc["id"]), None)
            if not target:
                wx.MessageBox("Description not found.", "Error", wx.OK | wx.ICON_ERROR)
                return

            target["videoVolumePercent"]        = self.vol_spin.GetValue()
            target["descriptionVolumePercent"]  = self.desc_vol_spin.GetValue()
            target["fadeInMs"]                  = self.fade_in_spin.GetValue()
            target["fadeOutMs"]                 = self.fade_out_spin.GetValue()
            target["speechRateModifier"]        = self.rate_ctrl.GetValue()
            target["priority"]                  = self.priority_combo.GetValue()
            target["audioContext"]              = self.ctx_combo.GetValue()
            target["notes"]                     = self.notes_ctrl.GetValue()

            desc_path = db.get_project_dir(project_id) / "descriptions.json"
            with open(desc_path, "w", encoding="utf-8") as f:
                json.dump(desc_data, f, indent=2, ensure_ascii=False)
            db.update_project(project_id, {"descriptions_data": desc_data})

            self.EndModal(wx.ID_OK)
        except Exception as e:
            wx.MessageBox(f"Save failed: {e}", "Error", wx.OK | wx.ICON_ERROR)
