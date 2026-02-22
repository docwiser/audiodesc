"""
export/export_manager.py
-------------------------
Central export hub. Allows the user to choose what to export
and packages everything into a zip archive or individual files.

Export options:
- Dubbed video (audio descriptions embedded)
- Original video + separate audio tracks
- Description audio track only (all clips merged, timeline-accurate)
- Individual description audio clips
- Subtitle files: VTT, SRT, JSON, TXT, CSV
- Mixed (ZIP of user-selected items)
"""

import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from rich.console import Console
from rich.table import Table

from db import database as db
from export import subtitle_exporter

console = Console()


def export_menu(project_id: str):
    """Interactive export menu. Let the user choose exactly what to export."""
    import questionary

    project = db.get_project(project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found.")

    console.print(f"\n[bold]📦 Export — [cyan]{project['name']}[/cyan][/bold]")
    console.print(f"   Stage: [yellow]{project.get('stage', 'unknown')}[/yellow]")

    has_video       = bool(project.get("video_path") and Path(project["video_path"]).exists())
    has_descriptions = bool(project.get("descriptions_data"))
    has_audio       = bool(project.get("generated_audio_files"))
    dubbed_path     = project.get("dubbed_video_path", "")
    has_dubbed      = bool(dubbed_path and Path(dubbed_path).exists())

    choices = []
    if has_dubbed:
        choices.append(questionary.Choice("🎬 Dubbed video (descriptions baked in)", "dubbed_video"))
    if has_video and has_audio:
        choices.append(questionary.Choice("🎬 Original video + separate AD audio track", "video_with_ad_track"))
    if has_audio:
        choices.append(questionary.Choice("🔊 Full AD audio track (timeline-accurate merged MP3)", "full_ad_audio"))
        choices.append(questionary.Choice("🎵 Individual description audio clips", "individual_clips"))
    if has_descriptions:
        choices.append(questionary.Choice("📄 VTT subtitle file",             "vtt"))
        choices.append(questionary.Choice("📄 SRT subtitle file",             "srt"))
        choices.append(questionary.Choice("📄 JSON (full workflow)",          "json_full"))
        choices.append(questionary.Choice("📄 JSON (descriptions only)",      "json_descriptions"))
        choices.append(questionary.Choice("📄 JSON (simple: id/time/text)",   "json_simple"))
        choices.append(questionary.Choice("📄 Plain text script",             "txt"))
        choices.append(questionary.Choice("📄 CSV spreadsheet",               "csv"))
        choices.append(questionary.Choice("📄 Individual description scripts (.txt each)", "scripts"))

    choices.append(questionary.Choice("📦 ZIP — pack all selected exports", "zip_all"))
    choices.append(questionary.Choice("❌ Cancel", "cancel"))

    if not choices:
        console.print("[red]Nothing to export yet. Complete pipeline steps first.[/red]")
        return

    selected = questionary.checkbox("Select what to export:", choices=choices).ask()

    if not selected or "cancel" in selected:
        console.print("[dim]Export cancelled.[/dim]")
        return

    exported_files = []
    for export_type in selected:
        if export_type == "zip_all":
            continue
        paths = run_export(project_id, export_type)
        exported_files.extend(paths)

    if "zip_all" in selected:
        zip_path = create_export_zip(project_id, exported_files)
        exported_files.append(zip_path)

    exports_dir = db.get_exports_dir(project_id)
    if exported_files:
        console.print(f"\n[bold green]✅ Export complete![/bold green]")
        console.print(f"   Location: [cyan]{exports_dir}[/cyan]")
        for f in exported_files:
            fp = Path(f)
            size = _format_size(fp.stat().st_size) if fp.exists() else "?"
            console.print(f"   [dim]• {fp.name}[/dim] ({size})")

        db.add_export_record(project_id, {
            "types": selected,
            "files": [str(f) for f in exported_files],
        })


def run_export(project_id: str, export_type: str) -> list:
    """Execute a specific export type. Returns list of created file paths."""
    project         = db.get_project(project_id)
    exports_dir     = db.get_exports_dir(project_id)
    descriptions_data = project.get("descriptions_data", {})
    descriptions    = descriptions_data.get("descriptions", [])
    video_name      = Path(project.get("video_path", "video")).stem

    created = []

    if export_type == "dubbed_video":
        dubbed = project.get("dubbed_video_path")
        if dubbed and Path(dubbed).exists():
            created.append(dubbed)
        else:
            console.print("[yellow]Dubbed video not found. Run Step 4 first.[/yellow]")

    elif export_type == "video_with_ad_track":
        path = _export_video_with_ad_track(project_id, video_name, exports_dir)
        if path:
            created.append(path)

    elif export_type == "full_ad_audio":
        out = exports_dir / f"{video_name}_AD_track.mp3"
        path = merge_all_description_audio(project_id, out)
        if path:
            created.append(path)

    elif export_type == "individual_clips":
        clips_dir = exports_dir / "individual_clips"
        clips_dir.mkdir(exist_ok=True)
        for af in project.get("generated_audio_files", []):
            src = Path(af["audio_path"])
            if src.exists():
                dest = clips_dir / src.name
                shutil.copy2(src, dest)
                created.append(str(dest))
        console.print(f"[green]✅ Individual clips: {len(created)} files[/green]")

    elif export_type == "vtt":
        path = exports_dir / f"{video_name}_descriptions.vtt"
        subtitle_exporter.export_vtt(descriptions, str(path))
        created.append(str(path))
        console.print(f"[green]✅ VTT: {path.name}[/green]")

    elif export_type == "srt":
        path = exports_dir / f"{video_name}_descriptions.srt"
        subtitle_exporter.export_srt(descriptions, str(path))
        created.append(str(path))
        console.print(f"[green]✅ SRT: {path.name}[/green]")

    elif export_type == "json_full":
        path = exports_dir / f"{video_name}_workflow.json"
        subtitle_exporter.export_json(descriptions_data, str(path), mode="full")
        created.append(str(path))
        console.print(f"[green]✅ JSON (full): {path.name}[/green]")

    elif export_type == "json_descriptions":
        path = exports_dir / f"{video_name}_descriptions.json"
        subtitle_exporter.export_json(descriptions_data, str(path), mode="descriptions")
        created.append(str(path))
        console.print(f"[green]✅ JSON (descriptions): {path.name}[/green]")

    elif export_type == "json_simple":
        path = exports_dir / f"{video_name}_descriptions_simple.json"
        subtitle_exporter.export_json(descriptions_data, str(path), mode="simple")
        created.append(str(path))
        console.print(f"[green]✅ JSON (simple): {path.name}[/green]")

    elif export_type == "txt":
        path = exports_dir / f"{video_name}_descriptions.txt"
        subtitle_exporter.export_txt(descriptions, str(path))
        created.append(str(path))
        console.print(f"[green]✅ TXT: {path.name}[/green]")

    elif export_type == "csv":
        path = exports_dir / f"{video_name}_descriptions.csv"
        subtitle_exporter.export_csv(descriptions, str(path))
        created.append(str(path))
        console.print(f"[green]✅ CSV: {path.name}[/green]")

    elif export_type == "scripts":
        scripts_dir = exports_dir / "description_scripts"
        paths = subtitle_exporter.export_description_scripts(descriptions, str(scripts_dir))
        created.extend(paths)
        console.print(f"[green]✅ Scripts: {len(paths)} files[/green]")

    return created


# ── AD audio track merge ───────────────────────────────────────────────────────

def merge_all_description_audio(project_id: str, output_path: Path) -> Optional[str]:
    """
    Merge all description audio clips into a single timeline-accurate MP3 track.

    Uses ffmpeg with adelay:all=1 + amix:duration=longest — the same approach
    as the video dubber — so the track perfectly syncs when played alongside
    the original video.

    Falls back to pydub if ffmpeg is unavailable.
    """
    from core.video_dubber import (
        _collect_segments, _fix_timestamps, _get_video_duration
    )

    project  = db.get_project(project_id)

    # Get real video duration for timestamp auto-fix
    video_path = project.get('video_path', '')
    if video_path and Path(video_path).exists():
        video_duration = _get_video_duration(video_path)
    else:
        video_duration = float(
            project.get('descriptions_data', {})
            .get('videoMetadata', {})
            .get('totalDurationSeconds', 600)
        )

    raw_segments = _collect_segments(project)
    segments     = _fix_timestamps(raw_segments, video_duration) if video_duration > 0 else raw_segments

    if not segments:
        console.print("[yellow]No audio segments to merge.[/yellow]")
        return None

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    console.print(f"[cyan]Merging {len(segments)} clips into AD audio track...[/cyan]")

    # ── Strategy 1: ffmpeg (preferred — same engine as dubber) ───────────────
    ok = _merge_ffmpeg(segments, str(output_path), video_duration)
    if ok:
        console.print(f"[green]✅ AD track: {output_path.name}[/green]")
        return str(output_path)

    # ── Strategy 2: pydub fallback ───────────────────────────────────────────
    console.print("[yellow]ffmpeg merge failed. Trying pydub...[/yellow]")
    ok = _merge_pydub(segments, str(output_path))
    if ok:
        console.print(f"[green]✅ AD track (pydub): {output_path.name}[/green]")
        return str(output_path)

    console.print("[red]❌ Could not merge AD audio track.[/red]")
    return None


def _merge_ffmpeg(segments: list, output_path: str, total_duration: float) -> bool:
    """
    Build the AD-only audio track using the same two-pass approach as the dubber.
    Reuses _build_desc_track which handles batching for large segment counts.
    Outputs MP3 (converts from the intermediate WAV).
    """
    from core.video_dubber import _build_desc_track

    if not segments:
        return False

    # Build combined WAV first (handles batching for 80+ clips)
    tmp_wav = output_path.replace(".mp3", "_tmp.wav").replace(".MP3", "_tmp.wav")
    if not tmp_wav.endswith("_tmp.wav"):
        tmp_wav = output_path + "_tmp.wav"

    ok = _build_desc_track(segments, tmp_wav, total_duration)
    if not ok:
        return False

    # Convert WAV → MP3
    cmd = [
        "ffmpeg", "-y",
        "-i", tmp_wav,
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        output_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        Path(tmp_wav).unlink()
    except Exception:
        pass
    if r.returncode != 0:
        console.print(f"[dim]WAV→MP3 stderr: {r.stderr[-300:]}[/dim]")
    return r.returncode == 0


def _merge_pydub(segments: list, output_path: str) -> bool:
    """
    Fallback: build AD track using pydub by overlaying clips onto a silent base.

    Uses overlay() instead of concatenation so each clip lands at EXACTLY
    its start_ms position regardless of how long the previous clip was.
    This is the correct approach — overlay at absolute position, not append.
    """
    try:
        from pydub import AudioSegment
    except ImportError:
        return False

    try:
        # Calculate total duration
        total_ms = int(max(
            seg["start"] * 1000 + seg["duration"] * 1000
            for seg in segments
        ) + 2000)

        # Start with a silent base track of the full duration
        combined = AudioSegment.silent(duration=total_ms, frame_rate=44100)

        for seg in segments:
            audio_path = seg["audio_path"]
            if not Path(audio_path).exists():
                continue
            try:
                clip = AudioSegment.from_file(audio_path)
                # Apply description volume
                if seg["desc_vol"] != 1.0:
                    clip = clip + (20 * (seg["desc_vol"] - 1))  # pydub uses dB
                start_ms = int(seg["start"] * 1000)
                # overlay() places the clip at the ABSOLUTE position — correct!
                combined = combined.overlay(clip, position=start_ms)
            except Exception as e:
                console.print(f"[yellow]⚠️  Skipping {seg['desc_id']}: {e}[/yellow]")
                continue

        combined.export(output_path, format="mp3", bitrate="192k")
        return True
    except Exception as e:
        console.print(f"[yellow]pydub merge error: {e}[/yellow]")
        return False


# ── Video + AD sidecar export ─────────────────────────────────────────────────

def _export_video_with_ad_track(project_id: str, video_name: str, exports_dir: Path) -> Optional[str]:
    """Export original video + separate AD audio as sidecar file."""
    project    = db.get_project(project_id)
    video_path = project.get("video_path")

    if not video_path or not Path(video_path).exists():
        console.print("[yellow]Original video not found.[/yellow]")
        return None

    # Copy original video
    video_ext  = Path(video_path).suffix
    video_dest = exports_dir / f"{video_name}_original{video_ext}"
    shutil.copy2(video_path, video_dest)

    # Generate AD audio track
    ad_track = exports_dir / f"{video_name}_AD_track.mp3"
    merged   = merge_all_description_audio(project_id, ad_track)

    if merged:
        console.print(f"[green]✅ Original video + AD sidecar exported.[/green]")

    return str(video_dest)


# ── ZIP packaging ─────────────────────────────────────────────────────────────

def create_export_zip(project_id: str, files: list) -> str:
    """Package all exported files into a ZIP archive."""
    exports_dir  = db.get_exports_dir(project_id)
    project_name = db.get_project(project_id).get("name", "project").replace(" ", "_")
    timestamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path     = exports_dir / f"{project_name}_export_{timestamp}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for filepath in files:
            fp = Path(filepath)
            if fp.is_file():
                zf.write(fp, fp.name)
            elif fp.is_dir():
                for child in fp.rglob("*"):
                    if child.is_file():
                        zf.write(child, str(child.relative_to(exports_dir)))

    size = _format_size(zip_path.stat().st_size)
    console.print(f"[bold green]📦 ZIP: {zip_path.name}[/bold green] ({size})")
    return str(zip_path)


def _format_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes //= 1024
    return f"{size_bytes:.1f} TB"
