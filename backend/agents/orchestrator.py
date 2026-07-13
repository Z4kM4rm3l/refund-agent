"""Orchestrator — master agent for the MelodyMax Gear Refund Agent.

Drives a natural, multi-turn conversation rather than resolving a refund in
a single shot. Per customer message, the Orchestrator:

  1. Identifies the customer/order by calling the crm_lookup tool (raw
     function calling — Claude decides the lookup arguments from whatever
     identifying information is available). Knowing *who* the customer is
     (e.g. via a pre-selected demo profile) is not the same as knowing
     *which order* they mean — the order is only considered identified once
     the customer has actually named it (an order number or item), so the
     conversation still asks for it even when the customer is already known.
  2. If the order isn't identified yet, asks for it and stops for this turn.
  3. Once the order is known but the reason for return isn't, confirms what
     was found in the CRM and asks why — and stops for this turn.
  4. Once both the order and the reason are known, classifies for pushback /
     manager-request signals and routes to the Policy Validator, then the
     Refund Resolver, to reach a final decision.

Every step emits a structured reasoning-log entry via ReasoningLogger so the
admin dashboard can show the full trace for a turn.
"""

import json
import re
from datetime import date
from concurrent.futures import ThreadPoolExecutor

import anthropic

from backend.agents import policy_validator, refund_resolver
from backend.config import CLAUDE_MODEL, FAST_REPLY_MODEL
from backend.tools import crm_lookup
from backend.utils.logger import ReasoningLogger

# Made the hyphen optional here as well so the pipeline matches "MMX10007" smoothly
ORDER_NUMBER_PATTERN = re.compile(r"\bMMX-?\d+\b", re.IGNORECASE)

CRM_SYSTEM_PROMPT = """You are the identification step of the Orchestrator agent for MelodyMax \
Gear customer support. Your only job is to call the crm_lookup tool to identify which customer and \
order this conversation is about.

Prefer identifiers already known (given to you explicitly) over guessing. If both a known customer_id \
and an order_number are available, prefer looking up by order_number for precision. If none are \
known, look for an order number (format MMX-##### ) or an email address in the customer's message \
and use that. If there is truly no identifying information anywhere — no known identifiers and \
nothing in the message — do not call any tool; just respond in one short sentence."""

CLASSIFY_SCHEMA = {
    "name": "classify_message",
    "description": "Classify the customer's latest message so the Orchestrator can route it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["refund_request", "general_question", "other"],
                "description": "refund_request if they want to return/refund/exchange an item, are describing a problem with a purchase, or are responding to an agent's request regarding the item's condition, packaging, or return eligibility state.",
            },
            "claimed_issue": {"type": "string", "description": "Customer's explicitly stated reason for the return/complaint (why they want to return it and/or the item's condition), short phrase. Merely naming an order number or product ('I got the Stratocaster, it's MMX-10001') is identification, NOT a reason — return an empty string unless the customer actually says what's wrong or why they're returning it."},
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
concise, and helpful. Speak naturally and do NOT overuse or repeat the customer's name if they have \
already been greeted. If relevant, you may reference the customer's known order. If the question is \
actually about a return or refund, gently invite them to describe what they'd like to return. Output \
ONLY the message itself — no JSON, no preamble."""

ASK_FOR_ORDER_SYSTEM_PROMPT = """You are the Orchestrator agent for MelodyMax Gear, a musical \
instrument and pro audio retailer, at the very start of a refund conversation. You don't yet know \
which order this is about. Write a short, warm reply (1-2 sentences) that acknowledges what they \
said and asks for their order number (format MMX-#####) or the name of the item they purchased, so \
you can look it up. Use the customer's name naturally for a first greeting, but do not over-index on it. \
If wants_manager is true, briefly acknowledge that you'll get a manager involved, but explain you still \
need the order first so the manager has something to review. Output ONLY the message itself — no JSON, no preamble."""

