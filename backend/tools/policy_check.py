"""policy_check tool — validates a refund request against refund_policy.md.

The policy document's rules are encoded as a deterministic Python rule engine
(one evaluator per product category) so the same request always gets the same
answer — the Policy Validator agent calls this tool rather than asking Claude
to freehand-interpret the markdown. The tool also returns the source policy
text so agents can cite it, and flags conditions that require manager
escalation per the store's escalation policy.

Categories match the section headings in policy/refund_policy.md exactly.

Interpretation note — holiday extension: the policy states holiday purchases
get "an extended return window through January 31." Rather than depending on
wall-clock proximity to a specific calendar Jan 31 (which would make this
demo's behavior depend on what day it happens to be run), holiday purchases
are given a flat extended window of HOLIDAY_EXTENDED_WINDOW_DAYS in place of
the category's normal window.
"""

from datetime import date

from backend.config import (
    MANAGER_APPROVAL_THRESHOLD,
    NO_RECEIPT_HIGH_VALUE_THRESHOLD,
    POLICY_PATH,
)

HOLIDAY_EXTENDED_WINDOW_DAYS = 75

DEFECT_KEYWORDS = [
    "faulty", "broken", "defective", "doesn't work", "does not work", "not working",
    "malfunction", "dead on arrival", "doa", "damaged", "unresponsive",
    "stopped working", "won't turn on", "wont turn on", "won't power on",
    "broken screen", "cracked", "cuts out", "fails to",
]

POLICY_SECTION_HEADINGS = {
    "Stringed & Fretted Instruments": "STRINGED & FRETTED INSTRUMENTS",
    "Amplifiers & Electronics": "AMPLIFIERS & ELECTRONICS",
    "Software & Digital Downloads": "SOFTWARE & DIGITAL DOWNLOADS",
    "Accessories": "ACCESSORIES (strings, picks, cables, straps)",
    "Drums & Percussion": "DRUMS & PERCUSSION",
    "Pro Audio & Recording Equipment": "PRO AUDIO & RECORDING EQUIPMENT",
    "Keyboards & MIDI Controllers": "KEYBOARDS & MIDI CONTROLLERS",
    "Sheet Music & Books": "SHEET MUSIC & BOOKS",
}

_BUNDLE_COMPONENT_SCHEMA = {
    "type": "object",
    "properties": {
        "component": {"type": "string", "description": "Name of this bundle component, e.g. 'MIDI Controller (hardware)'."},
        "category": {"type": "string", "enum": list(POLICY_SECTION_HEADINGS.keys())},
        "price": {"type": "number"},
        "condition": {"type": "string", "description": "unopened | opened | used | used_vintage | floor_model | open_box | display | activated | damaged_defective | opened_creased"},
        "activated": {"type": "boolean", "description": "Whether a software/license component has been activated or registered."},
        "claimed_issue": {"type": "string", "description": "Customer's stated problem with this specific component, if any."},
    },
    "required": ["component", "category", "price", "condition"],
    "additionalProperties": False,
}

SCHEMA = {
    "name": "policy_check",
    "description": (
        "Validate a refund request against MelodyMax Gear's refund policy. Pass the order's "
        "category, price, purchase_date, condition, receipt/packaging status, and the "
        "customer's stated reason for the return (claimed_issue). For a bundle purchase "
        "(e.g. a MIDI controller sold with a bundled software license), set is_bundle=true and "
        "pass bundle_components so hardware and software are evaluated against their own "
        "policy sections independently, as required for a split decision. Returns eligibility, "
        "refund type, the applicable policy citation, and any manager-escalation flags."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": list(POLICY_SECTION_HEADINGS.keys())},
            "price": {"type": "number"},
            "purchase_date": {"type": "string", "description": "ISO date YYYY-MM-DD."},
            "condition": {"type": "string", "description": "unopened | opened | used | used_vintage | floor_model | open_box | display | activated | damaged_defective | opened_creased"},
            "has_receipt": {"type": "boolean"},
            "has_original_packaging": {"type": "boolean"},
            "is_holiday_purchase": {"type": "boolean", "default": False},
            "claimed_issue": {"type": "string", "description": "Customer's stated reason for the return, verbatim or summarized."},
            "is_bundle": {"type": "boolean", "default": False},
            "bundle_components": {"type": "array", "items": _BUNDLE_COMPONENT_SCHEMA},
        },
        "required": ["category", "price", "purchase_date", "condition", "has_receipt", "has_original_packaging"],
        "additionalProperties": False,
    },
}


