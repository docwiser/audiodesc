"""
core/description_generator.py
------------------------------
Uses Gemini's structured output to generate a full audio description
workflow JSON from an uploaded video.

After generation:
  1. Validator auto-repairs the output (sort, trim overlaps, flag issues)
  2. Audio analyzer optionally applies smart ducking over AI guesses
  3. Cost tracker logs token usage + estimated USD cost per project

Timestamp format:
  Gemini natively generates MM:SS timestamps (e.g. "1:30", "34:03", "129:45").
  _mmss_to_seconds() handles 2-digit and 3+-digit minute values.
"""

import json
import os
import re
from pathlib import Path
from typing import List, Literal, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from db import database as db
from core.gemini_uploader import get_gemini_client, get_or_reuse_gemini_file

console = Console()

BASE_DIR    = Path(__file__).resolve().parent.parent
PROMPTS_DIR = BASE_DIR / "prompts"

# ── Available models ───────────────────────────────────────────────────────────

GEMINI_MODELS = [
    ("gemini-2.5-flash",       "Gemini 2.5 Flash      — Fast, strong quality (recommended)"),
    ("gemini-2.5-pro",         "Gemini 2.5 Pro        — Slower, best quality"),
    ("gemini-2.5-flash-lite",  "Gemini 2.5 Flash-Lite — Fastest, lightweight"),
    ("gemini-2.0-flash",       "Gemini 2.0 Flash      — Previous gen, fast"),
    ("gemini-3-flash-preview", "Gemini 3 Flash Preview— Latest preview model"),
]


# ── Pydantic schema — all fields have descriptions for the model ───────────────

class DescriptionItem(BaseModel):
    id: str = Field(
        description="Unique identifier for this description. Format: desc_001, desc_002, etc."
    )
    startTime: str = Field(
        description=(
            "Start time in MM:SS format. MM = total elapsed minutes (2+ digits), "
            "SS = seconds (2 digits). Examples: '0:04', '1:30', '34:03', '129:45'. "
            "NEVER use HH:MM:SS format."
        )
    )
    endTime: str = Field(
        description=(
            "End time of the gap in MM:SS format. Same rules as startTime. "
            "Must be after startTime."
        )
    )
    durationSeconds: float = Field(
        description="Total gap duration in seconds. Equals endTime minus startTime."
    )
    format: Literal["standard", "extended"] = Field(
        description=(
            "standard: 1-2 sentence description for short gaps. "
            "extended: 3-5 sentences for long gaps or video pauses."
        )
    )
    priority: Literal["critical", "high", "medium", "low"] = Field(
        description=(
            "Narrative importance. critical=essential plot. high=important character/action. "
            "medium=supporting context. low=optional detail."
        )
    )
    descriptionText: str = Field(
        description=(
            "The spoken audio description text. Present tense, active voice. "
            "No filler phrases. Must fit within estimatedSpeechDurationSeconds at 130-150 wpm."
        )
    )
    estimatedSpeechDurationSeconds: float = Field(
        description=(
            "Estimated seconds to speak descriptionText at given speechRateModifier. "
            "Must be <= durationSeconds."
        )
    )
    fitsInGap: bool = Field(
        description="True if estimatedSpeechDurationSeconds <= durationSeconds."
    )
    videoVolumePercent: float = Field(
        description=(
            "Video audio volume during description (0-100). "
            "silence=100, soft_music=65-75, loud_music=50-60, "
            "ambient=80-90, near_dialogue=85-90, over_dialogue=40-50."
        )
    )
    descriptionVolumePercent: float = Field(
        description="Description audio volume (0-100). Usually 100."
    )
    fadeInMs: int = Field(
        description="Milliseconds to fade video audio DOWN before description. 200-500ms typical."
    )
    fadeOutMs: int = Field(
        description="Milliseconds to fade video audio UP after description. 300-500ms typical."
    )
    speechRateModifier: str = Field(
        description=(
            "TTS rate modifier. '+0%'=normal. '-10%'=slower. '+10%'=faster. "
            "Range: -20% to +15%."
        )
    )
    audioContext: Literal[
        "silence", "soft_music", "loud_music", "ambient", "near_dialogue", "over_dialogue"
    ] = Field(
        description=(
            "Audio environment at this timestamp. Determines ducking strategy. "
            "silence/soft_music/loud_music/ambient/near_dialogue/over_dialogue."
        )
    )
    visualCategory: Literal[
        "character_intro", "action", "setting", "text_overlay",
        "object", "emotion", "transition", "credits"
    ] = Field(
        description=(
            "Primary visual type: character_intro/action/setting/text_overlay/"
            "object/emotion/transition/credits."
        )
    )
    narrativePriority: int = Field(
        description="Integer ranking of importance (1=highest). Used when cutting for time."
    )
    notes: str = Field(
        description="Production notes for this description. e.g., 'speaker is off-screen'."
    )


