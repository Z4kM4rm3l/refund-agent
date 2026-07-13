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

# FIX: Added a '?' after the hyphen so it smoothly catches "MMX10007" in addition to "MMX-10007"
_ORDER_NUMBER_PATTERN = re.compile(r"\bMMX-?([0-9\-\s]+)\b", re.IGNORECASE)

# Pattern to capture standard hyphens (-), en-dashes (–), and em-dashes (—) between numeric ranges
_RANGE_PATTERN = re.compile(r"\b(\d+)\s*[\-\–\—]\s*(\d+)\b")

_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _int_to_words(n: int) -> str:
    """Spell out 0-9999 in words ("nine hundred ninety nine"). Lookup-based,
    no libraries — amounts at or above 10,000 stay as digits (see caller)."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] + (f" {_ONES[ones]}" if ones else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"{_ONES[hundreds]} hundred" + (f" {_int_to_words(rest)}" if rest else "")
    thousands, rest = divmod(n, 1000)
    return f"{_ONES[thousands]} thousand" + (f" {_int_to_words(rest)}" if rest else "")


def _dollars_to_words(match: re.Match) -> str:
    whole = int(match.group(1).replace(",", ""))
    cents = int(match.group(2)) if match.group(2) else 0
    if whole >= 10_000:
        spoken = f"{whole} dollars"  # digits are fine at this size; words get unwieldy
    else:
        spoken = f"{_int_to_words(whole)} dollars"
    if cents:
        spoken += f" and {_int_to_words(cents)} cents"
    return spoken


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

    # Real order numbers: strip internal spaces/hyphens, then map digits to explicit 
    # words so the voice engine reads them sequentially and smoothly.
    digit_map = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine"}
    
    def _normalize_order_num(m):
        clean_digits = re.sub(r"[\-\s]", "", m.group(1))
        return f"M-M-X, {' '.join(digit_map[d] for d in clean_digits)}"

    text = _ORDER_NUMBER_PATTERN.sub(_normalize_order_num, text)

    # Dollar amounts in words: "$999.99" -> "nine hundred ninety nine dollars
    # and ninety nine cents", "$500" -> "five hundred dollars".
    text = re.sub(r"\$(\d[\d,]*)(?:\.(\d{2}))?\b", _dollars_to_words, text)

    # Numeric ranges: "5-7 business days" -> "5 to 7 business days".
    text = _RANGE_PATTERN.sub(r"\1 to \2", text)

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

    # FIX: Prepend a small pause block to generate audio headroom, keeping the
    # browser player from clipping the absolute first word of speech.
    cleaned_text = "... " + _clean_for_speech(text)

    return client.text_to_speech.convert(
        voice_id=voice_id or _fresh_env("ELEVENLABS_VOICE_ID", config.ELEVENLABS_VOICE_ID),
        text=cleaned_text,
        model_id=_MODEL_ID,
        output_format="mp3_44100_128",
    )