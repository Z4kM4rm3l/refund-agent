"""ElevenLabs text-to-speech handler for the voice output pipeline.

Purely additive: takes the customer-facing reply text — only ever passed in
*after* the existing, unmodified Refund Resolver / Orchestrator pipeline has
finished streaming it in full — and turns it into spoken audio. Nothing
here touches agent logic.
"""

import re

from dotenv import dotenv_values
from elevenlabs.client import ElevenLabs

from backend import config

# Turbo model: low latency, well suited to a live customer-support reply
# that's about to be played back immediately rather than downloaded.
_MODEL_ID = "eleven_turbo_v2_5"


def _fresh_env(key: str, fallback: str) -> str:
    # config.py snapshots .env once, when the Flask process first imports it —
    # so an edit to .env (new voice ID, new key) is invisible to the running
    # server even though a fresh `python -c "import backend.config"` shows the
    # new value. Re-reading .env per call keeps voice settings hot-swappable
    # without a server restart; the config snapshot remains the fallback for
    # values set via real environment variables rather than the .env file.
    return dotenv_values(config.PROJECT_ROOT / ".env").get(key) or fallback

_ORDER_NUMBER_PATTERN = re.compile(r"\bMMX-(\d+)\b", re.IGNORECASE)


def _clean_for_speech(text: str) -> str:
    """Rewrite the reply into clean, speakable prose for ElevenLabs.

    The chat UI keeps the original markdown-formatted text — this only
    shapes the copy handed to TTS, where markdown markers, placeholder
    patterns, and symbols otherwise come out as garbled audio ("asterisk
    asterisk", "hash hash hash", "ten thousand and one"...).
    """
    # Markdown: headers, bold/italic markers, inline code backticks.
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
    text = text.replace("`", "")

    # Placeholder order-number examples: "MMX-#####" -> "M-M-X, five digits".
    text = re.sub(r"\bMMX-#{4,}", "M-M-X, five digits", text, flags=re.IGNORECASE)
    text = re.sub(r"#{4,}", "five digits", text)

    # Real order numbers: spell out letter by letter, digit by digit —
    # "MMX-10001" -> "M-M-X, 1 0 0 0 1" — the way an agent would read it out.
    text = _ORDER_NUMBER_PATTERN.sub(lambda m: f"M-M-X, {' '.join(m.group(1))}", text)

    # Dollar amounts: "$479.99" -> "479 dollars and 99 cents", "$500" -> "500 dollars".
    text = re.sub(r"\$(\d[\d,]*)\.(\d{2})\b", r"\1 dollars and \2 cents", text)
    text = re.sub(r"\$(\d[\d,]*)\b", r"\1 dollars", text)

    # Numeric ranges: "5-7 business days" -> "5 to 7 business days".
    text = re.sub(r"\b(\d+)\s*-\s*(\d+)\b", r"\1 to \2", text)

    # Bullet/list dashes at line starts become a sentence pause, so list items
    # don't run together once newlines are collapsed below.
    text = re.sub(r"(?:^|\n)\s*[-*•]\s+", ". ", text)

    # Drop anything that isn't a letter, digit, standard punctuation, or space.
    text = re.sub(r"[^A-Za-z0-9 \n.,!?;:'\"()\-]", " ", text)

    # Collapse runs of whitespace/newlines into single spaces, tidy up any
    # doubled sentence punctuation the substitutions above may have created.
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[:;,]\s*\.", ".", text)
    text = re.sub(r"(?:\.\s*)+\.", ".", text)
    return text.strip()


def _get_client():
    # Built lazily, per call, with a freshly-read key — never baked in at
    # module import (see _fresh_env for why).
    api_key = _fresh_env("ELEVENLABS_API_KEY", config.ELEVENLABS_API_KEY)
    if not api_key:
        return None
    return ElevenLabs(api_key=api_key)


def synthesize(text: str, voice_id: str | None = None):
    """Convert text to speech, returning an iterator of MP3 audio-chunk bytes.

    A professional, calm voice — Rachel by default (see config.py) — fits
    the tone of the agent's replies. The returned iterator is handed
    straight to Flask as a streaming response body.
    """
    if not text or not text.strip():
        raise ValueError("No text to synthesize.")
    client = _get_client()
    if client is None:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured on the server.")

    return client.text_to_speech.convert(
        voice_id=voice_id or _fresh_env("ELEVENLABS_VOICE_ID", config.ELEVENLABS_VOICE_ID),
        text=_clean_for_speech(text),
        model_id=_MODEL_ID,
        output_format="mp3_44100_128",
    )