CONFIRM_ORDER_SYSTEM_PROMPT = """You are the Orchestrator agent for MelodyMax Gear. \
You have successfully found the customer's order details in our CRM. Look directly at the 'order' context object provided to you.

Your task is to write a warm, human-like confirmation response (1-2 sentences) explicitly stating the exact item name found in their order record (e.g., "I see your Fender Mustang LT25 Amplifier").

CRITICAL PIPELINE CONSTRAINTS:
1. Speak naturally like a human peer. Do NOT include or repeat the customer's name in this message since they have already been greeted earlier in the conversation.
2. If the 'order' object contains only a single item, you already know EXACTLY what they want to return. Do NOT ask them what item they want to return, do NOT ask them to confirm what is in the order, and do NOT ask if they want to return a specific item or the entire order. 
3. Completely ignore any stray or unrelated words from previous turns (like "hat"). Trust ONLY the 'order' payload data from the CRM.
4. Conclude your message by asking a single, clean, open-ended question inviting them to describe why they want to request a return and what condition the item is currently in (e.g., "What prompted the return, and is the amplifier still unopened or has it been used?").

Output ONLY the text of the message itself — no JSON, no preamble."""


class Orchestrator:
    def __init__(self):
        self.client = anthropic.Anthropic()

    def handle_message_stream(
        self,
        conversation_id: str,
        message: str,
        state: dict,
        customer_id: int | None = None,
        email: str | None = None,
        order_number: str | None = None,
    ):
        """Generator driving one conversation turn, yielding streaming events."""
        logger = ReasoningLogger(conversation_id)
        logger.log("Orchestrator", "received_message", {"message": message})

        state.setdefault("history", [])
        state["history"].append({"role": "customer", "text": message})

        had_prior_context = state.get("customer") is not None and state.get("order") is not None
        had_prior_decision = state.get("last_decision") is not None
        prior_order_number = state.get("order", {}).get("order_number") if had_prior_context else None

        customer, order = self._resolve_identity(state, message, customer_id, email, order_number, logger)
        yield {"type": "context", "customer": customer, "order": order}

        if order and prior_order_number and order.get("order_number") != prior_order_number:
            state["claimed_issue"] = None
            state["last_validation"] = None
            state["last_decision"] = None
            state["reason_provided"] = False
            state["order_identified"] = False
            had_prior_context = False
            had_prior_decision = False

        classification = self._classify(message, state, logger)
        wants_manager = bool(classification.get("wants_manager")) or bool(state.get("wants_manager"))
        state["wants_manager"] = wants_manager
        is_pushback = bool(classification.get("is_pushback")) and had_prior_decision
        intent = classification.get("intent", "other")
        message_claimed_issue = (classification.get("claimed_issue") or "").strip()

        if is_pushback and customer and order:
            logger.log("Orchestrator", "routing_decision", "Customer is pushing back on a prior decision — Refund Resolver will hold the line.")
            reply_text = yield from self._stream_resolver_and_capture_reply(
                conversation_id, customer, order, message,
                state.get("last_validation"), wants_manager, True, state.get("last_decision"), logger, state, None
            )
            state["history"].append({"role": "agent", "text": reply_text})
            state["customer"], state["order"] = customer, order
            return

        if customer is None:
            if intent == "general_question" and not wants_manager:
                logger.log("Orchestrator", "routing_decision", "General question — replying directly, no refund pipeline needed.")
                yield {"type": "reasoning", "entries": list(logger.trace)}
                reply_text = ""
                for chunk in self._general_reply_stream(message, None, None, state["history"], logger):
                    reply_text += chunk
                    yield {"type": "reply_delta", "text": chunk}
                state["history"].append({"role": "agent", "text": reply_text})
                yield {"type": "reasoning", "entries": list(logger.trace)}
                yield {"type": "final", "status": "info", "decision": None}
                return

            logger.log("Orchestrator", "needs_identification", "No customer could be identified from this message.")
            reply = (
                "I'd be glad to help with that — could you share the email on your account or "
                "your order number (e.g. MMX-10001) so I can pull things up?"
            )
            state["history"].append({"role": "agent", "text": reply})
            yield {"type": "reasoning", "entries": list(logger.trace)}
            yield {"type": "reply_delta", "text": reply}
            yield {"type": "final", "status": "needs_identification", "decision": None}
            return

        if order is None:
            if intent == "general_question" and not had_prior_context and not wants_manager:
                logger.log("Orchestrator", "routing_decision", "General question — replying directly, no refund pipeline needed.")
                yield {"type": "reasoning", "entries": list(logger.trace)}
                reply_text = ""
                for chunk in self._general_reply_stream(message, customer, None, state["history"], logger):
                    reply_text += chunk
                    yield {"type": "reply_delta", "text": chunk}
                state["history"].append({"role": "agent", "text": reply_text})
                yield {"type": "reasoning", "entries": list(logger.trace)}
                yield {"type": "final", "status": "info", "decision": None}
                return

            logger.log("Orchestrator", "routing_decision", "Order not yet identified — asking the customer for it.")
            yield {"type": "reasoning", "entries": list(logger.trace)}
            reply_text = ""
            for chunk in self._ask_for_order_stream(customer, wants_manager, state["history"], logger):
                reply_text += chunk
                yield {"type": "reply_delta", "text": chunk}
            state["history"].append({"role": "agent", "text": reply_text})
            state["customer"] = customer
            yield {"type": "reasoning", "entries": list(logger.trace)}
            yield {"type": "final", "status": "gathering_order", "decision": None}
            return

        state["customer"] = customer
        state["order"] = order

        if wants_manager:
            logger.log("Orchestrator", "routing_decision", "Customer requested a manager — escalating now.")
            validation = policy_validator.validate(order, message, conversation_id, logger)
            state["last_validation"] = validation["validation"]
            reply_text = yield from self._stream_resolver_and_capture_reply(
                conversation_id, customer, order, message,
                validation["validation"], True, False, state.get("last_decision"), logger, state, None
            )
            state["history"].append({"role": "agent", "text": reply_text})
            return

        known_issue = (state.get("claimed_issue") or "").strip() or message_claimed_issue

        if not known_issue and not state.get("order_identified"):
            state["reason_provided"] = False
            state["order_identified"] = True
            logger.log("Orchestrator", "routing_decision", "Order identified — confirming details and asking for the reason for return.")
            yield {"type": "reasoning", "entries": list(logger.trace)}
            reply_text = ""
            for chunk in self._confirm_order_ask_reason_stream(customer, order, state["history"], logger):
                reply_text += chunk
                yield {"type": "reply_delta", "text": chunk}
            state["history"].append({"role": "agent", "text": reply_text})
            yield {"type": "reasoning", "entries": list(logger.trace)}
            yield {"type": "final", "status": "gathering_reason", "decision": None}
            return

        if not known_issue:
            known_issue = message_claimed_issue or message

        state["claimed_issue"] = known_issue
        state["reason_provided"] = True
        state["order_identified"] = True
        
        logger.log("Orchestrator", "routing_decision", {
            "order_identified": True,
            "reason_provided": True,
            "claimed_issue": known_issue,
            "note": "Order and reason both verified — routing directly to Policy Validator and executing pipeline.",
        })
        augmented_message = message if known_issue.strip() == message.strip() else f"{message}\n\nReason for return: {known_issue}"
        
        with ThreadPoolExecutor(max_workers=1) as executor:
            validation_future = executor.submit(
                policy_validator.validate, order, augmented_message, conversation_id, logger
            )
            
            reply_text = yield from self._stream_resolver_and_capture_reply(
                conversation_id, customer, order, augmented_message,
                None, False, False, state.get("last_decision"), logger, state, validation_future
            )
            
        state["history"].append({"role": "agent", "text": reply_text})

    def _stream_resolver_and_capture_reply(self, conversation_id, customer, order, message, validation, wants_manager, is_pushback, prior_decision, logger, state, validation_future=None):
        """Relay refund_resolver.resolve_stream's events and return the full reply text."""
        if validation_future is not None:
            resolved_validation = validation_future.result()
            validation = resolved_validation["validation"]
            state["last_validation"] = validation

        is_first_agent_message = not any(m.get("role") == "agent" for m in state.get("history", []))
        reply_text = ""
        for event in refund_resolver.resolve_stream(
            conversation_id, customer, order, message, validation, wants_manager, is_pushback, prior_decision, logger,
            is_first_agent_message=is_first_agent_message,
        ):
            if event["type"] == "reply_delta":
                reply_text += event["text"]
            if event["type"] == "final" and event.get("decision"):
                state["last_decision"] = {
                    "status": event["status"],
                    "customer_reply": event["decision"].get("customer_reply"),
                    "order_number": order.get("order_number"),
                }
            yield event
        return reply_text

    # -- identification -----------------------------------------------------

    def _resolve_identity(self, state, message, customer_id, email, order_number, logger):
        mentioned_order = self._mentioned_order_number(message)
        target_order_number = order_number or mentioned_order

        cached_customer = state.get("customer")
        cached_order = state.get("order")
        identity_matches_cache = cached_customer is not None and (
            customer_id is None or customer_id == cached_customer.get("id")
        ) and (
            email is None or email.lower() == (cached_customer.get("email") or "").lower()
        )
        if cached_order and identity_matches_cache and (
            not target_order_number or target_order_number.upper() == cached_order.get("order_number", "").upper()
        ):
            logger.log("Orchestrator", "reused_context", {"order_number": cached_order.get("order_number")})
            return cached_customer, cached_order

        known = {"customer_id": customer_id, "email": email, "order_number": target_order_number}
        user_content = (
            "Known identifiers (any may be null): " + json.dumps(known) +
            "\nCustomer message: " + message
        )

        response = self.client.messages.create(
            model=FAST_REPLY_MODEL,
            max_tokens=256,
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
        order = self._select_order(result["orders"], target_order_number, message)
        return customer, order

    @staticmethod
    def _mentioned_order_number(message: str) -> str | None:
        match = ORDER_NUMBER_PATTERN.search(message)
        return match.group(0).upper() if match else None

    @staticmethod
    def _select_order(orders: list, target_order_number: str | None, message: str = ""):
        if not orders:
            return None

        if target_order_number:
            for o in orders:
                if o["order_number"].upper() == target_order_number.upper():
                    return o
            return None

        if not message:
            return None

        message_words = set(re.findall(r"[a-z]{3,}", message.lower()))
        if not message_words:
            return None

        scored = []
        for o in orders:
            product_words = set(re.findall(r"[a-z]{3,}", o["product_name"].lower()))
            overlap = len(product_words & message_words)
            if overlap > 0:
                scored.append((overlap, o))

        if not scored:
            return None
        best_score = max(s for s, _ in scored)
        best_matches = [o for s, o in scored if s == best_score]
        return best_matches[0] if len(best_matches) == 1 else None

    # -- classification -------------------------------------------------------

    def _classify(self, message: str, state: dict, logger: ReasoningLogger) -> dict:
        context = {
            "customer_message": message,
            "prior_decision_this_conversation": state.get("last_decision"),
        }
        response = self.client.messages.create(
            model=FAST_REPLY_MODEL,
            max_tokens=200,
            system=CLASSIFY_SYSTEM_PROMPT,
            tools=[CLASSIFY_SCHEMA],
            tool_choice={"type": "tool", "name": "classify_message"},
            messages=[{"role": "user", "content": json.dumps(context, default=str)}],
        )
        tool_use = next((b for b in response.content if b.type == "tool_use"), None)
        classification = tool_use.input if tool_use else {"intent": "other", "wants_manager": False, "is_pushback": False}
        logger.log("Orchestrator", "classify_message", classification)
        return classification

    # -- conversational turns (all fast-model, short replies) -----------------

    def _general_reply_stream(self, message: str, customer: dict | None, order: dict | None, history: list, logger: ReasoningLogger):
        context = {"customer": customer, "order": order, "customer_message": message, "conversation_so_far": history}
        full_text = ""
        with self.client.messages.stream(
            model=FAST_REPLY_MODEL,
            max_tokens=300,
            system=GENERAL_REPLY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(context, default=str)}],
        ) as stream:
            for chunk in stream.text_stream:
                full_text += chunk
                yield chunk
        logger.log("Orchestrator", "general_response", full_text)

    def _ask_for_order_stream(self, customer: dict | None, wants_manager: bool, history: list, logger: ReasoningLogger):
        context = {"customer": customer, "wants_manager": wants_manager, "conversation_so_far": history}
        full_text = ""
        with self.client.messages.stream(
            model=FAST_REPLY_MODEL,
            max_tokens=200,
            system=ASK_FOR_ORDER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(context, default=str)}],
        ) as stream:
            for chunk in stream.text_stream:
                full_text += chunk
                yield chunk
        logger.log("Orchestrator", "ask_for_order", full_text)

    def _confirm_order_ask_reason_stream(self, customer: dict, order: dict, history: list, logger: ReasoningLogger):
        days_since_purchase = None
        try:
            days_since_purchase = (date.today() - date.fromisoformat(order["purchase_date"])).days
        except (KeyError, ValueError, TypeError):
            pass

        context = {
            "customer": customer,
            "order": order,
            "days_since_purchase": days_since_purchase,
            "conversation_so_far": history,
        }
        full_text = ""
        with self.client.messages.stream(
            model=FAST_REPLY_MODEL,
            max_tokens=200,
            system=CONFIRM_ORDER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(context, default=str)}],
        ) as stream:
            for chunk in stream.text_stream:
                full_text += chunk
                yield chunk
        logger.log("Orchestrator", "confirm_order_ask_reason", full_text)