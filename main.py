#!/usr/bin/env python3
"""
main.py
--------
AudioDesc — AI-Powered Audio Description Generator
Entry point. Main menu and project selector.

Usage:
    python main.py           # Launch interactive app
    python main.py --check   # Run environment/dependency check
    python main.py --batch   # Run batch queue immediately (non-interactive)
"""

import argparse
import os
import sys
from pathlib import Path


# ── Load .env before any imports that need API key ────────────────────────────
def _load_env():
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

_load_env()

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from db import database as db
from core import project_manager, pipeline

console = Console()

BANNER = """[bold cyan]
╔══════════════════════════════════════════════════════════════╗
║        🎙️  AudioDesc — AI Audio Description Tool             ║
║   Gemini · Edge TTS · ElevenLabs · OpenAI · gTTS · ffmpeg   ║
╚══════════════════════════════════════════════════════════════╝
[/bold cyan]"""


# ── Dependency Check ──────────────────────────────────────────────────────────

def _try_import(module: str) -> tuple:
    import importlib
    try:
        importlib.import_module(module)
        return True, "✅ installed"
    except ModuleNotFoundError as e:
        missing = str(e)
        if module in missing:
            return False, "❌ not installed"
        return None, f"⚠️  installed (broken dep: {missing})"
    except Exception as e:
        return None, f"⚠️  installed (error: {type(e).__name__})"


def run_checks() -> bool:
    import subprocess
    console.print("\n[bold]🔍 Checking environment...[/bold]\n")

    checks = []

    # Python version
    major, minor = sys.version_info[:2]
    ok = major >= 3 and minor >= 10
    checks.append(("Python version", f"{major}.{minor}", ok,
                   "Python 3.10+ required" if not ok else ""))
    if minor >= 13:
        checks.append(("Python 3.13+ note", "audioop removed", None,
                       "pydub audio-merge may be limited — core features unaffected"))

    # ffmpeg + ffprobe + ffplay
    for tool in ["ffmpeg", "ffprobe", "ffplay"]:
        try:
            subprocess.run([tool, "-version"], capture_output=True, timeout=5)
            checks.append((tool, "found", True, ""))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            checks.append((tool, "NOT FOUND", False, f"Install ffmpeg (includes {tool})"))

    # Python packages
    packages = [
        ("google.genai", "google-genai",  True),
        ("edge_tts",     "edge-tts",      True),
        ("gtts",         "gTTS",          True),
        ("moviepy",      "moviepy",       True),
        ("pydub",        "pydub",         None),
        ("rich",         "rich",          True),
        ("questionary",  "questionary",   True),
        ("pydantic",     "pydantic",      True),
        ("elevenlabs",   "elevenlabs",    None),
        ("openai",       "openai",        None),
    ]

    for module, pip_name, required in packages:
        ok_flag, msg = _try_import(module)
        if ok_flag is True:
            status, hint = True, ""
        elif ok_flag is False:
            status = False if required else None
            hint   = f"pip install {pip_name}"
        else:
            status = None
            hint   = ("audioop-lts needed: pip install audioop-lts"
                      if module == "pydub" else f"Check {pip_name} compatibility")
        checks.append((pip_name, msg, status, hint))

    # API key
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if api_key:
        masked = api_key[:8] + "..." + api_key[-4:]
        checks.append(("GEMINI_API_KEY", masked, True, ""))
    else:
        checks.append(("GEMINI_API_KEY", "NOT SET", False,
                       "Set in .env file or environment variable"))

    # ElevenLabs key (optional)
    el_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if el_key:
        checks.append(("ELEVENLABS_API_KEY", el_key[:8] + "...", None, ""))
    else:
        checks.append(("ELEVENLABS_API_KEY", "not set", None, "Optional — needed for ElevenLabs TTS"))

    # OpenAI key (optional)
    oai_key = os.environ.get("OPENAI_API_KEY", "")
    if oai_key:
        checks.append(("OPENAI_API_KEY", oai_key[:8] + "...", None, ""))
    else:
        checks.append(("OPENAI_API_KEY", "not set", None, "Optional — needed for OpenAI TTS"))

    hard_fail = False
    for name, value, status, hint in checks:
        if status is True:   icon = "[green]✅[/green]"
        elif status is False: icon = "[red]❌[/red]"; hard_fail = True
        else:                 icon = "[yellow]⚠️ [/yellow]"
        hint_str = f"  [dim]→ {hint}[/dim]" if hint else ""
        console.print(f"  {icon} {name:<26} {value}{hint_str}")

    console.print()
    if hard_fail:
        console.print("[bold red]Some required checks failed. See install.md for help.[/bold red]")
    else:
        console.print("[bold green]All required checks passed. You're ready to go![/bold green]")
    return not hard_fail


