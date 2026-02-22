"""
tts/tts_manager.py
------------------
Unified TTS interface supporting 4 engines:
  - edge:       Microsoft Edge TTS (neural, free, recommended)
  - gtts:       Google TTS (simple, free)
  - elevenlabs: ElevenLabs (highest quality, paid)
  - openai:     OpenAI TTS (high quality, paid)

Features:
  - Voice preview: hear a sample before committing
  - Per-description speech rate from AI recommendations
  - SSML-style pause injection between sentences (Edge only)
  - Loudness normalization per clip (ffmpeg loudnorm, -16 LUFS)
  - Partial regeneration: regenerate just one clip
  - Batch generation with progress bar and error recovery
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import (
    BarColumn, Progress, TaskProgressColumn,
    TextColumn, TimeRemainingColumn
)

from db import database as db
from tts import edge_engine, gtts_engine

console = Console()


# ── Speech rate converter ──────────────────────────────────────────────────────

def _rate_to_speed_float(rate_modifier: str) -> float:
    """Convert '+10%' → 1.10, '-15%' → 0.85 (for OpenAI speed param)."""
    try:
        pct = float(rate_modifier.replace("%", "").replace("+", ""))
        return max(0.25, min(4.0, 1.0 + pct / 100.0))
    except Exception:
        return 1.0


def _inject_sentence_pauses(text: str, pause_ms: int = 250) -> str:
    """
    Add SSML-style short pauses between sentences for Edge TTS.
    Edge TTS accepts <break> tags in text for natural pacing.
    """
    import re
    # Insert a short break after sentence-ending punctuation
    text = re.sub(
        r'([.!?])\s+([A-Z])',
        lambda m: f'{m.group(1)} <break time="{pause_ms}ms"/> {m.group(2)}',
        text
    )
    return text


# ── Loudness normalization ─────────────────────────────────────────────────────

def _normalize_clip(input_path: str, output_path: str, target_lufs: float = -16.0) -> bool:
    """
    Normalize a TTS audio clip to target LUFS using ffmpeg loudnorm (2-pass).
    Returns True on success. Falls back to copy on failure.
    """
    try:
        # Pass 1: measure
        r1 = subprocess.run(
            ["ffmpeg", "-i", input_path,
             "-af", "loudnorm=print_format=json", "-f", "null", "-"],
            capture_output=True, text=True, timeout=60
        )
        import re, json
        m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', r1.stderr, re.DOTALL)
        if not m:
            raise ValueError("loudnorm measurement failed")
        stats = json.loads(m.group())

        # Pass 2: apply
        af = (
            f"loudnorm=I={target_lufs}:LRA=7:TP=-1.5:"
            f"measured_I={stats['input_i']}:"
            f"measured_LRA={stats['input_lra']}:"
            f"measured_TP={stats['input_tp']}:"
            f"measured_thresh={stats['input_thresh']}:"
            f"print_format=summary"
        )
        r2 = subprocess.run(
            ["ffmpeg", "-y", "-i", input_path,
             "-af", af, "-c:a", "libmp3lame", "-b:a", "192k", output_path],
            capture_output=True, text=True, timeout=120
        )
        return r2.returncode == 0
    except Exception as e:
        import shutil
        try:
            shutil.copy2(input_path, output_path)
        except Exception:
            pass
        return False


def _get_audio_duration_ffprobe(audio_path: str) -> Optional[float]:
    """Get audio file duration using ffprobe."""
    try:
        import json
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", audio_path],
            capture_output=True, text=True, timeout=15
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return None


def _get_audio_duration(audio_path: str) -> Optional[float]:
    """Get duration: try ffprobe first, fall back to pydub."""
    d = _get_audio_duration_ffprobe(audio_path)
    if d is not None:
        return d
    try:
        from pydub import AudioSegment
        return len(AudioSegment.from_file(audio_path)) / 1000.0
    except Exception:
        return None


# ── Core synthesis dispatcher ──────────────────────────────────────────────────

def synthesize_description(
    text: str,
    output_path: str,
    tts_config: dict,
    speech_rate_override: Optional[str] = None,
    normalize: bool = True,
    inject_pauses: bool = True,
) -> str:
    """
    Synthesize a single description using the configured TTS engine.

    Steps:
    1. Optionally inject sentence pauses (Edge only)
    2. Synthesize to a temp file
    3. Optionally loudnorm-normalize to -16 LUFS
    4. Move to final output_path

    Returns: path to final audio file
    """
    import shutil

    engine = tts_config.get("engine", "edge")
    rate   = speech_rate_override or tts_config.get("rate", "+0%")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Use temp file for raw synthesis, then normalize into output_path
    tmp_raw = output_path + ".raw.mp3"

    try:
        if engine == "edge":
            synth_text = _inject_sentence_pauses(text) if inject_pauses else text
            edge_engine.synthesize(
                text=synth_text,
                output_path=tmp_raw,
                voice=tts_config.get("voice", edge_engine.DEFAULT_VOICE),
                rate=rate,
                pitch=tts_config.get("pitch", "+0Hz"),
            )

        elif engine == "gtts":
            gtts_engine.synthesize(
                text=text,
                output_path=tmp_raw,
                lang=tts_config.get("gtts_lang", "en"),
                slow=tts_config.get("gtts_slow", False),
            )

        elif engine == "elevenlabs":
            from tts import elevenlabs_engine
            elevenlabs_engine.synthesize(
                text=text,
                output_path=tmp_raw,
                voice_id=tts_config.get("elevenlabs_voice_id",
                                        elevenlabs_engine.DEFAULT_VOICE_ID),
                model=tts_config.get("elevenlabs_model",
                                     elevenlabs_engine.DEFAULT_MODEL),
                stability=tts_config.get("elevenlabs_stability", 0.5),
                similarity_boost=tts_config.get("elevenlabs_similarity", 0.75),
            )

        elif engine == "openai":
            from tts import openai_engine
            speed = _rate_to_speed_float(rate)
            openai_engine.synthesize(
                text=text,
                output_path=tmp_raw,
                voice=tts_config.get("openai_voice", openai_engine.DEFAULT_VOICE),
                model=tts_config.get("openai_model", openai_engine.DEFAULT_MODEL),
                speed=speed,
            )
        else:
            raise ValueError(f"Unknown TTS engine: '{engine}'")

        # Loudness normalization
        if normalize and Path(tmp_raw).exists():
            ok = _normalize_clip(tmp_raw, output_path)
            if not ok:
                shutil.copy2(tmp_raw, output_path)
        else:
            shutil.copy2(tmp_raw, output_path)

    finally:
        try:
            if Path(tmp_raw).exists():
                os.unlink(tmp_raw)
        except Exception:
            pass

    return output_path


# ── Voice preview ──────────────────────────────────────────────────────────────

PREVIEW_TEXT = (
    "The young woman looks up, expression thoughtful. "
    "She glances toward the window, then turns back."
)


def preview_voice(tts_config: dict, sample_text: str = PREVIEW_TEXT) -> bool:
    """
    Synthesize a short sample with current TTS config and play it.
    Uses ffplay (bundled with ffmpeg) to play the audio.

    Returns True if playback succeeded.
    """
    tmp = tempfile.mktemp(suffix="_voice_preview.mp3")
    engine = tts_config.get("engine", "edge")
    console.print(f"[cyan]🔊 Generating voice preview ({engine})...[/cyan]")

    try:
        # Synthesize without normalization for speed
        synthesize_description(
            text=sample_text,
            output_path=tmp,
            tts_config=tts_config,
            normalize=False,
            inject_pauses=False,
        )

        # Play with ffplay (silent output)
        result = subprocess.run(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", tmp],
            timeout=30,
        )
        return result.returncode == 0

    except FileNotFoundError:
        console.print(
            "[yellow]ffplay not found. Preview saved to:[/yellow] "
            f"[dim]{tmp}[/dim]"
        )
        console.print("[dim]Play it manually with any audio player.[/dim]")
        return False
    except subprocess.TimeoutExpired:
        console.print("[yellow]Preview timed out.[/yellow]")
        return False
    except Exception as e:
        console.print(f"[red]Preview failed: {e}[/red]")
        return False
    finally:
        try:
            if Path(tmp).exists():
                os.unlink(tmp)
        except Exception:
            pass


# ── Batch synthesis ────────────────────────────────────────────────────────────

def generate_all_audio(
    project_id: str,
    force_regenerate: bool = False,
    normalize: bool = True,
) -> list:
    """
    Generate TTS audio for ALL descriptions in a project.

    Features:
    - Skips already-generated clips (unless force_regenerate)
    - Per-description speech rate from AI speechRateModifier
    - Sentence pause injection (Edge engine)
    - Loudness normalization to -16 LUFS
    - Continues on individual clip failures
    """
    project = db.get_project(project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found.")

    descriptions_data = project.get("descriptions_data")
    if not descriptions_data:
        raise ValueError("No descriptions found. Run Step 2 first.")

    descriptions = descriptions_data.get("descriptions", [])
    if not descriptions:
        raise ValueError("Descriptions list is empty.")

    tts_config  = project.get("tts_config", {})
    audio_dir   = db.get_audio_dir(project_id)
    engine_name = tts_config.get("engine", "edge")
    existing    = {af["desc_id"]: af for af in project.get("generated_audio_files", [])}

    # Determine voice display name
    if engine_name == "edge":
        voice_display = tts_config.get("voice", "en-US-AriaNeural")
    elif engine_name == "elevenlabs":
        voice_display = f"EL:{tts_config.get('elevenlabs_voice_id', 'Rachel')[:12]}"
    elif engine_name == "openai":
        voice_display = f"OAI:{tts_config.get('openai_voice', 'nova')}"
    else:
        voice_display = tts_config.get("gtts_lang", "en")

    console.print(f"[bold cyan]🎙️  Generating audio...[/bold cyan]")
    console.print(
        f"   Engine: [cyan]{engine_name}[/cyan]  "
        f"Voice: [cyan]{voice_display}[/cyan]  "
        f"Normalize: [cyan]{'yes' if normalize else 'no'}[/cyan]"
    )
    console.print(f"   Total descriptions: [cyan]{len(descriptions)}[/cyan]")

    results = []
    errors  = []

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Synthesizing...", total=len(descriptions))

        for desc in descriptions:
            desc_id    = desc["id"]
            audio_path = audio_dir / f"{desc_id}.mp3"

            # Skip if exists and not forcing
            if audio_path.exists() and not force_regenerate and desc_id in existing:
                results.append(existing[desc_id])
                progress.advance(task)
                continue

            try:
                progress.update(task, description=f"Synthesizing {desc_id}…")

                synthesize_description(
                    text=desc["descriptionText"],
                    output_path=str(audio_path),
                    tts_config=tts_config,
                    speech_rate_override=desc.get("speechRateModifier"),
                    normalize=normalize,
                    inject_pauses=(engine_name == "edge"),
                )

                duration = (
                    _get_audio_duration(str(audio_path))
                    or desc.get("estimatedSpeechDurationSeconds", 3.0)
                )
                result = {
                    "desc_id":    desc_id,
                    "audio_path": str(audio_path),
                    "duration":   duration,
                }
                results.append(result)
                db.add_audio_file(project_id, desc_id, str(audio_path), duration)

            except Exception as e:
                console.print(f"\n[red]❌ {desc_id}: {e}[/red]")
                errors.append({"desc_id": desc_id, "error": str(e)})

            progress.advance(task)

    if not errors:
        db.set_stage(project_id, "audio_generated")
        console.print(f"\n[bold green]✅ {len(results)} clips generated![/bold green]")
    else:
        console.print(
            f"\n[yellow]⚠  {len(results)}/{len(descriptions)} clips generated. "
            f"{len(errors)} failed:[/yellow]"
        )
        for err in errors:
            console.print(f"  [red]• {err['desc_id']}: {err['error']}[/red]")

    return results


# ── Single-clip regeneration ───────────────────────────────────────────────────

def regenerate_single_audio(
    project_id: str,
    desc_id: str,
    normalize: bool = True,
) -> dict:
    """Regenerate audio for one description (after text edit, voice change, etc.)."""
    project = db.get_project(project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found.")

    descs = project.get("descriptions_data", {}).get("descriptions", [])
    desc  = next((d for d in descs if d["id"] == desc_id), None)
    if not desc:
        raise ValueError(f"Description '{desc_id}' not found.")

    tts_config = project.get("tts_config", {})
    audio_path = db.get_audio_dir(project_id) / f"{desc_id}.mp3"
    engine     = tts_config.get("engine", "edge")

    console.print(f"[cyan]🔄 Regenerating {desc_id} ({engine})...[/cyan]")

    synthesize_description(
        text=desc["descriptionText"],
        output_path=str(audio_path),
        tts_config=tts_config,
        speech_rate_override=desc.get("speechRateModifier"),
        normalize=normalize,
        inject_pauses=(engine == "edge"),
    )

    duration = (
        _get_audio_duration(str(audio_path))
        or desc.get("estimatedSpeechDurationSeconds", 3.0)
    )
    db.add_audio_file(project_id, desc_id, str(audio_path), duration)
    console.print(f"[green]✅ {audio_path.name} ({duration:.1f}s)[/green]")
    return {"desc_id": desc_id, "audio_path": str(audio_path), "duration": duration}


# ── Interactive TTS configuration ──────────────────────────────────────────────

def configure_tts_interactive(project_id: str) -> dict:
    """Full interactive TTS configuration wizard with voice preview."""
    import questionary

    project = db.get_project(project_id)
    current = project.get("tts_config", {})

    console.print("\n[bold]🎙️  TTS Configuration[/bold]")

    # ── Engine selection ───────────────────────────────────────────────────────
    engine_choices = [
        questionary.Choice(
            "Microsoft Edge TTS  — Neural voices, free, internet required",
            "edge"
        ),
        questionary.Choice(
            "Google TTS (gTTS)   — Simple, free, less natural",
            "gtts"
        ),
        questionary.Choice(
            "ElevenLabs          — Most natural, paid, needs API key",
            "elevenlabs"
        ),
        questionary.Choice(
            "OpenAI TTS          — Very natural, paid, needs API key",
            "openai"
        ),
    ]

    engine = questionary.select(
        "TTS engine:",
        choices=engine_choices,
        default=current.get("engine", "edge"),
    ).ask()

    new_config = {"engine": engine}

    # ── Per-engine config ──────────────────────────────────────────────────────

    if engine == "edge":
        console.print("\n[dim]Recommended voices for audio description:[/dim]")
        for v, desc in list(edge_engine.get_recommended_voices().items())[:10]:
            console.print(f"  [cyan]{v}[/cyan] — {desc}")

        voice = questionary.text(
            "Voice name:",
            default=current.get("voice", edge_engine.DEFAULT_VOICE),
        ).ask()
        new_config["voice"] = voice or edge_engine.DEFAULT_VOICE

        rate = questionary.text(
            "Speech rate (+0%, -10%, +15% etc.):",
            default=current.get("rate", "+0%"),
        ).ask()
        new_config["rate"] = rate or "+0%"

        pitch = questionary.text(
            "Pitch (+0Hz, +5Hz, -3Hz etc.):",
            default=current.get("pitch", "+0Hz"),
        ).ask()
        new_config["pitch"] = pitch or "+0Hz"

    elif engine == "gtts":
        console.print("\n[dim]Common language codes: en, fr, de, es, hi, ja, zh-TW[/dim]")
        lang = questionary.text(
            "Language code:", default=current.get("gtts_lang", "en")
        ).ask()
        new_config["gtts_lang"] = lang or "en"
        new_config["gtts_slow"] = questionary.confirm(
            "Use slow speech?", default=current.get("gtts_slow", False)
        ).ask()

    elif engine == "elevenlabs":
        from tts import elevenlabs_engine
        console.print("\n[dim]Recommended ElevenLabs voices:[/dim]")
        for name, info in elevenlabs_engine.RECOMMENDED_VOICES.items():
            console.print(f"  [cyan]{name}[/cyan]  ID:{info['id']}  {info['desc']}")

        vid = questionary.text(
            "Voice ID (copy from above or https://elevenlabs.io/voice-library):",
            default=current.get("elevenlabs_voice_id",
                                elevenlabs_engine.DEFAULT_VOICE_ID),
        ).ask()
        new_config["elevenlabs_voice_id"] = vid or elevenlabs_engine.DEFAULT_VOICE_ID

        mdl = questionary.select(
            "ElevenLabs model:",
            choices=[
                questionary.Choice("eleven_multilingual_v2 (recommended)", "eleven_multilingual_v2"),
                questionary.Choice("eleven_monolingual_v1 (English only, faster)", "eleven_monolingual_v1"),
                questionary.Choice("eleven_turbo_v2 (fastest, lower quality)", "eleven_turbo_v2"),
            ],
            default=current.get("elevenlabs_model", "eleven_multilingual_v2"),
        ).ask()
        new_config["elevenlabs_model"]      = mdl
        new_config["elevenlabs_stability"]  = 0.5
        new_config["elevenlabs_similarity"] = 0.75

    elif engine == "openai":
        from tts import openai_engine
        console.print("\n[dim]OpenAI voices:[/dim]")
        for v, desc in openai_engine.VOICES.items():
            console.print(f"  [cyan]{v}[/cyan] — {desc}")

        voice = questionary.select(
            "Voice:",
            choices=list(openai_engine.VOICES.keys()),
            default=current.get("openai_voice", openai_engine.DEFAULT_VOICE),
        ).ask()
        new_config["openai_voice"] = voice

        model = questionary.select(
            "Model:",
            choices=[
                questionary.Choice("tts-1    — Fast, standard quality", "tts-1"),
                questionary.Choice("tts-1-hd — Slower, highest quality", "tts-1-hd"),
            ],
            default=current.get("openai_model", "tts-1"),
        ).ask()
        new_config["openai_model"] = model

        rate = questionary.text(
            "Speech rate modifier (+0%, -10%, +15% etc.):",
            default=current.get("rate", "+0%"),
        ).ask()
        new_config["rate"] = rate or "+0%"

    # ── Normalization option ───────────────────────────────────────────────────
    normalize = questionary.confirm(
        "Normalize clip loudness to -16 LUFS? (recommended — ensures consistent volume)",
        default=current.get("normalize_clips", True),
    ).ask()
    new_config["normalize_clips"] = normalize

    # ── Voice preview ──────────────────────────────────────────────────────────
    if questionary.confirm(
        "Preview voice with a sample sentence?", default=True
    ).ask():
        sample = questionary.text(
            "Sample text for preview:",
            default=PREVIEW_TEXT,
        ).ask()
        preview_voice(new_config, sample_text=sample or PREVIEW_TEXT)

    # Save
    db.update_project(project_id, {"tts_config": new_config})
    console.print("[green]✅ TTS configuration saved.[/green]")
    return new_config
