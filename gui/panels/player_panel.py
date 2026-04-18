"""
gui/panels/player_panel.py
---------------------------
Audio / Video Playback Panel — 100% screen-reader accessible.

Because wxPython's built-in media control has poor screen-reader support
and platform inconsistency, we use ffplay (bundled with ffmpeg) as the
playback engine, controlled via subprocess.

This avoids any visual-only custom drawing. All controls are standard
wx widgets: buttons, sliders, labels, list.

Features:
  - Play original video audio
  - Play dubbed video audio
  - Play individual description audio clips
  - Seek (slider + time spinners)
  - Volume control
  - Playback speed (0.5x, 0.75x, 1x, 1.25x, 1.5x, 2x)
  - Description timeline: click a description → jump to that time
  - Keyboard: Space=play/pause, Left/Right=seek 5s, Up/Down=volume

Screen-reader notes:
  - Time position announced via StaticText updated every second
  - Play/Pause button label changes to "Pause" when playing
  - All controls labeled
"""

import wx
import wx.lib.scrolledpanel as scrolled
import subprocess
import threading
import time
import os
from pathlib import Path


SPEEDS = ["0.5x", "0.75x", "1.0x", "1.25x", "1.5x", "2.0x"]
SPEED_MAP = {"0.5x": 0.5, "0.75x": 0.75, "1.0x": 1.0, "1.25x": 1.25, "1.5x": 1.5, "2.0x": 2.0}


def _secs_to_hms(s: float) -> str:
    s = max(0.0, s)
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    if h:
        return f"{h}:{m:02d}:{sec:05.2f}"
    return f"{m}:{sec:05.2f}"


def _get_duration(path: str) -> float:
    """Get media duration via ffprobe."""
    try:
        import json
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
            capture_output=True, text=True, timeout=15,
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0


