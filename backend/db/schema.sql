-- MelodyMax Gear Refund Agent — SQLite schema

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS reasoning_logs;
DROP TABLE IF EXISTS refund_requests;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    phone         TEXT,
    member_since  TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per purchased line item. Bundle purchases (e.g. a MIDI controller
-- sold with a bundled DAW license) store the per-component breakdown as JSON
-- in bundle_components so the policy engine can evaluate hardware and
-- software eligibility separately within a single order.
CREATE TABLE orders (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id             INTEGER NOT NULL REFERENCES customers(id),
    order_number            TEXT NOT NULL UNIQUE,
    product_name            TEXT NOT NULL,
    category                TEXT NOT NULL,
    price                   REAL NOT NULL,
    purchase_date           TEXT NOT NULL,
    condition               TEXT NOT NULL DEFAULT 'unopened',
    has_receipt             INTEGER NOT NULL DEFAULT 1,
    has_original_packaging  INTEGER NOT NULL DEFAULT 1,
    is_holiday_purchase     INTEGER NOT NULL DEFAULT 0,
    is_bundle               INTEGER NOT NULL DEFAULT 0,
    bundle_components       TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE refund_requests (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id     TEXT NOT NULL,
    customer_id         INTEGER REFERENCES customers(id),
    order_id            INTEGER REFERENCES orders(id),
    order_number        TEXT,
    request_text        TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    decision_summary    TEXT,
    decision_details    TEXT,
    policy_reasoning    TEXT,
    escalation_reason   TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE reasoning_logs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id     TEXT NOT NULL,
    refund_request_id   INTEGER REFERENCES refund_requests(id),
    timestamp           TEXT NOT NULL,
    agent_name          TEXT NOT NULL,
    action              TEXT NOT NULL,
    result              TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_orders_customer_id ON orders(customer_id);
CREATE INDEX idx_orders_order_number ON orders(order_number);
CREATE INDEX idx_refund_requests_conversation_id ON refund_requests(conversation_id);
CREATE INDEX idx_reasoning_logs_conversation_id ON reasoning_logs(conversation_id);