class VideoMetadata(BaseModel):
    title: str = Field(description="Inferred video title or 'Untitled'.")
    totalDurationSeconds: float = Field(description="Total runtime in seconds.")
    genre: str = Field(description="Genre: drama/documentary/comedy/music_video/tutorial/news.")
    targetAudience: str = Field(description="Audience: general/children/adult/educational.")
    contentWarnings: List[str] = Field(description="Content warnings. Empty list if none.")
    audioLandscape: str = Field(description="Overall audio character description.")
    descriptionStyle: str = Field(description="Style: neutral/cinematic/educational/descriptive.")
    analysisNotes: str = Field(description="Observations affecting description strategy.")


class ProductionSummary(BaseModel):
    totalDescriptions: int = Field(description="Count of descriptions in the array.")
    totalDescriptionDurationSeconds: float = Field(description="Sum of all durationSeconds.")
    coveragePercent: float = Field(description="(totalDescriptionDurationSeconds/totalDurationSeconds)*100.")
    criticalGapsCovered: bool = Field(description="True if all critical moments have descriptions.")
    recommendedTTSVoice: str = Field(
        description="Edge TTS voice name. e.g. 'en-US-AriaNeural', 'en-GB-RyanNeural', 'en-IN-NeerjaNeural'."
    )
    recommendedSpeechRate: str = Field(description="Global TTS rate. e.g. '+0%', '-5%', '+5%'.")
    mixingNotes: str = Field(description="Overall audio mixing strategy notes.")
    qualityFlags: List[str] = Field(description="Quality warnings for human review. Empty if all good.")


class AudioDescriptionWorkflow(BaseModel):
    videoMetadata: VideoMetadata = Field(description="Metadata about the video.")
    descriptions: List[DescriptionItem] = Field(
        description="All description entries, sorted by startTime."
    )
    productionSummary: ProductionSummary = Field(description="Summary statistics and recommendations.")


# ── Timestamp parser — handles MM:SS (Gemini's native format) ─────────────────

