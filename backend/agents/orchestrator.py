"""Orchestrator — master agent for the MelodyMax Gear Refund Agent.

Per customer message, the Orchestrator:
  1. Identifies the customer/order by calling the crm_lookup tool (raw
     function calling — Claude decides the lookup arguments from whatever
     identifying information is available).
  2. Classifies the message's intent (refund request, pushback on a prior
     decision in this conversation, an explicit request for a manager, or a
     general question).
  3. Routes refund-shaped requests to the Policy Validator, then the Refund
     Resolver; handles pushback and manager requests by re-invoking the
     Resolver with the appropriate override flags; answers general questions
     directly.

Every step emits a structured reasoning-log entry via ReasoningLogger so the
admin dashboard can show the full trace for a turn.
"""

import json
import re

import anthropic

from backend.agents import policy_validator, refund_resolver
from backend.config import CLAUDE_MODEL
from backend.tools import crm_lookup
from backend.utils.logger import ReasoningLogger

ORDER_NUMBER_PATTERN = re.compile(r"\bMMX-\d+\b", re.IGNORECASE)

CRM_SYSTEM_PROMPT = """You are the identification step of the Orchestrator agent for MelodyMax \
Gear customer support. Your only job is to call the crm_lookup tool to identify which customer and \
order this conversation is about.

Prefer identifiers already known (given to you explicitly) over guessing. If none are known, look \
for an order number (format MMX-##### ) or an email address in the customer's message and use that. \
If there is truly no identifying information anywhere — no known identifiers and nothing in the \
message — do not call any tool; just respond in one short sentence."""

CLASSIFY_SCHEMA = {
    "name": "classify_message",
    "description": "Classify the customer's latest message so the Orchestrator can route it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["refund_request", "general_question", "other"],
                "description": "refund_request if they want to return/refund/exchange an item or are describing a problem with a purchase.",
            },
            "claimed_issue": {"type": "string", "description": "Customer's stated reason for the return/complaint, short phrase. Empty string if none."},
            "wants_manager": {"type": "boolean", "description": "True only if they explicitly ask to speak with a manager/supervisor/human escalation."},
            "is_pushback": {"type": "boolean", "description": "True only if prior_decision_this_conversation is not null AND the customer is objecting to or disputing that prior decision."},
        },
        "required": ["intent", "wants_manager", "is_pushback"],
        "additionalProperties": False,
    },
}

CLASSIFY_SYSTEM_PROMPT = """You are the intent-classification step of the Orchestrator agent for \
MelodyMax Gear customer support. Classify the customer's latest message by calling classify_message. \
Always call it."""

GENERAL_REPLY_SYSTEM_PROMPT = """You are the Orchestrator agent for MelodyMax Gear, a musical \
instrument and pro audio retailer, answering a general (non-refund) customer message. Be warm, \
concise, and helpful. If relevant, you may reference the customer's known order. If the question is \
actually about a return or refund, gently invite them to describe what they'd like to return."""


