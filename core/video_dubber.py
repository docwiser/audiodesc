"""
core/video_dubber.py
---------------------
Mixes audio description clips into the source video.

ARCHITECTURE — Two-pass approach (reliable for any number of clips):
  Pass 1: Merge ALL description audio clips into a single combined track.
          Each clip is positioned via adelay:all=1 on a silent base.
          amix only ever sees N desc clips (no video audio) — avoids the
          ffmpeg amix reliability issue with 80+ mixed inputs.

  Pass 2: Mix the combined desc track into the video using only 2 inputs:
          [video_audio] + [combined_desc_track]
          Volume ducking via sendcmd file on the video audio stream.
          amix=inputs=2 — always reliable, no input count limits.

  Progress: live bar via ffmpeg -progress pipe on Pass 2.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import (
    BarColumn, Progress, TaskProgressColumn,
    TextColumn, TimeElapsedColumn,
)

from db import database as db

console = Console()


# ── Time utilities ─────────────────────────────────────────────────────────────

def _time_to_seconds(time_str: str) -> float:
    """
    Parse timestamps. Delegates to _mmss_to_seconds which handles:
      MM:SS  — Gemini native format (e.g. "1:30", "34:03", "129:45")
      HH:MM:SS — legacy format from old data
    """
    from core.description_generator import _mmss_to_seconds
    return _mmss_to_seconds(time_str)


def _seconds_to_hms(s: float) -> str:
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:06.3f}"


def _get_video_duration(video_path: str) -> float:
    """Get exact video duration in seconds via ffprobe."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", video_path],
            capture_output=True, text=True, timeout=30,
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def _escape_fc(path: str) -> str:
    """Escape a path for use inside an ffmpeg -filter_complex string."""
    return path.replace("\\", "/").replace("'", "\\'").replace(":", "\\:")


# ── Timestamp auto-fix ─────────────────────────────────────────────────────────

def _fix_timestamps(segments: list, video_duration: float) -> list:
    """
    Detect and fix AI-generated timestamps that exceed the video duration.

    Gemini sometimes generates timestamps for a 4-minute video as if it
    were 4 hours (e.g. 03:50:00 for a 240-second clip). We rescale all
    timestamps proportionally so they fit within the actual video length.
    """
    if not segments or video_duration <= 0:
        return segments

    max_start = max(seg["start"] for seg in segments)
    if max_start <= video_duration:
        return segments  # Already fine

    scale   = video_duration / max_start
    n_bad   = sum(1 for s in segments if s["start"] > video_duration)
    console.print(
        f"[yellow]⚠️  Auto-fix: {n_bad}/{len(segments)} timestamps exceeded "
        f"video duration ({video_duration:.0f}s). Rescaling by {scale:.4f}.[/yellow]"
    )

    fixed = []
    for seg in segments:
        ns = dict(seg)
        # Clamp start: last description must start at least 0.5s before video end
        ns["start"] = round(min(seg["start"] * scale, video_duration - 0.5), 3)
        # Clamp duration so end never exceeds video
        ns["duration"] = round(
            min(seg["duration"] * scale, video_duration - ns["start"] - 0.05),
            3
        )
        if ns["duration"] <= 0:
            ns["duration"] = 0.5
        fixed.append(ns)
    return fixed


# ── Segment collection ─────────────────────────────────────────────────────────

def _collect_segments(project: dict) -> list:
    """
    Return list of dicts for each description that has an audio file on disk.
    Timestamps are raw (not yet rescaled).
    """
    descs     = project.get("descriptions_data", {}).get("descriptions", [])
    audio_map = {af["desc_id"]: af
                 for af in project.get("generated_audio_files", [])}
    segments  = []
    for desc in descs:
        did = desc["id"]
        if did not in audio_map:
            continue
        ap = audio_map[did]["audio_path"]
        if not Path(ap).exists():
            console.print(f"[yellow]⚠  Audio missing for {did} — skipped.[/yellow]")
            continue
        segments.append({
            "desc_id":    did,
            "start":      _time_to_seconds(desc["startTime"]),
            "duration":   float(desc.get("durationSeconds", 3.0)),
            "vid_vol":    float(desc.get("videoVolumePercent", 80)) / 100.0,
            "desc_vol":   float(desc.get("descriptionVolumePercent", 100)) / 100.0,
            "fade_in":    float(desc.get("fadeInMs", 300)) / 1000.0,
            "fade_out":   float(desc.get("fadeOutMs", 400)) / 1000.0,
            "audio_path": ap,
        })
    return segments


# ── Pass 1: build combined description audio track ────────────────────────────

