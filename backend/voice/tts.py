"""ElevenLabs text-to-speech handler for the voice output pipeline.

Purely additive: takes the customer-facing reply text — only ever passed in
*after* the existing, unmodified Refund Resolver / Orchestrator pipeline has
finished streaming it in full — and turns it into spoken audio. Nothing
here touches agent logic.
"""

import re

from elevenlabs.client import ElevenLabs

from backend import config

# Turbo model: low latency, well suited to a live customer-support reply
# that's about to be played back immediately rather than downloaded.
_MODEL_ID = "eleven_turbo_v2_5"

_ORDER_NUMBER_PATTERN = re.compile(r"\bMMX-(\d+)\b", re.IGNORECASE)


def _speakable_order_numbers(text: str) -> str:
    """Rewrite MMX-##### order numbers into a character-by-character form.

    Spoken as-is, ElevenLabs tends to read "MMX-10001" as a word or a large
    number ("ten thousand and one"), which is useless to a customer trying
    to jot it down. "M-M-X, 1 0 0 0 1" makes it pronounce each letter and
    digit individually, the way a support agent would read it out.
    """

    def _spell_out(match: re.Match) -> str:
        digits = " ".join(match.group(1))
        return f"M-M-X, {digits}"

    return _ORDER_NUMBER_PATTERN.sub(_spell_out, text)


def _get_client():
    # Built lazily, on first use, rather than at module-import time — the
    # Flask process imports this module once at startup, so a client built
    # at import time would permanently bake in whatever ELEVENLABS_API_KEY
    # happened to be set (or blank) at that instant, even if .env is edited
    # afterward.
    if not config.ELEVENLABS_API_KEY:
        return None
    return ElevenLabs(api_key=config.ELEVENLABS_API_KEY)


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
        voice_id=voice_id or config.ELEVENLABS_VOICE_ID,
        text=_speakable_order_numbers(text),
        model_id=_MODEL_ID,
        output_format="mp3_44100_128",
    )
