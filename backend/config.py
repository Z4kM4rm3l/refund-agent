"""Environment configuration for the MelodyMax Gear Refund Agent backend."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Default model per Anthropic's current guidance: Claude Opus 4.8. Override
# via CLAUDE_MODEL in .env if a different tier is desired (e.g. for cost).
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")

# Fast model used for short, customer-facing conversational replies (asking
# for order info, confirming an order, drafting the final decision reply).
# Decision-making / structured-JSON tool calls stay on CLAUDE_MODEL — only
# free-text prose generation moves to Haiku for latency.
FAST_REPLY_MODEL = os.environ.get("FAST_REPLY_MODEL", "claude-haiku-4-5-20251001")

DB_PATH = Path(os.environ.get("DB_PATH", BACKEND_DIR / "db" / "melodymaxgear.db"))
SCHEMA_PATH = BACKEND_DIR / "db" / "schema.sql"
POLICY_PATH = Path(os.environ.get("POLICY_PATH", PROJECT_ROOT / "policy" / "refund_policy.md"))

FLASK_HOST = os.environ.get("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.environ.get("FLASK_PORT", "5000"))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "true").lower() == "true"

SUPPORT_EMAIL = "support@melodymaxgear.com"

# Manager escalation triggers
MANAGER_APPROVAL_THRESHOLD = float(os.environ.get("MANAGER_APPROVAL_THRESHOLD", "500"))
NO_RECEIPT_HIGH_VALUE_THRESHOLD = float(os.environ.get("NO_RECEIPT_HIGH_VALUE_THRESHOLD", "150"))

CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")

# Voice pipeline — purely additive input/output layer around the existing
# text /chat endpoint. Whisper transcribes speech to text before /chat ever
# sees it; ElevenLabs speaks the already-complete reply text after /chat has
# finished. Neither key is required for the app to run — voice endpoints
# fail gracefully (the frontend falls back to text-only) if unset.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
# Rachel — a calm, professional voice well suited to customer support.
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