def get_policy_text() -> str:
    """Return the raw policy document text, for agents that want to cite it directly."""
    return POLICY_PATH.read_text(encoding="utf-8")


def _days_since(purchase_date: str) -> int:
    purchased = date.fromisoformat(purchase_date)
    return (date.today() - purchased).days


def _is_ambiguous_condition_claim(claimed_issue: str, condition: str) -> bool:
    if not claimed_issue:
        return False
    text = claimed_issue.lower()
    has_defect_language = any(keyword in text for keyword in DEFECT_KEYWORDS)
    return has_defect_language and condition in ("opened", "used", "used_vintage")


def _window(base_days: int, is_holiday_purchase: bool) -> int:
    return HOLIDAY_EXTENDED_WINDOW_DAYS if is_holiday_purchase else base_days


def _eval_stringed(item: dict) -> dict:
    condition = item["condition"]
    days = _days_since(item["purchase_date"])

    if condition == "used_vintage":
        return _result(False, "none", "Used/vintage instruments: all sales final, no returns.", days)
    if condition in ("floor_model", "open_box", "display"):
        return _result(True, "store_credit", "Open-box or display models: store credit only, no cash refund.", days)
    if not item["has_receipt"]:
        return _result(False, "none", "Original receipt required for all returns.", days)
    if condition != "unopened":
        return _result(False, "none", "Item must be unused and in original condition (with all original packaging and accessories) to qualify for a refund.", days)

    window = _window(45, item["is_holiday_purchase"])
    if days <= window and item["has_original_packaging"]:
        note = " (extended holiday return window applied)" if item["is_holiday_purchase"] and days > 45 else ""
        return _result(True, "full_refund", f"Unused, in original condition and packaging, within the {window}-day window{note}.", days)
    if not item["has_original_packaging"]:
        return _result(False, "none", "Original packaging and accessories are required for a refund.", days)
    return _result(False, "none", f"Outside the {window}-day return window ({days} days since purchase).", days)


def _eval_amplifiers(item: dict) -> dict:
    condition = item["condition"]
    days = _days_since(item["purchase_date"])

    if condition in ("visible_wear", "missing_components"):
        return _result(False, "none", "No returns on amplifiers with visible wear or missing components.", days)
    if not item["has_receipt"]:
        return _result(False, "none", "Original receipt required for all returns.", days)

    if condition == "unopened":
        if days <= 30:
            return _result(True, "full_refund", "Unopened, within the 30-day full-refund window.", days)
        return _result(False, "none", f"Outside the 30-day unopened return window ({days} days since purchase).", days)

    if condition == "opened":
        if days <= 15:
            return _result(True, "exchange_or_store_credit", "Opened amplifiers qualify for exchange or store credit within 15 days.", days)
        return _result(False, "none", f"Opened amplifiers are only eligible for exchange or store credit within 15 days ({days} days since purchase).", days)

    return _result(False, "none", "Amplifier condition does not qualify for a refund.", days)


def _eval_software(item: dict) -> dict:
    days = _days_since(item["purchase_date"])
    if item.get("activated") or item["condition"] == "activated":
        return _result(False, "none", "No refunds on activated or registered software licenses.", days)
    return _result(False, "none", "Software & digital downloads: all sales final, no exceptions.", days)


def _eval_accessories(item: dict) -> dict:
    condition = item["condition"]
    days = _days_since(item["purchase_date"])

    if condition == "opened":
        return _result(False, "none", "Opened accessories: no refund, no exchange.", days)
    if not item["has_receipt"]:
        return _result(False, "none", "Original receipt required for all returns.", days)
    if condition == "unopened" and days <= 15:
        return _result(True, "full_refund", "Unopened accessory within the 15-day return window.", days)
    return _result(False, "none", f"Outside the 15-day unopened accessory return window ({days} days since purchase).", days)


def _eval_drums(item: dict) -> dict:
    condition = item["condition"]
    days = _days_since(item["purchase_date"])
    is_cymbal = "cymbal" in item.get("product_name", "").lower() or "cymbal" in item.get("component", "").lower()

    if is_cymbal and condition == "opened":
        return _result(False, "none", "Cymbals: no returns once opened.", days)
    if not item["has_receipt"]:
        return _result(False, "none", "Original receipt required for all returns.", days)
    if condition == "unopened":
        if days <= 30 and item["has_original_packaging"]:
            return _result(True, "full_refund", "Unplayed and in original packaging, within the 30-day window.", days)
        if not item["has_original_packaging"]:
            return _result(False, "none", "Original packaging is required for a drums/percussion refund.", days)
        return _result(False, "none", f"Outside the 30-day unplayed return window ({days} days since purchase).", days)
    return _result(False, "none", "Item must be unplayed and in original packaging to qualify for a refund.", days)


