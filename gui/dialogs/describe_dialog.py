"""
gui/dialogs/describe_dialog.py
-------------------------------
Options dialog for Step 2: Generate AI Descriptions.
"""

import wx


MODELS = [
    ("gemini-2.5-flash",       "Gemini 2.5 Flash — Fast, strong quality (recommended)"),
    ("gemini-2.5-pro",         "Gemini 2.5 Pro — Slower, best quality"),
    ("gemini-2.5-flash-lite",  "Gemini 2.5 Flash-Lite — Fastest, lightweight"),
    ("gemini-2.0-flash",       "Gemini 2.0 Flash — Previous gen"),
    ("gemini-3-flash-preview",  "Gemini 3 Flash Preview — Latest preview"),
]


class DescribeDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(
            parent,
            title="Step 2: Generate AI Descriptions",
            size=(520, 500),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._opts = {}
        self._build_ui()

    def _build_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        info = wx.StaticText(
            self,
            label="Configure options for AI-powered audio description generation.\n"
                  "Gemini will analyze the video and generate timed description text."
        )
        info.Wrap(490)
        sizer.Add(info, 0, wx.ALL, 10)
        sizer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        g = wx.FlexGridSizer(rows=0, cols=2, vgap=10, hgap=8)
        g.AddGrowableCol(1)

        # Model
        g.Add(wx.StaticText(self, label="&Gemini Model:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.model_combo = wx.ComboBox(
            self,
            choices=[label for _, label in MODELS],
            style=wx.CB_READONLY,
        )
        self.model_combo.SetSelection(0)
        self.model_combo.SetName("Gemini model")
        self.model_combo.SetHelpText("Select the Gemini model for description generation")
        g.Add(self.model_combo, 1, wx.EXPAND)

        # Extra instructions
        g.Add(wx.StaticText(self, label="Extra &instructions:"), 0, wx.ALIGN_TOP | wx.TOP, 4)
        self.extra_ctrl = wx.TextCtrl(self, style=wx.TE_MULTILINE, size=(-1, 70))
        self.extra_ctrl.SetName("Extra instructions for AI")
        self.extra_ctrl.SetHelpText("Optional additional instructions to guide the AI's description style")
        g.Add(self.extra_ctrl, 1, wx.EXPAND)

        sizer.Add(g, 0, wx.EXPAND | wx.ALL, 10)

        # Checkboxes
        self.chk_force    = wx.CheckBox(self, label="&Force regenerate (overwrite existing descriptions)")
        self.chk_validate = wx.CheckBox(self, label="Run &validation & auto-repair after generation")
        self.chk_duck     = wx.CheckBox(self, label="Apply &smart volume ducking from audio analysis")
        self.chk_override = wx.CheckBox(self, label="Override &all AI volume suggestions with analysis")

        self.chk_validate.SetValue(True)
        self.chk_duck.SetValue(True)
        self.chk_override.SetValue(False)

        self.chk_force.SetHelpText("Regenerate even if descriptions already exist")
        self.chk_validate.SetHelpText("Automatically sort, fix overlaps, and flag issues")
        self.chk_duck.SetHelpText("Analyze actual audio levels and adjust volume ducking")
        self.chk_override.SetHelpText("If unchecked, only fixes large discrepancies between AI and analysis")

        for chk in [self.chk_force, self.chk_validate, self.chk_duck, self.chk_override]:
            sizer.Add(chk, 0, wx.LEFT | wx.BOTTOM, 10)

        sizer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # Buttons
        btn_sizer = wx.StdDialogButtonSizer()
        btn_ok     = wx.Button(self, wx.ID_OK, "&Start Generation")
        btn_cancel = wx.Button(self, wx.ID_CANCEL, "&Cancel")
        btn_ok.SetDefault()
        btn_sizer.AddButton(btn_ok)
        btn_sizer.AddButton(btn_cancel)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(sizer)
        btn_ok.Bind(wx.EVT_BUTTON, self._on_ok)

    def _on_ok(self, event):
        sel_idx = self.model_combo.GetSelection()
        model_id = MODELS[sel_idx][0] if 0 <= sel_idx < len(MODELS) else "gemini-2.5-flash"
        self._opts = {
            "model":        model_id,
            "force":        self.chk_force.GetValue(),
            "validate":     self.chk_validate.GetValue(),
            "smart_duck":   self.chk_duck.GetValue(),
            "duck_override": self.chk_override.GetValue(),
            "extra":        self.extra_ctrl.GetValue().strip(),
        }
        self.EndModal(wx.ID_OK)

    def get_options(self) -> dict:
        return self._opts
