"""Load the fake Nimbus company into Postgres.

Usage (from repo root, venv on):
    python backend/app/ingest/seed.py
"""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = Path(__file__).with_name("schema.sql")

load_dotenv(ROOT / ".env")


def run_sql_script(conn, sql_text):
    for statement in sql_text.split(";"):
        statement = statement.strip()
        if statement:
            conn.execute(statement)


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is missing. Copy .env.example to .env and paste the Neon URL.")

    schema = SCHEMA.read_text()

    with psycopg.connect(url) as conn:
        run_sql_script(conn, schema)

        conn.execute(
            """
            INSERT INTO plans (name, monthly_fee_cents, rate_limit_rps)
            VALUES
                ('Starter', 9900, 50),
                ('Pro', 49900, 200),
                ('Enterprise', 200000, 1000)
            """
        )

        conn.execute(
            """
            INSERT INTO customers (name, plan_id)
            VALUES
                ('Acme', (SELECT id FROM plans WHERE name = 'Enterprise')),
                ('Soylent', (SELECT id FROM plans WHERE name = 'Enterprise')),
                ('Globex', (SELECT id FROM plans WHERE name = 'Pro')),
                ('Initech', (SELECT id FROM plans WHERE name = 'Pro')),
                ('Umbrella', (SELECT id FROM plans WHERE name = 'Starter')),
                ('Hooli', (SELECT id FROM plans WHERE name = 'Starter'))
            """
        )

        # Acme's August bill jumps on purpose. Later we will ask "why?"
        conn.execute(
            """
            INSERT INTO invoices (customer_id, period_start, period_end, amount_cents)
            VALUES
                ((SELECT id FROM customers WHERE name = 'Acme'),     '2026-07-01', '2026-07-31', 210000),
                ((SELECT id FROM customers WHERE name = 'Acme'),     '2026-08-01', '2026-08-31', 347000),
                ((SELECT id FROM customers WHERE name = 'Soylent'),  '2026-07-01', '2026-07-31', 205000),
                ((SELECT id FROM customers WHERE name = 'Soylent'),  '2026-08-01', '2026-08-31', 218000),
                ((SELECT id FROM customers WHERE name = 'Globex'),   '2026-07-01', '2026-07-31',  52000),
                ((SELECT id FROM customers WHERE name = 'Globex'),   '2026-08-01', '2026-08-31',  49800),
                ((SELECT id FROM customers WHERE name = 'Initech'),  '2026-07-01', '2026-07-31',  49900),
                ((SELECT id FROM customers WHERE name = 'Initech'),  '2026-08-01', '2026-08-31',  61200),
                ((SELECT id FROM customers WHERE name = 'Umbrella'), '2026-07-01', '2026-07-31',   9900),
                ((SELECT id FROM customers WHERE name = 'Umbrella'), '2026-08-01', '2026-08-31',   9900),
                ((SELECT id FROM customers WHERE name = 'Hooli'),    '2026-07-01', '2026-07-31',   9900),
                ((SELECT id FROM customers WHERE name = 'Hooli'),    '2026-08-01', '2026-08-31',  11500)
            """
        )
        conn.commit()

        counts = conn.execute(
            """
            SELECT
                (SELECT count(*) FROM plans) AS plans,
                (SELECT count(*) FROM customers) AS customers,
                (SELECT count(*) FROM invoices) AS invoices
            """
        ).fetchone()

    print(f"Seeded Nimbus: {counts[0]} plans, {counts[1]} customers, {counts[2]} invoices.")


if __name__ == "__main__":
    main()
