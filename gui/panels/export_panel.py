"""
gui/panels/export_panel.py
---------------------------
Export dialog — choose what to export and run it.
Opened from Step 5 button in pipeline panel.
"""

import wx
import threading
from pathlib import Path


EXPORT_OPTIONS = [
    ("dubbed_video",       "Dubbed video (descriptions baked in)"),
    ("video_with_ad_track","Original video + separate AD audio sidecar"),
    ("full_ad_audio",      "Full AD audio track (timeline-accurate MP3)"),
    ("individual_clips",   "Individual description audio clips"),
    ("vtt",                "WebVTT subtitle file"),
    ("srt",                "SRT subtitle file"),
    ("json_full",          "JSON — full workflow"),
    ("json_descriptions",  "JSON — descriptions only"),
    ("json_simple",        "JSON — simple (id/time/text)"),
    ("txt",                "Plain text script"),
    ("csv",                "CSV spreadsheet"),
    ("scripts",            "Individual description script files (.txt each)"),
]


class ExportDialog(wx.Dialog):
    def __init__(self, parent, project):
        super().__init__(
            parent,
            title="Export — Step 5",
            size=(560, 580),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.project = project
        self._selected_types = []
        self._build_ui()

    def _build_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(self, label=f"Export project: {self.project.get('name','?')}")
        lbl.SetFont(lbl.GetFont().Bold())
        sizer.Add(lbl, 0, wx.ALL, 10)

        sizer.Add(wx.StaticText(self, label="Select what to export:"), 0, wx.LEFT, 10)

        # Checkboxes for each type
        self._checks = {}
        for type_id, label in EXPORT_OPTIONS:
            chk = wx.CheckBox(self, label=label)
            chk.SetName(f"Export: {label}")
            self._checks[type_id] = chk
            sizer.Add(chk, 0, wx.LEFT | wx.TOP, 10)

        # ZIP option
        self.chk_zip = wx.CheckBox(self, label="Package all selected as ZIP archive")
        self.chk_zip.SetName("Create ZIP archive")
        sizer.Add(self.chk_zip, 0, wx.LEFT | wx.TOP, 10)

        sizer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.ALL, 8)

        # Log
        self.log = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 100))
        self.log.SetName("Export log")
        sizer.Add(self.log, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # Buttons
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_export = wx.Button(self, wx.ID_OK, label="&Export Selected")
        btn_cancel = wx.Button(self, wx.ID_CANCEL, label="&Close")
        self.btn_export.SetHelpText("Run the selected exports")
        btn_row.Add(self.btn_export, 0, wx.RIGHT, 8)
        btn_row.Add(btn_cancel, 0)
        sizer.Add(btn_row, 0, wx.ALL, 8)

        self.SetSizer(sizer)
        self.btn_export.Bind(wx.EVT_BUTTON, self._on_export)

        # Auto-select based on project stage
        stage = self.project.get("stage", "")
        if self.project.get("dubbed_video_path"):
            self._checks.get("dubbed_video", wx.CheckBox(self)).SetValue(True)
        if stage in ("described", "audio_generated", "dubbed", "done"):
            self._checks.get("vtt", wx.CheckBox(self)).SetValue(True)
            self._checks.get("srt", wx.CheckBox(self)).SetValue(True)

    def _on_export(self, event):
        selected = [t for t, chk in self._checks.items() if chk.GetValue()]
        if not selected:
            wx.MessageBox("Select at least one export type.", "Nothing selected", wx.OK)
            return

        make_zip = self.chk_zip.GetValue()
        self.btn_export.Enable(False)

        def _do():
            from export.export_manager import run_export, create_export_zip
            all_files = []
            for t in selected:
                try:
                    wx.CallAfter(self.log.AppendText, f"Exporting: {t}…\n")
                    files = run_export(self.project["id"], t)
                    all_files.extend(files)
                    wx.CallAfter(self.log.AppendText, f"  ✅ {len(files)} file(s)\n")
                except Exception as e:
                    wx.CallAfter(self.log.AppendText, f"  ❌ Error: {e}\n")

            if make_zip and all_files:
                try:
                    zip_path = create_export_zip(self.project["id"], all_files)
                    wx.CallAfter(self.log.AppendText, f"ZIP: {Path(zip_path).name}\n")
                    all_files.append(zip_path)
                except Exception as e:
                    wx.CallAfter(self.log.AppendText, f"ZIP error: {e}\n")

            from db import database as db
            db.add_export_record(self.project["id"], {
                "types": selected,
                "files": [str(f) for f in all_files],
            })

            summary = f"\nExport complete! {len(all_files)} file(s) total."
            wx.CallAfter(self.log.AppendText, summary)
            wx.CallAfter(self.btn_export.Enable, True)

            if all_files:
                exports_dir = str(db.get_exports_dir(self.project["id"]))
                wx.CallAfter(
                    wx.MessageBox,
                    f"Export complete!\nFiles saved to:\n{exports_dir}",
                    "Done",
                    wx.OK | wx.ICON_INFORMATION,
                )

        threading.Thread(target=_do, daemon=True).start()


class ExportPanel(wx.Panel):
    """
    Wrapper that embeds ExportDialog-style UI in a wx.Panel
    for use in the radio-group project view.
    """
    def __init__(self, parent, main_window):
        super().__init__(parent)
        self.main_window = main_window
        self.project = None
        self._inner = None
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.placeholder = wx.StaticText(
            self,
            label="Open a project and navigate here to access export options."
        )
        sizer.Add(self.placeholder, 1, wx.EXPAND | wx.ALL, 20)
        self.SetSizer(sizer)

    def load_project(self, project):
        self.project = project
        # Rebuild inner UI with the project
        if self._inner:
            self._inner.Destroy()
        self._inner = _ExportInner(self, self.main_window, project)
        s = self.GetSizer()
        s.Clear(False)
        s.Add(self._inner, 1, wx.EXPAND)
        self.placeholder.Hide()
        self.Layout()
