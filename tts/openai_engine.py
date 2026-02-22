"""
tts/openai_engine.py
---------------------
OpenAI TTS engine integration.

OpenAI's TTS produces very natural neural speech. Supports 6 voices
and HD quality mode. Simple API, low latency.

Requirements:
  pip install openai

API key: Set OPENAI_API_KEY environment variable.
Pricing: ~$15/1M characters (tts-1), ~$30/1M characters (tts-1-hd)
"""

import os
from pathlib import Path
from typing import Literal, Optional

from rich.console import Console

console = Console()


VOICES: dict[str, str] = {
    "alloy":   "Neutral, versatile — good all-rounder",
    "echo":    "Clear male — clean, professional",
    "fable":   "Expressive, storytelling style",
    "onyx":    "Deep male — authoritative, documentary",
    "nova":    "Warm female — friendly narrator (recommended for AD)",
    "shimmer": "Soft female — gentle, clear",
}

DEFAULT_VOICE = "nova"
DEFAULT_MODEL = "tts-1"   # tts-1 | tts-1-hd (hd = higher quality, higher cost)


def _get_client():
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("OpenAI not installed. Run: pip install openai")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY not set. "
            "Get a key at https://platform.openai.com and set it in .env"
        )
    return OpenAI(api_key=api_key)


def synthesize(
    text: str,
    output_path: str,
    voice: str = DEFAULT_VOICE,
    model: str = DEFAULT_MODEL,
    speed: float = 1.0,
) -> str:
    """
    Synthesize text using OpenAI TTS.

    Args:
        text:         Text to speak
        output_path:  Output .mp3 file path
        voice:        One of: alloy, echo, fable, onyx, nova, shimmer
        model:        tts-1 (fast) or tts-1-hd (high quality)
        speed:        Speed multiplier (0.25–4.0; 1.0 = normal)

    Returns:
        Path to the generated audio file
    """
    client = _get_client()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        response = client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            speed=speed,
            response_format="mp3",
        )
        response.stream_to_file(output_path)
    except Exception as e:
        raise RuntimeError(f"OpenAI TTS failed: {e}") from e

    return output_path


def preview_voice(
    voice: str,
    sample_text: str = "The young woman looks up, her expression thoughtful.",
    output_path: Optional[str] = None,
) -> Optional[str]:
    """Synthesize a short sample for voice preview."""
    import tempfile
    if not output_path:
        output_path = tempfile.mktemp(suffix="_preview.mp3")
    try:
        return synthesize(sample_text, output_path, voice=voice)
    except Exception as e:
        console.print(f"[red]Preview failed: {e}[/red]")
        return None


def get_recommended_voices() -> dict:
    return VOICES.copy()


def _parse_rate_to_speed(rate_modifier: str) -> float:
    """
    Convert an Edge-TTS style rate modifier to OpenAI speed multiplier.
    '+10%' → 1.10,  '-15%' → 0.85, '+0%' → 1.0
    """
    try:
        pct = float(rate_modifier.replace("%", "").replace("+", ""))
        speed = 1.0 + pct / 100.0
        return max(0.25, min(4.0, speed))
    except Exception:
        return 1.0


def is_available() -> bool:
    """Quick check: is OpenAI configured and importable?"""
    try:
        _get_client()
        return True
    except Exception:
        return False
