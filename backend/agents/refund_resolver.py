"""Refund Resolver agent.

Takes the Policy Validator's structured result (plus manager-request and
pushback signals from the Orchestrator) and makes the final call: approved,
denied, escalated, or split. Drafts the exact customer-facing reply and
records everything via the refund_decision tool in a single forced tool
call — this agent is the only one that talks to the customer.
"""

import json

import anthropic

from backend.config import CLAUDE_MODEL, MANAGER_APPROVAL_THRESHOLD, SUPPORT_EMAIL
from backend.tools import refund_decision
from backend.utils.logger import ReasoningLogger

SYSTEM_PROMPT = f"""You are the Refund Resolver agent for MelodyMax Gear, a musical instrument and \
pro audio retailer. You are the only agent that speaks to the customer. You receive the Policy \
Validator's structured eligibility result and must make the final decision, then record it by \
calling refund_decision exactly once. You always call refund_decision — never respond without it.

## Decision rules, in priority order

1. If wants_manager is true, the customer explicitly asked to speak with a manager. status MUST be \
"escalated" regardless of policy eligibility. escalation_reason: "Customer explicitly requested a \
manager."
2. Else if the validation result carries escalation_reasons (missing receipt on a high-value item, \
refund amount at or above ${MANAGER_APPROVAL_THRESHOLD:.0f}, or an ambiguous condition/defect claim on an \
opened or used item), status MUST be "escalated". escalation_reason: summarize the specific \
trigger(s) from escalation_reasons.
3. Else if the validation is for a bundle (is_bundle true) and components disagree (one eligible, \
one not), status MUST be "split". The customer_reply MUST clearly state BOTH outcomes in one \
coherent message — do not make the customer piece it together.
4. Else if eligible is true, status is "approved". Say what they get (full refund / store credit / \
exchange) and the expected timeline (5-7 business days to the original payment method for cash \
refunds).
5. Else, status is "denied".

## Denial tone — hold the line, professionally

When status is "denied" (including when the customer is pushing back on a denial they've already \
received — see is_pushback below), the customer_reply must:
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

## Escalation tone

When status is "escalated", tell the customer plainly that this needs a manager's review, give a \
one-sentence reason, and set the expectation that a manager will follow up — do not promise an \
outcome.

## Split tone

When status is "split", walk through each component's outcome in plain language in a single \
message: what's eligible and what isn't, and why.

decision_details should be a JSON object capturing whatever structured breakdown is useful for the \
admin dashboard (refund_type, amount, per-component outcomes for split decisions, etc.)."""

client = anthropic.Anthropic()


def resolve(
    conversation_id: str,
    customer: dict,
    order: dict,
    customer_message: str,
    validation: dict | None,
    wants_manager: bool,
    is_pushback: bool,
    prior_decision: dict | None,
    logger: ReasoningLogger,
) -> dict:
    context = {
        "customer": customer,
        "order": order,
        "customer_message": customer_message,
        "policy_validation": validation,
        "wants_manager": wants_manager,
        "is_pushback": is_pushback,
        "prior_decision": prior_decision,
    }

    logger.log("Refund Resolver", "received_validation", {
        "order_number": order.get("order_number"),
        "wants_manager": wants_manager,
        "is_pushback": is_pushback,
    })

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        tools=[refund_decision.SCHEMA],
        tool_choice={"type": "tool", "name": "refund_decision"},
        messages=[{"role": "user", "content": json.dumps(context, indent=2, default=str)}],
    )

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        logger.log("Refund Resolver", "error", "Model did not call refund_decision as required.")
        raise RuntimeError("Refund Resolver: model did not call refund_decision.")

    tool_input = dict(tool_use.input)
    tool_input["conversation_id"] = conversation_id
    tool_input.setdefault("request_text", customer_message)
    tool_input.setdefault("order_number", order.get("order_number"))
    tool_input.setdefault("customer_id", customer.get("id"))

    logger.log("Refund Resolver", "decision", {
        "status": tool_input.get("status"),
        "decision_summary": tool_input.get("decision_summary"),
    })

    decision_record = refund_decision.run(tool_input)
    logger.set_refund_request_id(decision_record["id"])
    logger.log("Refund Resolver", "refund_decision_recorded", decision_record)

    return {
        "status": tool_input.get("status"),
        "customer_reply": tool_input.get("customer_reply"),
        "decision_record": decision_record,
    }
