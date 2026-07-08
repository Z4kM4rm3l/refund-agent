"""Flask app for the MelodyMax Gear Refund Agent — backend only.

Endpoints:
    POST /chat          Run one turn of the agent loop for a conversation.
    GET  /admin/logs     All refund decisions and reasoning logs, for the admin dashboard.
    GET  /customers      All CRM profiles + orders, for demo purposes.

Conversation state (which customer/order this thread is about, and the last
decision made) is kept in a simple in-memory dict keyed by conversation_id.
This is sufficient for a single-process demo; a production build would move
it to a real session store.
"""

import json
import traceback
import uuid

from flask import Flask, jsonify, request
from flask_cors import CORS

from backend.agents.orchestrator import Orchestrator
from backend.config import CORS_ORIGINS, FLASK_DEBUG, FLASK_HOST, FLASK_PORT
from backend.db.database import get_connection

app = Flask(__name__)
CORS(app, origins=CORS_ORIGINS)

orchestrator = Orchestrator()

# conversation_id -> {"customer": dict|None, "order": dict|None,
#                      "last_decision": dict|None, "last_validation": dict|None}
CONVERSATIONS: dict[str, dict] = {}


@app.route("/chat", methods=["POST"])
def chat():
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    conversation_id = payload.get("conversation_id") or str(uuid.uuid4())
    state = CONVERSATIONS.setdefault(conversation_id, {
        "customer": None, "order": None, "last_decision": None, "last_validation": None,
    })

    try:
        result = orchestrator.handle_message(
            conversation_id=conversation_id,
            message=message,
            state=state,
            customer_id=payload.get("customer_id"),
            email=payload.get("email"),
            order_number=payload.get("order_number"),
        )
    except Exception as exc:  # noqa: BLE001 — surface agent failures to the caller for this demo
        traceback.print_exc()
        return jsonify({"error": str(exc), "conversation_id": conversation_id}), 500

    return jsonify({
        "conversation_id": conversation_id,
        "reply": result["reply"],
        "status": result["status"],
        "customer": result["customer"],
        "order": result["order"],
        "reasoning_log": result["reasoning_log"],
        "decision": result["decision_record"],
    })


@app.route("/admin/logs", methods=["GET"])
def admin_logs():
    conn = get_connection()
    try:
        refund_requests = [dict(r) for r in conn.execute(
            "SELECT * FROM refund_requests ORDER BY created_at DESC"
        ).fetchall()]
        for r in refund_requests:
            if r.get("decision_details"):
                try:
                    r["decision_details"] = json.loads(r["decision_details"])
                except (TypeError, json.JSONDecodeError):
                    pass

        reasoning_logs = [dict(r) for r in conn.execute(
            "SELECT * FROM reasoning_logs ORDER BY id DESC"
        ).fetchall()]
        for entry in reasoning_logs:
            if entry.get("result"):
                try:
                    entry["result"] = json.loads(entry["result"])
                except (TypeError, json.JSONDecodeError):
                    pass
    finally:
        conn.close()

    return jsonify({"refund_requests": refund_requests, "reasoning_logs": reasoning_logs})


@app.route("/customers", methods=["GET"])
def customers():
    conn = get_connection()
    try:
        customer_rows = conn.execute("SELECT * FROM customers ORDER BY id").fetchall()
        order_rows = conn.execute("SELECT * FROM orders ORDER BY customer_id").fetchall()
    finally:
        conn.close()

    orders_by_customer: dict[int, list] = {}
    for row in order_rows:
        order = dict(row)
        if order.get("bundle_components"):
            try:
                order["bundle_components"] = json.loads(order["bundle_components"])
            except (TypeError, json.JSONDecodeError):
                pass
        orders_by_customer.setdefault(order["customer_id"], []).append(order)

    result = []
    for row in customer_rows:
        customer = dict(row)
        customer["orders"] = orders_by_customer.get(customer["id"], [])
        result.append(customer)

    return jsonify({"customers": result})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
