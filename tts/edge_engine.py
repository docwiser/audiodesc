"""
tts/edge_engine.py
------------------
Microsoft Edge Text-to-Speech engine wrapper using the edge-tts library.
Higher quality neural voices, async-based, with rate/pitch/volume control.
"""

import asyncio
import os
from pathlib import Path
from typing import Optional

import edge_tts
from rich.console import Console

console = Console()


# ── Recommended voices for audio description ──────────────────────────────────

RECOMMENDED_VOICES = {
    "en-US-AriaNeural": "US English Female — Warm, expressive (recommended)",
    "en-US-GuyNeural": "US English Male — Clear, authoritative",
    "en-US-JennyNeural": "US English Female — Friendly, conversational",
    "en-US-EricNeural": "US English Male — Professional narrator",
    "en-GB-SoniaNeural": "British English Female — Clear, professional",
    "en-GB-RyanNeural": "British English Male — Authoritative",
    "en-AU-NatashaNeural": "Australian English Female — Warm",
    "en-AU-WilliamNeural": "Australian English Male — Natural",
    "en-CA-ClaraNeural": "Canadian English Female — Clear",
    "en-IN-NeerjaNeural": "Indian English Female — Clear",
    "fr-FR-DeniseNeural": "French Female",
    "de-DE-KatjaNeural": "German Female",
    "es-ES-ElviraNeural": "Spanish Female",
    "ja-JP-NanamiNeural": "Japanese Female",
    "zh-CN-XiaoxiaoNeural": "Chinese Mandarin Female",
}

DEFAULT_VOICE = "en-US-AriaNeural"


# ── Core async synthesis ───────────────────────────────────────────────────────

async def _synthesize_async(
    text: str,
    output_path: str,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    volume: str = "+0%",
) -> str:
    """Internal async synthesis function."""
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        pitch=pitch,
        volume=volume,
    )
    await communicate.save(output_path)
    return output_path


def synthesize(
    text: str,
    output_path: str,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    volume: str = "+0%",
) -> str:
    """
    Synthesize text to speech using Edge TTS and save to output_path.

    Args:
        text: Text to speak
        output_path: Output .mp3 file path
        voice: Edge TTS voice name (e.g., 'en-US-AriaNeural')
        rate: Speech rate modifier (e.g., '+0%', '-10%', '+15%')
        pitch: Pitch modifier (e.g., '+0Hz', '+10Hz', '-5Hz')
        volume: Volume modifier (e.g., '+0%', '+10%', '-5%')

    Returns:
        Path to the generated audio file
    """
    output_path = str(Path(output_path))
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        # Run async in a new event loop (safe for both sync and async contexts)
        asyncio.run(
            _synthesize_async(text, output_path, voice, rate, pitch, volume)
        )
        return output_path
    except RuntimeError:
        # Already in an event loop (e.g., Jupyter), use nest_asyncio pattern
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                _synthesize_async(text, output_path, voice, rate, pitch, volume)
            )
        finally:
            loop.close()
        return output_path


async def list_voices_async() -> list:
    """Fetch all available Edge TTS voices."""
    voices = await edge_tts.list_voices()
    return voices


def list_voices() -> list:
    """Return all available Edge TTS voices (sync wrapper)."""
    return asyncio.run(list_voices_async())


def get_recommended_voices() -> dict:
    """Return curated recommended voices for audio description."""
    return RECOMMENDED_VOICES.copy()


def get_duration_estimate(text: str, rate_modifier: str = "+0%") -> float:
    """
    Estimate speech duration in seconds.
    Base rate: ~150 WPM for Edge TTS neural voices.
    Applies rate modifier to estimate.
    """
    words = len(text.split())
    base_wpm = 150

    # Parse rate modifier
    rate_percent = 0
    if rate_modifier and rate_modifier != "+0%":
        try:
            rate_percent = float(rate_modifier.replace("%", "").replace("+", ""))
        except ValueError:
            rate_percent = 0

    adjusted_wpm = base_wpm * (1 + rate_percent / 100)
    adjusted_wpm = max(50, adjusted_wpm)  # floor at 50 WPM

    return (words / adjusted_wpm) * 60


def validate_voice(voice: str) -> bool:
    """Check if a voice name looks valid (quick check, not API call)."""
    # Edge voice names follow pattern: xx-XX-NameNeural
    import re
    return bool(re.match(r'^[a-z]{2}-[A-Z]{2}-\w+Neural$', voice))
