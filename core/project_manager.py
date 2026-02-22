"""
core/project_manager.py
------------------------
Handles project creation, selection, and management in the CLI.
"""

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import questionary
from rich.console import Console
from rich.table import Table

from db import database as db

console = Console()


# ── Date formatting helpers ────────────────────────────────────────────────────

def _time_ago(iso_str: str) -> str:
    """
    Convert an ISO 8601 UTC string into a human-readable 'time ago' string.
    e.g. 'just now', '5 minutes ago', '3 hours ago', '24 days ago', '2 months ago'
    """
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        # Make sure we compare tz-aware datetimes
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = now - dt
        seconds = int(diff.total_seconds())

        if seconds < 10:
            return "just now"
        elif seconds < 60:
            return f"{seconds} seconds ago"
        elif seconds < 3600:
            m = seconds // 60
            return f"{m} minute{'s' if m != 1 else ''} ago"
        elif seconds < 86400:
            h = seconds // 3600
            return f"{h} hour{'s' if h != 1 else ''} ago"
        elif seconds < 86400 * 30:
            d = seconds // 86400
            return f"{d} day{'s' if d != 1 else ''} ago"
        elif seconds < 86400 * 365:
            mo = seconds // (86400 * 30)
            return f"{mo} month{'s' if mo != 1 else ''} ago"
        else:
            yr = seconds // (86400 * 365)
            return f"{yr} year{'s' if yr != 1 else ''} ago"
    except Exception:
        return iso_str[:10]


def _fmt_date(iso_str: str) -> str:
    """
    Format an ISO 8601 string into a human-readable full date.
    Output: 'February 18, 2026, 03:45 PM'
    """
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%B %d, %Y, %I:%M %p")
    except Exception:
        return iso_str[:19]


# ── Project actions ────────────────────────────────────────────────────────────

def create_project_interactive() -> dict:
    """Interactive project creation wizard."""
    console.print("\n[bold cyan]📁 Create New Project[/bold cyan]")

    name = questionary.text(
        "Project name:",
        validate=lambda t: len(t.strip()) > 0 or "Name cannot be empty",
    ).ask()

    description = questionary.text(
        "Description (optional):",
        default="",
    ).ask()

    project = db.create_project(name.strip(), description.strip())
    console.print(f"[green]✅ Project created![/green] ID: [cyan]{project['id']}[/cyan]")
    return project


def select_project() -> Optional[dict]:
    """
    Display list of projects and let user select one.
    Shows 'time ago' for last-updated date next to each project.
    Returns the selected project dict, or None if cancelled.
    """
    projects = db.list_projects()

    if not projects:
        console.print("[yellow]No projects found. Create one first.[/yellow]")
        return None

    choices = []
    for p in projects:
        stage_emoji = {
            "created":         "🆕",
            "uploaded":        "📤",
            "described":       "📝",
            "audio_generated": "🎙️",
            "dubbed":          "🎬",
            "done":            "✅",
        }.get(p.get("stage", ""), "❓")

        ago = _time_ago(p.get("updated_at") or p.get("created_at", ""))
        label = f"{stage_emoji} [{p['id']}] {p['name']}  ({p.get('stage', '?')})  · {ago}"
        choices.append(questionary.Choice(label, p))

    choices.append(questionary.Choice("❌ Cancel", None))

    selected = questionary.select(
        "Select project:",
        choices=choices,
    ).ask()

    return selected


def print_projects_table():
    """Print all projects in a rich table with 'time ago' dates."""
    projects = db.list_projects()

    if not projects:
        console.print("[dim]No projects yet.[/dim]")
        return

    table = Table(title="📁 Projects", show_lines=True)
    table.add_column("ID",           style="cyan", width=10)
    table.add_column("Name",         min_width=20)
    table.add_column("Stage",        width=16)
    table.add_column("Video",        width=22)
    table.add_column("Descs",        width=6)
    table.add_column("Created",      width=16)   # time ago
    table.add_column("Last Updated", width=16)   # time ago

    stage_colors = {
        "created":         "[dim]created[/dim]",
        "uploaded":        "[blue]uploaded[/blue]",
        "described":       "[yellow]described[/yellow]",
        "audio_generated": "[magenta]audio ready[/magenta]",
        "dubbed":          "[green]dubbed[/green]",
        "done":            "[bold green]done[/bold green]",
    }

    for p in projects:
        video_name  = Path(p["video_path"]).name if p.get("video_path") else "[dim]—[/dim]"
        desc_count  = str(len(p.get("descriptions_data", {}).get("descriptions", []))) \
                      if p.get("descriptions_data") else "[dim]—[/dim]"
        stage_str   = stage_colors.get(p.get("stage", ""), p.get("stage", "?"))
        created_ago = _time_ago(p.get("created_at", ""))
        updated_ago = _time_ago(p.get("updated_at", ""))

        table.add_row(
            p["id"],
            p["name"],
            stage_str,
            video_name,
            desc_count,
            created_ago,
            updated_ago,
        )

    console.print(table)


def delete_project_interactive():
    """Interactive project deletion with confirmation."""
    project = select_project()
    if not project:
        return

    confirm = questionary.confirm(
        f"Delete project '{project['name']}' (ID: {project['id']})? "
        "This removes the database entry but NOT the files.",
        default=False,
    ).ask()

    if confirm:
        db.delete_project(project["id"])
        console.print(f"[green]✅ Project '{project['name']}' deleted from database.[/green]")
    else:
        console.print("[dim]Cancelled.[/dim]")


def print_project_status(project: dict):
    """Print detailed status of a project with formatted dates."""
    console.print(f"\n[bold]Project: [cyan]{project['name']}[/cyan][/bold] (ID: {project['id']})")
    console.print(f"  Stage:   [yellow]{project.get('stage', '?')}[/yellow]")
    console.print(f"  Created: {_fmt_date(project.get('created_at', ''))}  [dim]({_time_ago(project.get('created_at', ''))})[/dim]")
    console.print(f"  Updated: {_fmt_date(project.get('updated_at', ''))}  [dim]({_time_ago(project.get('updated_at', ''))})[/dim]")

    video = project.get("video_path")
    if video:
        size = f" ({Path(video).stat().st_size // 1024 // 1024}MB)" if Path(video).exists() else " (missing!)"
        console.print(f"  Video:   {Path(video).name}{size}")

    gemini_id = project.get("gemini_file_id")
    if gemini_id:
        console.print(f"  Gemini File ID: [dim]{gemini_id}[/dim]")

    desc_data = project.get("descriptions_data")
    if desc_data:
        descs   = desc_data.get("descriptions", [])
        meta    = desc_data.get("videoMetadata", {})
        summary = desc_data.get("productionSummary", {})
        console.print(f"  Descriptions: {len(descs)} ({summary.get('coveragePercent', 0):.0f}% coverage)")
        console.print(f"  Genre: {meta.get('genre', '?')} | Audience: {meta.get('targetAudience', '?')}")

    audio_files = project.get("generated_audio_files", [])
    if audio_files:
        console.print(f"  Audio clips: {len(audio_files)} generated")

    tts = project.get("tts_config", {})
    if tts:
        engine = tts.get("engine", "edge")
        voice  = tts.get("voice") or tts.get("gtts_lang", "en")
        console.print(f"  TTS: {engine} / {voice}")

    dubbed = project.get("dubbed_video_path")
    if dubbed:
        exists = "✅" if Path(dubbed).exists() else "❌ missing"
        console.print(f"  Dubbed video: {Path(dubbed).name} {exists}")

    exports = project.get("exports", [])
    if exports:
        console.print(f"  Exports: {len(exports)} export(s)")
