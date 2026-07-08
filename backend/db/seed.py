"""Seed the MelodyMax Gear database with 15 demo customer/order scenarios.

Run from the project root:

    python -m backend.db.seed

Dates are computed relative to "now" (not hardcoded) so every scenario keeps
evaluating the way it's labeled, no matter when the seed is run.

Scenario coverage (15 total):
  - 5 clean approvals      (unopened, within window, receipt present)
  - 4 denials               (activated software, opened-past-window, used/vintage, damaged books)
  - 3 escalations           ($500+, missing receipt on high-value item, ambiguous condition claim)
  - 2 wildcards             (holiday extended-window edge case, missing receipt on a low-value item)
  - 1 split-eligibility     (MIDI controller bundle: hardware vs. bundled software)
"""

import json
import sqlite3
from datetime import datetime, timedelta

from backend.config import DB_PATH
from backend.db.database import init_db


def days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).date().isoformat()


CUSTOMERS = [
    {"name": "Jenna Ortiz", "email": "jenna.ortiz@gmail.com", "phone": "512-555-0101", "member_since": "2022-03-14"},
    {"name": "Marcus Webb", "email": "marcus.webb@yahoo.com", "phone": "512-555-0102", "member_since": "2023-07-02"},
    {"name": "Priya Chandran", "email": "priya.chandran@outlook.com", "phone": "512-555-0103", "member_since": "2021-11-30"},
    {"name": "Diego Fuentes", "email": "diego.fuentes@gmail.com", "phone": "512-555-0104", "member_since": "2024-01-19"},
    {"name": "Ashley Nguyen", "email": "ashley.nguyen@gmail.com", "phone": "512-555-0105", "member_since": "2020-05-08"},
    {"name": "Robert Kim", "email": "robert.kim@hotmail.com", "phone": "512-555-0106", "member_since": "2023-09-25"},
    {"name": "Lauren Castillo", "email": "lauren.castillo@gmail.com", "phone": "512-555-0107", "member_since": "2022-12-01"},
    {"name": "Terrence Adebayo", "email": "terrence.adebayo@gmail.com", "phone": "512-555-0108", "member_since": "2019-08-17"},
    {"name": "Grace Kowalski", "email": "grace.kowalski@yahoo.com", "phone": "512-555-0109", "member_since": "2024-04-22"},
    {"name": "Bianca Torres", "email": "bianca.torres@gmail.com", "phone": "512-555-0110", "member_since": "2021-02-11"},
    {"name": "Owen Whitfield", "email": "owen.whitfield@outlook.com", "phone": "512-555-0111", "member_since": "2023-03-30"},
    {"name": "Simone Delacroix", "email": "simone.delacroix@gmail.com", "phone": "512-555-0112", "member_since": "2022-06-19"},
    {"name": "Holly Jensen", "email": "holly.jensen@gmail.com", "phone": "512-555-0113", "member_since": "2020-10-03"},
    {"name": "Callum Rhys", "email": "callum.rhys@yahoo.com", "phone": "512-555-0114", "member_since": "2024-02-08"},
    {"name": "Nadia Okafor", "email": "nadia.okafor@gmail.com", "phone": "512-555-0115", "member_since": "2023-01-27"},
]

