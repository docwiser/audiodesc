"""
tts/gtts_engine.py
------------------
Google Text-to-Speech (gTTS) engine wrapper.
Simple, free, language-focused TTS. Lower quality than Edge but robust.
"""

import os
from pathlib import Path
from gtts import gTTS
from rich.console import Console

console = Console()


# Commonly used language codes
GTTS_LANGUAGES = {
    "English (US)": "en",
    "English (UK)": "en-uk",
    "English (AU)": "en-au",
    "English (IN)": "en-in",
    "French": "fr",
    "Spanish": "es",
    "German": "de",
    "Italian": "it",
    "Portuguese (BR)": "pt",
    "Japanese": "ja",
    "Korean": "ko",
    "Chinese (Mandarin)": "zh-CN",
    "Arabic": "ar",
    "Hindi": "hi",
    "Russian": "ru",
}


def synthesize(
    text: str,
    output_path: str,
    lang: str = "en",
    slow: bool = False,
    tld: str = "com",
) -> str:
    """
    Synthesize text to speech using gTTS and save to output_path.

    Args:
        text: The text to speak
        output_path: Where to save the .mp3 file
        lang: Language code (e.g., 'en', 'fr', 'de')
        slow: If True, speak more slowly
        tld: Top-level domain for accent variant (e.g., 'co.uk' for British)

    Returns:
        Path to the generated audio file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        tts = gTTS(text=text, lang=lang, slow=slow, tld=tld)
        tts.save(str(output_path))
        return str(output_path)
    except Exception as e:
        raise RuntimeError(f"gTTS synthesis failed: {e}") from e


def get_duration_estimate(text: str, slow: bool = False) -> float:
    """
    Estimate speech duration in seconds based on word count.
    gTTS speaks at approximately 130 WPM (normal), 90 WPM (slow).
    """
    words = len(text.split())
    wpm = 90 if slow else 130
    return (words / wpm) * 60


def list_voices() -> dict:
    """Return available gTTS language options."""
    return GTTS_LANGUAGES.copy()


def get_tld_for_accent(accent: str) -> str:
    """Map accent name to TLD for gTTS."""
    accents = {
        "US": "com",
        "UK": "co.uk",
        "AU": "com.au",
        "IN": "co.in",
        "CA": "ca",
    }
    return accents.get(accent.upper(), "com")