def _mmss_to_seconds(time_str: str) -> float:
    """
    Parse MM:SS format timestamps as generated by Gemini.

    Handles:
      "0:04"    →  4.0s
      "1:30"    →  90.0s
      "34:03"   →  2043.0s
      "129:45"  →  7785.0s
      "00:01:30"→  90.0s  (legacy HH:MM:SS fallback)
    """
    if not time_str:
        return 0.0
    try:
        time_str = time_str.strip().replace(",", ".")
        parts = time_str.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60.0 + float(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600.0 + int(parts[1]) * 60.0 + float(parts[2])
        return float(time_str)
    except Exception:
        return 0.0


# ── Loader helpers ─────────────────────────────────────────────────────────────

def _load_prompt() -> str:
    p = PROMPTS_DIR / "prompt.txt"
    if not p.exists():
        raise FileNotFoundError(f"prompt.txt not found at {p}")
    return p.read_text(encoding="utf-8")


def _load_instructions() -> str:
    p = PROMPTS_DIR / "instructions.txt"
    if not p.exists():
        raise FileNotFoundError(f"instructions.txt not found at {p}")
    return p.read_text(encoding="utf-8")


# ── JSON repair helpers ────────────────────────────────────────────────────────

def _close_json(s: str) -> str:
    """Append missing closing brackets to a truncated JSON string."""
    s = re.sub(r",\s*$", "", s.rstrip())
    stack, in_str, esc = [], False, False
    for ch in s:
        if esc:            esc = False; continue
        if ch == "\\" and in_str: esc = True; continue
        if ch == '"':      in_str = not in_str; continue
        if in_str:         continue
        if ch in "{[":     stack.append(ch)
        elif ch in "}]" and stack: stack.pop()
    return s + "".join({"{": "}", "[": "]"}[c] for c in reversed(stack))


def _partial_parse(raw: str) -> Optional[dict]:
    """Last-resort: extract whatever complete description objects are present."""
    descriptions = []
    for m in re.finditer(r'\{[^{}]*"id"\s*:\s*"desc_\d+"[^{}]*\}', raw, re.DOTALL):
        try:
            obj = json.loads(re.sub(r",\s*([}\]])", r"\1", m.group()))
            descriptions.append(obj)
        except Exception:
            pass
    if not descriptions:
        return None
    console.print(f"[yellow]⚠  Partial recovery: {len(descriptions)} descriptions extracted.[/yellow]")
    return {
        "videoMetadata": {
            "title": "Unknown", "totalDurationSeconds": 0, "genre": "unknown",
            "targetAudience": "general", "contentWarnings": [],
            "audioLandscape": "", "descriptionStyle": "neutral",
            "analysisNotes": "Partial parse — response was truncated."
        },
        "descriptions": descriptions,
        "productionSummary": {
            "totalDescriptions": len(descriptions), "totalDescriptionDurationSeconds": 0,
            "coveragePercent": 0, "criticalGapsCovered": False,
            "recommendedTTSVoice": "en-US-AriaNeural", "recommendedSpeechRate": "+0%",
            "mixingNotes": "Generated from partial response.",
            "qualityFlags": ["PARTIAL_RESPONSE_RECOVERY"]
        }
    }


def _parse_response(raw: str) -> Optional[dict]:
    """Try multiple strategies to parse a Gemini response."""
    for attempt in [
        raw,
        re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE).rstrip().rstrip("```").strip(),
    ]:
        cleaned = re.sub(r",\s*([}\]])", r"\1", attempt)
        try:
            return json.loads(cleaned)
        except Exception:
            pass
        try:
            return json.loads(_close_json(cleaned))
        except Exception:
            pass
    return None


# ── Main generator ─────────────────────────────────────────────────────────────

