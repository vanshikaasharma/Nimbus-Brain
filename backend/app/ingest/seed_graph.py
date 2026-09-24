"""Build a tiny property graph next to the invoice tables.

Does not touch plans / customers / invoices / doc_chunks.

Usage (from repo root, venv on):
    python backend/app/ingest/seed_graph.py
"""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

SCHEMA = """
DROP TABLE IF EXISTS edges;
DROP TABLE IF EXISTS nodes;

CREATE TABLE nodes (
    id SERIAL PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    UNIQUE (type, name)
);

CREATE TABLE edges (
    id SERIAL PRIMARY KEY,
    src INTEGER NOT NULL REFERENCES nodes (id),
    dst INTEGER NOT NULL REFERENCES nodes (id),
    type TEXT NOT NULL
);
"""


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is missing. Copy .env.example to .env.")

    with psycopg.connect(url) as conn:
        for statement in SCHEMA.split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(statement)

        conn.execute(
            """
            INSERT INTO nodes (type, name)
            SELECT 'Plan', name FROM plans
            """
        )
        conn.execute(
            """
            INSERT INTO nodes (type, name)
            SELECT 'Account', name FROM customers
            """
        )
        conn.execute(
            """
            INSERT INTO nodes (type, name)
            VALUES ('Incident', 'INC-104')
            """
        )

        conn.execute(
            """
            INSERT INTO edges (src, dst, type)
            SELECT account.id, plan_node.id, 'SUBSCRIBED_TO'
            FROM customers c
            JOIN plans p ON p.id = c.plan_id
            JOIN nodes account ON account.type = 'Account' AND account.name = c.name
            JOIN nodes plan_node ON plan_node.type = 'Plan' AND plan_node.name = p.name
            """
        )
        conn.execute(
            """
            INSERT INTO edges (src, dst, type)
            SELECT incident.id, account.id, 'IMPACTS'
            FROM nodes incident
            JOIN nodes account ON account.type = 'Account'
            WHERE incident.name = 'INC-104'
              AND account.name IN ('Acme', 'Soylent')
            """
        )
        conn.commit()

        counts = conn.execute(
            """
            SELECT
                (SELECT count(*) FROM nodes),
                (SELECT count(*) FROM edges)
            """
        ).fetchone()

    print(f"Seeded graph: {counts[0]} nodes, {counts[1]} edges.")


if __name__ == "__main__":
    main()
