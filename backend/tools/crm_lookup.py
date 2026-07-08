"""crm_lookup tool — looks up a customer's profile and order history.

Queries SQLite directly by customer ID, email, or order number. This is the
tool the Orchestrator calls first for nearly every conversation turn, since
almost every refund decision needs the customer's identity and the specific
order in question.
"""

import json

from backend.db.database import get_connection

SCHEMA = {
    "name": "crm_lookup",
    "description": (
        "Look up a MelodyMax Gear customer's profile and order history in the CRM. "
        "Provide at least one of customer_id, email, or order_number. Looking up by "
        "order_number also returns the owning customer's profile. Returns an error "
        "if no matching record is found."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "customer_id": {"type": "integer", "description": "Internal numeric customer ID, if known."},
            "email": {"type": "string", "description": "Customer's email address."},
            "order_number": {"type": "string", "description": "Order number, e.g. MMX-10001."},
        },
        "additionalProperties": False,
    },
}


def _row_to_customer(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "phone": row["phone"],
        "member_since": row["member_since"],
    }


def _row_to_order(row) -> dict:
    order = {
        "id": row["id"],
        "order_number": row["order_number"],
        "product_name": row["product_name"],
        "category": row["category"],
        "price": row["price"],
        "purchase_date": row["purchase_date"],
        "condition": row["condition"],
        "has_receipt": bool(row["has_receipt"]),
        "has_original_packaging": bool(row["has_original_packaging"]),
        "is_holiday_purchase": bool(row["is_holiday_purchase"]),
        "is_bundle": bool(row["is_bundle"]),
    }
    if row["is_bundle"] and row["bundle_components"]:
        order["bundle_components"] = json.loads(row["bundle_components"])
    return order


def execute(customer_id: int | None = None, email: str | None = None, order_number: str | None = None) -> dict:
    if not any([customer_id, email, order_number]):
        return {"error": "Provide at least one of customer_id, email, or order_number."}

    conn = get_connection()
    try:
        customer_row = None

        if order_number:
            order_row = conn.execute(
                "SELECT * FROM orders WHERE order_number = ?", (order_number,)
            ).fetchone()
            if not order_row:
                return {"error": f"No order found with order_number '{order_number}'."}
            customer_row = conn.execute(
                "SELECT * FROM customers WHERE id = ?", (order_row["customer_id"],)
            ).fetchone()
            return {
                "customer": _row_to_customer(customer_row),
                "orders": [_row_to_order(order_row)],
            }

        if customer_id:
            customer_row = conn.execute(
                "SELECT * FROM customers WHERE id = ?", (customer_id,)
            ).fetchone()
        elif email:
            customer_row = conn.execute(
                "SELECT * FROM customers WHERE email = ?", (email,)
            ).fetchone()

        if not customer_row:
            identifier = customer_id if customer_id else email
            return {"error": f"No customer found for '{identifier}'."}

        order_rows = conn.execute(
            "SELECT * FROM orders WHERE customer_id = ? ORDER BY purchase_date DESC",
            (customer_row["id"],),
        ).fetchall()

        return {
            "customer": _row_to_customer(customer_row),
            "orders": [_row_to_order(r) for r in order_rows],
        }
    finally:
        conn.close()


def run(tool_input: dict) -> dict:
    return execute(
        customer_id=tool_input.get("customer_id"),
        email=tool_input.get("email"),
        order_number=tool_input.get("order_number"),
    )