def _build_desc_track(segments: list, output_wav: str, total_duration: float) -> bool:
    """
    Merge all description clips into a single WAV file with silence between.

    Uses a silent base track (anullsrc) + adelay:all=1 per clip, then amix.
    amix only mixes the desc clips here — NO video audio involved.
    This avoids the N+1 input problem; amix just needs to handle N desc clips.

    For very large N (>50), splits into batches of 50 and merges iteratively.
    """
    if not segments:
        return False

    MAX_BATCH = 48   # stay well under ffmpeg's practical amix limit

    if len(segments) <= MAX_BATCH:
        return _amix_batch(segments, output_wav, total_duration)

    # ── Batch processing for large sets ───────────────────────────────────────
    console.print(f"[dim]Large set ({len(segments)} clips) — batching in groups of {MAX_BATCH}...[/dim]")

    batch_files = []
    batches = [segments[i:i+MAX_BATCH]
               for i in range(0, len(segments), MAX_BATCH)]

    for idx, batch in enumerate(batches):
        tmp = tempfile.mktemp(suffix=f"_batch{idx}.wav")
        ok = _amix_batch(batch, tmp, total_duration)
        if not ok:
            for f in batch_files:
                _try_delete(f)
            return False
        batch_files.append(tmp)
        console.print(f"[dim]  Batch {idx+1}/{len(batches)} done.[/dim]")

    # Merge all batch files into final output (simple amix of batch files)
    ok = _merge_wav_files(batch_files, output_wav)
    for f in batch_files:
        _try_delete(f)
    return ok


def _amix_batch(segments: list, output_wav: str, total_duration: float) -> bool:
    """
    Run ffmpeg to mix one batch of segments into a WAV file.
    Uses a silent anullsrc base + adelay:all=1 per clip.
    """
    # Silent base long enough for the last clip to finish
    last_end    = max(seg["start"] + seg["duration"] for seg in segments)
    base_dur    = max(last_end + 1.0, total_duration)

    inputs      = ["-f", "lavfi", "-i",
                   f"anullsrc=r=44100:cl=stereo:d={base_dur:.3f}"]
    fc_parts    = []
    mix_labels  = ["[base]"]

    # Label the silent base
    fc_parts.append("[0:a]anull[base]")

    for i, seg in enumerate(segments, start=1):
        inputs.extend(["-i", seg["audio_path"]])
        delay_ms = int(seg["start"] * 1000)
        vol      = seg["desc_vol"]
        lbl      = f"[dc{i}]"
        # :all=1 → delay ALL channels, not just channel 0
        fc_parts.append(
            f"[{i}:a]adelay={delay_ms}:all=1,volume={vol:.3f}{lbl}"
        )
        mix_labels.append(lbl)

    n = len(mix_labels)
    fc_parts.append(
        f"{''.join(mix_labels)}amix=inputs={n}:duration=longest:normalize=0[out]"
    )

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", ";".join(fc_parts),
        "-map", "[out]",
        "-c:a", "pcm_s16le",   # uncompressed WAV — fast, no quality loss
        output_wav,
    ]

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        console.print(f"[red]Pass-1 batch failed:\n{r.stderr[-600:]}[/red]")
    return r.returncode == 0


def _merge_wav_files(wav_files: list, output_wav: str) -> bool:
    """Merge multiple WAV files by mixing them (simple 2-at-a-time amix chain)."""
    if len(wav_files) == 1:
        shutil.copy2(wav_files[0], output_wav)
        return True

    inputs     = []
    mix_labels = []
    fc_parts   = []

    for i, f in enumerate(wav_files):
        inputs.extend(["-i", f])
        lbl = f"[w{i}]"
        fc_parts.append(f"[{i}:a]anull{lbl}")
        mix_labels.append(lbl)

    n = len(mix_labels)
    fc_parts.append(
        f"{''.join(mix_labels)}amix=inputs={n}:duration=longest:normalize=0[out]"
    )

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", ";".join(fc_parts),
        "-map", "[out]",
        "-c:a", "pcm_s16le",
        output_wav,
    ]

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        console.print(f"[red]Batch-merge failed:\n{r.stderr[-400:]}[/red]")
    return r.returncode == 0


# ── sendcmd writer ─────────────────────────────────────────────────────────────

