"""
core/pipeline.py
-----------------
Step-by-step pipeline runner for a project.

Stages:
  Step 1: Create Project + Upload Video (to Gemini Files API)
  Step 2: Generate Descriptions (AI analysis)
          → validator auto-repair
          → smart ducking from audio analysis
          → cost tracking
  Step 3: Generate Audio (TTS with preview, per-clip controls)
  Step 4: Dub Video (two-pass ffmpeg, progress bar)
  Step 5: Export (choose what to export)

Side menus:
  • Description editor (view/edit/single regen)
  • Segment preview (hear one description in context)
  • Validation report on demand
  • Cost report
  • Batch queue
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from db import database as db
from core import (
    project_manager, gemini_uploader,
    description_generator, video_dubber,
)
from tts import tts_manager
from export import export_manager

console = Console()

STAGE_ORDER = ["created", "uploaded", "described", "audio_generated", "dubbed", "done"]

STAGE_LABELS = {
    "created":         "1️⃣  Project Created",
    "uploaded":        "2️⃣  Video Uploaded to Gemini",
    "described":       "3️⃣  Descriptions Generated",
    "audio_generated": "4️⃣  Audio Generated",
    "dubbed":          "5️⃣  Video Dubbed",
    "done":            "✅  Done",
}


# ── Main pipeline menu ─────────────────────────────────────────────────────────

def run_pipeline_menu(project: dict):
    """Main pipeline menu for a specific project."""
    while True:
        project = db.get_project(project["id"])
        if not project:
            console.print("[red]Project no longer found.[/red]")
            return

        project_manager.print_project_status(project)

        stage   = project.get("stage", "created")
        choices = _build_pipeline_choices(project, stage)

        console.print()
        action = questionary.select(
            f"What would you like to do with '{project['name']}'?",
            choices=choices,
        ).ask()

        if action is None or action == "back":
            return

        dispatch = {
            "step1_upload":         lambda: _run_step1_upload(project),
            "step2_describe":       lambda: _run_step2_describe(project),
            "step3_audio":          lambda: _run_step3_audio(project),
            "step4_dub":            lambda: _run_step4_dub(project),
            "step5_export":         lambda: _run_step5_export(project),
            "view_descriptions":    lambda: _view_descriptions(project),
            "edit_description":     lambda: _edit_description_interactive(project),
            "validate_descriptions":lambda: _validate_descriptions_interactive(project),
            "smart_duck_now":       lambda: _apply_smart_ducking_interactive(project),
            "segment_preview":      lambda: _segment_preview_interactive(project),
            "configure_tts":        lambda: tts_manager.configure_tts_interactive(project["id"]),
            "regenerate_audio":     lambda: _run_step3_audio(project, force=True),
            "regen_single_audio":   lambda: _regenerate_single_clip(project),
            "view_exports":         lambda: _view_exports(project),
            "cost_report":          lambda: _show_cost_report(project),
        }

        if action in dispatch:
            dispatch[action]()
        elif action == "regenerate_description":
            _run_step2_describe(project, force=True)


def _build_pipeline_choices(project: dict, stage: str) -> list:
    """Build context-aware menu choices based on pipeline stage."""
    choices = []
    si = STAGE_ORDER.index(stage) if stage in STAGE_ORDER else 0

    # ── Step 1 ────────────────────────────────────────────────────────────────
    lbl1 = "📤 Step 1: Upload Video to Gemini" if si == 0 else "📤 Step 1: Re-upload / New Video"
    choices.append(questionary.Choice(lbl1, "step1_upload"))

    # ── Step 2 ────────────────────────────────────────────────────────────────
    if si >= 1:
        lbl2 = "📝 Step 2: Generate AI Descriptions" if si < 2 else "📝 Step 2: Regenerate Descriptions"
        choices.append(questionary.Choice(lbl2, "step2_describe"))

    if si >= 2:
        choices.append(questionary.Choice("👁️  View Descriptions Table",        "view_descriptions"))
        choices.append(questionary.Choice("✏️  Edit a Description",              "edit_description"))
        choices.append(questionary.Choice("🔍 Run Validation Report",           "validate_descriptions"))
        choices.append(questionary.Choice("🔊 Apply Smart Volume Ducking",      "smart_duck_now"))

    # ── TTS config ────────────────────────────────────────────────────────────
    choices.append(questionary.Choice("🎙️  Configure TTS (voice/engine/preview)", "configure_tts"))

    # ── Step 3 ────────────────────────────────────────────────────────────────
    if si >= 2:
        lbl3 = "🎵 Step 3: Generate Description Audio" if si < 3 else "🎵 Step 3: Regenerate All Audio"
        choices.append(questionary.Choice(lbl3, "step3_audio"))

    if si >= 3:
        choices.append(questionary.Choice("🔄 Regenerate Single Audio Clip",    "regen_single_audio"))
        choices.append(questionary.Choice("🎧 Preview Segment in Context",      "segment_preview"))

    # ── Step 4 ────────────────────────────────────────────────────────────────
    if si >= 3:
        lbl4 = "🎬 Step 4: Dub Video" if si < 4 else "🎬 Step 4: Re-dub Video"
        choices.append(questionary.Choice(lbl4, "step4_dub"))

    # ── Step 5 ────────────────────────────────────────────────────────────────
    if si >= 2:
        choices.append(questionary.Choice("📦 Step 5: Export",                  "step5_export"))

    if project.get("exports"):
        choices.append(questionary.Choice("📋 View Export History",             "view_exports"))

    if project.get("api_usage"):
        choices.append(questionary.Choice("💰 API Cost Report",                 "cost_report"))

    choices.append(questionary.Choice("◀  Back to Project List", "back"))
    return choices


# ── Step 1: Upload ─────────────────────────────────────────────────────────────

def _run_step1_upload(project: dict):
    console.print(Panel("[bold cyan]Step 1: Upload Video[/bold cyan]", expand=False))

    current_video = project.get("video_path", "")
    video_path = questionary.path(
        "Path to video file:",
        default=current_video or "",
        validate=lambda p: Path(p).exists() or "File not found",
    ).ask()
    if not video_path:
        return

    uploads_dir = db.get_uploads_dir(project["id"])
    src  = Path(video_path)
    dest = uploads_dir / src.name
    if str(src) != str(dest):
        console.print("[dim]Copying video to project folder...[/dim]")
        import shutil
        shutil.copy2(src, dest)
        video_path = str(dest)

    db.update_project(project["id"], {"video_path": str(video_path)})

    try:
        gemini_uploader.upload_video_to_gemini(project["id"], video_path)
        console.print("[bold green]✅ Step 1 Complete![/bold green]")
    except Exception as e:
        console.print(f"[red]❌ Upload failed: {e}[/red]")


# ── Step 2: Describe ───────────────────────────────────────────────────────────

def _run_step2_describe(project: dict, force: bool = False):
    console.print(Panel("[bold cyan]Step 2: Generate AI Descriptions[/bold cyan]", expand=False))

    if project.get("descriptions_data") and not force:
        confirm = questionary.confirm(
            "Descriptions already exist. Regenerate? (Will overwrite current descriptions)",
            default=False,
        ).ask()
        if not confirm:
            return

    from core.description_generator import GEMINI_MODELS
    model = questionary.select(
        "Gemini model:",
        choices=[questionary.Choice(label, value) for value, label in GEMINI_MODELS],
        default="gemini-2.5-flash",
    ).ask()

    extra = questionary.text(
        "Extra instructions for the AI? (optional):",
        default="",
    ).ask()

    # Options
    run_validation = questionary.confirm(
        "Run automatic validation & repair after generation?",
        default=True,
    ).ask()

    run_smart_duck = questionary.confirm(
        "Apply smart volume ducking from audio analysis? (analyzes actual audio levels)",
        default=True,
    ).ask()

    smart_override = False
    if run_smart_duck:
        smart_override = questionary.confirm(
            "Override ALL AI volume suggestions with analysis? (No = only fix big discrepancies)",
            default=False,
        ).ask()

    try:
        description_generator.generate_descriptions(
            project["id"],
            model=model,
            force_regenerate=True,
            extra_instructions=extra.strip() if extra else None,
            run_validation=run_validation,
            run_smart_ducking=run_smart_duck,
            smart_ducking_override=smart_override,
        )
        console.print("[bold green]✅ Step 2 Complete![/bold green]")
    except Exception as e:
        console.print(f"[red]❌ Description generation failed: {e}[/red]")
        import traceback
        traceback.print_exc()


# ── Step 3: Audio ──────────────────────────────────────────────────────────────

def _run_step3_audio(project: dict, force: bool = False):
    console.print(Panel("[bold cyan]Step 3: Generate Description Audio[/bold cyan]", expand=False))

    if not project.get("tts_config"):
        console.print("[yellow]No TTS configured. Setting up now...[/yellow]")
        tts_manager.configure_tts_interactive(project["id"])

    tts = project.get("tts_config", {})
    console.print(
        f"[dim]Engine: {tts.get('engine','?')} | "
        f"Voice: {tts.get('voice') or tts.get('gtts_lang','?')}[/dim]"
    )

    if questionary.confirm("Change TTS settings?", default=False).ask():
        tts_manager.configure_tts_interactive(project["id"])

    normalize = questionary.confirm(
        "Normalize clip loudness to -16 LUFS?", default=True
    ).ask()

    try:
        tts_manager.generate_all_audio(project["id"], force_regenerate=force, normalize=normalize)
        console.print("[bold green]✅ Step 3 Complete![/bold green]")
    except Exception as e:
        console.print(f"[red]❌ Audio generation failed: {e}[/red]")
        import traceback
        traceback.print_exc()


# ── Step 4: Dub ───────────────────────────────────────────────────────────────

def _run_step4_dub(project: dict):
    console.print(Panel("[bold cyan]Step 4: Dub Video[/bold cyan]", expand=False))

    method = questionary.select(
        "Dubbing method:",
        choices=[
            questionary.Choice("ffmpeg  — Two-pass, reliable for any number of clips, progress bar", "ffmpeg"),
            questionary.Choice("moviepy — Python-based, slower, fallback", "moviepy"),
        ],
        default="ffmpeg",
    ).ask()

    try:
        if method == "ffmpeg":
            video_dubber.dub_video_ffmpeg(project["id"])
        else:
            video_dubber.dub_video(project["id"])
        console.print("[bold green]✅ Step 4 Complete![/bold green]")
    except Exception as e:
        console.print(f"[red]❌ Dubbing failed: {e}[/red]")
        import traceback
        traceback.print_exc()


# ── Step 5: Export ─────────────────────────────────────────────────────────────

def _run_step5_export(project: dict):
    console.print(Panel("[bold cyan]Step 5: Export[/bold cyan]", expand=False))
    export_manager.export_menu(project["id"])


# ── View descriptions ──────────────────────────────────────────────────────────

def _view_descriptions(project: dict):
    data = description_generator.load_descriptions(project["id"])
    if not data:
        console.print("[yellow]No descriptions found.[/yellow]")
        return

    descriptions = data.get("descriptions", [])
    if not descriptions:
        console.print("[yellow]Descriptions list is empty.[/yellow]")
        return

    meta    = data.get("videoMetadata", {})
    summary = data.get("productionSummary", {})

    console.print(f"\n[bold]Video:[/bold] {meta.get('title','?')} | Genre: {meta.get('genre','?')}")
    console.print(
        f"[bold]Coverage:[/bold] {summary.get('coveragePercent',0):.1f}%  |  "
        f"Recommended Voice: {summary.get('recommendedTTSVoice','?')}"
    )
    flags = summary.get("qualityFlags", [])
    if flags:
        console.print(f"[yellow]Flags: {', '.join(flags)}[/yellow]")
    console.print(f"[bold]Mixing:[/bold] {summary.get('mixingNotes','')[:120]}\n")

    description_generator.print_descriptions_table(descriptions)

    # Offer sub-actions
    action = questionary.select(
        "Action:",
        choices=[
            questionary.Choice("📊 Show stats by priority",       "stats"),
            questionary.Choice("⚠️  Show only non-fitting (fitsInGap=False)", "bad"),
            questionary.Choice("◀  Back",                          "back"),
        ],
    ).ask()

    if action == "stats":
        _show_description_stats(descriptions)
    elif action == "bad":
        bad = [d for d in descriptions if not d.get("fitsInGap", True)]
        if bad:
            console.print(f"\n[yellow]{len(bad)} descriptions may be too long:[/yellow]")
            description_generator.print_descriptions_table(bad)
        else:
            console.print("[green]All descriptions fit within their gaps.[/green]")


def _show_description_stats(descriptions: list):
    """Show priority and category breakdown."""
    from collections import Counter
    priorities = Counter(d.get("priority","?") for d in descriptions)
    categories = Counter(d.get("visualCategory","?") for d in descriptions)
    contexts   = Counter(d.get("audioContext","?") for d in descriptions)

    table = Table(title="Description Statistics", show_lines=False, box=None)
    table.add_column("Metric",    style="cyan", width=20)
    table.add_column("Breakdown", min_width=50)

    def fmt(counter):
        return "  ".join(f"{k}={v}" for k, v in counter.most_common())

    total_dur = sum(d.get("durationSeconds", 0) for d in descriptions)
    fits_all  = all(d.get("fitsInGap", True) for d in descriptions)

    table.add_row("Total descriptions", str(len(descriptions)))
    table.add_row("Total gap duration", f"{total_dur:.1f}s  ({total_dur/60:.1f}m)")
    table.add_row("All fit in gap",     "✅ Yes" if fits_all else "⚠️  No — some overflow")
    table.add_row("Priority breakdown", fmt(priorities))
    table.add_row("Visual categories", fmt(categories))
    table.add_row("Audio contexts",    fmt(contexts))
    console.print(table)


# ── Edit description ───────────────────────────────────────────────────────────

def _edit_description_interactive(project: dict):
    data = description_generator.load_descriptions(project["id"])
    if not data:
        console.print("[yellow]No descriptions found.[/yellow]")
        return

    descriptions = data.get("descriptions", [])

    choices = [
        questionary.Choice(
            f"[{d['id']}] {d['startTime']} — {d['descriptionText'][:70]}",
            d["id"]
        )
        for d in descriptions
    ] + [questionary.Choice("❌ Cancel", None)]

    desc_id = questionary.select("Select description to edit:", choices=choices).ask()
    if not desc_id:
        return

    desc = next(d for d in descriptions if d["id"] == desc_id)

    # Show details
    table = Table(show_lines=False, box=None)
    table.add_column("Field", style="cyan", width=28)
    table.add_column("Value", min_width=50)
    table.add_row("Time",      f"{desc.get('startTime','')} → {desc.get('endTime','')}")
    table.add_row("Gap",       f"{desc.get('durationSeconds',0):.1f}s available")
    table.add_row("Est. speech", f"{desc.get('estimatedSpeechDurationSeconds',0):.1f}s")
    table.add_row("Fits in gap", "✅ Yes" if desc.get("fitsInGap", True) else "⚠️  No")
    table.add_row("Audio ctx",  desc.get("audioContext",""))
    table.add_row("Vol duck",   f"{desc.get('videoVolumePercent',70):.0f}%")
    table.add_row("Priority",  desc.get("priority",""))
    console.print(table)
    console.print(f"\n[dim]Current text:[/dim]\n  {desc['descriptionText']}\n")

    # What to edit
    edit_action = questionary.select(
        "Edit:",
        choices=[
            questionary.Choice("📝 Description text",            "text"),
            questionary.Choice("🔊 Video volume percent",         "volume"),
            questionary.Choice("⚡ Speech rate modifier",         "rate"),
            questionary.Choice("🎚️  Fade in/out milliseconds",    "fade"),
            questionary.Choice("📊 Priority",                     "priority"),
            questionary.Choice("🗒️  Notes",                       "notes"),
            questionary.Choice("◀  Cancel",                       None),
        ]
    ).ask()

    if not edit_action:
        return

    project_data = db.get_project(project["id"])
    all_descs    = project_data.get("descriptions_data", {}).get("descriptions", [])
    target       = next((d for d in all_descs if d["id"] == desc_id), None)
    if not target:
        return

    if edit_action == "text":
        new_text = questionary.text(
            "New description text:",
            default=desc["descriptionText"],
        ).ask()
        if new_text and new_text != desc["descriptionText"]:
            success = description_generator.edit_description(project["id"], desc_id, new_text)
            if success:
                console.print("[green]✅ Text updated.[/green]")
                if project.get("generated_audio_files"):
                    if questionary.confirm("Regenerate audio for this description?", default=True).ask():
                        tts_manager.regenerate_single_audio(project["id"], desc_id)

    elif edit_action == "volume":
        val = questionary.text(
            "Video volume during description (0-100):",
            default=str(int(desc.get("videoVolumePercent", 70)))
        ).ask()
        try:
            target["videoVolumePercent"] = max(0, min(100, float(val)))
            _save_descriptions_inline(project["id"], project_data)
            console.print(f"[green]✅ Volume set to {target['videoVolumePercent']:.0f}%[/green]")
        except ValueError:
            console.print("[red]Invalid number.[/red]")

    elif edit_action == "rate":
        val = questionary.text(
            "Speech rate modifier (e.g. +0%, -10%, +15%):",
            default=desc.get("speechRateModifier", "+0%")
        ).ask()
        target["speechRateModifier"] = val or "+0%"
        _save_descriptions_inline(project["id"], project_data)
        console.print("[green]✅ Rate updated.[/green]")

    elif edit_action == "fade":
        fi = questionary.text("Fade in ms:", default=str(desc.get("fadeInMs", 300))).ask()
        fo = questionary.text("Fade out ms:", default=str(desc.get("fadeOutMs", 400))).ask()
        try:
            target["fadeInMs"]  = int(fi)
            target["fadeOutMs"] = int(fo)
            _save_descriptions_inline(project["id"], project_data)
            console.print("[green]✅ Fades updated.[/green]")
        except ValueError:
            console.print("[red]Invalid number.[/red]")

    elif edit_action == "priority":
        val = questionary.select(
            "Priority:",
            choices=["critical", "high", "medium", "low"],
            default=desc.get("priority", "medium")
        ).ask()
        target["priority"] = val
        _save_descriptions_inline(project["id"], project_data)
        console.print("[green]✅ Priority updated.[/green]")

    elif edit_action == "notes":
        val = questionary.text("Notes:", default=desc.get("notes", "")).ask()
        target["notes"] = val or ""
        _save_descriptions_inline(project["id"], project_data)
        console.print("[green]✅ Notes updated.[/green]")


def _save_descriptions_inline(project_id: str, project_data: dict):
    """Save modified descriptions_data back to disk and DB."""
    import json
    desc_path = db.get_project_dir(project_id) / "descriptions.json"
    desc_data = project_data.get("descriptions_data", {})
    with open(desc_path, "w", encoding="utf-8") as f:
        json.dump(desc_data, f, indent=2, ensure_ascii=False)
    db.update_project(project_id, {"descriptions_data": desc_data})


# ── Validation on demand ───────────────────────────────────────────────────────

def _validate_descriptions_interactive(project: dict):
    data = description_generator.load_descriptions(project["id"])
    if not data:
        console.print("[yellow]No descriptions to validate.[/yellow]")
        return

    from core.validator import validate_and_repair, print_validation_report
    from core.video_dubber import _get_video_duration
    video_path = project.get("video_path", "")
    video_dur  = _get_video_duration(video_path) if video_path else 0.0

    repaired, result = validate_and_repair(
        data, video_duration=video_dur, auto_repair=True
    )
    print_validation_report(result)

    if result.descriptions_modified:
        if questionary.confirm("Save auto-repaired descriptions?", default=True).ask():
            _save_descriptions_inline(project["id"],
                                      {**project, "descriptions_data": repaired})
            db.update_project(project["id"], {"descriptions_data": repaired})
            console.print("[green]✅ Repaired descriptions saved.[/green]")


# ── Smart ducking on demand ────────────────────────────────────────────────────

def _apply_smart_ducking_interactive(project: dict):
    data = description_generator.load_descriptions(project["id"])
    if not data:
        console.print("[yellow]No descriptions found.[/yellow]")
        return

    video_path = project.get("video_path", "")
    if not video_path or not Path(video_path).exists():
        console.print("[red]No video file found.[/red]")
        return

    override = questionary.confirm(
        "Override ALL AI volume suggestions? (No = only fix large discrepancies)",
        default=False
    ).ask()

    from core.audio_analyzer import analyze_video_audio, apply_smart_ducking
    console.print("[dim]Analyzing video audio levels (may take a moment)...[/dim]")
    analysis = analyze_video_audio(video_path)
    if not analysis:
        console.print("[red]Audio analysis failed.[/red]")
        return

    modified = apply_smart_ducking(data, analysis, override_ai=override)
    _save_descriptions_inline(project["id"], {**project, "descriptions_data": modified})
    db.update_project(project["id"], {"descriptions_data": modified})
    console.print("[green]✅ Smart ducking applied and saved.[/green]")


# ── Segment preview ────────────────────────────────────────────────────────────

def _segment_preview_interactive(project: dict):
    """
    Preview one description in context: extract ±3s of original video audio,
    mix it with the description audio clip, and play it.

    Lets the user verify volume ducking sounds right before full dubbing.
    """
    audio_files = project.get("generated_audio_files", [])
    if not audio_files:
        console.print("[yellow]No audio clips yet. Run Step 3 first.[/yellow]")
        return

    data = description_generator.load_descriptions(project["id"])
    if not data:
        console.print("[yellow]No descriptions found.[/yellow]")
        return

    descriptions = {d["id"]: d for d in data.get("descriptions", [])}

    choices = []
    for af in audio_files:
        did  = af["desc_id"]
        desc = descriptions.get(did, {})
        label = (
            f"{did}  {desc.get('startTime','?')} — "
            f"{desc.get('descriptionText','')[:50]}"
        )
        choices.append(questionary.Choice(label, did))
    choices.append(questionary.Choice("❌ Cancel", None))

    desc_id = questionary.select("Select description to preview:", choices=choices).ask()
    if not desc_id:
        return

    desc       = descriptions.get(desc_id, {})
    audio_info = next((af for af in audio_files if af["desc_id"] == desc_id), None)
    if not audio_info or not Path(audio_info["audio_path"]).exists():
        console.print("[red]Audio file not found.[/red]")
        return

    video_path = project.get("video_path", "")
    if not video_path or not Path(video_path).exists():
        console.print("[red]Original video not found — cannot mix context audio.[/red]")
        _play_file(audio_info["audio_path"])
        return

    from core.description_generator import _mmss_to_seconds
    start_s = _mmss_to_seconds(desc.get("startTime", "0:00"))
    dur_s   = desc.get("durationSeconds", 3.0)
    vol     = desc.get("videoVolumePercent", 70) / 100.0
    pad     = 2.0  # seconds of context before/after

    preview_start = max(0.0, start_s - pad)
    preview_dur   = dur_s + pad * 2

    console.print(
        f"[cyan]🎧 Preview: {desc_id}  "
        f"[dim]{desc.get('startTime','')}  ({preview_dur:.1f}s total)[/dim]"
    )

    tmp_preview = tempfile.mktemp(suffix="_segment_preview.mp3")
    try:
        # Desc clip delay relative to preview start
        delay_ms = int((start_s - preview_start) * 1000)

        fc = (
            f"[0:a]atrim=start={preview_start:.3f}:duration={preview_dur:.3f},"
            f"asetpts=PTS-STARTPTS,volume={vol:.3f}[orig];"
            f"[1:a]adelay={delay_ms}:all=1[desc];"
            f"[orig][desc]amix=inputs=2:duration=first:normalize=0[out]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_info["audio_path"],
            "-filter_complex", fc,
            "-map", "[out]",
            "-c:a", "libmp3lame", "-b:a", "192k",
            tmp_preview,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            console.print(f"[yellow]Mix failed — playing description only.[/yellow]")
            _play_file(audio_info["audio_path"])
            return

        console.print(f"[dim]Playing {preview_dur:.1f}s preview (video vol={vol*100:.0f}%)...[/dim]")
        _play_file(tmp_preview)

    finally:
        try:
            if Path(tmp_preview).exists():
                os.unlink(tmp_preview)
        except Exception:
            pass


def _play_file(path: str):
    """Play audio via ffplay."""
    try:
        subprocess.run(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
            timeout=60,
        )
    except FileNotFoundError:
        console.print(f"[yellow]ffplay not found. File at: {path}[/yellow]")
    except subprocess.TimeoutExpired:
        console.print("[yellow]Playback timed out.[/yellow]")


# ── Single clip regeneration ───────────────────────────────────────────────────

def _regenerate_single_clip(project: dict):
    audio_files = project.get("generated_audio_files", [])
    if not audio_files:
        console.print("[yellow]No audio files found.[/yellow]")
        return

    data = description_generator.load_descriptions(project["id"]) or {}
    desc_map = {d["id"]: d for d in data.get("descriptions", [])}

    choices = [
        questionary.Choice(
            f"{af['desc_id']}  ({af.get('duration',0):.1f}s)  "
            f"— {desc_map.get(af['desc_id'],{}).get('descriptionText','')[:50]}",
            af["desc_id"]
        )
        for af in audio_files
    ] + [questionary.Choice("❌ Cancel", None)]

    desc_id = questionary.select("Select clip to regenerate:", choices=choices).ask()
    if not desc_id:
        return

    normalize = questionary.confirm("Normalize loudness?", default=True).ask()
    tts_manager.regenerate_single_audio(project["id"], desc_id, normalize=normalize)

    if questionary.confirm("Preview this clip?", default=True).ask():
        _segment_preview_interactive(project)


# ── Cost report ────────────────────────────────────────────────────────────────

def _show_cost_report(project: dict):
    from core.cost_tracker import print_cost_report
    print_cost_report(project["id"])
    questionary.press_any_key_to_continue("Press any key...").ask()


# ── View exports ───────────────────────────────────────────────────────────────

def _view_exports(project: dict):
    exports = project.get("exports", [])
    if not exports:
        console.print("[dim]No exports yet.[/dim]")
        return

    table = Table(title="Export History", show_lines=True)
    table.add_column("Date",   style="dim",  width=20)
    table.add_column("Types",              min_width=30)
    table.add_column("Files",              min_width=40)

    for exp in reversed(exports):
        files_str = "\n".join(
            f"{'✅' if Path(f).exists() else '❌'} {Path(f).name}"
            for f in exp.get("files", [])
        )
        table.add_row(
            exp.get("exported_at", "")[:19],
            ", ".join(exp.get("types", [])),
            files_str or "(none)",
        )
    console.print(table)