def _eval_pro_audio(item: dict) -> dict:
    condition = item["condition"]
    days = _days_since(item["purchase_date"])

    if not item["has_receipt"]:
        return _result(False, "none", "Original receipt required for all returns.", days)
    if condition == "unopened":
        if days <= 30:
            return _result(True, "full_refund", "Unopened, within the 30-day full-refund window.", days)
        return _result(False, "none", f"Outside the 30-day unopened return window ({days} days since purchase).", days)
    if condition == "opened":
        if days <= 14:
            return _result(True, "store_credit", "Opened pro audio equipment qualifies for store credit within 14 days.", days)
        return _result(False, "none", f"Opened pro audio equipment is only eligible for store credit within 14 days ({days} days since purchase).", days)
    return _result(False, "none", "Item condition does not qualify for a refund.", days)


def _eval_keyboards(item: dict) -> dict:
    condition = item["condition"]
    days = _days_since(item["purchase_date"])

    if condition in ("floor_model", "open_box", "display"):
        return _result(False, "none", "Floor models and open-box purchases: all sales final, no refunds or exchanges.", days)
    if not item["has_receipt"]:
        return _result(False, "none", "Original receipt required for all returns.", days)

    if condition == "unopened":
        window = _window(30, item["is_holiday_purchase"])
        if days <= window and item["has_original_packaging"]:
            return _result(True, "full_refund", f"Unopened, in original packaging with all included accessories, within the {window}-day window.", days)
        if not item["has_original_packaging"]:
            return _result(False, "none", "Original packaging and included accessories are required for a refund.", days)
        return _result(False, "none", f"Outside the {window}-day unopened return window ({days} days since purchase).", days)

    if condition == "opened":
        window = _window(14, item["is_holiday_purchase"])
        if days <= window:
            return _result(True, "store_credit", f"Opened keyboards/controllers qualify for store credit only within {window} days.", days)
        return _result(False, "none", f"Opened keyboards/controllers are only eligible for store credit within {window} days ({days} days since purchase).", days)

    return _result(False, "none", "Item condition does not qualify for a refund.", days)


def _eval_sheet_music(item: dict) -> dict:
    condition = item["condition"]
    days = _days_since(item["purchase_date"])

    if condition == "damaged_defective":
        return _result(True, "exchange", "Damaged or defective items are eligible for exchange only, no cash refund.", days)
    if condition in ("opened", "opened_creased"):
        return _result(False, "none", "All sales final once packaging is opened or binding is creased.", days)
    if "digital" in item.get("product_name", "").lower():
        return _result(False, "none", "Digital sheet music downloads: all sales final, no exceptions.", days)
    if not item["has_receipt"]:
        return _result(False, "none", "Original receipt required for all returns.", days)
    if condition == "unopened" and days <= 15:
        return _result(True, "full_refund", "Unopened, with original receipt, within the 15-day window.", days)
    return _result(False, "none", f"Outside the 15-day unopened sheet music/books return window ({days} days since purchase).", days)


_EVALUATORS = {
    "Stringed & Fretted Instruments": _eval_stringed,
    "Amplifiers & Electronics": _eval_amplifiers,
    "Software & Digital Downloads": _eval_software,
    "Accessories": _eval_accessories,
    "Drums & Percussion": _eval_drums,
    "Pro Audio & Recording Equipment": _eval_pro_audio,
    "Keyboards & MIDI Controllers": _eval_keyboards,
    "Sheet Music & Books": _eval_sheet_music,
}


def _result(eligible: bool, refund_type: str, reason: str, days_since_purchase: int) -> dict:
    return {"eligible": eligible, "refund_type": refund_type, "reason": reason, "days_since_purchase": days_since_purchase}


