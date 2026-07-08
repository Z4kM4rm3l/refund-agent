"""Flask app for the MelodyMax Gear Refund Agent — backend only.

Endpoints:
    POST /chat          Run one turn of the agent loop for a conversation, streamed as NDJSON.
    GET  /admin/logs     All refund decisions and reasoning logs, for the admin dashboard.
    GET  /customers      All CRM profiles + orders, for demo purposes.

Conversation state (which customer/order this thread is about, and the last
decision made) is kept in a simple in-memory dict keyed by conversation_id.
This is sufficient for a single-process demo; a production build would move
it to a real session store.

/chat streaming format: the response body is newline-delimited JSON
(one `application/x-ndjson` object per line), so the client can render the
customer-facing reply as it's generated instead of waiting for the whole
turn to finish. Event shapes, in the order they're emitted:

    {"type": "conversation_id", "conversation_id": "..."}
    {"type": "context", "customer": {...}|null, "order": {...}|null}
    {"type": "reasoning", "entries": [...]}            (may repeat)
    {"type": "reply_delta", "text": "..."}             (repeats — one chunk per token/line)
    {"type": "final", "status": "...", "decision": {...}|null}
    {"type": "error", "error": "..."}                  (only on failure, terminal)
"""

import json
import threading
import traceback
import uuid

from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS

from backend.agents.orchestrator import Orchestrator
from backend.config import CORS_ORIGINS, FLASK_DEBUG, FLASK_HOST, FLASK_PORT
from backend.db.database import get_connection

app = Flask(__name__)
CORS(app, origins=CORS_ORIGINS)

orchestrator = Orchestrator()

# conversation_id -> {"customer": dict|None, "order": dict|None, "claimed_issue": str|None,
#                      "last_decision": dict|None, "last_validation": dict|None, "history": list}
CONVERSATIONS: dict[str, dict] = {}

# Running with threaded=True means two /chat requests for the SAME
# conversation_id can be handled by different OS threads concurrently — e.g.
# a customer double-sends, or a slow turn is still in flight when the next
# one arrives. Without serialization they race on the same `state` dict
# (one thread's partial read/write interleaves with another's), corrupting
# it and producing wrong routing (asking for info already given, silently
# dropping a decision, etc). One lock per conversation_id keeps unrelated
# conversations fully concurrent while forcing same-conversation turns to
# process strictly in order, which also matches real conversational
# semantics — you can't process message 2 before message 1 has landed.
_conversation_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _get_conversation_lock(conversation_id: str) -> threading.Lock:
    with _locks_guard:
        lock = _conversation_locks.get(conversation_id)
        if lock is None:
            lock = threading.Lock()
            _conversation_locks[conversation_id] = lock
        return lock


@app.route("/chat", methods=["POST"])
def chat():
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    conversation_id = payload.get("conversation_id") or str(uuid.uuid4())
    state = CONVERSATIONS.setdefault(conversation_id, {
        "customer": None, "order": None, "claimed_issue": None,
        "last_decision": None, "last_validation": None, "history": [],
    })
    customer_id = payload.get("customer_id")
    email = payload.get("email")
    order_number = payload.get("order_number")

    def generate():
        yield json.dumps({"type": "conversation_id", "conversation_id": conversation_id}) + "\n"

        lock = _get_conversation_lock(conversation_id)
        if not lock.acquire(timeout=90):
            yield json.dumps({
                "type": "error",
                "error": "This conversation is still processing a previous message — please wait a moment and try again.",
            }) + "\n"
            return

        try:
            for event in orchestrator.handle_message_stream(
                conversation_id=conversation_id,
                message=message,
                state=state,
                customer_id=customer_id,
                email=email,
                order_number=order_number,
            ):
                yield json.dumps(event, default=str) + "\n"
        except Exception as exc:  # noqa: BLE001 — surface agent failures to the caller for this demo
            traceback.print_exc()
            yield json.dumps({"type": "error", "error": str(exc)}) + "\n"
        finally:
            lock.release()

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


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
    # threaded=True so a streaming /chat request doesn't block /admin/logs polling.
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG, threaded=True)
