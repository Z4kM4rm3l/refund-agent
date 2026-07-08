"""Structured reasoning-log emission shared by every agent and tool.

Each log entry is (timestamp, agent_name, action, result). Entries are
persisted to reasoning_logs immediately (so GET /admin/logs always reflects
reality) and also collected in-memory so POST /chat can return the full
reasoning trace for a single turn alongside the reply.
"""

import json
from datetime import datetime, timezone

from backend.db.database import get_connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReasoningLogger:
    def __init__(self, conversation_id: str, refund_request_id: int | None = None):
        self.conversation_id = conversation_id
        self.refund_request_id = refund_request_id
        self.trace: list[dict] = []

    def set_refund_request_id(self, refund_request_id: int) -> None:
        self.refund_request_id = refund_request_id

    def log(self, agent_name: str, action: str, result) -> dict:
        serialized_result = result if isinstance(result, str) else json.dumps(result, default=str)
        timestamp = _now()

        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO reasoning_logs
                       (conversation_id, refund_request_id, timestamp, agent_name, action, result)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (self.conversation_id, self.refund_request_id, timestamp, agent_name, action, serialized_result),
            )
            conn.commit()
        finally:
            conn.close()

        entry = {"timestamp": timestamp, "agent": agent_name, "action": action, "result": result}
        self.trace.append(entry)
        return entry