def _evaluate_single_item(item: dict, check_ambiguous: bool = True) -> dict:
    category = item["category"]
    evaluator = _EVALUATORS.get(category)
    if evaluator is None:
        return {
            "eligible": False,
            "refund_type": "none",
            "reason": f"Unrecognized product category '{category}'.",
            "days_since_purchase": None,
            "policy_section": None,
            "requires_manager_review": False,
        }

    outcome = evaluator(item)
    outcome["policy_section"] = POLICY_SECTION_HEADINGS.get(category)
    outcome["category"] = category
    outcome["price"] = item["price"]

    # Bundle components skip this check: a bundle's hardware/software split is
    # already resolved by clear-cut rules (e.g. "opened controller -> store
    # credit within 14 days" applies regardless of why the customer is
    # returning it), so a defect claim there doesn't need manager review on
    # its own. Ambiguous-condition escalation is for standalone items where
    # the claim could plausibly change an otherwise-denied outcome.
    ambiguous = check_ambiguous and _is_ambiguous_condition_claim(item.get("claimed_issue", ""), item["condition"])
    outcome["requires_manager_review"] = ambiguous
    if ambiguous:
        outcome["ambiguous_condition_reason"] = (
            "Customer claims a defect/damage on an item that is opened or used — condition cannot be "
            "verified from records alone and requires manager review before a decision is finalized."
        )
    return outcome


def execute(
    category: str,
    price: float,
    purchase_date: str,
    condition: str,
    has_receipt: bool,
    has_original_packaging: bool,
    is_holiday_purchase: bool = False,
    claimed_issue: str = "",
    is_bundle: bool = False,
    bundle_components: list | None = None,
    product_name: str = "",
) -> dict:
    base_item = {
        "category": category,
        "price": price,
        "purchase_date": purchase_date,
        "condition": condition,
        "has_receipt": has_receipt,
        "has_original_packaging": has_original_packaging,
        "is_holiday_purchase": is_holiday_purchase,
        "claimed_issue": claimed_issue,
        "product_name": product_name,
    }

    escalation_reasons = []

    if is_bundle and bundle_components:
        components_result = []
        for component in bundle_components:
            comp_item = dict(base_item)
            comp_item.update(component)
            comp_item.setdefault("has_receipt", has_receipt)
            comp_item.setdefault("has_original_packaging", has_original_packaging)
            comp_item.setdefault("is_holiday_purchase", is_holiday_purchase)
            comp_item.setdefault("claimed_issue", component.get("claimed_issue", claimed_issue))
            comp_result = _evaluate_single_item(comp_item, check_ambiguous=False)
            comp_result["component"] = component.get("component")
            components_result.append(comp_result)
            if comp_result["requires_manager_review"]:
                escalation_reasons.append(
                    f"Ambiguous condition claim on '{component.get('component')}' requires manager review."
                )

        total_price = sum(c.get("price", 0) for c in bundle_components) or price
        if total_price >= MANAGER_APPROVAL_THRESHOLD:
            escalation_reasons.append(f"Bundle total (${total_price:.2f}) exceeds ${MANAGER_APPROVAL_THRESHOLD:.0f} — manager approval required.")
        if not has_receipt and total_price >= NO_RECEIPT_HIGH_VALUE_THRESHOLD:
            escalation_reasons.append("Missing receipt on a high-value bundle — manager review required.")

        return {
            "is_bundle": True,
            "components": components_result,
            "escalation_reasons": escalation_reasons,
            "requires_manager_review": bool(escalation_reasons),
            "policy_excerpt": (
                "MIDI controllers with registered software bundles: software component is non-refundable "
                "once activated, hardware only eligible for store credit within 14 days."
            ),
        }

    result = _evaluate_single_item(base_item)

    if result["eligible"] and price >= MANAGER_APPROVAL_THRESHOLD:
        escalation_reasons.append(f"Refund amount (${price:.2f}) exceeds ${MANAGER_APPROVAL_THRESHOLD:.0f} — manager approval required.")
    if not has_receipt and price >= NO_RECEIPT_HIGH_VALUE_THRESHOLD:
        escalation_reasons.append(
            f"Missing receipt on a high-value item (${price:.2f}) — manager review required to verify purchase."
        )
    if result["requires_manager_review"]:
        escalation_reasons.append(result.get("ambiguous_condition_reason", "Ambiguous condition claim requires manager review."))

    result["is_bundle"] = False
    result["escalation_reasons"] = escalation_reasons
    result["requires_manager_review"] = bool(escalation_reasons)
    return result


def run(tool_input: dict) -> dict:
    return execute(
        category=tool_input["category"],
        price=tool_input["price"],
        purchase_date=tool_input["purchase_date"],
        condition=tool_input["condition"],
        has_receipt=tool_input["has_receipt"],
        has_original_packaging=tool_input["has_original_packaging"],
        is_holiday_purchase=tool_input.get("is_holiday_purchase", False),
        claimed_issue=tool_input.get("claimed_issue", ""),
        is_bundle=tool_input.get("is_bundle", False),
        bundle_components=tool_input.get("bundle_components"),
        product_name=tool_input.get("product_name", ""),
    )
