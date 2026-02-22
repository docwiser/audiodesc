"""
tts/elevenlabs_engine.py
-------------------------
ElevenLabs TTS engine integration.

ElevenLabs produces significantly more natural, human-like speech than
Edge TTS or gTTS. Supports voice cloning and a large voice library.

Requirements:
  pip install elevenlabs

API key: Set ELEVENLABS_API_KEY environment variable.
Get a key: https://elevenlabs.io
Free tier: 10,000 characters/month. Paid plans for more.
"""

import os
from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()

# ── Voice catalog (stable voice IDs from ElevenLabs library) ──────────────────

RECOMMENDED_VOICES = {
    "Rachel":   {"id": "21m00Tcm4TlvDq8ikWAM", "desc": "Calm, clear female — ideal for narration"},
    "Adam":     {"id": "pNInz6obpgDQGcFmaJgB", "desc": "Deep male — documentary style"},
    "Bella":    {"id": "EXAVITQu4vr4xnSDxMaL", "desc": "Soft female — warm and expressive"},
    "Arnold":   {"id": "VR6AewLTigWG4xSOukaG", "desc": "Strong male — authoritative narrator"},
    "Elli":     {"id": "MF3mGyEYCl7XYWbV9V6O", "desc": "Young female — friendly, accessible"},
    "Josh":     {"id": "TxGEqnHWrfWFTfGW9XjX", "desc": "Young male — conversational"},
    "Antoni":   {"id": "ErXwobaYiN019PkySvjV", "desc": "Warm male — classic narrator"},
    "Domi":     {"id": "AZnzlk1XvdvUeBnXmlld", "desc": "Strong female — confident"},
}

DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel
DEFAULT_MODEL    = "eleven_multilingual_v2"


def _get_client():
    """Get ElevenLabs client. Raises ImportError if not installed."""
    try:
        from elevenlabs.client import ElevenLabs
    except ImportError:
        raise ImportError(
            "ElevenLabs not installed. Run: pip install elevenlabs"
        )

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise ValueError(
            "ELEVENLABS_API_KEY not set. "
            "Get a key at https://elevenlabs.io and set it in .env"
        )
    return ElevenLabs(api_key=api_key)


def synthesize(
    text: str,
    output_path: str,
    voice_id: str = DEFAULT_VOICE_ID,
    model: str = DEFAULT_MODEL,
    stability: float = 0.5,
    similarity_boost: float = 0.75,
    style: float = 0.0,
    use_speaker_boost: bool = True,
) -> str:
    """
    Synthesize text using ElevenLabs API.

    Args:
        text:              Text to speak
        output_path:       Output .mp3 file path
        voice_id:          ElevenLabs voice ID
        model:             ElevenLabs model ID
        stability:         Voice stability (0.0–1.0; higher = more consistent)
        similarity_boost:  Adherence to original voice (0.0–1.0)
        style:             Style exaggeration (0.0–1.0; 0 = neutral, best for AD)
        use_speaker_boost: Boost speaker clarity (recommended True for narration)

    Returns:
        Path to the generated audio file
    """
    client = _get_client()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        from elevenlabs import VoiceSettings
        audio = client.generate(
            text=text,
            voice_id=voice_id,
            model=model,
            voice_settings=VoiceSettings(
                stability=stability,
                similarity_boost=similarity_boost,
                style=style,
                use_speaker_boost=use_speaker_boost,
            ),
        )
        # audio is a generator of bytes
        with open(output_path, "wb") as f:
            for chunk in audio:
                f.write(chunk)

    except Exception as e:
        raise RuntimeError(f"ElevenLabs synthesis failed: {e}") from e

    return output_path


def preview_voice(
    voice_id: str,
    sample_text: str = "The young woman looks up, her expression thoughtful.",
    output_path: Optional[str] = None,
) -> Optional[str]:
    """
    Synthesize a short sample with a specific voice for preview.
    Saves to a temp file if output_path not given.
    """
    import tempfile
    if not output_path:
        output_path = tempfile.mktemp(suffix="_preview.mp3")

    try:
        return synthesize(sample_text, output_path, voice_id=voice_id)
    except Exception as e:
        console.print(f"[red]Preview failed: {e}[/red]")
        return None


def list_voices() -> list:
    """Fetch all available voices from ElevenLabs API."""
    try:
        client = _get_client()
        result = client.voices.get_all()
        return [
            {
                "voice_id": v.voice_id,
                "name":     v.name,
                "category": getattr(v, "category", ""),
                "labels":   getattr(v, "labels", {}),
            }
            for v in result.voices
        ]
    except Exception as e:
        console.print(f"[red]Could not fetch ElevenLabs voices: {e}[/red]")
        return []


def get_recommended_voices() -> dict:
    """Return the curated recommended voices dict."""
    return {
        name: f"{info['id']} — {info['desc']}"
        for name, info in RECOMMENDED_VOICES.items()
    }


def is_available() -> bool:
    """Quick check: is ElevenLabs configured and importable?"""
    try:
        _get_client()
        return True
    except Exception:
        return False
