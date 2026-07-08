"""refund_decision tool — records the final refund decision to the database.

Called once by the Refund Resolver agent per conversation, after policy
validation is complete. Writes (or updates, if called again for the same
conversation) a row in refund_requests that the admin dashboard reads from.
"""

import json

from backend.db.database import get_connection

SCHEMA = {
    "name": "refund_decision",
    "description": (
        "Record the final refund decision for this customer conversation. Call this exactly "
        "once a final decision has been reached: approved, denied, escalated, or split "
        "(part approved/credited, part denied — e.g. a hardware+software bundle). This is the "
        "system of record read by the admin dashboard."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string"},
            "customer_id": {"type": "integer"},
            "order_number": {"type": "string"},
            "request_text": {"type": "string", "description": "The customer's refund request, summarized."},
            "status": {"type": "string", "enum": ["approved", "denied", "escalated", "split"]},
            "decision_summary": {"type": "string", "description": "One-paragraph plain-English summary of the outcome, for the admin dashboard."},
            "customer_reply": {"type": "string", "description": "The exact message to send back to the customer. Warm, professional, on-brand for MelodyMax Gear."},
            "decision_details": {
                "type": "object",
                "description": "Structured breakdown: refund_type, amount, per-component outcomes for split decisions, etc.",
                "additionalProperties": True,
            },
            "policy_reasoning": {"type": "string", "description": "The policy section(s) and rule(s) applied."},
            "escalation_reason": {"type": "string", "description": "Why this needs manager review, if status is 'escalated'."},
        },
        "required": ["conversation_id", "request_text", "status", "decision_summary", "customer_reply", "policy_reasoning"],
        "additionalProperties": False,
    },
}


def execute(
    conversation_id: str,
    request_text: str,
    status: str,
    decision_summary: str,
    customer_reply: str,
    policy_reasoning: str,
    customer_id: int | None = None,
    order_number: str | None = None,
    decision_details: dict | None = None,
    escalation_reason: str = "",
) -> dict:
    conn = get_connection()
    try:
        order_id = None
        if order_number:
            order_row = conn.execute(
                "SELECT id, customer_id FROM orders WHERE order_number = ?", (order_number,)
            ).fetchone()
            if order_row:
                order_id = order_row["id"]
                if customer_id is None:
                    customer_id = order_row["customer_id"]

        details = dict(decision_details or {})
        details["customer_reply"] = customer_reply

        cur = conn.execute(
            """INSERT INTO refund_requests
                   (conversation_id, customer_id, order_id, order_number, request_text, status,
                    decision_summary, decision_details, policy_reasoning, escalation_reason, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                conversation_id, customer_id, order_id, order_number, request_text, status,
                decision_summary, json.dumps(details), policy_reasoning, escalation_reason,
            ),
        )
        conn.commit()
        refund_request_id = cur.lastrowid

        return {
            "id": refund_request_id,
            "conversation_id": conversation_id,
            "status": status,
            "decision_summary": decision_summary,
            "customer_reply": customer_reply,
            "recorded": True,
        }
    finally:
        conn.close()


def run(tool_input: dict) -> dict:
    return execute(
        conversation_id=tool_input["conversation_id"],
        request_text=tool_input["request_text"],
        status=tool_input["status"],
        decision_summary=tool_input["decision_summary"],
        customer_reply=tool_input["customer_reply"],
        policy_reasoning=tool_input["policy_reasoning"],
        customer_id=tool_input.get("customer_id"),
        order_number=tool_input.get("order_number"),
        decision_details=tool_input.get("decision_details"),
        escalation_reason=tool_input.get("escalation_reason", ""),
    )
