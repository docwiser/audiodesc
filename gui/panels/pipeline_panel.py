"""
gui/panels/pipeline_panel.py
-----------------------------
Step-by-step pipeline panel.

Layout:
  Top:    Project info labels (name, stage, video, descriptions count)
  Middle: Step buttons grid (Step 1-5 + side actions)
  Bottom: Log window (TextCtrl, read-only, screen-reader announced)
          Progress gauge
          Cancel button (stops background thread)

All pipeline steps run in background threads so the UI stays responsive.
Progress and log updates use wx.CallAfter() for thread safety.
"""

import wx
import threading
import traceback
from pathlib import Path


STEP_INFO = {
    1: ("Upload Video",         "Upload your video file to the Gemini Files API for AI analysis."),
    2: ("Generate Descriptions","Use Gemini AI to generate timestamped audio descriptions."),
    3: ("Generate Audio",       "Convert description text to speech using your configured TTS engine."),
    4: ("Dub Video",            "Mix the description audio clips into the source video."),
    5: ("Export",               "Export dubbed video, subtitle files, and audio tracks."),
}


class PipelinePanel(wx.Panel):
    def __init__(self, parent, main_window):
        super().__init__(parent)
        self.main_window = main_window
        self.project = None
        self._cancel_event = threading.Event()
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)

        # ── Project info bar ──────────────────────────────────────────────────
        info_box = wx.StaticBox(self, label="Current Project")
        info_sizer = wx.StaticBoxSizer(info_box, wx.VERTICAL)

        grid = wx.FlexGridSizer(rows=2, cols=4, vgap=4, hgap=12)
        grid.AddGrowableCol(1); grid.AddGrowableCol(3)

        self.lbl_name  = self._make_info_pair(grid, "Name:")
        self.lbl_stage = self._make_info_pair(grid, "Stage:")
        self.lbl_video = self._make_info_pair(grid, "Video:")
        self.lbl_descs = self._make_info_pair(grid, "Descriptions:")

        info_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 8)
        outer.Add(info_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # ── Pipeline steps grid ───────────────────────────────────────────────
        steps_box = wx.StaticBox(self, label="Pipeline Steps")
        steps_sizer = wx.StaticBoxSizer(steps_box, wx.VERTICAL)

        # Step buttons
        self.step_buttons = {}
        self.step_status  = {}

        for step_num in range(1, 6):
            label, tip = STEP_INFO[step_num]
            row = wx.BoxSizer(wx.HORIZONTAL)

            btn = wx.Button(self, label=f"&{step_num}. {label}", size=(220, -1))
            btn.SetHelpText(tip)
            btn.SetName(f"Pipeline Step {step_num}: {label}")
            btn.Bind(wx.EVT_BUTTON, lambda e, n=step_num: self.run_step(n))
            self.step_buttons[step_num] = btn

            status = wx.StaticText(self, label="—")
            status.SetName(f"Step {step_num} status")
            self.step_status[step_num] = status

            row.Add(btn, 0, wx.RIGHT, 8)
            row.Add(status, 1, wx.ALIGN_CENTER_VERTICAL)
            steps_sizer.Add(row, 0, wx.EXPAND | wx.ALL, 4)

        # Separator
        steps_sizer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 6)

        # Side-action buttons
        side_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_validate    = wx.Button(self, label="&Validate")
        self.btn_smart_duck  = wx.Button(self, label="Smart &Ducking")
        self.btn_tts_config  = wx.Button(self, label="&TTS Config")
        self.btn_cost        = wx.Button(self, label="Cost &Report")

        self.btn_validate.SetHelpText("Run validation and auto-repair on descriptions")
        self.btn_smart_duck.SetHelpText("Apply audio-analysis-based volume ducking")
        self.btn_tts_config.SetHelpText("Configure TTS voice, engine and speech rate")
        self.btn_cost.SetHelpText("View Gemini API usage and estimated costs")

        for btn in [self.btn_validate, self.btn_smart_duck, self.btn_tts_config, self.btn_cost]:
            side_row.Add(btn, 0, wx.RIGHT, 6)

        steps_sizer.Add(side_row, 0, wx.ALL, 4)
        outer.Add(steps_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Progress gauge ────────────────────────────────────────────────────
        self.gauge = wx.Gauge(self, range=100, style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)
        self.gauge.SetName("Pipeline Progress")
        self.gauge.SetHelpText("Shows pipeline step progress")
        outer.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        self.gauge_label = wx.StaticText(self, label="")
        self.gauge_label.SetName("Progress label")
        outer.Add(self.gauge_label, 0, wx.LEFT | wx.BOTTOM, 8)

        # ── Log window ────────────────────────────────────────────────────────
        log_box = wx.StaticBox(self, label="Pipeline Log")
        log_sizer = wx.StaticBoxSizer(log_box, wx.VERTICAL)

        self.log_ctrl = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_AUTO_URL | wx.HSCROLL,
        )
        self.log_ctrl.SetName("Pipeline Log")
        self.log_ctrl.SetHelpText(
            "Log output from pipeline steps. Screen readers will announce new lines."
        )
        # Use monospace font for log readability
        font = wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        self.log_ctrl.SetFont(font)
        log_sizer.Add(self.log_ctrl, 1, wx.EXPAND | wx.ALL, 4)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_cancel   = wx.Button(self, label="&Cancel Running Step")
        self.btn_clear_log = wx.Button(self, label="C&lear Log")
        self.btn_cancel.SetHelpText("Cancel the currently running pipeline step")
        self.btn_clear_log.SetHelpText("Clear the log window")
        self.btn_cancel.Enable(False)
        btn_row.Add(self.btn_cancel, 0, wx.RIGHT, 8)
        btn_row.Add(self.btn_clear_log, 0)
        log_sizer.Add(btn_row, 0, wx.ALL, 4)

        outer.Add(log_sizer, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.SetSizer(outer)

        # Events
        self.btn_validate.Bind(wx.EVT_BUTTON,   self._on_validate)
        self.btn_smart_duck.Bind(wx.EVT_BUTTON, self._on_smart_duck)
        self.btn_tts_config.Bind(wx.EVT_BUTTON, self._on_tts_config)
        self.btn_cost.Bind(wx.EVT_BUTTON,       self._on_cost_report)
        self.btn_cancel.Bind(wx.EVT_BUTTON,     self._on_cancel)
        self.btn_clear_log.Bind(wx.EVT_BUTTON,  lambda e: self.log_ctrl.Clear())

        self._update_step_buttons()

    def _make_info_pair(self, grid, label_text: str):
        lbl = wx.StaticText(self, label=label_text)
        val = wx.StaticText(self, label="—")
        val.SetName(label_text.strip(":"))
        grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(val, 1, wx.EXPAND)
        return val

    # ── Project loading ───────────────────────────────────────────────────────

    def load_project(self, project: dict):
        self.project = project
        self._refresh_info()
        self._update_step_buttons()
        self.log("Project loaded: " + project.get("name", "?"))

    def _refresh_info(self):
        if not self.project:
            self.lbl_name.SetLabel("—")
            self.lbl_stage.SetLabel("—")
            self.lbl_video.SetLabel("—")
            self.lbl_descs.SetLabel("—")
            return
        p = self.project
        self.lbl_name.SetLabel(p.get("name", "?"))
        self.lbl_stage.SetLabel(p.get("stage", "?"))
        video = p.get("video_path", "")
        self.lbl_video.SetLabel(Path(video).name if video else "—")
        desc_data = p.get("descriptions_data") or {}
        n_descs = len(desc_data.get("descriptions", []))
        self.lbl_descs.SetLabel(str(n_descs) if n_descs else "—")

    def _update_step_buttons(self):
        """Enable steps based on current pipeline stage."""
        if not self.project:
            for btn in self.step_buttons.values():
                btn.Enable(False)
            return

        stage = self.project.get("stage", "created")
        stage_order = ["created", "uploaded", "described", "audio_generated", "dubbed", "done"]
        stage_idx = stage_order.index(stage) if stage in stage_order else 0

        for step_num, btn in self.step_buttons.items():
            # Step N is enabled if we're at stage N-1 or higher
            btn.Enable(stage_idx >= step_num - 1)

        # Update status labels
        stage_status = {
            "created":         {1: "—",  2: "🔒", 3: "🔒", 4: "🔒", 5: "🔒"},
            "uploaded":        {1: "✅", 2: "—",  3: "🔒", 4: "🔒", 5: "🔒"},
            "described":       {1: "✅", 2: "✅", 3: "—",  4: "🔒", 5: "🔒"},
            "audio_generated": {1: "✅", 2: "✅", 3: "✅", 4: "—",  5: "🔒"},
            "dubbed":          {1: "✅", 2: "✅", 3: "✅", 4: "✅", 5: "—"},
            "done":            {1: "✅", 2: "✅", 3: "✅", 4: "✅", 5: "✅"},
        }
        statuses = stage_status.get(stage, {})
        for step_num, lbl in self.step_status.items():
            lbl.SetLabel(statuses.get(step_num, "—"))

    # ── Logging ───────────────────────────────────────────────────────────────

    def log(self, msg: str, newline: bool = True):
        """Append a message to the log window (thread-safe)."""
        def _do():
            self.log_ctrl.AppendText(msg + ("\n" if newline else ""))
            # Announce to screen reader via SetValue on a hidden control would be
            # fragile; the TextCtrl in MULTILINE READONLY mode is announced by
            # NVDA/JAWS when it receives focus and new text is appended.
        wx.CallAfter(_do)

    def set_progress(self, pct: int, label: str = ""):
        def _do():
            self.gauge.SetValue(max(0, min(100, pct)))
            if label:
                self.gauge_label.SetLabel(label)
        wx.CallAfter(_do)

    # ── Background task runner ────────────────────────────────────────────────

    def _run_in_thread(self, func, *args, on_done=None, **kwargs):
        """Run func(*args, **kwargs) in a background thread."""
        if self._worker and self._worker.is_alive():
            wx.MessageBox(
                "A pipeline step is already running. Please wait or cancel it.",
                "Busy", wx.OK | wx.ICON_WARNING,
            )
            return

        self._cancel_event.clear()
        self.btn_cancel.Enable(True)
        self._set_steps_enabled(False)

        def _thread():
            try:
                result = func(*args, **kwargs)
            except Exception as e:
                result = None
                msg = f"ERROR: {type(e).__name__}: {e}\n{traceback.format_exc()}"
                self.log(msg)
                wx.CallAfter(
                    wx.MessageBox, f"Step failed:\n{e}", "Error",
                    wx.OK | wx.ICON_ERROR
                )
            finally:
                wx.CallAfter(self._on_step_done, result, on_done)

        self._worker = threading.Thread(target=_thread, daemon=True)
        self._worker.start()

    def _on_step_done(self, result, on_done):
        self.btn_cancel.Enable(False)
        self._set_steps_enabled(True)
        self.set_progress(0, "")
        self.main_window.refresh_current_project()
        if self.main_window.current_project:
            self.project = self.main_window.current_project
            self._refresh_info()
            self._update_step_buttons()
        if on_done:
            try:
                on_done(result)
            except Exception:
                pass

    def _set_steps_enabled(self, enabled: bool):
        for btn in self.step_buttons.values():
            btn.Enable(enabled)
        for btn in [self.btn_validate, self.btn_smart_duck,
                    self.btn_tts_config, self.btn_cost]:
            btn.Enable(enabled)

    def _on_cancel(self, event):
        self._cancel_event.set()
        self.log("--- Cancel requested ---")
        self.btn_cancel.Enable(False)

    # ── Step runners ──────────────────────────────────────────────────────────

    def run_step(self, step: int):
        if not self.project:
            wx.MessageBox("Open a project first.", "No Project", wx.OK | wx.ICON_INFORMATION)
            return

        runners = {
            1: self._step1_upload,
            2: self._step2_describe,
            3: self._step3_audio,
            4: self._step4_dub,
            5: self._step5_export,
        }
        runner = runners.get(step)
        if runner:
            runner()

    # ── Step 1: Upload ────────────────────────────────────────────────────────

    def _step1_upload(self):
        # Pick file first (must be on main thread)
        dlg = wx.FileDialog(
            self,
            message="Select video file to upload",
            wildcard="Video files (*.mp4;*.mov;*.avi;*.mkv;*.webm)|*.mp4;*.mov;*.avi;*.mkv;*.webm|All files (*.*)|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        video_path = dlg.GetPath()
        dlg.Destroy()

        project_id = self.project["id"]
        self.log(f"\n=== Step 1: Upload Video ===\nFile: {video_path}")
        self.set_progress(10, "Uploading to Gemini Files API…")

        def _do():
            import shutil
            from db import database as db
            from core.gemini_uploader import upload_video_to_gemini

            # Copy to project uploads dir
            uploads_dir = db.get_uploads_dir(project_id)
            src = Path(video_path)
            dest = uploads_dir / src.name
            if str(src) != str(dest):
                self.log("Copying video to project folder…")
                shutil.copy2(src, dest)
                video_path_final = str(dest)
            else:
                video_path_final = video_path

            db.update_project(project_id, {"video_path": video_path_final})
            self.log("Uploading to Gemini Files API…")
            self.set_progress(30, "Uploading…")
            upload_video_to_gemini(project_id, video_path_final)
            self.set_progress(100, "Upload complete!")
            self.log("✅ Step 1 complete — video uploaded.")
            return True

        self._run_in_thread(_do)

    # ── Step 2: Describe ──────────────────────────────────────────────────────

    def _step2_describe(self):
        from gui.dialogs.describe_dialog import DescribeDialog
        dlg = DescribeDialog(self)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        opts = dlg.get_options()
        dlg.Destroy()

        project_id = self.project["id"]
        self.log(f"\n=== Step 2: Generate Descriptions ===\nModel: {opts['model']}")
        self.set_progress(5, "Starting description generation…")

        def _do():
            from core.description_generator import generate_descriptions

            class LogRedirect:
                def __init__(self, panel):
                    self.panel = panel
                def print(self, *args, **kwargs):
                    msg = " ".join(str(a) for a in args)
                    self.panel.log(msg)

            self.set_progress(15, "Analyzing video with Gemini AI…")
            result = generate_descriptions(
                project_id=project_id,
                model=opts["model"],
                force_regenerate=opts["force"],
                extra_instructions=opts.get("extra") or None,
                run_validation=opts["validate"],
                run_smart_ducking=opts["smart_duck"],
                smart_ducking_override=opts["duck_override"],
            )
            n = len(result.get("descriptions", []))
            self.set_progress(100, f"Done! {n} descriptions generated.")
            self.log(f"✅ Step 2 complete — {n} descriptions generated.")
            wx.CallAfter(
                self.main_window.project_view.panel_descriptions.load_project,
                self.main_window.current_project
            )
            return result

        self._run_in_thread(_do)

    # ── Step 3: Audio ─────────────────────────────────────────────────────────

    def _step3_audio(self):
        from gui.dialogs.tts_dialog import TTSConfigDialog
        p = self.project
        if not p.get("tts_config"):
            dlg = TTSConfigDialog(self, project=p)
            if dlg.ShowModal() != wx.ID_OK:
                dlg.Destroy()
                return
            dlg.Destroy()
            from db import database as db
            p = db.get_project(p["id"])
            self.project = p

        ans = wx.MessageBox(
            "Generate TTS audio for all descriptions?\n\n"
            "This may take several minutes for large projects.",
            "Step 3: Generate Audio",
            wx.YES_NO | wx.YES_DEFAULT | wx.ICON_QUESTION,
        )
        if ans != wx.YES:
            return

        project_id = p["id"]
        normalize = wx.MessageBox(
            "Normalize clip loudness to -16 LUFS? (Recommended)",
            "Loudness Normalization",
            wx.YES_NO | wx.YES_DEFAULT | wx.ICON_QUESTION,
        ) == wx.YES

        self.log(f"\n=== Step 3: Generate Audio ===")
        self.set_progress(5, "Starting TTS synthesis…")

        def _do():
            from tts.tts_manager import generate_all_audio
            results = generate_all_audio(project_id, normalize=normalize)
            n = len(results)
            self.set_progress(100, f"Done! {n} audio clips generated.")
            self.log(f"✅ Step 3 complete — {n} clips generated.")
            return results

        self._run_in_thread(_do)

    # ── Step 4: Dub ───────────────────────────────────────────────────────────

    def _step4_dub(self):
        ans = wx.MessageBox(
            "Dub the video with audio descriptions?\n\n"
            "This uses a two-pass ffmpeg approach with a live progress bar.\n"
            "Large videos may take several minutes.",
            "Step 4: Dub Video",
            wx.YES_NO | wx.YES_DEFAULT | wx.ICON_QUESTION,
        )
        if ans != wx.YES:
            return

        project_id = self.project["id"]
        self.log(f"\n=== Step 4: Dub Video ===")
        self.set_progress(5, "Starting video dubbing…")

        def _do():
            from core.video_dubber import dub_video_ffmpeg

            class ProgressProxy:
                def __init__(self, panel):
                    self.panel = panel
                def update(self, pct, label=""):
                    self.panel.set_progress(pct, label)

            self.set_progress(10, "Building combined description audio track (Pass 1/2)…")
            output_path = dub_video_ffmpeg(project_id)
            self.set_progress(100, "Dubbing complete!")
            self.log(f"✅ Step 4 complete — dubbed video: {Path(output_path).name}")

            # Offer to open in player
            wx.CallAfter(self._offer_player, output_path)
            return output_path

        self._run_in_thread(_do)

    def _offer_player(self, video_path: str):
        if wx.MessageBox(
            f"Video dubbed successfully!\n{Path(video_path).name}\n\nOpen in player?",
            "Dubbing Complete",
            wx.YES_NO | wx.YES_DEFAULT | wx.ICON_INFORMATION,
        ) == wx.YES:
            self.main_window.project_view.panel_player.load_file(video_path)
            self.main_window.project_view.show_section(2)  # SEC_PLAYER

    # ── Step 5: Export ────────────────────────────────────────────────────────

    def _step5_export(self):
        # Switch to the Export section in the project view
        self.main_window.project_view.show_section(4)  # SEC_EXPORT
        self.main_window.project_view.panel_export.load_project(self.project)

    # ── Side actions ──────────────────────────────────────────────────────────

    def _on_validate(self, event):
        if not self.project:
            wx.MessageBox("No project loaded.", "Info", wx.OK)
            return
        from gui.dialogs.validation_dialog import ValidationDialog
        dlg = ValidationDialog(self, self.project)
        dlg.ShowModal()
        dlg.Destroy()

    def apply_smart_ducking(self):
        if not self.project:
            return
        override = wx.MessageBox(
            "Override ALL AI volume suggestions with audio analysis?\n\n"
            "No = only fix large discrepancies (recommended).",
            "Smart Volume Ducking",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        ) == wx.YES

        project_id = self.project["id"]
        self.log(f"\n=== Applying Smart Volume Ducking ===")

        def _do():
            from core.audio_analyzer import analyze_video_audio, apply_smart_ducking
            from core.description_generator import load_descriptions
            import json
            from db import database as db

            p = db.get_project(project_id)
            video_path = p.get("video_path", "")
            if not video_path or not Path(video_path).exists():
                self.log("ERROR: Video file not found.")
                return None

            self.log("Analyzing audio levels…")
            analysis = analyze_video_audio(video_path)
            if not analysis:
                self.log("ERROR: Audio analysis failed.")
                return None

            data = load_descriptions(project_id)
            if not data:
                self.log("ERROR: No descriptions found.")
                return None

            modified = apply_smart_ducking(data, analysis, override_ai=override)

            desc_path = db.get_project_dir(project_id) / "descriptions.json"
            with open(desc_path, "w", encoding="utf-8") as f:
                json.dump(modified, f, indent=2, ensure_ascii=False)
            db.update_project(project_id, {"descriptions_data": modified})

            self.log("✅ Smart ducking applied and saved.")
            return True

        self._run_in_thread(_do)

    def _on_smart_duck(self, event):
        self.apply_smart_ducking()

    def _on_tts_config(self, event):
        if not self.project:
            wx.MessageBox("No project loaded.", "Info", wx.OK)
            return
        from gui.dialogs.tts_dialog import TTSConfigDialog
        dlg = TTSConfigDialog(self, self.project)
        if dlg.ShowModal() == wx.ID_OK:
            self.main_window.refresh_current_project()
        dlg.Destroy()

    def _on_cost_report(self, event):
        if not self.project:
            wx.MessageBox("No project loaded.", "Info", wx.OK)
            return
        from gui.dialogs.cost_dialog import CostDialog
        dlg = CostDialog(self, self.project)
        dlg.ShowModal()
        dlg.Destroy()
