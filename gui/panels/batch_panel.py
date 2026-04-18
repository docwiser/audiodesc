"""
gui/panels/batch_panel.py
--------------------------
Batch Queue Panel — manage and run batch processing jobs.

Layout:
  Top:    Jobs ListCtrl (Job ID | Project | Steps | Status | Queued)
  Middle: Add job controls (project selector, steps checkboxes, model, extra)
  Bottom: Run queue button + status

Screen-reader accessible: all controls labeled, list announced.
"""

import wx
import threading
from pathlib import Path


class BatchPanel(wx.Panel):
    def __init__(self, parent, main_window):
        super().__init__(parent)
        self.main_window = main_window
        self._build_ui()
        self.refresh_jobs()

    def _build_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        hdr = wx.StaticText(self, label="Batch Queue")
        hdr.SetFont(hdr.GetFont().Bold().Scaled(1.2))
        sizer.Add(hdr, 0, wx.ALL, 8)

        # ── Jobs list ─────────────────────────────────────────────────────────
        list_box = wx.StaticBox(self, label="Queued Jobs")
        list_sizer = wx.StaticBoxSizer(list_box, wx.VERTICAL)

        self.jobs_list = wx.ListCtrl(
            self,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES,
        )
        self.jobs_list.SetName("Batch Jobs List")
        self.jobs_list.SetHelpText("All batch processing jobs. Select to view details.")
        self.jobs_list.InsertColumn(0, "Job ID",  width=80)
        self.jobs_list.InsertColumn(1, "Project", width=180)
        self.jobs_list.InsertColumn(2, "Steps",   width=180)
        self.jobs_list.InsertColumn(3, "Status",  width=80)
        self.jobs_list.InsertColumn(4, "Queued",  width=160)
        self.jobs_list.InsertColumn(5, "Error",   width=200)
        list_sizer.Add(self.jobs_list, 1, wx.EXPAND | wx.ALL, 4)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_refresh_jobs = wx.Button(self, label="&Refresh")
        self.btn_remove_job   = wx.Button(self, label="Remove &Selected")
        self.btn_clear_done   = wx.Button(self, label="&Clear Done/Failed")
        self.btn_run_queue    = wx.Button(self, label="▶  &Run All Pending")

        self.btn_refresh_jobs.SetHelpText("Refresh the jobs list from disk")
        self.btn_remove_job.SetHelpText("Remove the selected pending job from the queue")
        self.btn_clear_done.SetHelpText("Remove all completed and failed jobs from the list")
        self.btn_run_queue.SetHelpText("Start processing all pending jobs in order")

        for btn in [self.btn_refresh_jobs, self.btn_remove_job, self.btn_clear_done, self.btn_run_queue]:
            btn_row.Add(btn, 0, wx.RIGHT, 6)
        list_sizer.Add(btn_row, 0, wx.ALL, 4)
        sizer.Add(list_sizer, 1, wx.EXPAND | wx.ALL, 8)

        # ── Add job form ──────────────────────────────────────────────────────
        add_box = wx.StaticBox(self, label="Add Job to Queue")
        add_sizer = wx.StaticBoxSizer(add_box, wx.VERTICAL)

        # Project selector
        proj_row = wx.BoxSizer(wx.HORIZONTAL)
        proj_row.Add(wx.StaticText(self, label="&Project:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.proj_combo = wx.ComboBox(self, style=wx.CB_READONLY, size=(220, -1))
        self.proj_combo.SetName("Project selector for batch")
        self.btn_refresh_projs = wx.Button(self, label="Refresh &Projects")
        proj_row.Add(self.proj_combo, 0, wx.RIGHT, 6)
        proj_row.Add(self.btn_refresh_projs, 0)
        add_sizer.Add(proj_row, 0, wx.ALL, 4)

        # Steps checkboxes
        steps_lbl = wx.StaticText(self, label="&Steps to run:")
        add_sizer.Add(steps_lbl, 0, wx.LEFT | wx.TOP, 4)
        steps_row = wx.BoxSizer(wx.HORIZONTAL)
        self.chk_describe = wx.CheckBox(self, label="&AI Descriptions")
        self.chk_audio    = wx.CheckBox(self, label="&TTS Audio")
        self.chk_dub      = wx.CheckBox(self, label="&Dub Video")
        self.chk_export   = wx.CheckBox(self, label="&Export")
        self.chk_describe.SetValue(True)
        self.chk_audio.SetValue(True)
        self.chk_dub.SetValue(True)
        for chk in [self.chk_describe, self.chk_audio, self.chk_dub, self.chk_export]:
            steps_row.Add(chk, 0, wx.RIGHT, 12)
        add_sizer.Add(steps_row, 0, wx.ALL, 4)

        # Model selector
        model_row = wx.BoxSizer(wx.HORIZONTAL)
        model_row.Add(wx.StaticText(self, label="&Model:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.model_combo = wx.ComboBox(
            self,
            choices=["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite", "gemini-2.0-flash"],
            style=wx.CB_READONLY, size=(200, -1)
        )
        self.model_combo.SetValue("gemini-2.5-flash")
        self.model_combo.SetName("Gemini model for batch")
        model_row.Add(self.model_combo, 0)
        add_sizer.Add(model_row, 0, wx.ALL, 4)

        # Extra instructions
        add_sizer.Add(wx.StaticText(self, label="Extra &instructions (optional):"), 0, wx.LEFT, 4)
        self.extra_ctrl = wx.TextCtrl(self, size=(-1, 50), style=wx.TE_MULTILINE)
        self.extra_ctrl.SetName("Extra instructions for AI")
        add_sizer.Add(self.extra_ctrl, 0, wx.EXPAND | wx.ALL, 4)

        self.btn_add_job = wx.Button(self, label="&Add Job to Queue")
        self.btn_add_job.SetHelpText("Add the configured job to the batch queue")
        add_sizer.Add(self.btn_add_job, 0, wx.ALL, 4)

        sizer.Add(add_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Run log ───────────────────────────────────────────────────────────
        self.run_log = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            size=(-1, 80),
        )
        self.run_log.SetName("Batch run log")
        self.run_log.SetHelpText("Output from batch queue execution")
        sizer.Add(self.run_log, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.SetSizer(sizer)

        # Events
        self.btn_refresh_jobs.Bind(wx.EVT_BUTTON,   lambda e: self.refresh_jobs())
        self.btn_remove_job.Bind(wx.EVT_BUTTON,     self._on_remove_job)
        self.btn_clear_done.Bind(wx.EVT_BUTTON,     self._on_clear_done)
        self.btn_run_queue.Bind(wx.EVT_BUTTON,      self._on_run_queue)
        self.btn_refresh_projs.Bind(wx.EVT_BUTTON,  self._on_refresh_projs)
        self.btn_add_job.Bind(wx.EVT_BUTTON,        self._on_add_job)
        self._on_refresh_projs(None)

    def _on_refresh_projs(self, event):
        try:
            from db import database as db
            projects = db.list_projects()
            choices  = [f"{p['id']} — {p['name']}" for p in projects]
            self.proj_combo.Clear()
            self.proj_combo.Append(choices)
            if choices:
                self.proj_combo.SetSelection(0)
            self._project_list = projects
        except Exception as e:
            self._project_list = []

    def refresh_jobs(self):
        try:
            from core.batch_queue import list_jobs
            jobs = list_jobs()
        except Exception:
            jobs = []

        self.jobs_list.DeleteAllItems()
        status_colors = {
            "pending": wx.Colour(255, 255, 180),
            "running": wx.Colour(180, 220, 255),
            "done":    wx.Colour(180, 255, 180),
            "failed":  wx.Colour(255, 180, 180),
        }
        for j in reversed(jobs):
            idx = self.jobs_list.InsertItem(self.jobs_list.GetItemCount(), j["job_id"])
            self.jobs_list.SetItem(idx, 1, j.get("project_id", ""))
            self.jobs_list.SetItem(idx, 2, ", ".join(j.get("steps", [])))
            self.jobs_list.SetItem(idx, 3, j.get("status", ""))
            self.jobs_list.SetItem(idx, 4, j.get("queued_at", "")[:19])
            self.jobs_list.SetItem(idx, 5, (j.get("error") or "")[:60])
            col = status_colors.get(j.get("status", ""), None)
            if col:
                self.jobs_list.SetItemBackgroundColour(idx, col)

    def _on_add_job(self, event):
        if not hasattr(self, "_project_list") or not self._project_list:
            wx.MessageBox("No projects available.", "Info", wx.OK)
            return
        sel_idx = self.proj_combo.GetSelection()
        if sel_idx < 0 or sel_idx >= len(self._project_list):
            wx.MessageBox("Select a project.", "Info", wx.OK)
            return

        project = self._project_list[sel_idx]
        steps = []
        if self.chk_describe.GetValue(): steps.append("describe")
        if self.chk_audio.GetValue():    steps.append("audio")
        if self.chk_dub.GetValue():      steps.append("dub")
        if self.chk_export.GetValue():   steps.append("export")
        if not steps:
            wx.MessageBox("Select at least one step.", "Info", wx.OK)
            return

        model = self.model_combo.GetValue()
        extra = self.extra_ctrl.GetValue().strip()

        from core.batch_queue import add_job
        add_job(project["id"], steps, model=model, extra_instructions=extra)
        self.refresh_jobs()
        wx.MessageBox(f"Job added for '{project['name']}'.", "Added", wx.OK | wx.ICON_INFORMATION)

    def _on_remove_job(self, event):
        idx = self.jobs_list.GetFirstSelected()
        if idx < 0:
            wx.MessageBox("Select a job to remove.", "No Selection", wx.OK)
            return
        job_id = self.jobs_list.GetItemText(idx, 0)
        from core.batch_queue import remove_job
        if remove_job(job_id):
            self.refresh_jobs()
        else:
            wx.MessageBox(f"Could not remove job {job_id} (may be running).", "Error", wx.OK | wx.ICON_WARNING)

    def _on_clear_done(self, event):
        from core.batch_queue import _load_queue, _save_queue
        queue   = _load_queue()
        cleaned = [j for j in queue if j["status"] in ("pending", "running")]
        removed = len(queue) - len(cleaned)
        _save_queue(cleaned)
        self.refresh_jobs()
        wx.MessageBox(f"Cleared {removed} completed/failed jobs.", "Done", wx.OK | wx.ICON_INFORMATION)

    def _on_run_queue(self, event):
        stop_on_error = wx.MessageBox(
            "Stop processing on first error?",
            "Batch Run Options",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        ) == wx.YES

        self.run_log.Clear()
        self.btn_run_queue.Enable(False)

        def _do():
            from core.batch_queue import run_queue
            try:
                result = run_queue(stop_on_error=stop_on_error)
                msg = f"\nBatch complete: {result['done']} done, {result['failed']} failed."
            except Exception as e:
                msg = f"\nBatch error: {e}"
            wx.CallAfter(self.run_log.AppendText, msg)
            wx.CallAfter(self.btn_run_queue.Enable, True)
            wx.CallAfter(self.refresh_jobs)

        threading.Thread(target=_do, daemon=True).start()
