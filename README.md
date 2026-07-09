# MelodyMax Gear — Refund Agent

AI customer support agent for a Guitar Center-style music retailer that processes or denies
e-commerce refunds, using the Claude API with raw function calling across a 3-agent
architecture (Orchestrator → Policy Validator → Refund Resolver). Backend only for now —
Flask API + SQLite, no frontend yet.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then add your ANTHROPIC_API_KEY
python -m backend.db.seed   # creates + seeds backend/db/melodymaxgear.db
python -m backend.app       # starts the Flask server on :5000
```

## Endpoints

- `POST /chat` — `{ "message": "...", "conversation_id"?: "...", "customer_id"?, "email"?, "order_number"? }`
  Runs one turn of the agent loop and returns the reply, resolved customer/order, the
  recorded decision, and the full structured reasoning trace for that turn.
- `GET /admin/logs` — every refund decision ever recorded, plus every reasoning-log entry
  (timestamp, agent, action, result) from every agent.
- `GET /customers` — all 15 seeded CRM profiles with their orders, for demo purposes.

Conversation state (which customer/order a thread is about, and the last decision made) is
kept in-memory per `conversation_id` for the life of the process — reuse the same
`conversation_id` across turns to test pushback handling.

## Demo data

`backend/db/seed.py` seeds 15 customers/orders covering: 5 clean approvals, 4 denials
(including an activated software license — the pushback scenario), 3 escalations ($500+,
missing receipt on a high-value item, and an ambiguous condition claim — the last one needs
a defect-sounding message at chat time to trigger, since it depends on what the customer
says), 2 wildcards (holiday extended-window approval, missing receipt on a low-value item),
and 1 split-eligibility MIDI controller + bundled software license bundle (order `MMX-10015`).

## Architecture

- `backend/tools/crm_lookup.py` — queries SQLite for customer + order data.
- `backend/tools/policy_check.py` — deterministic rule engine encoding `policy/refund_policy.md`,
  including bundle-aware split evaluation and escalation-trigger detection.
- `backend/tools/refund_decision.py` — records the final decision (and customer-facing reply) to SQLite.
- `backend/agents/policy_validator.py` — forces a `policy_check` tool call and returns the structured result.
- `backend/agents/refund_resolver.py` — decides approve/deny/escalate/split and drafts the reply, via a forced `refund_decision` tool call.
- `backend/agents/orchestrator.py` — identifies the customer (via `crm_lookup`), classifies intent
  (refund request / pushback / manager request / general question), and routes accordingly.

Every agent call emits structured reasoning-log entries (`timestamp`, `agent_name`, `action`,
`result`) to the `reasoning_logs` table via `backend/utils/logger.py`, streamed back in each
`/chat` response and queryable in full via `/admin/logs`.