# ── Global cost summary ───────────────────────────────────────────────────────

def _show_global_cost():
    """Show total API spending across all projects."""
    from core.cost_tracker import MODEL_PRICING
    projects = db.list_projects()
    all_usage = []
    for p in projects:
        for u in p.get("api_usage", []):
            all_usage.append({**u, "project_name": p.get("name", p["id"])})

    if not all_usage:
        console.print("[dim]No API usage recorded yet.[/dim]")
        return

    table = Table(title="Global API Cost Summary", show_lines=False)
    table.add_column("Project",    width=22)
    table.add_column("Calls",      justify="right", width=7)
    table.add_column("In tokens",  justify="right", width=12)
    table.add_column("Out tokens", justify="right", width=12)
    table.add_column("Cost (USD)", justify="right", width=12)

    from collections import defaultdict
    by_project = defaultdict(lambda: {"calls":0,"input":0,"output":0,"cost":0.0,"name":""})
    for u in all_usage:
        pid = u.get("project_name","?")
        by_project[pid]["name"]   = pid
        by_project[pid]["calls"]  += 1
        by_project[pid]["input"]  += u.get("input_tokens",0)
        by_project[pid]["output"] += u.get("output_tokens",0)
        by_project[pid]["cost"]   += u.get("cost_usd",0.0)

    total_cost = 0.0
    for name, s in sorted(by_project.items()):
        table.add_row(
            name[:22], str(s["calls"]),
            f"{s['input']:,}", f"{s['output']:,}",
            f"${s['cost']:.4f}",
        )
        total_cost += s["cost"]

    console.print(table)
    console.print(f"\n  [bold yellow]Total spend: ${total_cost:.4f} USD[/bold yellow]")
    questionary.press_any_key_to_continue("Press any key...").ask()


# ── Main Menu ─────────────────────────────────────────────────────────────────

def main_menu():
    console.print(BANNER)

    while True:
        projects = db.list_projects()
        n        = len(projects)

        action = questionary.select(
            "Main Menu:",
            choices=[
                questionary.Choice(
                    f"📂 Open Project  ({n} project{'s' if n != 1 else ''})", "open"
                ),
                questionary.Choice("📁 Create New Project",              "create"),
                questionary.Choice("📋 List All Projects",               "list"),
                questionary.Choice("🗑️  Delete a Project",              "delete"),
                questionary.Choice("🚀 Batch Queue",                    "batch"),
                questionary.Choice("💰 Global API Cost Summary",        "cost"),
                questionary.Choice("🔍 Environment Check",              "check"),
                questionary.Choice("❌ Exit",                           "exit"),
            ]
        ).ask()

        if action is None or action == "exit":
            console.print("[dim]Goodbye![/dim]")
            sys.exit(0)

        elif action == "open":
            project = project_manager.select_project()
            if project:
                pipeline.run_pipeline_menu(project)

        elif action == "create":
            project  = project_manager.create_project_interactive()
            open_now = questionary.confirm("Open the new project now?", default=True).ask()
            if open_now:
                pipeline.run_pipeline_menu(project)

        elif action == "list":
            project_manager.print_projects_table()
            questionary.press_any_key_to_continue("Press any key...").ask()

        elif action == "delete":
            project_manager.delete_project_interactive()

        elif action == "batch":
            from core.batch_queue import queue_menu
            queue_menu()

        elif action == "cost":
            _show_global_cost()

        elif action == "check":
            run_checks()
            questionary.press_any_key_to_continue("Press any key...").ask()


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AudioDesc — AI-Powered Audio Description Generator"
    )
    parser.add_argument("--check", action="store_true",
                        help="Run environment/dependency check and exit")
    parser.add_argument("--batch", action="store_true",
                        help="Run all pending batch jobs and exit")
    args = parser.parse_args()

    if args.check:
        ok = run_checks()
        sys.exit(0 if ok else 1)
    elif args.batch:
        from core.batch_queue import run_queue
        result = run_queue()
        sys.exit(0 if result["failed"] == 0 else 1)
    else:
        try:
            main_menu()
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted. Goodbye![/dim]")
            sys.exit(0)
