"""
core/batch_queue.py
--------------------
File-based batch processing queue for AudioDesc.

Allows the user to queue multiple projects for overnight/unattended processing.
Each job is a project + a list of pipeline steps to execute automatically.

Queue file: data/batch_queue.json
  [
    {
      "job_id": "...",
      "project_id": "...",
      "steps": ["describe", "audio", "dub"],
      "model": "gemini-2.5-flash",
      "status": "pending" | "running" | "done" | "failed",
      "queued_at": "...",
      "started_at": "...",
      "finished_at": "...",
      "error": "..."
    }
  ]
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from rich.console import Console
from rich.table import Table

console = Console()

BASE_DIR   = Path(__file__).resolve().parent.parent
DATA_DIR   = BASE_DIR / "data"
QUEUE_FILE = DATA_DIR / "batch_queue.json"

VALID_STEPS = ["describe", "audio", "dub", "export"]


# ── Queue persistence ──────────────────────────────────────────────────────────

def _load_queue() -> list:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not QUEUE_FILE.exists():
        return []
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_queue(queue: list):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)


# ── Queue operations ───────────────────────────────────────────────────────────

def add_job(
    project_id: str,
    steps: List[str],
    model: str = "gemini-2.5-flash",
    extra_instructions: str = "",
    export_types: Optional[List[str]] = None,
) -> dict:
    """Add a project to the batch queue. Returns the job dict."""
    queue = _load_queue()

    # Check if project already queued (pending or running)
    existing = [j for j in queue
                if j["project_id"] == project_id
                and j["status"] in ("pending", "running")]
    if existing:
        console.print(
            f"[yellow]Project {project_id} already has a "
            f"{existing[0]['status']} job in the queue.[/yellow]"
        )
        return existing[0]

    job = {
        "job_id":            str(uuid.uuid4())[:8],
        "project_id":        project_id,
        "steps":             [s for s in steps if s in VALID_STEPS],
        "model":             model,
        "extra_instructions": extra_instructions,
        "export_types":      export_types or [],
        "status":            "pending",
        "queued_at":         datetime.utcnow().isoformat(),
        "started_at":        None,
        "finished_at":       None,
        "error":             None,
    }

    queue.append(job)
    _save_queue(queue)
    console.print(f"[green]✅ Job {job['job_id']} queued for project {project_id}[/green]")
    console.print(f"   Steps: {', '.join(job['steps'])}")
    return job


def remove_job(job_id: str) -> bool:
    """Remove a pending job from the queue."""
    queue = _load_queue()
    job   = next((j for j in queue if j["job_id"] == job_id), None)
    if not job:
        return False
    if job["status"] == "running":
        console.print("[red]Cannot remove a running job.[/red]")
        return False
    queue = [j for j in queue if j["job_id"] != job_id]
    _save_queue(queue)
    return True


def list_jobs() -> list:
    return _load_queue()


def get_pending_jobs() -> list:
    return [j for j in _load_queue() if j["status"] == "pending"]


def _update_job(job_id: str, updates: dict):
    queue = _load_queue()
    for job in queue:
        if job["job_id"] == job_id:
            job.update(updates)
            break
    _save_queue(queue)


# ── Batch runner ───────────────────────────────────────────────────────────────

def run_queue(stop_on_error: bool = False) -> dict:
    """
    Execute all pending jobs in order.

    Returns a summary dict with counts of done/failed jobs.
    """
    from core import description_generator, video_dubber
    from tts  import tts_manager
    from export import export_manager
    from db import database as db

    pending = get_pending_jobs()
    if not pending:
        console.print("[dim]No pending jobs in the queue.[/dim]")
        return {"done": 0, "failed": 0, "skipped": 0}

    console.print(f"\n[bold cyan]🚀 Batch Queue — {len(pending)} job(s)[/bold cyan]\n")

    done = 0; failed = 0

    for job in pending:
        project_id = job["project_id"]
        project    = db.get_project(project_id)

        if not project:
            _update_job(job["job_id"], {
                "status": "failed",
                "error": f"Project {project_id} not found.",
                "finished_at": datetime.utcnow().isoformat(),
            })
            failed += 1
            continue

        console.print(
            f"[bold]▶ Job {job['job_id']} — {project['name']}[/bold]  "
            f"Steps: {', '.join(job['steps'])}"
        )
        _update_job(job["job_id"], {
            "status": "running",
            "started_at": datetime.utcnow().isoformat(),
        })

        error = None
        try:
            for step in job["steps"]:
                console.print(f"  [cyan]→ {step}[/cyan]")

                if step == "describe":
                    description_generator.generate_descriptions(
                        project_id,
                        model=job.get("model", "gemini-2.5-flash"),
                        force_regenerate=True,
                        extra_instructions=job.get("extra_instructions") or None,
                    )
                    project = db.get_project(project_id)  # refresh

                elif step == "audio":
                    tts_manager.generate_all_audio(project_id, force_regenerate=False)
                    project = db.get_project(project_id)

                elif step == "dub":
                    video_dubber.dub_video_ffmpeg(project_id)

                elif step == "export":
                    for etype in job.get("export_types", []):
                        try:
                            export_manager.run_export(project_id, etype)
                        except Exception as ex:
                            console.print(f"  [yellow]Export '{etype}' failed: {ex}[/yellow]")

        except Exception as e:
            import traceback
            error = f"{type(e).__name__}: {e}"
            console.print(f"  [red]❌ Job failed: {error}[/red]")
            traceback.print_exc()
            failed += 1
        else:
            console.print(f"  [green]✅ Job {job['job_id']} complete.[/green]")
            done += 1

        _update_job(job["job_id"], {
            "status": "failed" if error else "done",
            "error": error,
            "finished_at": datetime.utcnow().isoformat(),
        })

        if error and stop_on_error:
            console.print("[red]Stopping queue due to error.[/red]")
            break

    console.print(
        f"\n[bold]Batch complete:[/bold] "
        f"[green]{done} done[/green]  [red]{failed} failed[/red]"
    )
    return {"done": done, "failed": failed}


# ── Display ────────────────────────────────────────────────────────────────────

def print_queue():
    """Print a rich table of all queued jobs."""
    from db import database as db

    jobs = _load_queue()
    if not jobs:
        console.print("[dim]Queue is empty.[/dim]")
        return

    table = Table(title="Batch Queue", show_lines=True)
    table.add_column("Job ID",    width=10)
    table.add_column("Project",   width=22)
    table.add_column("Steps",     width=28)
    table.add_column("Status",    width=10)
    table.add_column("Queued",    width=20)
    table.add_column("Error",     min_width=20)

    status_colors = {
        "pending": "yellow", "running": "cyan",
        "done": "green",     "failed": "red",
    }

    for job in reversed(jobs):  # newest first
        p    = db.get_project(job["project_id"])
        name = p["name"] if p else job["project_id"]
        c    = status_colors.get(job["status"], "white")
        table.add_row(
            job["job_id"],
            name[:22],
            ", ".join(job["steps"]),
            f"[{c}]{job['status']}[/{c}]",
            job["queued_at"][:19],
            (job.get("error") or "")[:40],
        )
    console.print(table)


def queue_menu():
    """Interactive batch queue management menu."""
    import questionary
    from core import project_manager
    from db import database as db

    while True:
        print_queue()
        console.print()

        action = questionary.select(
            "Batch Queue:",
            choices=[
                questionary.Choice("➕ Add project(s) to queue",   "add"),
                questionary.Choice("▶  Run all pending jobs",       "run"),
                questionary.Choice("🗑️  Remove a pending job",       "remove"),
                questionary.Choice("🧹 Clear completed/failed jobs", "clear"),
                questionary.Choice("◀  Back",                       "back"),
            ],
        ).ask()

        if action is None or action == "back":
            return

        elif action == "add":
            project = project_manager.select_project()
            if not project:
                continue

            steps = questionary.checkbox(
                "Which pipeline steps to run?",
                choices=[
                    questionary.Choice("AI Description Generation", "describe", checked=True),
                    questionary.Choice("TTS Audio Generation",      "audio",    checked=True),
                    questionary.Choice("Video Dubbing",             "dub",      checked=True),
                    questionary.Choice("Export (select types below)","export",  checked=False),
                ],
            ).ask() or []

            export_types = []
            if "export" in steps:
                export_types = questionary.checkbox(
                    "Export types:",
                    choices=[
                        questionary.Choice("Dubbed video",      "dubbed_video"),
                        questionary.Choice("Full AD audio MP3", "full_ad_audio"),
                        questionary.Choice("VTT",               "vtt"),
                        questionary.Choice("SRT",               "srt"),
                        questionary.Choice("JSON (full)",       "json_full"),
                    ],
                ).ask() or []

            from core.description_generator import GEMINI_MODELS
            model = questionary.select(
                "Gemini model for description generation:",
                choices=[questionary.Choice(label, value) for value, label in GEMINI_MODELS],
                default="gemini-2.5-flash",
            ).ask()

            extra = questionary.text(
                "Extra AI instructions (optional):", default=""
            ).ask()

            add_job(
                project["id"], steps, model=model,
                extra_instructions=extra.strip(),
                export_types=export_types,
            )

        elif action == "run":
            stop = questionary.confirm("Stop on first error?", default=False).ask()
            run_queue(stop_on_error=stop)
            questionary.press_any_key_to_continue("Press any key...").ask()

        elif action == "remove":
            jobs  = [j for j in _load_queue() if j["status"] == "pending"]
            if not jobs:
                console.print("[dim]No pending jobs to remove.[/dim]")
                continue
            from db import database as db2
            choices = [
                questionary.Choice(
                    f"{j['job_id']} — {(db2.get_project(j['project_id']) or {}).get('name', j['project_id'])}",
                    j["job_id"]
                )
                for j in jobs
            ] + [questionary.Choice("Cancel", None)]
            jid = questionary.select("Remove which job?", choices=choices).ask()
            if jid:
                remove_job(jid)

        elif action == "clear":
            queue    = _load_queue()
            cleaned  = [j for j in queue if j["status"] in ("pending", "running")]
            removed  = len(queue) - len(cleaned)
            _save_queue(cleaned)
            console.print(f"[green]Cleared {removed} completed/failed jobs.[/green]")