class PlayerPanel(wx.Panel):
    """
    Media player panel using ffplay subprocess for actual playback,
    with wxPython controls for UI / accessibility.
    """

    def __init__(self, parent, main_window):
        super().__init__(parent)
        self.main_window = main_window
        self.project = None
        self._current_file = None
        self._duration = 0.0
        self._position = 0.0
        self._playing = False
        self._ffplay_proc = None
        self._position_thread = None
        self._volume = 100
        self._start_offset = 0.0  # seek start for current playback
        self._play_start_time = 0.0  # wall-clock time when play started
        self._build_ui()

        # Keyboard shortcuts on this panel
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)

    def _build_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = wx.StaticText(self, label="Audio / Video Player")
        hdr.SetFont(hdr.GetFont().Bold().Scaled(1.2))
        sizer.Add(hdr, 0, wx.ALL, 8)

        # ── File selector ─────────────────────────────────────────────────────
        file_box = wx.StaticBox(self, label="Load Media File")
        file_sizer = wx.StaticBoxSizer(file_box, wx.HORIZONTAL)

        self.file_path_ctrl = wx.TextCtrl(self, style=wx.TE_READONLY)
        self.file_path_ctrl.SetName("Loaded file path")
        self.file_path_ctrl.SetHelpText("Path of the currently loaded media file")
        self.btn_browse      = wx.Button(self, label="&Browse…")
        self.btn_load_orig   = wx.Button(self, label="Load &Original Video")
        self.btn_load_dubbed = wx.Button(self, label="Load &Dubbed Video")

        self.btn_browse.SetHelpText("Browse for any audio or video file to play")
        self.btn_load_orig.SetHelpText("Load the original (un-dubbed) project video")
        self.btn_load_dubbed.SetHelpText("Load the dubbed video with embedded descriptions")

        file_sizer.Add(self.file_path_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        file_sizer.Add(self.btn_browse,      0, wx.RIGHT, 4)
        file_sizer.Add(self.btn_load_orig,   0, wx.RIGHT, 4)
        file_sizer.Add(self.btn_load_dubbed, 0)
        sizer.Add(file_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # ── Playback controls ─────────────────────────────────────────────────
        ctrl_box = wx.StaticBox(self, label="Playback Controls (Space=Play/Pause, ←→=Seek 5s, ↑↓=Volume)")
        ctrl_sizer = wx.StaticBoxSizer(ctrl_box, wx.VERTICAL)

        # Time position
        time_row = wx.BoxSizer(wx.HORIZONTAL)
        self.lbl_position = wx.StaticText(self, label="0:00.00")
        self.lbl_position.SetName("Playback position")
        self.lbl_position.SetFont(self.lbl_position.GetFont().Scaled(1.4))
        self.lbl_slash    = wx.StaticText(self, label=" / ")
        self.lbl_duration = wx.StaticText(self, label="0:00.00")
        self.lbl_duration.SetName("Total duration")
        self.lbl_duration.SetFont(self.lbl_duration.GetFont().Scaled(1.4))

        time_row.Add(self.lbl_position, 0, wx.ALIGN_CENTER_VERTICAL)
        time_row.Add(self.lbl_slash,    0, wx.ALIGN_CENTER_VERTICAL)
        time_row.Add(self.lbl_duration, 0, wx.ALIGN_CENTER_VERTICAL)
        ctrl_sizer.Add(time_row, 0, wx.ALL, 6)

        # Seek slider
        self.seek_slider = wx.Slider(self, minValue=0, maxValue=1000, value=0)
        self.seek_slider.SetName("Seek slider")
        self.seek_slider.SetHelpText(
            "Drag to seek. Left/right arrow keys move 5 seconds. Accessible via keyboard."
        )
        ctrl_sizer.Add(self.seek_slider, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        # Transport buttons
        transport_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_play_pause = wx.Button(self, label="&Play")
        self.btn_stop       = wx.Button(self, label="&Stop")
        self.btn_seek_back  = wx.Button(self, label="← &-5s")
        self.btn_seek_fwd   = wx.Button(self, label="+5s →")
        self.btn_seek_back10 = wx.Button(self, label="←← -&10s")
        self.btn_seek_fwd10  = wx.Button(self, label="+10s →→")

        self.btn_play_pause.SetHelpText("Play or pause playback (Space key)")
        self.btn_stop.SetHelpText("Stop playback and reset position")
        self.btn_seek_back.SetHelpText("Seek backward 5 seconds (Left arrow key)")
        self.btn_seek_fwd.SetHelpText("Seek forward 5 seconds (Right arrow key)")
        self.btn_seek_back10.SetHelpText("Seek backward 10 seconds")
        self.btn_seek_fwd10.SetHelpText("Seek forward 10 seconds")

        for btn in [self.btn_seek_back10, self.btn_seek_back, self.btn_play_pause,
                    self.btn_stop, self.btn_seek_fwd, self.btn_seek_fwd10]:
            transport_row.Add(btn, 0, wx.RIGHT, 4)
        ctrl_sizer.Add(transport_row, 0, wx.ALL, 6)

        # Volume + speed row
        vs_row = wx.BoxSizer(wx.HORIZONTAL)
        vs_row.Add(wx.StaticText(self, label="&Volume:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.vol_slider = wx.Slider(self, minValue=0, maxValue=150, value=100, size=(120, -1))
        self.vol_slider.SetName("Volume slider")
        self.vol_slider.SetHelpText("Volume level 0–150%. Up/Down arrow keys adjust when focused.")
        self.lbl_vol = wx.StaticText(self, label="100%")
        vs_row.Add(self.vol_slider, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        vs_row.Add(self.lbl_vol,   0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 16)

        vs_row.Add(wx.StaticText(self, label="S&peed:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.speed_combo = wx.ComboBox(self, choices=SPEEDS, style=wx.CB_READONLY, size=(80, -1))
        self.speed_combo.SetValue("1.0x")
        self.speed_combo.SetName("Playback speed")
        vs_row.Add(self.speed_combo, 0, wx.ALIGN_CENTER_VERTICAL)
        ctrl_sizer.Add(vs_row, 0, wx.ALL, 6)

        sizer.Add(ctrl_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # ── Description clip list ─────────────────────────────────────────────
        clip_box = wx.StaticBox(self, label="Description Audio Clips (double-click to play)")
        clip_sizer = wx.StaticBoxSizer(clip_box, wx.VERTICAL)

        self.clip_list = wx.ListCtrl(
            self,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES,
        )
        self.clip_list.SetName("Description clips list")
        self.clip_list.SetHelpText("List of generated description audio clips. Double-click to play one.")
        self.clip_list.InsertColumn(0, "ID",        width=80)
        self.clip_list.InsertColumn(1, "Time",      width=100)
        self.clip_list.InsertColumn(2, "Duration",  width=70)
        self.clip_list.InsertColumn(3, "Description (preview)", width=280)
        clip_sizer.Add(self.clip_list, 1, wx.EXPAND | wx.ALL, 4)

        btn_clip_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_play_clip   = wx.Button(self, label="&Play Selected Clip")
        self.btn_preview_ctx = wx.Button(self, label="Preview in &Context")
        self.btn_play_clip.SetHelpText("Play the selected description audio clip")
        self.btn_preview_ctx.SetHelpText("Preview the clip mixed with video audio in context")
        btn_clip_row.Add(self.btn_play_clip,   0, wx.RIGHT, 6)
        btn_clip_row.Add(self.btn_preview_ctx, 0)
        clip_sizer.Add(btn_clip_row, 0, wx.ALL, 4)

        sizer.Add(clip_sizer, 1, wx.EXPAND | wx.ALL, 8)

        # ── Status ────────────────────────────────────────────────────────────
        self.status_label = wx.StaticText(self, label="No file loaded.")
        self.status_label.SetName("Player status")
        sizer.Add(self.status_label, 0, wx.LEFT | wx.BOTTOM, 8)

        self.SetSizer(sizer)

        # ── Events ────────────────────────────────────────────────────────────
        self.btn_browse.Bind(wx.EVT_BUTTON,       self._on_browse)
        self.btn_load_orig.Bind(wx.EVT_BUTTON,    self._on_load_orig)
        self.btn_load_dubbed.Bind(wx.EVT_BUTTON,  self._on_load_dubbed)
        self.btn_play_pause.Bind(wx.EVT_BUTTON,   self._on_play_pause)
        self.btn_stop.Bind(wx.EVT_BUTTON,         self._on_stop)
        self.btn_seek_back.Bind(wx.EVT_BUTTON,    lambda e: self._seek_relative(-5))
        self.btn_seek_fwd.Bind(wx.EVT_BUTTON,     lambda e: self._seek_relative(5))
        self.btn_seek_back10.Bind(wx.EVT_BUTTON,  lambda e: self._seek_relative(-10))
        self.btn_seek_fwd10.Bind(wx.EVT_BUTTON,   lambda e: self._seek_relative(10))
        self.vol_slider.Bind(wx.EVT_SLIDER,       self._on_vol_change)
        self.seek_slider.Bind(wx.EVT_SLIDER,      self._on_seek_slide)
        self.clip_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_play_clip)
        self.btn_play_clip.Bind(wx.EVT_BUTTON,   self._on_play_clip)
        self.btn_preview_ctx.Bind(wx.EVT_BUTTON, self._on_preview_ctx)

        # Position update timer
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_timer, self._timer)

    # ── Project loading ───────────────────────────────────────────────────────

    def load_project(self, project):
        self.project = project
        self._refresh_clip_list()

    def _refresh_clip_list(self):
        self.clip_list.DeleteAllItems()
        if not self.project:
            return
        audio_files = self.project.get("generated_audio_files", [])
        desc_data   = self.project.get("descriptions_data") or {}
        desc_map    = {d["id"]: d for d in desc_data.get("descriptions", [])}

        for af in audio_files:
            did  = af["desc_id"]
            desc = desc_map.get(did, {})
            txt  = desc.get("descriptionText", "")
            dur  = af.get("duration", 0)
            t    = desc.get("startTime", "")

            idx = self.clip_list.InsertItem(self.clip_list.GetItemCount(), did)
            self.clip_list.SetItem(idx, 1, t)
            self.clip_list.SetItem(idx, 2, f"{dur:.2f}s")
            self.clip_list.SetItem(idx, 3, txt[:80])

            if not Path(af.get("audio_path", "")).exists():
                self.clip_list.SetItemTextColour(idx, wx.Colour(150, 150, 150))

    def load_file(self, path: str):
        """Load a media file for playback."""
        if not Path(path).exists():
            wx.MessageBox(f"File not found:\n{path}", "Error", wx.OK | wx.ICON_ERROR)
            return
        self.stop()
        self._current_file = path
        self._duration = _get_duration(path)
        self._position = 0.0
        self.file_path_ctrl.SetValue(str(path))
        self.lbl_duration.SetLabel(_secs_to_hms(self._duration))
        self.lbl_position.SetLabel("0:00.00")
        self.seek_slider.SetValue(0)
        self.status_label.SetLabel(f"Loaded: {Path(path).name}  ({self._duration:.1f}s)")
        self.btn_play_pause.SetLabel("&Play")

    # ── Playback ──────────────────────────────────────────────────────────────

    def _on_play_pause(self, event):
        if self._playing:
            self.pause()
        else:
            self.play()

    def play(self, start_offset: float = None):
        if not self._current_file:
            wx.MessageBox("Load a file first.", "No file", wx.OK)
            return
        if start_offset is None:
            start_offset = self._position

        # Kill any existing process
        self._kill_ffplay()

        speed_str = self.speed_combo.GetValue()
        speed     = SPEED_MAP.get(speed_str, 1.0)
        vol       = self._volume

        cmd = [
            "ffplay",
            "-nodisp",          # audio-only display (no window)
            "-autoexit",
            "-loglevel", "quiet",
            "-ss", str(start_offset),
            "-af", f"volume={vol/100:.2f},atempo={speed:.2f}",
            self._current_file,
        ]

        try:
            self._ffplay_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._playing = True
            self._start_offset = start_offset
            self._play_start_time = time.monotonic()
            self.btn_play_pause.SetLabel("&Pause")
            self.status_label.SetLabel(f"Playing: {Path(self._current_file).name}")
            self._timer.Start(500)  # update every 500ms
        except FileNotFoundError:
            wx.MessageBox(
                "ffplay not found. Install ffmpeg to enable audio/video playback.\n"
                "(ffplay is included with most ffmpeg distributions)",
                "ffplay Not Found",
                wx.OK | wx.ICON_ERROR,
            )

    def pause(self):
        """Pause by recording position and killing ffplay."""
        if self._ffplay_proc and self._playing:
            # Record current position estimate
            elapsed = time.monotonic() - self._play_start_time
            self._position = self._start_offset + elapsed
            self._position = min(self._position, self._duration)
            self._kill_ffplay()
        self._playing = False
        self._timer.Stop()
        self.btn_play_pause.SetLabel("&Play")
        self.status_label.SetLabel("Paused.")

    def stop(self):
        self._kill_ffplay()
        self._playing = False
        self._position = 0.0
        self._timer.Stop()
        self.btn_play_pause.SetLabel("&Play")
        self.seek_slider.SetValue(0)
        self.lbl_position.SetLabel("0:00.00")
        self.status_label.SetLabel("Stopped." if self._current_file else "No file loaded.")

    def _kill_ffplay(self):
        if self._ffplay_proc:
            try:
                self._ffplay_proc.terminate()
                self._ffplay_proc.wait(timeout=2)
            except Exception:
                try:
                    self._ffplay_proc.kill()
                except Exception:
                    pass
            self._ffplay_proc = None

    def _on_stop(self, event):
        self.stop()

    def _on_timer(self, event):
        """Update position display every 500ms."""
        if not self._playing or not self._ffplay_proc:
            return

        # Check if ffplay finished
        if self._ffplay_proc.poll() is not None:
            self._playing = False
            self._position = 0.0
            self._timer.Stop()
            self.btn_play_pause.SetLabel("&Play")
            self.lbl_position.SetLabel("0:00.00")
            self.seek_slider.SetValue(0)
            self.status_label.SetLabel("Finished.")
            return

        elapsed  = time.monotonic() - self._play_start_time
        speed    = SPEED_MAP.get(self.speed_combo.GetValue(), 1.0)
        pos      = self._start_offset + elapsed * speed
        pos      = min(pos, self._duration)
        self._position = pos
        self.lbl_position.SetLabel(_secs_to_hms(pos))

        if self._duration > 0:
            pct = int(pos / self._duration * 1000)
            self.seek_slider.SetValue(pct)

    def _on_seek_slide(self, event):
        if self._duration <= 0:
            return
        pct = self.seek_slider.GetValue() / 1000.0
        new_pos = pct * self._duration
        self._position = new_pos
        self.lbl_position.SetLabel(_secs_to_hms(new_pos))
        if self._playing:
            self.play(start_offset=new_pos)

    def _seek_relative(self, delta: float):
        new_pos = max(0.0, min(self._duration, self._position + delta))
        self._position = new_pos
        self.lbl_position.SetLabel(_secs_to_hms(new_pos))
        if self._duration > 0:
            self.seek_slider.SetValue(int(new_pos / self._duration * 1000))
        if self._playing:
            self.play(start_offset=new_pos)

    def _on_vol_change(self, event):
        self._volume = self.vol_slider.GetValue()
        self.lbl_vol.SetLabel(f"{self._volume}%")
        if self._playing:
            # Restart with new volume
            self.play(start_offset=self._position)

    def _on_key(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_SPACE:
            self._on_play_pause(None)
        elif key == wx.WXK_LEFT:
            self._seek_relative(-5)
        elif key == wx.WXK_RIGHT:
            self._seek_relative(5)
        elif key == wx.WXK_UP:
            self.vol_slider.SetValue(min(150, self._volume + 5))
            self._on_vol_change(None)
        elif key == wx.WXK_DOWN:
            self.vol_slider.SetValue(max(0, self._volume - 5))
            self._on_vol_change(None)
        else:
            event.Skip()

    # ── File loading buttons ──────────────────────────────────────────────────

    def _on_browse(self, event):
        dlg = wx.FileDialog(
            self,
            message="Select audio or video file",
            wildcard="Media files (*.mp4;*.mp3;*.mov;*.avi;*.wav;*.m4a;*.webm)|*.mp4;*.mp3;*.mov;*.avi;*.wav;*.m4a;*.webm|All files (*.*)|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self.load_file(dlg.GetPath())
        dlg.Destroy()

    def _on_load_orig(self, event):
        if not self.project:
            wx.MessageBox("Open a project first.", "No Project", wx.OK)
            return
        path = self.project.get("video_path", "")
        if not path or not Path(path).exists():
            wx.MessageBox("Original video not found in project.", "Not Found", wx.OK | wx.ICON_WARNING)
            return
        self.load_file(path)

    def _on_load_dubbed(self, event):
        if not self.project:
            wx.MessageBox("Open a project first.", "No Project", wx.OK)
            return
        path = self.project.get("dubbed_video_path", "")
        if not path or not Path(path).exists():
            wx.MessageBox(
                "Dubbed video not found. Run Step 4 (Dub Video) first.",
                "Not Found", wx.OK | wx.ICON_WARNING,
            )
            return
        self.load_file(path)

    # ── Clip list playback ────────────────────────────────────────────────────

    def _on_play_clip(self, event=None):
        idx = self.clip_list.GetFirstSelected()
        if idx < 0:
            wx.MessageBox("Select a clip first.", "No Selection", wx.OK)
            return
        if not self.project:
            return

        did = self.clip_list.GetItemText(idx, 0)
        audio_files = self.project.get("generated_audio_files", [])
        af = next((a for a in audio_files if a["desc_id"] == did), None)
        if not af or not Path(af["audio_path"]).exists():
            wx.MessageBox(f"Audio file for {did} not found.", "Not Found", wx.OK | wx.ICON_WARNING)
            return

        self.load_file(af["audio_path"])
        self.play()

    def _on_preview_ctx(self, event):
        """Preview selected clip in context using ffplay mix."""
        idx = self.clip_list.GetFirstSelected()
        if idx < 0:
            wx.MessageBox("Select a clip first.", "No Selection", wx.OK)
            return
        if not self.project:
            return

        did = self.clip_list.GetItemText(idx, 0)
        desc_data = self.project.get("descriptions_data") or {}
        desc = next((d for d in desc_data.get("descriptions", []) if d["id"] == did), None)
        if not desc:
            return

        from gui.dialogs.preview_dialog import PreviewDialog
        dlg = PreviewDialog(self, desc, self.project)
        dlg.ShowModal()
        dlg.Destroy()
