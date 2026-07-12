"""Refund Resolver agent.

Takes the Policy Validator's structured result (plus manager-request and
pushback signals from the Orchestrator) and makes the final call: approved,
denied, escalated, or split. This agent is the only one that talks to the
customer, and it does so in two steps so the customer-facing message can be
streamed token by token:

  1. Decide — one forced `refund_decision` tool call determines status,
     decision_summary, decision_details, policy_reasoning, and
     escalation_reason. This is structured JSON with no customer-facing
     prose, so there's nothing meaningful to stream here.
  2. Draft the reply — a second, plain-text call composes the actual
     customer-facing message given the decision from step 1. This call uses
     `client.messages.stream()` and its text is yielded chunk by chunk, so
     the caller can relay real tokens to the HTTP response as they arrive.
     It runs on FAST_REPLY_MODEL (Haiku), not the main decision model —
     these are short, tone-driven replies, not policy reasoning, so the
     smaller/faster model keeps end-to-end turn latency down.

Once the reply is fully drafted, the decision (status/summary/reasoning) and
the drafted reply are written to the database via refund_decision.execute().
"""

import json

import anthropic

from backend.config import CLAUDE_MODEL, FAST_REPLY_MODEL, MANAGER_APPROVAL_THRESHOLD, SUPPORT_EMAIL
from backend.tools import refund_decision
from backend.utils.logger import ReasoningLogger

DECISION_SYSTEM_PROMPT = f"""You are the decision-making step of the Refund Resolver agent for \
MelodyMax Gear, a musical instrument and pro audio retailer. You receive the Policy Validator's \
structured eligibility result and must make the final call, then record it by calling \
refund_decision exactly once. You always call refund_decision — never respond without it.

A separate step drafts the actual customer-facing message, so for the customer_reply field write \
only a brief one-sentence internal placeholder (e.g. "Reply drafted separately.") — it will not be \
shown to the customer, so don't spend effort on it.

## Decision rules, in priority order

1. If wants_manager is true, the customer explicitly asked to speak with a manager. status MUST be \
"escalated" regardless of policy eligibility. escalation_reason: "Customer explicitly requested a \
manager."
2. Else if the validation result carries escalation_reasons (missing receipt on a high-value item, \
refund amount at or above ${MANAGER_APPROVAL_THRESHOLD:.0f}, or an ambiguous condition/defect claim on an \
opened or used item), status MUST be "escalated". escalation_reason: summarize the specific \
trigger(s) from escalation_reasons.
3. Else if the validation is for a bundle (is_bundle true) and components disagree (one eligible, \
one not), status MUST be "split".
4. Else if eligible is true, status is "approved".
5. Else, status is "denied".

decision_summary should be a clear one-paragraph internal summary of the outcome and why, for the \
admin dashboard.

decision_details should be a JSON object capturing whatever structured breakdown is useful for the \
admin dashboard (refund_type, amount, per-component outcomes for split decisions, etc.).

policy_reasoning should cite the specific policy section(s) and rule(s) applied."""

REPLY_SYSTEM_PROMPT = f"""You are the Refund Resolver agent for MelodyMax Gear, a musical instrument \
and pro audio retailer, drafting the customer-facing reply for a refund decision that has already \
been made (given to you in the `decision` field below). Output ONLY the message itself — no JSON, no \
headers, no meta-commentary, no "Here is the reply:" preamble. Write it as plain prose ready to send \
directly to the customer right now (light markdown like **bold** for amounts/product names is fine).

Greeting: check is_first_agent_message in the context. Only if it is true may you open with a \
greeting like "Hi Jenna,". If it is false, the customer has already been greeted earlier in this \
conversation — do NOT greet them again. Start directly with the substance: the decision, the \
reason, or the next steps. No "Hi [name]," no "Thanks for reaching out," no re-introduction.

Tone by decision status:

APPROVED — Say what they get (full refund / store credit / exchange) and the expected timeline \
(5-7 business days to the original payment method for cash refunds).

DENIED — hold the line, professionally. This applies whether it's the first denial or the customer \
is pushing back on a denial they've already received (see is_pushback in the context):
- Acknowledge the customer's frustration genuinely, without being dismissive.
- Restate the specific policy reason clearly and factually (cite the rule, e.g. "our digital \
download policy is a strict no-refund policy once a license has been activated").
- Make clear you are not able to override the policy yourself.
- Offer {SUPPORT_EMAIL} as a formal feedback/appeal channel — every denial reply must include it.
- Never repeat the same canned sentence twice in one conversation, never sound robotic, never cave \
just because the customer pushes back harder. If is_pushback is true, you are holding the same line \
as before, with more empathy, not reopening the decision.

Reference tone (adapt, don't copy verbatim):
"I completely understand how frustrating that feels, and I'm sorry the software didn't meet your \
expectations. Unfortunately our digital download policy is a strict no-refund policy once a license \
has been activated — this applies regardless of usage time and is consistent with industry standards \
for software licensing. I'm not able to override this policy, but I don't want you to feel unheard. \
If you'd like to share your feedback or make a formal appeal, our customer experience team reviews \
every submission at {SUPPORT_EMAIL}. While I can't guarantee a different outcome, your feedback does \
reach real people and influences how we handle future cases."

ESCALATED — tell the customer plainly that this needs a manager's review, give a one-sentence \
reason, and set the expectation that a manager will follow up — do not promise an outcome.

SPLIT — walk through each component's outcome in plain language in a single message: what's \
eligible and what isn't, and why. Do not make the customer piece it together."""

