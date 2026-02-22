"""
export/subtitle_exporter.py
----------------------------
Exports audio descriptions as subtitle/caption files in multiple formats:
- WebVTT (.vtt)
- SubRip (.srt)
- JSON (structured)
- Plain text (.txt)
- CSV (spreadsheet-friendly)
"""

import csv
import json
import os
from pathlib import Path
from typing import List, Optional

from rich.console import Console

console = Console()


def _time_to_seconds(time_str: str) -> float:
    """Convert HH:MM:SS.mmm to seconds."""
    try:
        parts = time_str.replace(",", ".").split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        return float(parts[0])
    except Exception:
        return 0.0


def _seconds_to_vtt(seconds: float) -> str:
    """Convert seconds to WebVTT timestamp: HH:MM:SS.mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def _seconds_to_srt(seconds: float) -> str:
    """Convert seconds to SRT timestamp: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    milliseconds = int((secs % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{int(secs):02d},{milliseconds:03d}"


def _normalize_time(time_str: str) -> float:
    """Normalize any time string to seconds."""
    return _time_to_seconds(time_str)


# ── VTT Export ─────────────────────────────────────────────────────────────────

def export_vtt(descriptions: list, output_path: str, include_metadata: bool = True) -> str:
    """Export descriptions as WebVTT file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = ["WEBVTT", ""]
    if include_metadata:
        lines.append("NOTE AudioDesc - AI-Generated Audio Descriptions")
        lines.append("")

    for i, desc in enumerate(descriptions, 1):
        start_sec = _normalize_time(desc["startTime"])
        end_sec = _normalize_time(desc["endTime"])

        start_vtt = _seconds_to_vtt(start_sec)
        end_vtt = _seconds_to_vtt(end_sec)

        lines.append(f"desc_{i:03d}")
        lines.append(f"{start_vtt} --> {end_vtt}")
        # Add NOTE for priority/category in VTT
        if include_metadata:
            priority = desc.get("priority", "")
            category = desc.get("visualCategory", "")
            lines.append(f"[AD] [{priority.upper()}] {desc['descriptionText']}")
        else:
            lines.append(f"[AD] {desc['descriptionText']}")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return str(output_path)


# ── SRT Export ─────────────────────────────────────────────────────────────────

def export_srt(descriptions: list, output_path: str) -> str:
    """Export descriptions as SubRip (.srt) file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    for i, desc in enumerate(descriptions, 1):
        start_sec = _normalize_time(desc["startTime"])
        end_sec = _normalize_time(desc["endTime"])

        start_srt = _seconds_to_srt(start_sec)
        end_srt = _seconds_to_srt(end_sec)

        lines.append(str(i))
        lines.append(f"{start_srt} --> {end_srt}")
        lines.append(f"[AD] {desc['descriptionText']}")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return str(output_path)


# ── JSON Export ────────────────────────────────────────────────────────────────

def export_json(workflow_data: dict, output_path: str, mode: str = "full") -> str:
    """
    Export descriptions as JSON.

    Modes:
    - 'full': Complete workflow JSON including metadata and production summary
    - 'descriptions': Just the descriptions array
    - 'simple': Simplified format {id, start, end, text}
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if mode == "full":
        data = workflow_data
    elif mode == "descriptions":
        data = workflow_data.get("descriptions", [])
    elif mode == "simple":
        data = [
            {
                "id": d["id"],
                "startTime": d["startTime"],
                "endTime": d["endTime"],
                "text": d["descriptionText"],
                "priority": d.get("priority", ""),
                "format": d.get("format", "standard"),
            }
            for d in workflow_data.get("descriptions", [])
        ]
    else:
        data = workflow_data

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return str(output_path)


# ── Plain Text Export ──────────────────────────────────────────────────────────

def export_txt(descriptions: list, output_path: str, include_timestamps: bool = True) -> str:
    """Export descriptions as readable plain text."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = ["AUDIO DESCRIPTIONS", "=" * 60, ""]

    for i, desc in enumerate(descriptions, 1):
        if include_timestamps:
            lines.append(f"[{desc['startTime']} → {desc['endTime']}]")
        lines.append(f"  [{desc.get('priority', '').upper()}] [{desc.get('format', 'standard').upper()}]")
        lines.append(f"  {desc['descriptionText']}")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return str(output_path)


# ── CSV Export ─────────────────────────────────────────────────────────────────

def export_csv(descriptions: list, output_path: str) -> str:
    """Export descriptions as CSV for spreadsheet editing."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "id", "startTime", "endTime", "durationSeconds",
        "format", "priority", "descriptionText",
        "estimatedSpeechDurationSeconds", "fitsInGap",
        "videoVolumePercent", "speechRateModifier",
        "audioContext", "visualCategory", "notes"
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(descriptions)

    return str(output_path)


# ── Per-description audio scripts ─────────────────────────────────────────────

def export_description_scripts(descriptions: list, output_dir: str) -> list:
    """
    Export each description as its own .txt script file.
    Useful for individual re-recording or review.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    for desc in descriptions:
        filename = f"{desc['id']}.txt"
        filepath = output_dir / filename
        content = (
            f"ID: {desc['id']}\n"
            f"Time: {desc['startTime']} → {desc['endTime']}\n"
            f"Duration available: {desc['durationSeconds']:.2f}s\n"
            f"Format: {desc.get('format', 'standard')}\n"
            f"Priority: {desc.get('priority', '')}\n"
            f"Speech rate: {desc.get('speechRateModifier', '+0%')}\n"
            f"Audio context: {desc.get('audioContext', '')}\n"
            f"\n"
            f"DESCRIPTION TEXT:\n"
            f"{desc['descriptionText']}\n"
        )
        filepath.write_text(content, encoding="utf-8")
        paths.append(str(filepath))

    return paths