# Each order maps 1:1 to CUSTOMERS by index. bundle_components is a JSON
# string when is_bundle=1, else None.
ORDERS = [
    # --- 5 clean approvals ---
    dict(order_number="MMX-10001", product_name="Fender Player Stratocaster",
         category="Stringed & Fretted Instruments", price=479.99, purchase_date=days_ago(10),
         condition="unopened", has_receipt=1, has_original_packaging=1, is_holiday_purchase=0,
         is_bundle=0, bundle_components=None),
    dict(order_number="MMX-10002", product_name="Boss DS-1 Distortion Pedal",
         category="Accessories", price=59.99, purchase_date=days_ago(5),
         condition="unopened", has_receipt=1, has_original_packaging=1, is_holiday_purchase=0,
         is_bundle=0, bundle_components=None),
    dict(order_number="MMX-10003", product_name="Yamaha PSR-E373 Keyboard",
         category="Keyboards & MIDI Controllers", price=249.99, purchase_date=days_ago(12),
         condition="unopened", has_receipt=1, has_original_packaging=1, is_holiday_purchase=0,
         is_bundle=0, bundle_components=None),
    dict(order_number="MMX-10004", product_name="Pearl Export 5-Piece Drum Set",
         category="Drums & Percussion", price=459.00, purchase_date=days_ago(18),
         condition="unopened", has_receipt=1, has_original_packaging=1, is_holiday_purchase=0,
         is_bundle=0, bundle_components=None),
    dict(order_number="MMX-10005", product_name="Focusrite Scarlett 2i2 Audio Interface",
         category="Pro Audio & Recording Equipment", price=169.99, purchase_date=days_ago(9),
         condition="unopened", has_receipt=1, has_original_packaging=1, is_holiday_purchase=0,
         is_bundle=0, bundle_components=None),

    # --- 4 denials ---
    dict(order_number="MMX-10006", product_name="Ableton Live 12 Standard (License)",
         category="Software & Digital Downloads", price=449.00, purchase_date=days_ago(3),
         condition="activated", has_receipt=1, has_original_packaging=1, is_holiday_purchase=0,
         is_bundle=0, bundle_components=None),
    dict(order_number="MMX-10007", product_name="Fender Mustang LT25 Amplifier",
         category="Amplifiers & Electronics", price=179.99, purchase_date=days_ago(25),
         condition="opened", has_receipt=1, has_original_packaging=1, is_holiday_purchase=0,
         is_bundle=0, bundle_components=None),
    dict(order_number="MMX-10008", product_name="1978 Gibson Les Paul (Used/Vintage)",
         category="Stringed & Fretted Instruments", price=2899.00, purchase_date=days_ago(40),
         condition="used_vintage", has_receipt=1, has_original_packaging=0, is_holiday_purchase=0,
         is_bundle=0, bundle_components=None),
    dict(order_number="MMX-10009", product_name='"The Real Book" Sheet Music',
         category="Sheet Music & Books", price=34.99, purchase_date=days_ago(8),
         condition="opened_creased", has_receipt=1, has_original_packaging=0, is_holiday_purchase=0,
         is_bundle=0, bundle_components=None),

    # --- 3 escalations ---
    dict(order_number="MMX-10010", product_name="Taylor 214ce Acoustic-Electric Guitar",
         category="Stringed & Fretted Instruments", price=999.00, purchase_date=days_ago(15),
         condition="unopened", has_receipt=1, has_original_packaging=1, is_holiday_purchase=0,
         is_bundle=0, bundle_components=None),
    dict(order_number="MMX-10011", product_name="QSC K12.2 Powered PA Speaker",
         category="Pro Audio & Recording Equipment", price=549.00, purchase_date=days_ago(10),
         condition="unopened", has_receipt=0, has_original_packaging=1, is_holiday_purchase=0,
         is_bundle=0, bundle_components=None),
    dict(order_number="MMX-10012", product_name="Allen & Heath ZED-12FX Mixer",
         category="Pro Audio & Recording Equipment", price=429.00, purchase_date=days_ago(20),
         condition="opened", has_receipt=1, has_original_packaging=1, is_holiday_purchase=0,
         is_bundle=0, bundle_components=None),

    # --- 2 wildcards ---
    dict(order_number="MMX-10013", product_name="Ibanez GRX70QA Electric Guitar",
         category="Stringed & Fretted Instruments", price=329.99, purchase_date=days_ago(60),
         condition="unopened", has_receipt=1, has_original_packaging=1, is_holiday_purchase=1,
         is_bundle=0, bundle_components=None),
    dict(order_number="MMX-10014", product_name="Planet Waves Instrument Cable",
         category="Accessories", price=14.99, purchase_date=days_ago(6),
         condition="unopened", has_receipt=0, has_original_packaging=1, is_holiday_purchase=0,
         is_bundle=0, bundle_components=None),

    # --- 1 split eligibility ---
    dict(order_number="MMX-10015", product_name="Akai MPK249 MIDI Controller + Ableton Live Lite Bundle",
         category="Keyboards & MIDI Controllers", price=399.00, purchase_date=days_ago(9),
         condition="opened", has_receipt=1, has_original_packaging=1, is_holiday_purchase=0,
         is_bundle=1, bundle_components=json.dumps([
             {
                 "component": "Akai MPK249 MIDI Controller (hardware)",
                 "category": "Keyboards & MIDI Controllers",
                 "price": 279.00,
                 "condition": "opened",
                 "activated": False,
                 "claimed_issue": "customer reports unresponsive pads / faulty controller",
             },
             {
                 "component": "Ableton Live Lite License (bundled software)",
                 "category": "Software & Digital Downloads",
                 "price": 120.00,
                 "condition": "activated",
                 "activated": True,
             },
         ])),
]


def seed():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()

        customer_ids = []
        for c in CUSTOMERS:
            cur.execute(
                "INSERT INTO customers (name, email, phone, member_since) VALUES (?, ?, ?, ?)",
                (c["name"], c["email"], c["phone"], c["member_since"]),
            )
            customer_ids.append(cur.lastrowid)

        for customer_id, o in zip(customer_ids, ORDERS):
            cur.execute(
                """INSERT INTO orders
                       (customer_id, order_number, product_name, category, price, purchase_date,
                        condition, has_receipt, has_original_packaging, is_holiday_purchase,
                        is_bundle, bundle_components)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    customer_id, o["order_number"], o["product_name"], o["category"], o["price"],
                    o["purchase_date"], o["condition"], o["has_receipt"], o["has_original_packaging"],
                    o["is_holiday_purchase"], o["is_bundle"], o["bundle_components"],
                ),
            )

        conn.commit()
        print(f"Seeded {len(CUSTOMERS)} customers and {len(ORDERS)} orders into {DB_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    seed()
