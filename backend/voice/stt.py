"""Whisper speech-to-text handler for the voice input pipeline.

Purely additive: turns raw browser-recorded audio into text, which then
flows into the *existing*, unmodified /chat pipeline exactly as if the
customer had typed it. No agent files are touched by anything in this
module.
"""

import io

from openai import OpenAI

from backend import config

# MediaRecorder's native output varies by browser (Chrome: audio/webm,
# Firefox: audio/ogg, Safari: audio/mp4) — Whisper's endpoint infers the
# container/codec from the uploaded filename's extension, so the in-memory
# file object needs *a* name. The frontend never has to pick one itself;
# MediaRecorder already reports its own mimeType, which we map here.
_EXTENSION_BY_MIME = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}


def _get_client():
    # Built lazily, on first use, rather than at module-import time — the
    # Flask process imports this module once at startup, so a client built
    # at import time would permanently bake in whatever OPENAI_API_KEY
    # happened to be set (or blank) at that instant, even if .env is edited
    # afterward.
    if not config.OPENAI_API_KEY:
        return None
    return OpenAI(api_key=config.OPENAI_API_KEY)


def transcribe(audio_bytes: bytes, mimetype: str | None = None) -> str:
    """Transcribe raw recorded audio bytes to text via Whisper (whisper-1).

    `audio_bytes` is read directly into an in-memory buffer and passed
    through exactly as captured by the browser's MediaRecorder — no format
    conversion, no temp files on disk, no required file extension from the
    caller.
    """
    if not audio_bytes:
        raise ValueError("No audio data received.")
    client = _get_client()
    if client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured on the server.")

    extension = _EXTENSION_BY_MIME.get((mimetype or "").split(";")[0].strip().lower(), "webm")

    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = f"recording.{extension}"  # gives OpenAI's multipart upload a usable filename

    transcript = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
    )
    return (transcript.text or "").strip()
