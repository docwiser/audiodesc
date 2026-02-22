"""
core/validator.py
------------------
Post-generation validation and auto-repair of AI-produced descriptions.

Checks:
  1. Timestamp ordering (descriptions sorted by startTime)
  2. Overlap detection (desc A end > desc B start)
  3. Duration integrity (estimatedSpeech > duration = fitsInGap=False)
  4. Long uncovered gaps (>30s with no description = potential miss)
  5. Timestamp out-of-range (beyond video duration)
  6. Empty or suspiciously short description text

Auto-repairs:
  - Sorts descriptions by startTime
  - Trims endTime to not exceed next description's startTime
  - Recalculates durationSeconds after trim
  - Updates fitsInGap accordingly
  - Flags unfixable issues for human review
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional
from rich.console import Console
from rich.table import Table

console = Console()


# ── Result structures ──────────────────────────────────────────────────────────

@dataclass
class ValidationIssue:
    severity: str          # "error" | "warning" | "info"
    desc_id: str
    issue_type: str
    message: str
    auto_fixed: bool = False


@dataclass
class ValidationResult:
    passed: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    descriptions_modified: bool = False

    @property
    def errors(self):   return [i for i in self.issues if i.severity == "error"]
    @property
    def warnings(self): return [i for i in self.issues if i.severity == "warning"]
    @property
    def infos(self):    return [i for i in self.issues if i.severity == "info"]


# ── Time helpers ───────────────────────────────────────────────────────────────

def _t2s(ts: str) -> float:
    """MM:SS or HH:MM:SS → float seconds."""
    from core.description_generator import _mmss_to_seconds
    return _mmss_to_seconds(ts)


def _s2mmss(s: float) -> str:
    """Float seconds → MM:SS.mmm string."""
    total_mins = int(s // 60)
    secs = s % 60
    return f"{total_mins}:{secs:06.3f}"


# ── Main validator ─────────────────────────────────────────────────────────────

def validate_and_repair(
    workflow: dict,
    video_duration: float = 0.0,
    auto_repair: bool = True,
    long_gap_threshold: float = 30.0,
) -> tuple[dict, ValidationResult]:
    """
    Validate and optionally auto-repair a descriptions workflow dict.

    Args:
        workflow:             The full AI-generated workflow dict
        video_duration:       Actual video duration in seconds (0 = skip range check)
        auto_repair:          Whether to fix sortable/trimmable issues automatically
        long_gap_threshold:   Seconds without description considered a gap warning

    Returns:
        (repaired_workflow, ValidationResult)
    """
    result = ValidationResult(passed=True, issues=[])
    descs  = workflow.get("descriptions", [])

    if not descs:
        result.issues.append(ValidationIssue(
            severity="error", desc_id="*",
            issue_type="empty",
            message="Descriptions list is empty."
        ))
        result.passed = False
        return workflow, result

    # ── 1. Parse all times ─────────────────────────────────────────────────────
    parsed = []
    for d in descs:
        start = _t2s(d.get("startTime", "0:00"))
        end   = _t2s(d.get("endTime",   "0:00"))
        parsed.append({"desc": d, "start": start, "end": end})

    # ── 2. Sort by start time ──────────────────────────────────────────────────
    original_order = [p["desc"]["id"] for p in parsed]
    parsed.sort(key=lambda x: x["start"])
    sorted_order = [p["desc"]["id"] for p in parsed]

    if original_order != sorted_order:
        result.issues.append(ValidationIssue(
            severity="warning", desc_id="*",
            issue_type="unsorted",
            message="Descriptions were not sorted by startTime — auto-sorted.",
            auto_fixed=True
        ))
        result.descriptions_modified = True

    # ── 3. Overlap detection + auto-trim ──────────────────────────────────────
    for i in range(len(parsed) - 1):
        cur  = parsed[i]
        nxt  = parsed[i + 1]
        if cur["end"] > nxt["start"]:
            overlap_s = cur["end"] - nxt["start"]
            if auto_repair:
                # Trim current description's end to next description's start
                cur["end"] = nxt["start"] - 0.05
                cur["desc"]["endTime"] = _s2mmss(cur["end"])
                new_dur = max(0.1, cur["end"] - cur["start"])
                cur["desc"]["durationSeconds"] = round(new_dur, 3)
                est = cur["desc"].get("estimatedSpeechDurationSeconds", new_dur)
                cur["desc"]["fitsInGap"] = est <= new_dur
                result.issues.append(ValidationIssue(
                    severity="warning", desc_id=cur["desc"]["id"],
                    issue_type="overlap",
                    message=(f"Overlapped next desc by {overlap_s:.2f}s — "
                             f"endTime trimmed to {cur['desc']['endTime']}."),
                    auto_fixed=True
                ))
                result.descriptions_modified = True
            else:
                result.issues.append(ValidationIssue(
                    severity="error", desc_id=cur["desc"]["id"],
                    issue_type="overlap",
                    message=(f"Overlaps with {nxt['desc']['id']} by {overlap_s:.2f}s."),
                ))
                result.passed = False

    # ── 4. Duration integrity ──────────────────────────────────────────────────
    for p in parsed:
        d   = p["desc"]
        dur = p["end"] - p["start"]
        est = d.get("estimatedSpeechDurationSeconds", 0)
        if dur <= 0:
            result.issues.append(ValidationIssue(
                severity="error", desc_id=d["id"],
                issue_type="zero_duration",
                message=f"Gap duration is {dur:.3f}s — description has no usable time.",
            ))
            result.passed = False
        elif est > dur + 0.1:
            d["fitsInGap"] = False
            result.issues.append(ValidationIssue(
                severity="warning", desc_id=d["id"],
                issue_type="too_long",
                message=(f"Speech estimate {est:.1f}s > gap {dur:.1f}s "
                         f"({est-dur:.1f}s over). Consider shortening text."),
                auto_fixed=True  # fitsInGap corrected
            ))
            result.descriptions_modified = True

    # ── 5. Out-of-range timestamps ─────────────────────────────────────────────
    if video_duration > 0:
        for p in parsed:
            d = p["desc"]
            if p["start"] > video_duration:
                result.issues.append(ValidationIssue(
                    severity="error", desc_id=d["id"],
                    issue_type="out_of_range",
                    message=(f"startTime {p['start']:.1f}s > video "
                             f"duration {video_duration:.1f}s.")
                ))
                result.passed = False
            elif p["end"] > video_duration + 1.0:
                result.issues.append(ValidationIssue(
                    severity="warning", desc_id=d["id"],
                    issue_type="end_beyond_video",
                    message=f"endTime {p['end']:.1f}s exceeds video duration."
                ))

    # ── 6. Long uncovered gaps ─────────────────────────────────────────────────
    prev_end = 0.0
    for p in parsed:
        gap = p["start"] - prev_end
        if gap > long_gap_threshold:
            result.issues.append(ValidationIssue(
                severity="info", desc_id=p["desc"]["id"],
                issue_type="long_gap",
                message=(f"{gap:.0f}s uncovered gap before this description "
                         f"(from {_s2mmss(prev_end)} to {p['desc']['startTime']}).")
            ))
        prev_end = p["end"]

    # ── 7. Empty/short text ────────────────────────────────────────────────────
    for p in parsed:
        d    = p["desc"]
        text = d.get("descriptionText", "").strip()
        if not text:
            result.issues.append(ValidationIssue(
                severity="error", desc_id=d["id"],
                issue_type="empty_text",
                message="Description text is empty."
            ))
            result.passed = False
        elif len(text.split()) < 2:
            result.issues.append(ValidationIssue(
                severity="warning", desc_id=d["id"],
                issue_type="very_short",
                message=f"Very short description: '{text}' — may be incomplete."
            ))

    # ── Rebuild descriptions list (sorted, repaired) ───────────────────────────
    if auto_repair:
        workflow["descriptions"] = [p["desc"] for p in parsed]

        # Update productionSummary counts
        summary = workflow.get("productionSummary", {})
        summary["totalDescriptions"] = len(workflow["descriptions"])
        if result.issues:
            flags = summary.get("qualityFlags", [])
            flag_types = list({i.issue_type for i in result.issues})
            for ft in flag_types:
                tag = f"VALIDATOR:{ft}"
                if tag not in flags:
                    flags.append(tag)
            summary["qualityFlags"] = flags
        workflow["productionSummary"] = summary

    return workflow, result


# ── Display helpers ────────────────────────────────────────────────────────────

def print_validation_report(result: ValidationResult):
    """Print a rich-formatted validation report."""
    if not result.issues:
        console.print("[bold green]✅ Validation passed — no issues found.[/bold green]")
        return

    table = Table(title="Validation Report", show_lines=True)
    table.add_column("Severity", width=10)
    table.add_column("Desc ID",  width=12)
    table.add_column("Type",     width=16)
    table.add_column("Message",  min_width=45)
    table.add_column("Fixed?",   width=7)

    sev_colors = {"error": "red", "warning": "yellow", "info": "dim cyan"}

    for issue in result.issues:
        c = sev_colors.get(issue.severity, "white")
        table.add_row(
            f"[{c}]{issue.severity.upper()}[/{c}]",
            issue.desc_id,
            issue.issue_type,
            issue.message,
            "✅" if issue.auto_fixed else "—",
        )
    console.print(table)

    e = len(result.errors)
    w = len(result.warnings)
    i = len(result.infos)
    status = "[green]PASSED[/green]" if result.passed else "[red]FAILED[/red]"
    console.print(
        f"  Status: {status}  |  "
        f"[red]{e} error{'s' if e!=1 else ''}[/red]  "
        f"[yellow]{w} warning{'s' if w!=1 else ''}[/yellow]  "
        f"[dim]{i} info[/dim]"
    )
    if result.descriptions_modified:
        console.print("  [dim]Auto-repairs applied and saved.[/dim]")
