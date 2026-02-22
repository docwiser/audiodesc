"""
core/cost_tracker.py
---------------------
Tracks Gemini API token usage and estimated cost per project.

Pricing (as of early 2025, approximate — update if changed):
  gemini-2.5-flash:      input $0.075/1M tokens  output $0.30/1M tokens
  gemini-2.5-pro:        input $1.25/1M tokens   output $5.00/1M tokens
  gemini-2.5-flash-lite: input $0.04/1M tokens   output $0.16/1M tokens
  gemini-2.0-flash:      input $0.075/1M tokens  output $0.30/1M tokens
  gemini-3-flash-preview:input $0.075/1M tokens  output $0.30/1M tokens

Video tokens: approximately 300 tokens/second at default resolution.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from db import database as db

console = Console()


# ── Pricing table (per 1M tokens, USD) ────────────────────────────────────────

MODEL_PRICING = {
    "gemini-2.5-flash":       {"input": 0.075, "output": 0.30},
    "gemini-2.5-pro":         {"input": 1.25,  "output": 5.00},
    "gemini-2.5-flash-lite":  {"input": 0.04,  "output": 0.16},
    "gemini-2.0-flash":       {"input": 0.075, "output": 0.30},
    "gemini-3-flash-preview": {"input": 0.075, "output": 0.30},
}

DEFAULT_PRICING = {"input": 0.075, "output": 0.30}

# Video token rate at default resolution
VIDEO_TOKENS_PER_SECOND = 300


# ── Token estimation ───────────────────────────────────────────────────────────

def estimate_video_tokens(duration_seconds: float) -> int:
    """Estimate input tokens for a video of given duration."""
    return int(duration_seconds * VIDEO_TOKENS_PER_SECOND)


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Calculate USD cost for a Gemini API call."""
    pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)
    cost = (
        (input_tokens  / 1_000_000) * pricing["input"] +
        (output_tokens / 1_000_000) * pricing["output"]
    )
    return round(cost, 6)


# ── Project cost logging ───────────────────────────────────────────────────────

def log_api_call(
    project_id: str,
    call_type: str,        # "description_generation" | "retry" | etc.
    model: str,
    input_tokens: int,
    output_tokens: int,
    video_duration: float = 0.0,
):
    """
    Log an API call's token usage and cost to the project database.
    """
    cost = calculate_cost(model, input_tokens, output_tokens)

    project = db.get_project(project_id)
    if not project:
        return

    usage_log = project.get("api_usage", [])
    usage_log.append({
        "timestamp":      datetime.utcnow().isoformat(),
        "call_type":      call_type,
        "model":          model,
        "input_tokens":   input_tokens,
        "output_tokens":  output_tokens,
        "video_duration": video_duration,
        "cost_usd":       cost,
    })
    db.update_project(project_id, {"api_usage": usage_log})

    console.print(
        f"[dim]API usage logged: {model} | "
        f"in={input_tokens:,} out={output_tokens:,} | "
        f"~${cost:.4f}[/dim]"
    )


def get_project_cost_summary(project_id: str) -> dict:
    """Return total token usage and cost for a project."""
    project = db.get_project(project_id)
    if not project:
        return {}

    usage_log = project.get("api_usage", [])
    if not usage_log:
        return {"total_calls": 0, "total_input": 0, "total_output": 0, "total_cost": 0.0}

    return {
        "total_calls":  len(usage_log),
        "total_input":  sum(u["input_tokens"] for u in usage_log),
        "total_output": sum(u["output_tokens"] for u in usage_log),
        "total_cost":   round(sum(u["cost_usd"] for u in usage_log), 6),
        "breakdown":    usage_log,
    }


def print_cost_report(project_id: str):
    """Print a formatted cost report for a project."""
    summary = get_project_cost_summary(project_id)
    project = db.get_project(project_id)
    name    = project.get("name", project_id) if project else project_id

    console.print(f"\n[bold]💰 API Cost Report — {name}[/bold]")

    if not summary.get("total_calls"):
        console.print("  [dim]No API calls logged yet.[/dim]")
        return

    table = Table(show_lines=False, box=None)
    table.add_column("Timestamp",   style="dim",    width=20)
    table.add_column("Type",        width=24)
    table.add_column("Model",       width=22)
    table.add_column("In tokens",   justify="right", width=12)
    table.add_column("Out tokens",  justify="right", width=12)
    table.add_column("Cost (USD)",  justify="right", width=12)

    for u in summary.get("breakdown", []):
        table.add_row(
            u["timestamp"][:19],
            u["call_type"],
            u["model"],
            f"{u['input_tokens']:,}",
            f"{u['output_tokens']:,}",
            f"${u['cost_usd']:.4f}",
        )

    console.print(table)
    console.print(
        f"\n  Totals: [cyan]{summary['total_calls']}[/cyan] calls | "
        f"[cyan]{summary['total_input']:,}[/cyan] input + "
        f"[cyan]{summary['total_output']:,}[/cyan] output tokens | "
        f"[bold yellow]${summary['total_cost']:.4f} USD[/bold yellow]"
    )

    # All-time across all projects
    all_projects = db.list_projects()
    all_cost = sum(
        sum(u.get("cost_usd", 0) for u in p.get("api_usage", []))
        for p in all_projects
    )
    console.print(f"  [dim]All-time total across all projects: ${all_cost:.4f}[/dim]")