def generate_descriptions(
    project_id: str,
    model: str = "gemini-2.5-flash",
    force_regenerate: bool = False,
    extra_instructions: Optional[str] = None,
    max_retries: int = 2,
    run_validation: bool = True,
    run_smart_ducking: bool = True,
    smart_ducking_override: bool = False,
) -> dict:
    """
    Generate audio descriptions for a project's video using Gemini.

    Post-generation pipeline (all auto-enabled):
      1. Validator: sort, trim overlaps, flag issues
      2. Smart ducking: apply audio-analysis-based volume levels
      3. Cost tracker: log token usage + USD cost

    Args:
        run_validation:       Run validator and auto-repair after generation
        run_smart_ducking:    Override AI volume suggestions with audio analysis
        smart_ducking_override: If True, override ALL volumes; if False, only fix big discrepancies
    """
    project = db.get_project(project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found.")

    if project.get("descriptions_data") and not force_regenerate:
        console.print("[yellow]Descriptions already exist. Use force_regenerate=True to overwrite.[/yellow]")
        return project["descriptions_data"]

    gemini_file_id, gemini_file_uri = get_or_reuse_gemini_file(project_id)

    console.print(f"\n[bold cyan]🤖 Generating audio descriptions...[/bold cyan]")
    console.print(f"   Model:   [cyan]{model}[/cyan]")
    console.print(f"   Project: [cyan]{project['name']}[/cyan]")

    client             = get_gemini_client()
    system_instruction = _load_instructions()
    user_prompt        = _load_prompt()

    if extra_instructions:
        user_prompt += f"\n\n## Additional Instructions from User\n{extra_instructions}"

    file_uri = (
        gemini_file_uri
        or f"https://generativelanguage.googleapis.com/v1beta/{gemini_file_id}"
    )

    contents = types.Content(parts=[
        types.Part(file_data=types.FileData(file_uri=file_uri)),
        types.Part(text=user_prompt),
    ])

    last_raw      = ""
    workflow_dict = None
    total_in_tokens  = 0
    total_out_tokens = 0

    for attempt in range(1, max_retries + 2):
        if attempt > 1:
            console.print(f"[yellow]🔄 Retry {attempt - 1}/{max_retries}...[/yellow]")

        with Progress(
            SpinnerColumn(), TextColumn("{task.description}"), console=console
        ) as progress:
            task = progress.add_task(
                f"Analyzing video (attempt {attempt})..." if attempt > 1
                else "Analyzing video and generating descriptions...",
                total=None,
            )
            try:
                response = client.models.generate_content(
                    model=model,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_json_schema=AudioDescriptionWorkflow.model_json_schema(),
                        temperature=0.4,
                        max_output_tokens=65536,
                    ),
                    contents=contents,
                )
                last_raw = response.text or ""

                # Collect token usage if available
                usage = getattr(response, "usage_metadata", None)
                if usage:
                    total_in_tokens  += getattr(usage, "prompt_token_count",     0) or 0
                    total_out_tokens += getattr(usage, "candidates_token_count",  0) or 0

                progress.update(task, description="✅ Response received!")
            except Exception as e:
                progress.update(task, description=f"❌ API error: {e}")
                console.print(f"[red]API error on attempt {attempt}: {e}[/red]")
                if attempt <= max_retries:
                    continue
                raise

        if not last_raw.strip():
            console.print(f"[yellow]Empty response on attempt {attempt}.[/yellow]")
            continue

        workflow_dict = _parse_response(last_raw)
        if workflow_dict and workflow_dict.get("descriptions"):
            break
        console.print(f"[yellow]Could not parse valid descriptions on attempt {attempt}.[/yellow]")

    # Last-resort partial extraction
    if not workflow_dict or not workflow_dict.get("descriptions"):
        console.print("[yellow]Attempting partial extraction from raw response...[/yellow]")
        workflow_dict = _partial_parse(last_raw)

    if not workflow_dict:
        raw_path = db.get_project_dir(project_id) / "raw_response_debug.txt"
        raw_path.write_text(last_raw, encoding="utf-8")
        raise ValueError(
            f"Could not extract valid descriptions.\n"
            f"Raw response saved to: {raw_path}\n"
            f"Try gemini-2.5-pro for better schema compliance."
        )

    # ── Post-generation: Validation & auto-repair ─────────────────────────────
    if run_validation:
        console.print("[dim]Running validator...[/dim]")
        from core.validator import validate_and_repair, print_validation_report
        from core.video_dubber import _get_video_duration
        video_path = project.get("video_path", "")
        video_dur  = _get_video_duration(video_path) if video_path else 0.0
        workflow_dict, val_result = validate_and_repair(
            workflow_dict, video_duration=video_dur, auto_repair=True
        )
        print_validation_report(val_result)

    # ── Post-generation: Smart ducking via audio analysis ─────────────────────
    if run_smart_ducking:
        _apply_smart_ducking_pass(project_id, project, workflow_dict, smart_ducking_override)

    # ── Save to disk and database ──────────────────────────────────────────────
    desc_path = db.get_project_dir(project_id) / "descriptions.json"
    with open(desc_path, "w", encoding="utf-8") as f:
        json.dump(workflow_dict, f, indent=2, ensure_ascii=False)

    db.save_descriptions(project_id, workflow_dict, str(desc_path))

    # ── Cost tracking ──────────────────────────────────────────────────────────
    if total_in_tokens or total_out_tokens:
        try:
            from core.cost_tracker import log_api_call
            video_dur_s = workflow_dict.get("videoMetadata", {}).get("totalDurationSeconds", 0)
            log_api_call(
                project_id=project_id,
                call_type="description_generation",
                model=model,
                input_tokens=total_in_tokens,
                output_tokens=total_out_tokens,
                video_duration=float(video_dur_s),
            )
        except Exception:
            pass  # cost tracking is non-critical
    elif workflow_dict:
        # Estimate tokens if API didn't return usage metadata
        try:
            from core.cost_tracker import log_api_call, estimate_video_tokens
            video_dur_s  = workflow_dict.get("videoMetadata", {}).get("totalDurationSeconds", 0)
            est_in       = estimate_video_tokens(float(video_dur_s)) + 2000  # prompt overhead
            est_out      = len(json.dumps(workflow_dict)) // 4
            log_api_call(project_id, "description_generation_estimated",
                         model, est_in, est_out, float(video_dur_s))
        except Exception:
            pass

    # ── Summary ───────────────────────────────────────────────────────────────
    meta        = workflow_dict.get("videoMetadata", {})
    summary     = workflow_dict.get("productionSummary", {})
    descriptions = workflow_dict.get("descriptions", [])

    console.print(f"\n[bold green]✅ Descriptions Generated![/bold green]")
    console.print(f"   Video:        [cyan]{meta.get('title', 'N/A')}[/cyan] ({meta.get('genre', 'N/A')})")
    console.print(f"   Descriptions: [cyan]{len(descriptions)}[/cyan]")
    console.print(f"   Coverage:     [cyan]{summary.get('coveragePercent', 0):.1f}%[/cyan]")
    console.print(f"   Voice:        [cyan]{summary.get('recommendedTTSVoice', 'N/A')}[/cyan]")

    flags = summary.get("qualityFlags", [])
    if flags:
        console.print(f"   [yellow]Flags: {', '.join(flags)}[/yellow]")
    console.print(f"   Saved:        [dim]{desc_path}[/dim]")

    return workflow_dict


