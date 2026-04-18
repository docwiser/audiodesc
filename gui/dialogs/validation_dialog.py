"""
gui/dialogs/validation_dialog.py
----------------------------------
Validation report dialog — shows issues found in descriptions.
"""

import wx


class ValidationDialog(wx.Dialog):
    def __init__(self, parent, project: dict):
        super().__init__(
            parent,
            title=f"Validation Report — {project.get('name','')}",
            size=(720, 500),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.project = project
        self._build_ui()
        self._run_validation()

    def _build_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Summary
        self.summary_lbl = wx.StaticText(self, label="Running validation…")
        self.summary_lbl.SetFont(self.summary_lbl.GetFont().Bold())
        sizer.Add(self.summary_lbl, 0, wx.ALL, 10)

        # Issues list
        self.issues_list = wx.ListCtrl(
            self,
            style=wx.LC_REPORT | wx.LC_HRULES,
        )
        self.issues_list.SetName("Validation issues list")
        self.issues_list.SetHelpText("Validation issues found in the descriptions")
        self.issues_list.InsertColumn(0, "Severity", width=75)
        self.issues_list.InsertColumn(1, "Desc ID",  width=90)
        self.issues_list.InsertColumn(2, "Type",     width=120)
        self.issues_list.InsertColumn(3, "Message",  width=350)
        self.issues_list.InsertColumn(4, "Fixed?",   width=55)
        sizer.Add(self.issues_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # Save repaired button
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_save   = wx.Button(self, label="&Save Repaired Descriptions")
        self.btn_rerun  = wx.Button(self, label="&Re-run Validation")
        btn_close       = wx.Button(self, wx.ID_CANCEL, label="&Close")
        self.btn_save.Enable(False)
        self.btn_save.SetHelpText("Save the auto-repaired descriptions to disk")
        self.btn_rerun.SetHelpText("Run validation again on current descriptions")
        btn_row.Add(self.btn_save,  0, wx.RIGHT, 6)
        btn_row.Add(self.btn_rerun, 0, wx.RIGHT, 6)
        btn_row.Add(btn_close, 0)
        sizer.Add(btn_row, 0, wx.ALL, 8)

        self.SetSizer(sizer)

        self.btn_save.Bind(wx.EVT_BUTTON,  self._on_save)
        self.btn_rerun.Bind(wx.EVT_BUTTON, lambda e: self._run_validation())

    def _run_validation(self):
        self.issues_list.DeleteAllItems()
        self.summary_lbl.SetLabel("Running validation…")

        desc_data = self.project.get("descriptions_data")
        if not desc_data:
            self.summary_lbl.SetLabel("No descriptions to validate.")
            return

        try:
            from core.validator import validate_and_repair, print_validation_report
            from core.video_dubber import _get_video_duration

            video_path = self.project.get("video_path", "")
            video_dur  = _get_video_duration(video_path) if video_path else 0.0

            self._repaired, result = validate_and_repair(
                dict(desc_data), video_duration=video_dur, auto_repair=True
            )

            sev_colors = {
                "error":   wx.Colour(255, 180, 180),
                "warning": wx.Colour(255, 240, 180),
                "info":    wx.Colour(220, 240, 255),
            }

            for issue in result.issues:
                idx = self.issues_list.InsertItem(
                    self.issues_list.GetItemCount(),
                    issue.severity.upper()
                )
                self.issues_list.SetItem(idx, 1, issue.desc_id)
                self.issues_list.SetItem(idx, 2, issue.issue_type)
                self.issues_list.SetItem(idx, 3, issue.message)
                self.issues_list.SetItem(idx, 4, "✅" if issue.auto_fixed else "—")
                col = sev_colors.get(issue.severity)
                if col:
                    self.issues_list.SetItemBackgroundColour(idx, col)

            e_count = len(result.errors)
            w_count = len(result.warnings)
            i_count = len(result.infos)
            status  = "PASSED" if result.passed else "FAILED"
            summary = (
                f"Validation {status}  —  "
                f"{e_count} error(s)  |  {w_count} warning(s)  |  {i_count} info"
            )
            if result.descriptions_modified:
                summary += "  |  Auto-repairs applied (not yet saved)"
            self.summary_lbl.SetLabel(summary)
            self.btn_save.Enable(result.descriptions_modified)

        except Exception as e:
            self.summary_lbl.SetLabel(f"Validation error: {e}")

    def _on_save(self, event):
        if not hasattr(self, "_repaired"):
            return
        try:
            import json
            from db import database as db
            project_id = self.project["id"]
            desc_path  = db.get_project_dir(project_id) / "descriptions.json"
            with open(desc_path, "w", encoding="utf-8") as f:
                json.dump(self._repaired, f, indent=2, ensure_ascii=False)
            db.update_project(project_id, {"descriptions_data": self._repaired})
            wx.MessageBox("Repaired descriptions saved.", "Saved", wx.OK | wx.ICON_INFORMATION)
            self.btn_save.Enable(False)
        except Exception as e:
            wx.MessageBox(f"Save failed: {e}", "Error", wx.OK | wx.ICON_ERROR)