def _write_sendcmd(segments: list) -> str:
    """
    Write ffmpeg sendcmd volume-automation script to a temp file.
    File-based approach has no length limit regardless of how many segments.
    """
    lines = []
    for seg in segments:
        start      = seg["start"]
        end        = start + seg["duration"]
        vol        = seg["vid_vol"]
        ramp_start = max(0.0, start - seg["fade_in"])
        ramp_end   = end + seg["fade_out"]
        lines.append(f"{ramp_start:.3f} volume volume 1.0;")
        lines.append(f"{start:.3f} volume volume {vol:.3f};")
        lines.append(f"{end:.3f} volume volume {vol:.3f};")
        lines.append(f"{ramp_end:.3f} volume volume 1.0;")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write("\n".join(lines))
        return f.name


# ── Pass 2: mix combined desc track into video ────────────────────────────────

def _run_pass2_with_progress(
    video_path: str,
    desc_wav: str,
    sendcmd_path: Optional[str],
    output_path: str,
    video_duration: float,
) -> tuple[bool, str]:
    """
    Pass 2: final mix.
    Inputs: [0] video, [1] combined desc WAV
    Filter: duck video audio via sendcmd, then amix=inputs=2
    Progress: live bar via ffmpeg -progress pipe
    Returns (success, stderr_tail)
    """
    if sendcmd_path:
        esc = _escape_fc(sendcmd_path)
        fc  = (
            f"[0:a]asendcmd=f='{esc}',volume=1.0[ducked];"
            f"[ducked][1:a]amix=inputs=2:duration=first:normalize=0[mixed]"
        )
    else:
        fc  = "[0:a][1:a]amix=inputs=2:duration=first:normalize=0[mixed]"

    cmd = [
        "ffmpeg", "-y",
        "-progress", "pipe:2",   # send progress key=value to stderr
        "-nostats",
        "-i", video_path,
        "-i", desc_wav,
        "-filter_complex", fc,
        "-map", "0:v",
        "-map", "[mixed]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        output_path,
    ]

    stderr_buf = []

    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=38),
        TaskProgressColumn(),
        TextColumn("[cyan]{task.fields[info]}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as pb:
        task = pb.add_task("🎬 Dubbing video", total=100, info="starting…")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True, bufsize=1,
            encoding="utf-8", errors="replace",
        )

        def _read():
            t_re  = re.compile(r"out_time_ms=(\d+)")
            sp_re = re.compile(r"speed=([\d.]+)x")
            speed = ""
            for line in proc.stderr:
                stderr_buf.append(line)
                m = t_re.search(line)
                if m:
                    elapsed = int(m.group(1)) / 1_000_000
                    pct     = min(99.0, elapsed / video_duration * 100) if video_duration else 0
                    elapsed_hms = _seconds_to_hms(elapsed)[:8]
                    total_hms   = _seconds_to_hms(video_duration)[:8]
                    pb.update(task, completed=pct,
                               info=f"{elapsed_hms} / {total_hms}{speed}")
                ms = sp_re.search(line)
                if ms:
                    speed = f"  {ms.group(1)}x"

        t = threading.Thread(target=_read, daemon=True)
        t.start()
        proc.wait()
        t.join(timeout=5)

        if proc.returncode == 0:
            pb.update(task, completed=100, info="✅ done")
        else:
            pb.update(task, completed=0, info="❌ failed")

    return proc.returncode == 0, "".join(stderr_buf[-60:])


# ── Main public entry ──────────────────────────────────────────────────────────

