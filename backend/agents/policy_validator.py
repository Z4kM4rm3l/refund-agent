"""Policy Validator agent.

Given an order and the customer's stated reason for the return, this agent's
only job is to call the policy_check tool with correctly-derived arguments
and hand back a structured validation result. It never talks to the customer
directly and never makes the final approve/deny/escalate call — that's the
Refund Resolver's job.
"""

import json

import anthropic

from backend.config import CLAUDE_MODEL
from backend.tools import policy_check
from backend.utils.logger import ReasoningLogger

SYSTEM_PROMPT = """You are the Policy Validator agent for MelodyMax Gear, a musical instrument \
and pro audio retailer. You do not talk to customers. Your only job is to call the policy_check \
tool with the correct arguments, derived from the order record and the customer's message, so the \
return can be checked against store policy.

Rules:
- Always call policy_check. Never respond without calling it.
- Map the order's fields onto the tool's input schema (category, price, purchase_date, has_receipt, \
has_original_packaging, is_holiday_purchase).
- Extract customer confessions regarding packaging carefully: If the customer explicitly notes \
they "threw away", "discarded", or "don't have" the packaging, you MUST set `has_original_packaging=false`.
- The order record deliberately does NOT include the item's condition — in a real return, the store \
doesn't know whether the item is still sealed, opened, or used until the customer says so. You must \
derive the `condition` argument (one of: unopened, opened, used, used_vintage, floor_model, \
open_box, display, activated, damaged_defective, opened_creased) SOLELY from the customer's own \
words in their message. Look for cues like "never opened it" / "still sealed" -> unopened; "I opened \
it" / "tried it" / "used it a few times" -> opened; a software license they installed or registered \
-> activated. Never source condition from anything other than what the customer said. If their \
message gives no usable cue at all, default to "opened" — treat "unopened" as a claim that needs an \
affirmative statement from the customer, not an assumption.
- Read the customer's message and distill their stated reason for the return into a short \
claimed_issue string (e.g. "controller pads unresponsive, believes it's defective"). If they \
didn't give a reason, leave claimed_issue empty.
- If the order is a bundle (is_bundle is true), pass is_bundle=true and bundle_components through \
unchanged so hardware and software are each evaluated against their own policy section."""

client = anthropic.Anthropic()


def validate(order: dict, customer_message: str, conversation_id: str, logger: ReasoningLogger) -> dict:
    logger.log("Policy Validator", "received_order", {"order_number": order.get("order_number"), "category": order.get("category")})

    user_content = (
        "Order record:\n" + json.dumps(order, indent=2) +
        "\n\nCustomer's message:\n" + customer_message
    )

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[policy_check.SCHEMA],
        tool_choice={"type": "tool", "name": "policy_check"},
        messages=[{"role": "user", "content": user_content}],
    )

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        logger.log("Policy Validator", "error", "Model did not call policy_check as required.")
        raise RuntimeError("Policy Validator: model did not call policy_check.")

    logger.log("Policy Validator", "policy_check_call", tool_use.input)

    validation_result = policy_check.run(tool_use.input)

    logger.log("Policy Validator", "policy_check_result", validation_result)

    return {
        "policy_check_input": tool_use.input,
        "validation": validation_result,
    }