client = anthropic.Anthropic()


def resolve_stream(
    conversation_id: str,
    customer: dict,
    order: dict,
    customer_message: str,
    validation: dict | None,
    wants_manager: bool,
    is_pushback: bool,
    prior_decision: dict | None,
    logger: ReasoningLogger,
    is_first_agent_message: bool = False,
):
    """Generator yielding streaming events while deciding and replying.

    Yields dicts of the form:
      {"type": "reasoning", "entries": [...]}      — a fresh snapshot of the full trace so far
      {"type": "reply_delta", "text": "..."}        — one chunk of the customer-facing reply
      {"type": "final", "status": ..., "decision": {...}}  — the recorded decision
    """
    context = {
        "customer": customer,
        "order": order,
        "customer_message": customer_message,
        "policy_validation": validation,
        "wants_manager": wants_manager,
        "is_pushback": is_pushback,
        "prior_decision": prior_decision,
        "is_first_agent_message": is_first_agent_message,
    }

    logger.log("Refund Resolver", "received_validation", {
        "order_number": order.get("order_number"),
        "wants_manager": wants_manager,
        "is_pushback": is_pushback,
    })

    # Step 1 — decide. Forced tool call, not streamed: structured JSON only.
    decision_response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1000,
        system=DECISION_SYSTEM_PROMPT,
        tools=[refund_decision.SCHEMA],
        tool_choice={"type": "tool", "name": "refund_decision"},
        messages=[{"role": "user", "content": json.dumps(context, indent=2, default=str)}],
    )
    tool_use = next((b for b in decision_response.content if b.type == "tool_use"), None)
    if tool_use is None:
        logger.log("Refund Resolver", "error", "Model did not call refund_decision as required.")
        raise RuntimeError("Refund Resolver: model did not call refund_decision.")

    decision_fields = dict(tool_use.input)
    logger.log("Refund Resolver", "decision", {
        "status": decision_fields.get("status"),
        "decision_summary": decision_fields.get("decision_summary"),
    })

    yield {"type": "reasoning", "entries": list(logger.trace)}

    # Step 2 — draft the reply. Plain text, genuinely streamed token by token.
    reply_context = {
        **context,
        "decision": {
            "status": decision_fields.get("status"),
            "decision_summary": decision_fields.get("decision_summary"),
            "policy_reasoning": decision_fields.get("policy_reasoning"),
            "decision_details": decision_fields.get("decision_details"),
            "escalation_reason": decision_fields.get("escalation_reason"),
        },
    }

    full_reply = ""
    with client.messages.stream(
        model=FAST_REPLY_MODEL,
        max_tokens=300,
        system=REPLY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(reply_context, indent=2, default=str)}],
    ) as stream:
        for chunk in stream.text_stream:
            full_reply += chunk
            yield {"type": "reply_delta", "text": chunk}

    logger.log("Refund Resolver", "reply_composed", full_reply)

    decision_record = refund_decision.execute(
        conversation_id=conversation_id,
        request_text=customer_message,
        status=decision_fields.get("status"),
        decision_summary=decision_fields.get("decision_summary"),
        customer_reply=full_reply,
        policy_reasoning=decision_fields.get("policy_reasoning"),
        customer_id=customer.get("id"),
        order_number=order.get("order_number"),
        decision_details=decision_fields.get("decision_details"),
        escalation_reason=decision_fields.get("escalation_reason", ""),
    )
    logger.set_refund_request_id(decision_record["id"])
    logger.log("Refund Resolver", "refund_decision_recorded", decision_record)

    yield {"type": "reasoning", "entries": list(logger.trace)}
    yield {"type": "final", "status": decision_record["status"], "decision": decision_record}
