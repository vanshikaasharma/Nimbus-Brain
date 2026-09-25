"""Fixed pipeline for a question that needs more than one tool.

Order is always the same: graph, then invoices for those accounts, then the SLA doc.
If an API key is set, one model call writes the sentence from that evidence.
"""

from __future__ import annotations

from datetime import date, datetime

import psycopg
from psycopg.rows import dict_row

from app.rag.generate import answer_from_evidence, with_dollars
from app.rag.graph_tool import walk
from app.rag.naive import ask

SLA_QUERY = "Enterprise SLA credit after an ingest outage"


def accounts_from_paths(paths: list[str]) -> list[str]:
    names = []
    for path in paths:
        parts = [part.strip() for part in path.split("→")]
        if len(parts) >= 2 and parts[1] not in names:
            names.append(parts[1])
    return names


def invoices_for(database_url: str, names: list[str]) -> dict:
    if not names:
        return {
            "sql": None,
            "rows": [],
            "explanation": "The graph returned no accounts, so no invoice query ran.",
        }

    sql = """
SELECT c.name, i.period_start, i.period_end, i.amount_cents
FROM invoices i
JOIN customers c ON c.id = i.customer_id
WHERE c.name = ANY(%s)
  AND i.period_start = DATE '2026-08-01'
ORDER BY c.name
""".strip()

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        raw_rows = conn.execute(sql, (names,)).fetchall()

    rows = []
    for row in raw_rows:
        clean = {}
        for key, value in row.items():
            if isinstance(value, (date, datetime)):
                clean[key] = value.isoformat()
            else:
                clean[key] = value
        rows.append(clean)

    shown = sql.replace("%s", "(" + ", ".join(repr(name) for name in names) + ")")
    return {
        "sql": shown,
        "rows": rows,
        "explanation": "August invoices for the accounts the graph returned.",
    }


def run_mixed(database_url: str, question: str) -> dict:
    graph = walk(database_url, question)
    names = accounts_from_paths(graph.get("paths") or [])
    sql = invoices_for(database_url, names)
    docs = ask(database_url, SLA_QUERY, generate=False)
    chunks = docs.get("chunks") or []
    passages = "\n\n".join(
        f"[{c['doc_path']} > {c['section']}]\n{c['body']}" for c in chunks
    )
    evidence = (
        "Graph paths:\n"
        + "\n".join(graph.get("paths") or [])
        + "\n\nSQL rows:\n"
        + str(with_dollars(sql.get("rows")))
        + "\n\nDoc passages:\n"
        + passages
    )
    written = answer_from_evidence(question, evidence)
    listed = ", ".join(names) if names else "none"
    if not written:
        written = (
            f"Ran graph, then SQL, then docs. Accounts on the outage: {listed}. "
            "The SLA chunk and the August invoice rows are the evidence. "
            "Set OPENAI_API_KEY if you want a sentence written from that evidence."
        )
    return {
        "answer": written,
        "chunks": chunks,
        "sql": sql,
        "graph": graph,
    }