class Orchestrator:
    def __init__(self):
        self.client = anthropic.Anthropic()

    def handle_message(
        self,
        conversation_id: str,
        message: str,
        state: dict,
        customer_id: int | None = None,
        email: str | None = None,
        order_number: str | None = None,
    ) -> dict:
        logger = ReasoningLogger(conversation_id)
        logger.log("Orchestrator", "received_message", {"message": message})

        customer, order = self._resolve_identity(state, message, customer_id, email, order_number, logger)

        if customer is None or order is None:
            reply = (
                "I'd be glad to help with that — could you share your order number "
                "(e.g. MMX-10001) or the email on your account so I can pull up your order?"
            )
            logger.log("Orchestrator", "needs_identification", reply)
            return {
                "reply": reply,
                "status": "needs_identification",
                "customer": customer,
                "order": order,
                "reasoning_log": logger.trace,
                "decision_record": None,
            }

        classification = self._classify(message, state, logger)
        wants_manager = bool(classification.get("wants_manager"))
        is_pushback = bool(classification.get("is_pushback")) and state.get("last_decision") is not None
        intent = classification.get("intent", "other")

        if is_pushback:
            logger.log("Orchestrator", "routing_decision", "Customer is pushing back on a prior decision — Refund Resolver will hold the line.")
            result = refund_resolver.resolve(
                conversation_id, customer, order, message,
                validation=state.get("last_validation"),
                wants_manager=wants_manager,
                is_pushback=True,
                prior_decision=state.get("last_decision"),
                logger=logger,
            )
        elif wants_manager or intent == "refund_request":
            logger.log("Orchestrator", "routing_decision", "Refund-shaped request — routing to Policy Validator, then Refund Resolver.")
            validation = policy_validator.validate(order, message, conversation_id, logger)
            result = refund_resolver.resolve(
                conversation_id, customer, order, message,
                validation=validation["validation"],
                wants_manager=wants_manager,
                is_pushback=False,
                prior_decision=state.get("last_decision"),
                logger=logger,
            )
            state["last_validation"] = validation["validation"]
        else:
            logger.log("Orchestrator", "routing_decision", "General question — replying directly, no refund pipeline needed.")
            reply = self._general_reply(message, customer, order, logger)
            result = {"status": "info", "customer_reply": reply, "decision_record": None}

        state["customer"] = customer
        state["order"] = order
        if result.get("decision_record"):
            state["last_decision"] = {
                "status": result["status"],
                "customer_reply": result["customer_reply"],
                "order_number": order.get("order_number"),
            }

        return {
            "reply": result["customer_reply"],
            "status": result["status"],
            "customer": customer,
            "order": order,
            "reasoning_log": logger.trace,
            "decision_record": result.get("decision_record"),
        }

    # -- identification -----------------------------------------------------

    def _resolve_identity(self, state, message, customer_id, email, order_number, logger):
        mentioned_order = self._mentioned_order_number(message)
        target_order_number = order_number or mentioned_order

        cached_order = state.get("order")
        if cached_order and not customer_id and not email and (
            not target_order_number or target_order_number.upper() == cached_order.get("order_number", "").upper()
        ):
            logger.log("Orchestrator", "reused_context", {"order_number": cached_order.get("order_number")})
            return state.get("customer"), cached_order

        known = {"customer_id": customer_id, "email": email, "order_number": target_order_number}
        user_content = (
            "Known identifiers (any may be null): " + json.dumps(known) +
            "\nCustomer message: " + message
        )

        response = self.client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=CRM_SYSTEM_PROMPT,
            tools=[crm_lookup.SCHEMA],
            tool_choice={"type": "auto"},
            messages=[{"role": "user", "content": user_content}],
        )

        tool_use = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_use is None:
            logger.log("Orchestrator", "crm_lookup_skipped", "No identifying information available in this message.")
            return None, None

        logger.log("Orchestrator", "crm_lookup_call", tool_use.input)
        result = crm_lookup.run(tool_use.input)
        logger.log("Orchestrator", "crm_lookup_result", result)

        if "error" in result:
            return None, None

        customer = result["customer"]
        order = self._select_order(result["orders"], target_order_number)
        return customer, order

    @staticmethod
    def _mentioned_order_number(message: str) -> str | None:
        match = ORDER_NUMBER_PATTERN.search(message)
        return match.group(0).upper() if match else None

    @staticmethod
    def _select_order(orders: list, target_order_number: str | None):
        if not orders:
            return None
        if target_order_number:
            for o in orders:
                if o["order_number"].upper() == target_order_number.upper():
                    return o
        return orders[0]

    # -- classification -------------------------------------------------------

    def _classify(self, message: str, state: dict, logger: ReasoningLogger) -> dict:
        context = {
            "customer_message": message,
            "prior_decision_this_conversation": state.get("last_decision"),
        }
        response = self.client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=CLASSIFY_SYSTEM_PROMPT,
            tools=[CLASSIFY_SCHEMA],
            tool_choice={"type": "tool", "name": "classify_message"},
            messages=[{"role": "user", "content": json.dumps(context, default=str)}],
        )
        tool_use = next((b for b in response.content if b.type == "tool_use"), None)
        classification = tool_use.input if tool_use else {"intent": "other", "wants_manager": False, "is_pushback": False}
        logger.log("Orchestrator", "classify_message", classification)
        return classification

    # -- general conversation -------------------------------------------------

    def _general_reply(self, message: str, customer: dict, order: dict, logger: ReasoningLogger) -> str:
        context = {"customer": customer, "order": order, "customer_message": message}
        response = self.client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=GENERAL_REPLY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(context, default=str)}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        logger.log("Orchestrator", "general_response", text)
        return text
