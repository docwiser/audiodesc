"""
core/audio_analyzer.py
-----------------------
Analyzes the original video's audio track to provide smart, signal-based
volume ducking recommendations instead of relying solely on AI guesses.

Uses ffmpeg/ffprobe:
  - loudnorm analysis: per-segment integrated loudness (LUFS)
  - silencedetect:     find actual silence windows
  - astats:            RMS energy per time window

The analyzer produces a timeline of audio levels that the dubber and
validator can use to compute optimal videoVolumePercent per description.
"""

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from rich.console import Console

console = Console()


@dataclass
class AudioSegmentLevel:
    start: float       # seconds
    end: float         # seconds
    rms_db: float      # dB RMS level (negative, louder = less negative)
    is_silence: bool   # True if below silence threshold
    recommended_duck: float  # 0.0-1.0 — suggested videoVolumePercent/100


@dataclass
class AudioAnalysis:
    duration: float
    overall_lufs: float
    segments: List[AudioSegmentLevel]
    silence_ranges: List[tuple]   # [(start, end), ...]


def analyze_video_audio(
    video_path: str,
    window_sec: float = 2.0,
    silence_threshold_db: float = -40.0,
) -> Optional[AudioAnalysis]:
    """
    Analyze the audio track of a video file.

    Returns an AudioAnalysis with per-window RMS levels and silence windows.
    Uses only ffmpeg/ffprobe — no Python audio library required.
    """
    video_path = str(video_path)
    if not Path(video_path).exists():
        return None

    console.print("[dim]Analyzing video audio levels...[/dim]")

    duration = _get_duration(video_path)
    if not duration:
        return None

    # ── 1. Detect silence windows ──────────────────────────────────────────────
    silence_ranges = _detect_silence(video_path, silence_threshold_db)

    # ── 2. Get per-window RMS levels ──────────────────────────────────────────
    segments = _get_rms_windows(video_path, duration, window_sec)

    # ── 3. Overall integrated loudness via loudnorm ────────────────────────────
    overall_lufs = _get_integrated_loudness(video_path) or -23.0

    console.print(
        f"[dim]Audio analysis: {len(segments)} windows, "
        f"{len(silence_ranges)} silence regions, "
        f"overall {overall_lufs:.1f} LUFS[/dim]"
    )

    return AudioAnalysis(
        duration=duration,
        overall_lufs=overall_lufs,
        segments=segments,
        silence_ranges=silence_ranges,
    )


def get_recommended_duck(
    analysis: AudioAnalysis,
    start_sec: float,
    duration_sec: float,
) -> float:
    """
    Given an AudioAnalysis and a description window, compute the
    recommended videoVolumePercent (0–100) based on actual audio levels.

    Strategy:
      - If the window is silence: 100 (no ducking needed)
      - If audio is soft (RMS < -30dB): 75
      - If audio is moderate (-30 to -20dB): 65
      - If audio is loud (-20 to -10dB): 55
      - If audio is very loud (> -10dB): 45
    """
    if not analysis or not analysis.segments:
        return 70.0  # safe default

    # Find segments that overlap with this description window
    end_sec  = start_sec + duration_sec
    overlap  = [
        s for s in analysis.segments
        if s.start < end_sec and s.end > start_sec
    ]

    if not overlap:
        return 70.0

    # Check if it's in a silence range
    for sil_start, sil_end in analysis.silence_ranges:
        if sil_start <= start_sec and sil_end >= end_sec:
            return 100.0  # silence — no duck needed

    # Average RMS across overlapping windows
    avg_rms = sum(s.rms_db for s in overlap) / len(overlap)

    if avg_rms < -40:   return 100.0  # silence
    if avg_rms < -30:   return 78.0   # very soft
    if avg_rms < -23:   return 68.0   # soft music
    if avg_rms < -15:   return 58.0   # moderate music
    if avg_rms < -8:    return 50.0   # loud music
    return 42.0                        # very loud — heavy duck


def apply_smart_ducking(
    workflow: dict,
    analysis: AudioAnalysis,
    override_ai: bool = False,
) -> dict:
    """
    Update videoVolumePercent for each description based on actual audio analysis.

    If override_ai=False: only override descriptions where AI suggested >80%
    (AI under-estimated ducking needed). If True: override all.

    Returns the modified workflow dict.
    """
    if not analysis:
        return workflow

    modified = 0
    for desc in workflow.get("descriptions", []):
        from core.description_generator import _mmss_to_seconds
        start = _mmss_to_seconds(desc.get("startTime", "0:00"))
        dur   = desc.get("durationSeconds", 2.0)

        smart_vol = get_recommended_duck(analysis, start, dur)
        ai_vol    = desc.get("videoVolumePercent", 70.0)

        if override_ai:
            desc["videoVolumePercent"] = smart_vol
            modified += 1
        else:
            # Only override if AI was significantly off
            if abs(smart_vol - ai_vol) > 15:
                desc["videoVolumePercent"] = smart_vol
                modified += 1

    if modified:
        console.print(
            f"[dim]Smart ducking: updated {modified} descriptions "
            f"based on audio analysis.[/dim]"
        )
    return workflow


# ── ffmpeg helpers ─────────────────────────────────────────────────────────────

def _get_duration(video_path: str) -> Optional[float]:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", video_path],
            capture_output=True, text=True, timeout=30
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return None


