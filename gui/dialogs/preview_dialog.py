"""
gui/dialogs/preview_dialog.py
------------------------------
Preview a description in context — mixes ±2s of original video audio
with the description clip and plays it via ffplay subprocess.
"""

import wx
import subprocess
import tempfile
import threading
import os
from pathlib import Path


class PreviewDialog(wx.Dialog):
    def __init__(self, parent, desc: dict, project: dict):
        super().__init__(
            parent,
            title=f"Preview — {desc.get('id','')}",
            size=(500, 360),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        self.desc    = desc
        self.project = project
        self._proc   = None
        self._tmp    = None
        self._build_ui()
        self._load_info()

    def _build_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Info
        self.info_ctrl = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 100)
        )
        self.info_ctrl.SetName("Preview information")
        sizer.Add(self.info_ctrl, 0, wx.EXPAND | wx.ALL, 8)

        # Volume control
        vol_row = wx.BoxSizer(wx.HORIZONTAL)
        vol_row.Add(wx.StaticText(self, label="Video &volume during preview:"), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.vol_spin = wx.SpinCtrl(self, min=0, max=100,
                                     value=str(int(self.desc.get("videoVolumePercent", 70))))
        self.vol_spin.SetName("Video volume for preview")
        vol_row.Add(self.vol_spin, 0)
        sizer.Add(vol_row, 0, wx.LEFT | wx.BOTTOM, 8)

        # Pad control
        pad_row = wx.BoxSizer(wx.HORIZONTAL)
        pad_row.Add(wx.StaticText(self, label="Context &padding (seconds before/after):"), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.pad_spin = wx.SpinCtrlDouble(self, min=0.5, max=10.0, initial=2.0, inc=0.5)
        self.pad_spin.SetName("Context padding seconds")
        pad_row.Add(self.pad_spin, 0)
        sizer.Add(pad_row, 0, wx.LEFT | wx.BOTTOM, 8)

        # Description text (read-only)
        sizer.Add(wx.StaticText(self, label="Description text:"), 0, wx.LEFT, 8)
        self.desc_text = wx.TextCtrl(
            self, value=self.desc.get("descriptionText", ""),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP,
            size=(-1, 60),
        )
        self.desc_text.SetName("Description text preview")
        sizer.Add(self.desc_text, 0, wx.EXPAND | wx.ALL, 8)

        # Buttons
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_play   = wx.Button(self, label="▶  &Play Preview")
        self.btn_stop   = wx.Button(self, label="■  &Stop")
        btn_close       = wx.Button(self, wx.ID_CANCEL, label="&Close")
        self.btn_play.SetHelpText("Build and play the context preview using ffplay")
        self.btn_stop.SetHelpText("Stop playback")
        self.btn_stop.Enable(False)
        btn_row.Add(self.btn_play,  0, wx.RIGHT, 6)
        btn_row.Add(self.btn_stop,  0, wx.RIGHT, 6)
        btn_row.Add(btn_close,      0)
        sizer.Add(btn_row, 0, wx.ALL, 8)

        # Status
        self.status_lbl = wx.StaticText(self, label="")
        self.status_lbl.SetName("Preview status")
        sizer.Add(self.status_lbl, 0, wx.ALL, 8)

        self.SetSizer(sizer)

        self.btn_play.Bind(wx.EVT_BUTTON, self._on_play)
        self.btn_stop.Bind(wx.EVT_BUTTON, self._on_stop)
        self.Bind(wx.EVT_CLOSE, self._on_close)

    def _load_info(self):
        d = self.desc
        text = (
            f"ID: {d.get('id','')}  |  Time: {d.get('startTime','')} → {d.get('endTime','')}\n"
            f"Gap: {d.get('durationSeconds',0):.2f}s  |  Audio context: {d.get('audioContext','')}\n"
            f"Video vol: {d.get('videoVolumePercent',70):.0f}%  |  "
            f"Speech rate: {d.get('speechRateModifier','+0%')}\n"
            f"Priority: {d.get('priority','')}  |  Format: {d.get('format','')}"
        )
        self.info_ctrl.SetValue(text)

    def _on_play(self, event):
        audio_files = self.project.get("generated_audio_files", [])
        af = next((a for a in audio_files if a["desc_id"] == self.desc["id"]), None)
        if not af or not Path(af["audio_path"]).exists():
            wx.MessageBox(
                f"Audio file for {self.desc['id']} not found.\n"
                "Generate audio (Step 3) first.",
                "Not Found", wx.OK | wx.ICON_WARNING,
            )
            return

        video_path = self.project.get("video_path", "")
        if not video_path or not Path(video_path).exists():
            # Fall back to clip-only playback
            self._play_clip_only(af["audio_path"])
            return

        # Build mixed preview
        self.btn_play.Enable(False)
        self.status_lbl.SetLabel("Building preview mix…")

        desc = self.desc
        from core.description_generator import _mmss_to_seconds
        start_s = _mmss_to_seconds(desc.get("startTime", "0:00"))
        dur_s   = desc.get("durationSeconds", 3.0)
        vol     = self.vol_spin.GetValue() / 100.0
        pad     = self.pad_spin.GetValue()

        prev_start = max(0.0, start_s - pad)
        prev_dur   = dur_s + pad * 2
        delay_ms   = int((start_s - prev_start) * 1000)

        def _do():
            tmp = tempfile.mktemp(suffix="_preview.mp3")
            self._tmp = tmp
            fc = (
                f"[0:a]atrim=start={prev_start:.3f}:duration={prev_dur:.3f},"
                f"asetpts=PTS-STARTPTS,volume={vol:.3f}[orig];"
                f"[1:a]adelay={delay_ms}:all=1[desc];"
                f"[orig][desc]amix=inputs=2:duration=first:normalize=0[out]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", af["audio_path"],
                "-filter_complex", fc,
                "-map", "[out]",
                "-c:a", "libmp3lame", "-b:a", "192k",
                tmp,
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                wx.CallAfter(self.status_lbl.SetLabel, "Mix failed — playing clip only.")
                wx.CallAfter(self._play_clip_only, af["audio_path"])
                wx.CallAfter(self.btn_play.Enable, True)
                return

            wx.CallAfter(self.status_lbl.SetLabel, f"Playing {prev_dur:.1f}s preview…")
            wx.CallAfter(self._play_file, tmp)

        threading.Thread(target=_do, daemon=True).start()

    def _play_file(self, path: str):
        self._stop_proc()
        try:
            self._proc = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
            )
            self.btn_stop.Enable(True)
            self.btn_play.Enable(True)

            def _wait():
                self._proc.wait()
                wx.CallAfter(self.status_lbl.SetLabel, "Playback finished.")
                wx.CallAfter(self.btn_stop.Enable, False)
                # Clean temp
                try:
                    if self._tmp and Path(self._tmp).exists():
                        os.unlink(self._tmp)
                        self._tmp = None
                except Exception:
                    pass

            threading.Thread(target=_wait, daemon=True).start()
        except FileNotFoundError:
            wx.MessageBox(
                "ffplay not found. Install ffmpeg to enable audio preview.",
                "ffplay Not Found",
                wx.OK | wx.ICON_ERROR,
            )
            self.btn_play.Enable(True)

    def _play_clip_only(self, path: str):
        self._play_file(path)

    def _on_stop(self, event):
        self._stop_proc()
        self.status_lbl.SetLabel("Stopped.")
        self.btn_stop.Enable(False)

    def _stop_proc(self):
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    def _on_close(self, event):
        self._stop_proc()
        try:
            if self._tmp and Path(self._tmp).exists():
                os.unlink(self._tmp)
        except Exception:
            pass
        event.Skip()