def dub_video_ffmpeg(project_id: str, output_filename: Optional[str] = None) -> str:
    """
    Dub a video with audio descriptions. Two-pass ffmpeg approach:

    Pass 1 — Build combined description audio WAV
              (all clips positioned via adelay, mixed into one file)
    Pass 2 — Mix combined WAV into video
              (2-input amix only, volume ducking, progress bar)
    """
    project = db.get_project(project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found.")

    video_path = project.get("video_path")
    if not video_path or not Path(video_path).exists():
        raise FileNotFoundError(f"Source video not found: {video_path}")

    # ── Get real video duration ────────────────────────────────────────────────
    console.print("[dim]Probing video duration...[/dim]")
    video_duration = _get_video_duration(video_path)
    if not video_duration:
        video_duration = float(
            project.get("descriptions_data", {})
                   .get("videoMetadata", {})
                   .get("totalDurationSeconds", 300)
        )
    console.print(
        f"   Duration: [cyan]{_seconds_to_hms(video_duration)[:8]}[/cyan]"
        f"  ({video_duration:.1f}s)"
    )

    # ── Collect & validate segments ────────────────────────────────────────────
    raw = _collect_segments(project)
    if not raw:
        console.print("[yellow]No audio segments — copying original.[/yellow]")
        exports_dir = db.get_exports_dir(project_id)
        out = str(exports_dir / Path(video_path).name)
        shutil.copy2(video_path, out)
        return out

    segments = _fix_timestamps(raw, video_duration)

    exports_dir = db.get_exports_dir(project_id)
    if not output_filename:
        output_filename = Path(video_path).stem + "_with_descriptions.mp4"
    output_path = str(exports_dir / output_filename)

    console.print(
        f"\n[bold cyan]🎬 Dubbing video — {len(segments)} descriptions[/bold cyan]"
    )

    # ── Temp files ─────────────────────────────────────────────────────────────
    tmp_desc_wav  = tempfile.mktemp(suffix="_desc_track.wav")
    sendcmd_path  = _write_sendcmd(segments)

    try:
        # ── Pass 1: build combined description track ───────────────────────────
        console.print(
            f"[dim]Pass 1/2 — merging {len(segments)} clips into combined track...[/dim]"
        )
        p1_ok = _build_desc_track(segments, tmp_desc_wav, video_duration)
        if not p1_ok:
            raise RuntimeError(
                "Pass 1 failed: could not merge description audio clips.\n"
                "Check that all audio files in the project audio/ folder are valid."
            )
        size_kb = Path(tmp_desc_wav).stat().st_size // 1024
        console.print(f"[dim]Pass 1 done — {size_kb} KB combined track.[/dim]")

        # ── Pass 2: mix into video with progress bar ───────────────────────────
        console.print("[dim]Pass 2/2 — mixing into video...[/dim]\n")
        p2_ok, stderr = _run_pass2_with_progress(
            video_path, tmp_desc_wav, sendcmd_path,
            output_path, video_duration,
        )

        if not p2_ok:
            # Retry without sendcmd ducking
            console.print(
                f"[yellow]⚠  Volume-ducking mix failed — retrying without ducking...[/yellow]"
            )
            console.print(f"[dim]{stderr[-300:]}[/dim]")
            p2_ok, stderr2 = _run_pass2_with_progress(
                video_path, tmp_desc_wav, None,
                output_path, video_duration,
            )
            if not p2_ok:
                raise RuntimeError(
                    f"Pass 2 failed.\n{stderr2[-500:]}"
                )
            console.print("[dim](No volume ducking — mix successful)[/dim]")

    finally:
        _try_delete(tmp_desc_wav)
        _try_delete(sendcmd_path)

    db.update_project(project_id, {
        "dubbed_video_path": output_path,
        "stage": "dubbed",
    })

    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    console.print(f"\n[bold green]✅ Done![/bold green]  "
                  f"[cyan]{Path(output_path).name}[/cyan]  ({size_mb:.1f} MB)")
    return output_path


# ── moviepy fallback ───────────────────────────────────────────────────────────

def dub_video(project_id: str, output_filename: Optional[str] = None) -> str:
    """Fallback using moviepy (pure Python, slower but no ffmpeg filter limits)."""
    try:
        from moviepy import VideoFileClip, AudioFileClip, CompositeAudioClip
    except ImportError:
        from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip

    project    = db.get_project(project_id)
    video_path = project.get("video_path")
    if not video_path or not Path(video_path).exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    video_duration = _get_video_duration(video_path) or 300.0
    segments       = _fix_timestamps(_collect_segments(project), video_duration)
    exports_dir    = db.get_exports_dir(project_id)
    if not output_filename:
        output_filename = Path(video_path).stem + "_with_descriptions.mp4"
    output_path = str(exports_dir / output_filename)

    console.print(f"[bold cyan]🎬 moviepy dub — {len(segments)} clips[/bold cyan]")
    video       = VideoFileClip(str(video_path))
    audio_clips = [video.audio] if video.audio else []
    for seg in segments:
        if seg["start"] < video.duration:
            audio_clips.append(
                AudioFileClip(seg["audio_path"]).with_start(seg["start"])
            )

    (video.with_audio(CompositeAudioClip(audio_clips)
                      if len(audio_clips) > 1 else audio_clips[0])
         .write_videofile(output_path, codec="libx264",
                          audio_codec="aac", logger="bar",
                          temp_audiofile=str(exports_dir / "_tmp_audio.m4a")))
    video.close()

    db.update_project(project_id, {"dubbed_video_path": output_path, "stage": "dubbed"})
    console.print(f"[bold green]✅[/bold green] [cyan]{Path(output_path).name}[/cyan]")
    return output_path


# ── helpers ────────────────────────────────────────────────────────────────────

def _try_delete(path: str):
    try:
        if path and Path(path).exists():
            os.unlink(path)
    except Exception:
        pass
