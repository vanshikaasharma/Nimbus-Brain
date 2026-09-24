"""Two-hop lookup over nodes and edges.

Checkpoint 5. Still not a router — the UI calls this path on purpose.
The demo hop is incident → account → plan.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

HOP_SQL = """
SELECT
    inc.name AS incident,
    account.name AS account,
    plan.name AS plan
FROM nodes inc
JOIN edges impact
    ON impact.src = inc.id AND impact.type = 'IMPACTS'
JOIN nodes account
    ON account.id = impact.dst AND account.type = 'Account'
JOIN edges subscribed
    ON subscribed.src = account.id AND subscribed.type = 'SUBSCRIBED_TO'
JOIN nodes plan
    ON plan.id = subscribed.dst AND plan.type = 'Plan'
WHERE inc.name = 'INC-104'
"""


def walk(database_url: str, question: str) -> dict:
    q = question.lower()
    if not any(word in q for word in ("inc-104", "incident", "outage")):
        return {
            "error": (
                "No graph template matched. "
                "Try: Which Enterprise customers were on INC-104?"
            )
        }

    sql = HOP_SQL
    if "enterprise" in q:
        sql += " AND plan.name = 'Enterprise'"
    sql += "\nORDER BY account.name"

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(sql).fetchall()

    paths = [
        f"{row['incident']} → {row['account']} → {row['plan']}" for row in rows
    ]
    triples = []
    for row in rows:
        triples.append(f"{row['incident']} IMPACTS {row['account']}")
        triples.append(f"{row['account']} SUBSCRIBED_TO {row['plan']}")

    return {
        "paths": paths,
        "triples": triples,
        "explanation": "Walked INC-104 to impacted accounts, then to each account's plan.",
    }