def _apply_smart_ducking_pass(
    project_id: str,
    project: dict,
    workflow_dict: dict,
    override: bool,
):
    """Run audio analysis and apply smart volume ducking to descriptions."""
    try:
        from core.audio_analyzer import analyze_video_audio, apply_smart_ducking
        video_path = project.get("video_path", "")
        if not video_path or not Path(video_path).exists():
            return
        analysis = analyze_video_audio(video_path)
        if analysis:
            apply_smart_ducking(workflow_dict, analysis, override_ai=override)
            console.print("[dim]Smart ducking applied from audio analysis.[/dim]")
    except Exception as e:
        console.print(f"[dim]Smart ducking skipped: {e}[/dim]")


# ── Utilities ──────────────────────────────────────────────────────────────────

def load_descriptions(project_id: str) -> Optional[dict]:
    """Load existing descriptions from project database or JSON file."""
    project = db.get_project(project_id)
    if not project:
        return None
    if project.get("descriptions_data"):
        return project["descriptions_data"]
    path = project.get("descriptions_json")
    if path and Path(path).exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def edit_description(project_id: str, desc_id: str, new_text: str) -> bool:
    """Edit a single description's text in-place and recalculate speech estimates."""
    data = load_descriptions(project_id)
    if not data:
        return False
    for desc in data.get("descriptions", []):
        if desc["id"] == desc_id:
            desc["descriptionText"] = new_text
            wpm = len(new_text.split()) / 130 * 60
            desc["estimatedSpeechDurationSeconds"] = round(wpm, 2)
            desc["fitsInGap"] = wpm <= desc["durationSeconds"]
            break
    else:
        return False
    desc_path = db.get_project_dir(project_id) / "descriptions.json"
    with open(desc_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    db.update_project(project_id, {"descriptions_data": data})
    return True


def print_descriptions_table(descriptions: list):
    """Print a rich table of all descriptions."""
    from rich.table import Table
    table = Table(title="Audio Descriptions", show_lines=True)
    table.add_column("ID",       style="cyan",   width=10)
    table.add_column("Time",     style="yellow", width=20)
    table.add_column("Priority", width=10)
    table.add_column("Vol%",     width=6)
    table.add_column("Fits",     width=5)
    table.add_column("Description", min_width=40)

    pcolors = {
        "critical": "[red]critical[/red]", "high": "[orange1]high[/orange1]",
        "medium": "[yellow]medium[/yellow]", "low": "[dim]low[/dim]",
    }
    for desc in descriptions:
        txt = desc.get("descriptionText", "")
        fits = "✅" if desc.get("fitsInGap", True) else "⚠️"
        table.add_row(
            desc.get("id", ""),
            f"{desc.get('startTime', '')} →\n{desc.get('endTime', '')}",
            pcolors.get(desc.get("priority", ""), desc.get("priority", "")),
            str(int(desc.get("videoVolumePercent", 100))),
            fits,
            txt[:120] + ("..." if len(txt) > 120 else ""),
        )
    console.print(table)