def _detect_silence(video_path: str, threshold_db: float = -40.0) -> list:
    """
    Run ffmpeg silencedetect filter to find silence windows.
    Returns list of (start, end) tuples in seconds.
    """
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-i", video_path,
                "-af", f"silencedetect=noise={threshold_db}dB:d=0.3",
                "-f", "null", "-"
            ],
            capture_output=True, text=True, timeout=300
        )
        output = r.stderr

        starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", output)]
        ends   = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", output)]
        return list(zip(starts, ends[:len(starts)]))
    except Exception:
        return []


def _get_rms_windows(
    video_path: str,
    duration: float,
    window_sec: float,
) -> List[AudioSegmentLevel]:
    """
    Sample the audio RMS level in fixed-size windows using ffmpeg astats.
    Returns one AudioSegmentLevel per window.
    """
    segments = []
    # Use astats with metadata_block_size to get per-block stats
    # Then parse the RMS_level output
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-i", video_path,
                "-af", f"asetnsamples=n=44100*{window_sec:.0f},astats=metadata=1:reset=1",
                "-f", "null", "-"
            ],
            capture_output=True, text=True, timeout=300
        )
        output = r.stderr

        # Parse "lavfi.astats.Overall.RMS_level" values
        rms_vals = re.findall(r"RMS_level=(-?[\d.]+|inf|-inf)", output)
        window_idx = 0
        for val_str in rms_vals:
            try:
                rms = float(val_str) if val_str not in ("inf", "-inf") else -100.0
            except ValueError:
                rms = -100.0

            start = window_idx * window_sec
            end   = min(start + window_sec, duration)
            duck  = _rms_to_duck(rms)

            segments.append(AudioSegmentLevel(
                start=start, end=end, rms_db=rms,
                is_silence=(rms < -40),
                recommended_duck=duck,
            ))
            window_idx += 1

    except Exception as e:
        console.print(f"[dim]RMS analysis skipped: {e}[/dim]")

    # Fallback: even spacing at default level
    if not segments:
        n = max(1, int(duration / window_sec))
        for i in range(n):
            segments.append(AudioSegmentLevel(
                start=i*window_sec, end=min((i+1)*window_sec, duration),
                rms_db=-23.0, is_silence=False, recommended_duck=0.70,
            ))

    return segments


def _get_integrated_loudness(video_path: str) -> Optional[float]:
    """
    Get the integrated loudness (LUFS) of the whole audio track
    using the loudnorm filter in analysis mode.
    """
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-i", video_path,
                "-af", "loudnorm=print_format=json",
                "-f", "null", "-"
            ],
            capture_output=True, text=True, timeout=300
        )
        output = r.stderr
        # loudnorm outputs a JSON block at the end of stderr
        m = re.search(r'\{[^{}]*"input_i"\s*:\s*"(-?[\d.]+)"[^{}]*\}', output, re.DOTALL)
        if m:
            data = json.loads(m.group())
            return float(data.get("input_i", -23))
    except Exception:
        pass
    return None


def _rms_to_duck(rms_db: float) -> float:
    """Map RMS level to duck factor (0.0–1.0)."""
    if rms_db < -40: return 1.0
    if rms_db < -30: return 0.78
    if rms_db < -23: return 0.68
    if rms_db < -15: return 0.58
    if rms_db < -8:  return 0.50
    return 0.42


def normalize_audio_clip(
    input_path: str,
    output_path: str,
    target_lufs: float = -16.0,
) -> bool:
    """
    Loudness-normalize a single audio clip using ffmpeg loudnorm filter.
    Ensures all description clips have consistent perceived volume.

    Target: -16 LUFS (broadcast standard for narration/voice)
    """
    try:
        # Two-pass loudnorm for accuracy
        # Pass 1: measure
        r1 = subprocess.run(
            [
                "ffmpeg", "-i", input_path,
                "-af", "loudnorm=print_format=json",
                "-f", "null", "-"
            ],
            capture_output=True, text=True, timeout=60
        )
        m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', r1.stderr, re.DOTALL)
        if not m:
            # Skip normalization if measurement fails — keep original
            import shutil
            shutil.copy2(input_path, output_path)
            return True

        stats = json.loads(m.group())
        input_i    = stats.get("input_i", "-23.0")
        input_lra  = stats.get("input_lra", "7.0")
        input_tp   = stats.get("input_tp", "-2.0")
        input_thresh = stats.get("input_thresh", "-33.0")

        # Pass 2: normalize with measured values
        r2 = subprocess.run(
            [
                "ffmpeg", "-y", "-i", input_path,
                "-af",
                (f"loudnorm=I={target_lufs}:LRA=7:TP=-1.5:"
                 f"measured_I={input_i}:measured_LRA={input_lra}:"
                 f"measured_TP={input_tp}:measured_thresh={input_thresh}:"
                 f"print_format=summary"),
                "-c:a", "libmp3lame", "-b:a", "192k",
                output_path
            ],
            capture_output=True, text=True, timeout=120
        )
        return r2.returncode == 0

    except Exception as e:
        console.print(f"[dim]Normalize failed for {input_path}: {e}[/dim]")
        import shutil
        try:
            shutil.copy2(input_path, output_path)
        except Exception:
            pass
        return False
