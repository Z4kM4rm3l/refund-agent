# MelodyMax Gear — Refund Agent Vertical Slice

A fully functional three-agent AI customer support system for a professional audio and musical instrument retailer. The application automatically approves or denies e-commerce refund requests using deterministic policy logic and raw tool calling via the Anthropic Claude API.

The system is powered by a Flask backend, SQLite database, and a responsive frontend with integrated voice capabilities.

---

# Features

## 🤖 Multi-Agent Architecture

Three specialized agents collaborate to resolve refund requests:

- **Orchestrator** — Intent routing, conversation state management, and execution flow
- **Policy Validator** — Rule extraction and deterministic policy validation
- **Refund Resolver** — Final decision-making and streaming customer responses

## 💬 Persistent Conversations

- Tracks conversation state using `conversation_id`
- Supports multi-turn interactions
- Handles customer pushback without losing context

## 🎙️ Voice Processing

Integrated speech pipeline featuring:

- **Whisper STT** for speech-to-text
- **ElevenLabs TTS** for streaming text-to-speech
- Spoken order number normalization (e.g. `MMX10001` → `MMX-10001`)
- Dynamic currency formatting

## 📊 Real-Time Admin Dashboard

Live agent reasoning panel displaying:

- Timestamp
- Agent name
- Action performed
- Result

This provides complete visibility into the internal decision pipeline.

## 🎨 Frontend

- Responsive chat interface
- Customer and agent conversation threads
- Automatic scroll management
- Persistent Light/Dark mode via `localStorage`

### Voice Interaction

- **Microphone button** — click to record a spoken message; audio is transcribed via Whisper and sent through the same chat pipeline as typed text
- **Speaker toggle** — enables or disables automatic voice playback of agent responses (default: on)
- Agent replies are streamed as text first, then converted to speech via ElevenLabs once the full response is available
- All voice features degrade gracefully to text-only mode if API keys are not configured or a request fails

---

# Tech Stack

- Python
- Flask
- SQLite
- Anthropic Claude API
- Whisper
- ElevenLabs
- HTML/CSS/JavaScript

---

# Setup

## 1. Install Dependencies

```bash
pip install -r requirements.txt
```

## 2. Configure Environment Variables

Copy the example configuration:

```bash
cp .env.example .env
```

Populate the following variables:

```text
ANTHROPIC_API_KEY=...
CLAUDE_MODEL=claude-sonnet-4-6

OPENAI_API_KEY=...

ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...
```

> **Note:** `OPENAI_API_KEY` is required for voice input (Whisper transcription). `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` are required for voice output (spoken responses). All three voice-related keys are optional — the app runs in text-only mode if they are not configured, with graceful fallback and no errors.

## 3. Initialize the Database

Seed the SQLite database with mock CRM data:

```bash
python -m backend.db.seed
```

This creates:

```
backend/db/melodymaxgear.db
```

The database contains **15 customer profiles** designed to exercise a variety of refund scenarios.

## 4. Run the Application

```bash
python -m backend.app
```

The backend will be available at:

```
http://localhost:5000
```

## 5. Run the Frontend

In a separate terminal, install frontend dependencies and start the dev server:

```bash
cd frontend
npm install
npm run dev
```

The frontend will be available at:
```
http://localhost:5173
```

Vite proxies all `/api` requests to the Flask backend on port 5000, so both servers must be running simultaneously.

---

# Seeded Test Scenarios

The database includes **15 mock CRM profiles** covering common and edge-case refund requests.

## ✅ Standard Approvals (5)

Policy-compliant returns.

Example:

- `MMX-10001`
- Fender Stratocaster
- **$479.99**

---

## ❌ Policy Denials (4)

Examples include:

- Returns outside the allowed window
- Activated digital software licenses
- Customer pushback scenarios

Example:

- `MMX-10007`
- 25 days after purchase

---

## 👨‍💼 Manager Escalations (3)

Automatically escalated cases such as:

- Refunds over **$500**
- Missing proof of purchase
- Ambiguous damage claims

Example:

- `MMX-10010`
- Taylor Guitar
- **$999.00**

---

## 🎁 Special Cases (3)

Complex scenarios including:

- Holiday return extensions
- Mixed hardware/software bundles
- Split eligibility rules

Example:

- `MMX-10015`

---

# API

## `POST /chat`

Processes customer messages through the multi-agent pipeline.

### Request

```json
{
  "message": "...",
  "conversation_id": "...",
  "customer_id": 123
}
```

`customer_id` is optional.

### Response

Returns:

- Streamed assistant response
- Parsed CRM information
- Decision metrics
- Complete multi-agent reasoning trace

---

## `GET /admin/logs`

Returns the history of refund decisions together with detailed agent reasoning.

---

## `GET /customers`

Returns the seeded CRM profiles for dashboard rendering and debugging.

---

# Project Architecture

## Agents

### `backend/agents/orchestrator.py`

- Routes customer intent
- Performs CRM identity lookup
- Manages conversation flow
- Coordinates downstream agents

### `backend/agents/policy_validator.py`

- Extracts structured policy inputs
- Maps free-form conversation into deterministic rule checks

### `backend/agents/refund_resolver.py`

- Issues approvals, denials, or manager escalations
- Streams customer-facing responses

---

## Tools

### `backend/tools/policy_check.py`

Deterministic refund policy engine responsible for:

- Return window validation
- Bundle handling
- Holiday return extensions
- Rule enforcement

### `backend/tools/crm_lookup.py`

Retrieves customer and order information from SQLite.

### `backend/tools/refund_decision.py`

Persists refund decisions and updates transaction state.
