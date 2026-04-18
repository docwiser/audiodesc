"""
gui/panels/description_panel.py
--------------------------------
Descriptions panel — full-featured editor for audio description entries.

Layout:
  Top:    Summary labels (video title, coverage, recommended voice)
  Middle: ListCtrl with all descriptions (ID | Time | Priority | Vol | Fits | Text)
  Right:  Detail/edit pane (TextCtrl, spinners, comboboxes)
  Bottom: Action buttons (Edit Text | Edit Volume | Regenerate Audio | Preview)

Screen-reader notes:
  - ListCtrl announces row contents via GetItemText
  - Edit dialog uses labeled controls throughout
  - Preview plays audio via ffplay subprocess
"""

import wx
import wx.lib.scrolledpanel as scrolled
from pathlib import Path


PRIORITY_COLORS = {
    "critical": wx.Colour(255, 200, 200),
    "high":     wx.Colour(255, 220, 170),
    "medium":   wx.Colour(255, 255, 200),
    "low":      wx.Colour(230, 230, 230),
}

PRIORITY_ORDER = ["critical", "high", "medium", "low"]
AUDIO_CONTEXTS = ["silence", "soft_music", "loud_music", "ambient", "near_dialogue", "over_dialogue"]
VISUAL_CATS    = ["character_intro", "action", "setting", "text_overlay", "object", "emotion", "transition", "credits"]


class DescriptionPanel(wx.Panel):
    def __init__(self, parent, main_window):
        super().__init__(parent)
        self.main_window = main_window
        self.project = None
        self._descriptions = []
        self._build_ui()

    def _build_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        # ── Summary bar ───────────────────────────────────────────────────────
        summ_box = wx.StaticBox(self, label="Video Summary")
        summ_sizer = wx.StaticBoxSizer(summ_box, wx.HORIZONTAL)
        self.lbl_title    = wx.StaticText(self, label="—")
        self.lbl_coverage = wx.StaticText(self, label="—")
        self.lbl_voice    = wx.StaticText(self, label="—")
        self.lbl_flags    = wx.StaticText(self, label="")
        self.lbl_flags.SetForegroundColour(wx.Colour(180, 80, 0))
        for lbl in [self.lbl_title, self.lbl_coverage, self.lbl_voice]:
            summ_sizer.Add(lbl, 1, wx.ALL, 6)
        summ_sizer.Add(self.lbl_flags, 2, wx.ALL, 6)
        sizer.Add(summ_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # ── Filter / search row ───────────────────────────────────────────────
        filter_row = wx.BoxSizer(wx.HORIZONTAL)
        filter_row.Add(wx.StaticText(self, label="&Filter by priority:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.priority_filter = wx.ComboBox(
            self, choices=["All"] + PRIORITY_ORDER,
            style=wx.CB_READONLY,
        )
        self.priority_filter.SetValue("All")
        self.priority_filter.SetName("Priority filter")
        self.priority_filter.SetHelpText("Filter descriptions by priority level")

        filter_row.Add(self.priority_filter, 0, wx.RIGHT, 12)
        filter_row.Add(wx.StaticText(self, label="Sho&w only overflowing:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.chk_overflow = wx.CheckBox(self, label="")
        self.chk_overflow.SetName("Show overflowing descriptions only")
        filter_row.Add(self.chk_overflow, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)

        self.btn_reload = wx.Button(self, label="&Reload")
        filter_row.Add(self.btn_reload, 0)
        sizer.Add(filter_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Main split: list | detail ─────────────────────────────────────────
        splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3D)
        splitter.SetMinimumPaneSize(180)

        # Left: ListCtrl
        left_panel = wx.Panel(splitter)
        left_sizer = wx.BoxSizer(wx.VERTICAL)

        self.list_ctrl = wx.ListCtrl(
            left_panel,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES,
        )
        self.list_ctrl.SetName("Descriptions List")
        self.list_ctrl.SetHelpText(
            "All audio descriptions. Select one to view/edit details on the right. "
            "Press Enter to open the description editor."
        )
        self.list_ctrl.InsertColumn(0, "ID",      width=70)
        self.list_ctrl.InsertColumn(1, "Start",   width=65)
        self.list_ctrl.InsertColumn(2, "End",     width=65)
        self.list_ctrl.InsertColumn(3, "Priority",width=70)
        self.list_ctrl.InsertColumn(4, "Vol%",    width=45)
        self.list_ctrl.InsertColumn(5, "Fits",    width=40)
        self.list_ctrl.InsertColumn(6, "Description (first 80 chars)", width=280)
        left_sizer.Add(self.list_ctrl, 1, wx.EXPAND)

        # Count label
        self.count_label = wx.StaticText(left_panel, label="0 descriptions")
        left_sizer.Add(self.count_label, 0, wx.ALL, 4)

        left_panel.SetSizer(left_sizer)

        # Right: Detail / edit pane
        right_panel = scrolled.ScrolledPanel(splitter)
        right_panel.SetupScrolling()
        right_sizer = wx.BoxSizer(wx.VERTICAL)

        detail_box = wx.StaticBox(right_panel, label="Description Detail")
        detail_sizer = wx.StaticBoxSizer(detail_box, wx.VERTICAL)

        # ID, time
        g = wx.FlexGridSizer(rows=0, cols=2, vgap=6, hgap=8)
        g.AddGrowableCol(1)
        self.det_id       = self._add_detail_row(g, right_panel, "ID:")
        self.det_start    = self._add_detail_row(g, right_panel, "Start time:")
        self.det_end      = self._add_detail_row(g, right_panel, "End time:")
        self.det_duration = self._add_detail_row(g, right_panel, "Gap duration:")
        self.det_priority = self._add_detail_row(g, right_panel, "Priority:")
        self.det_format   = self._add_detail_row(g, right_panel, "Format:")
        self.det_ctx      = self._add_detail_row(g, right_panel, "Audio context:")
        self.det_vol      = self._add_detail_row(g, right_panel, "Video volume %:")
        self.det_rate     = self._add_detail_row(g, right_panel, "Speech rate:")
        self.det_fits     = self._add_detail_row(g, right_panel, "Fits in gap:")
        detail_sizer.Add(g, 0, wx.EXPAND | wx.ALL, 6)

        # Description text
        detail_sizer.Add(wx.StaticText(right_panel, label="Description text:"), 0, wx.LEFT, 6)
        self.det_text = wx.TextCtrl(
            right_panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP,
            size=(-1, 90)
        )
        self.det_text.SetName("Description text")
        detail_sizer.Add(self.det_text, 0, wx.EXPAND | wx.ALL, 6)

        # Notes
        detail_sizer.Add(wx.StaticText(right_panel, label="Notes:"), 0, wx.LEFT, 6)
        self.det_notes = wx.TextCtrl(
            right_panel, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 50)
        )
        detail_sizer.Add(self.det_notes, 0, wx.EXPAND | wx.ALL, 6)

        right_sizer.Add(detail_sizer, 0, wx.EXPAND | wx.ALL, 4)

        # Action buttons
        btn_sizer = wx.BoxSizer(wx.VERTICAL)
        self.btn_edit_text  = wx.Button(right_panel, label="&Edit Description Text")
        self.btn_edit_vol   = wx.Button(right_panel, label="Edit &Volume / Timing")
        self.btn_regen_audio = wx.Button(right_panel, label="&Regenerate Audio Clip")
        self.btn_preview    = wx.Button(right_panel, label="&Preview in Context")

        for btn in [self.btn_edit_text, self.btn_edit_vol, self.btn_regen_audio, self.btn_preview]:
            btn_sizer.Add(btn, 0, wx.EXPAND | wx.BOTTOM, 4)
        right_sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 4)

        right_panel.SetSizer(right_sizer)
        splitter.SplitVertically(left_panel, right_panel, sashPosition=570)

        sizer.Add(splitter, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.SetSizer(sizer)

        # Events
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_select)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_edit_text)
        self.list_ctrl.Bind(wx.EVT_KEY_DOWN, self._on_list_key)
        self.priority_filter.Bind(wx.EVT_COMBOBOX, self._on_filter)
        self.chk_overflow.Bind(wx.EVT_CHECKBOX, self._on_filter)
        self.btn_reload.Bind(wx.EVT_BUTTON, lambda e: self.load_project(self.project))
        self.btn_edit_text.Bind(wx.EVT_BUTTON, self._on_edit_text)
        self.btn_edit_vol.Bind(wx.EVT_BUTTON, self._on_edit_vol)
        self.btn_regen_audio.Bind(wx.EVT_BUTTON, self._on_regen_audio)
        self.btn_preview.Bind(wx.EVT_BUTTON, self._on_preview)

    def _add_detail_row(self, grid, parent, label_text: str):
        lbl = wx.StaticText(parent, label=label_text)
        val = wx.StaticText(parent, label="—")
        val.SetName(label_text.strip(":"))
        grid.Add(lbl, 0, wx.ALIGN_TOP)
        grid.Add(val, 1, wx.EXPAND)
        return val

    # ── Data loading ──────────────────────────────────────────────────────────

    def load_project(self, project):
        self.project = project
        if not project:
            self._descriptions = []
            self._populate([])
            return

        desc_data = project.get("descriptions_data") or {}
        self._descriptions = desc_data.get("descriptions", [])

        meta    = desc_data.get("videoMetadata", {})
        summary = desc_data.get("productionSummary", {})
        self.lbl_title.SetLabel(f"Title: {meta.get('title','?')}")
        self.lbl_coverage.SetLabel(f"Coverage: {summary.get('coveragePercent',0):.1f}%")
        self.lbl_voice.SetLabel(f"Voice: {summary.get('recommendedTTSVoice','?')}")
        flags = summary.get("qualityFlags", [])
        self.lbl_flags.SetLabel("Flags: " + ", ".join(flags) if flags else "")

        self._apply_filter()

    def _apply_filter(self):
        priority = self.priority_filter.GetValue()
        overflow_only = self.chk_overflow.GetValue()
        descs = self._descriptions
        if priority and priority != "All":
            descs = [d for d in descs if d.get("priority") == priority]
        if overflow_only:
            descs = [d for d in descs if not d.get("fitsInGap", True)]
        self._populate(descs)

    def _on_filter(self, event):
        self._apply_filter()

    def _populate(self, descriptions: list):
        self.list_ctrl.DeleteAllItems()
        for d in descriptions:
            txt = d.get("descriptionText", "")
            fits = "Yes" if d.get("fitsInGap", True) else "NO"
            idx = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), d.get("id", ""))
            self.list_ctrl.SetItem(idx, 1, d.get("startTime", ""))
            self.list_ctrl.SetItem(idx, 2, d.get("endTime", ""))
            self.list_ctrl.SetItem(idx, 3, d.get("priority", ""))
            self.list_ctrl.SetItem(idx, 4, str(int(d.get("videoVolumePercent", 70))))
            self.list_ctrl.SetItem(idx, 5, fits)
            self.list_ctrl.SetItem(idx, 6, txt[:80])

            # Color by priority
            col = PRIORITY_COLORS.get(d.get("priority", ""), None)
            if col:
                self.list_ctrl.SetItemBackgroundColour(idx, col)
            # Red for non-fitting
            if not d.get("fitsInGap", True):
                self.list_ctrl.SetItemTextColour(idx, wx.Colour(180, 0, 0))

        self.count_label.SetLabel(f"{len(descriptions)} description{'s' if len(descriptions)!=1 else ''}")

    def _get_selected(self):
        idx = self.list_ctrl.GetFirstSelected()
        if idx < 0:
            return None, None
        did = self.list_ctrl.GetItemText(idx, 0)
        desc = next((d for d in self._descriptions if d.get("id") == did), None)
        return idx, desc

    def _on_select(self, event):
        _, desc = self._get_selected()
        if desc:
            self._show_detail(desc)

    def _show_detail(self, desc: dict):
        self.det_id.SetLabel(desc.get("id", ""))
        self.det_start.SetLabel(desc.get("startTime", ""))
        self.det_end.SetLabel(desc.get("endTime", ""))
        dur = desc.get("durationSeconds", 0)
        est = desc.get("estimatedSpeechDurationSeconds", 0)
        self.det_duration.SetLabel(f"{dur:.2f}s gap  /  {est:.2f}s estimated speech")
        self.det_priority.SetLabel(desc.get("priority", ""))
        self.det_format.SetLabel(desc.get("format", ""))
        self.det_ctx.SetLabel(desc.get("audioContext", ""))
        self.det_vol.SetLabel(str(int(desc.get("videoVolumePercent", 70))) + "%")
        self.det_rate.SetLabel(desc.get("speechRateModifier", "+0%"))
        self.det_fits.SetLabel("Yes" if desc.get("fitsInGap", True) else "WARNING: Too long!")
        self.det_text.SetValue(desc.get("descriptionText", ""))
        self.det_notes.SetValue(desc.get("notes", ""))

    def _on_list_key(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN:
            self._on_edit_text(event)
        else:
            event.Skip()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_edit_text(self, event=None):
        _, desc = self._get_selected()
        if not desc:
            wx.MessageBox("Select a description first.", "No Selection", wx.OK)
            return
        from gui.dialogs.description_dialog import DescriptionEditDialog
        dlg = DescriptionEditDialog(self, desc, self.project)
        if dlg.ShowModal() == wx.ID_OK:
            new_text = dlg.get_text()
            if new_text:
                from core.description_generator import edit_description
                edit_description(self.project["id"], desc["id"], new_text)
                self.main_window.refresh_current_project()
                self.load_project(self.main_window.current_project)
                self.main_window.set_status(f"Description {desc['id']} updated.")
        dlg.Destroy()

    def _on_edit_vol(self, event):
        _, desc = self._get_selected()
        if not desc:
            wx.MessageBox("Select a description first.", "No Selection", wx.OK)
            return
        from gui.dialogs.description_dialog import DescriptionVolDialog
        dlg = DescriptionVolDialog(self, desc, self.project)
        if dlg.ShowModal() == wx.ID_OK:
            self.main_window.refresh_current_project()
            self.load_project(self.main_window.current_project)
        dlg.Destroy()

    def _on_regen_audio(self, event):
        _, desc = self._get_selected()
        if not desc or not self.project:
            wx.MessageBox("Select a description with a loaded project.", "Info", wx.OK)
            return
        normalize = wx.MessageBox(
            "Normalize loudness of this clip?",
            "Regenerate Audio",
            wx.YES_NO | wx.YES_DEFAULT,
        ) == wx.YES
        try:
            from tts.tts_manager import regenerate_single_audio
            regenerate_single_audio(self.project["id"], desc["id"], normalize=normalize)
            self.main_window.refresh_current_project()
            wx.MessageBox(f"Audio clip for {desc['id']} regenerated.", "Done", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Error: {e}", "Failed", wx.OK | wx.ICON_ERROR)

    def _on_preview(self, event):
        _, desc = self._get_selected()
        if not desc or not self.project:
            wx.MessageBox("Select a description with a loaded project.", "Info", wx.OK)
            return
        from gui.dialogs.preview_dialog import PreviewDialog
        dlg = PreviewDialog(self, desc, self.project)
        dlg.ShowModal()
        dlg.Destroy()
