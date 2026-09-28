"""Run only the tools a mixed question needs, in an order the model chooses.

Graph results are passed into SQL when both run and the graph ran first.
One empty result may be tried once more. The sentence has to cite source ids.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime

import psycopg
from psycopg.rows import dict_row

from app.rag.dates import period_for_question
from app.rag.generate import answer_with_sources, chunk_evidence, with_dollars
from app.rag.grade import rewrite_once
from app.rag.graph_tool import walk
from app.rag.naive import ask
from app.rag.router import classify
from app.rag.sql_tool import run_question

TOOLS = ("graph", "sql", "docs")
PLAN_ORDER = ("graph", "sql", "docs")
PLAN_NAMES = {"Starter", "Pro", "Enterprise"}
SLA_QUERY = "Enterprise SLA credit after an ingest outage"

PLAN_SYSTEM = """
Choose the tools this question needs, in the order to run them. Reply with JSON only.
Tools are graph, sql, and docs. Include only the ones the question needs.
graph: who an incident or outage hit.
sql: invoices or bills, including invoices for the accounts the graph just named.
docs: SLA, credits, pricing, rate limits.
When both graph and sql are needed, put graph first so SQL receives the account names.
Do not add a tool the question does not ask for.

{"steps":["graph","sql"]}
{"steps":["graph","docs"]}
{"steps":["sql","docs"]}
{"steps":["graph","sql","docs"]}
"""

TOOL_ALIASES = {
    "graph": "graph",
    "walk": "graph",
    "walk_graph": "graph",
    "incident": "graph",
    "sql": "sql",
    "invoice": "sql",
    "invoices": "sql",
    "bill": "sql",
    "bills": "sql",
    "lookup_invoices": "sql",
    "docs": "docs",
    "doc": "docs",
    "document": "docs",
    "documents": "docs",
    "search_docs": "docs",
}


def accounts_from_paths(paths: list[str]) -> list[str]:
    names = []
    for path in paths:
        parts = [part.strip() for part in re.split(r"[→←]", path)]
        for part in parts:
            if not part or part in PLAN_NAMES or part.upper().startswith("INC-"):
                continue
            if part not in names:
                names.append(part)
    return names


def invoices_for(database_url: str, names: list[str], period: date | None = None) -> dict:
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
""".strip()
    params: list = [names]
    if period is not None:
        sql += "\n  AND i.period_start = %s"
        params.append(period)
    sql += "\nORDER BY c.name, i.period_start"

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        raw_rows = conn.execute(sql, params).fetchall()

    rows = []
    for row in raw_rows:
        clean = {}
        for key, value in row.items():
            if isinstance(value, (date, datetime)):
                clean[key] = value.isoformat()
            else:
                clean[key] = value
        rows.append(clean)

    shown = sql.replace("%s", "(" + ", ".join(repr(name) for name in names) + ")", 1)
    if period is not None:
        shown = shown.replace("%s", f"DATE '{period.isoformat()}'", 1)
    scope = (
        f"Invoices for {period.isoformat()}"
        if period is not None
        else "Invoices from every seeded month"
    )
    return {
        "sql": shown,
        "rows": rows,
        "explanation": f"{scope} for the accounts the graph returned.",
    }


def _alias(name: str) -> str | None:
    return TOOL_ALIASES.get(name.lower().strip().replace(" ", "_"))


def parse_steps(text: str) -> list[str] | None:
    """Read a tool list. Unknown tokens are dropped; a synonym still counts."""
    body = text.strip()
    raw = None
    start = body.find("{")
    end = body.rfind("}")
    if start >= 0 and end > start:
        try:
            raw = json.loads(body[start : end + 1]).get("steps")
        except json.JSONDecodeError:
            raw = None
    if isinstance(raw, str):
        raw = re.split(r"[,>|]+", raw)
    steps = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, str):
                continue
            name = _alias(item)
            if name and name not in steps:
                steps.append(name)
    if not steps:
        for match in re.finditer(
            r"\b(walk_graph|lookup_invoices|search_docs|graph|sql|docs|invoices|invoice|documents|document)\b",
            body,
            flags=re.I,
        ):
            name = _alias(match.group(1))
            if name and name not in steps:
                steps.append(name)
    if not steps or len(steps) > 3:
        return None
    return steps


def order_steps(steps: list[str], question: str) -> list[str]:
    """Graph names the accounts before SQL looks up their invoices."""
    del question
    if "graph" in steps and "sql" in steps:
        rest = [name for name in steps if name not in ("graph", "sql")]
        return ["graph", "sql", *rest]
    return steps


def draft_steps(question: str) -> list[str] | None:
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None
    from app.rag.chat import ChatProblem, call_chat

    try:
        text = call_chat(
            [
                {"role": "system", "content": PLAN_SYSTEM},
                {"role": "user", "content": question},
            ],
            max_tokens=120,
        )
    except ChatProblem:
        return None
    parsed = parse_steps(text)
    if not parsed:
        return None
    from app.rag.coverage import needed_tools

    needed = set(needed_tools(question))
    if needed:
        parsed = [name for name in parsed if name in needed]
    if not parsed:
        return None
    return order_steps(parsed, question)


def fallback_steps(question: str) -> list[str]:
    hits = classify(question).get("tools") or []
    ordered = [name for name in PLAN_ORDER if name in hits]
    return ordered or ["graph", "sql", "docs"]


def run_mixed(database_url: str, question: str) -> dict:
    drafted = draft_steps(question)
    if drafted:
        steps = drafted
        planner = "llama"
    else:
        steps = fallback_steps(question)
        planner = "keyword"
    retries = 0
    graph = None
    sql = None
    chunks = []
    retried = False
    names: list[str] = []

    for tool in steps:
        if tool == "graph":
            graph = walk(database_url, question)
            names = accounts_from_paths(graph.get("paths") or [])
        elif tool == "sql":
            if names:
                period = period_for_question(question)
                sql = invoices_for(database_url, names, period=period)
                if period is not None and not sql.get("rows") and retries < 1:
                    retries += 1
                    retried = True
                    sql = invoices_for(database_url, names, period=None)
            else:
                sql = run_question(database_url, question)
        elif tool == "docs":
            docs = ask(database_url, question, generate=False)
            chunks = docs.get("chunks") or []
            retried = retried or bool(docs.get("retried"))
            if not chunks and retries < 1:
                retries += 1
                retried = True
                broader = SLA_QUERY if any(word in question.lower() for word in ("sla", "owe", "credit")) else rewrite_once(question)
                docs = ask(database_url, broader, generate=False)
                chunks = docs.get("chunks") or []

    missing = []
    if "graph" in steps and not (graph or {}).get("paths"):
        missing.append("graph path")
    if "sql" in steps and not (sql or {}).get("rows"):
        missing.append("invoice rows")
    if "docs" in steps and not chunks:
        missing.append("doc passage")

    sources = []
    for index, path in enumerate((graph or {}).get("paths") or [], start=1):
        sources.append((f"G{index}", path))
    for index, row in enumerate(with_dollars((sql or {}).get("rows")), start=1):
        sources.append((f"S{index}", str(row)))
    for index, chunk in enumerate(chunks, start=1):
        sources.append((f"D{index}", chunk_evidence(chunk)))

    written, flags = answer_with_sources(question, sources)
    if not written:
        found = ", ".join(steps)
        written = f"Ran {found}. Set OPENAI_API_KEY if you want a sentence from that evidence."
    if missing:
        written = written.rstrip() + " Missing evidence: " + ", ".join(missing) + "."
        flags = list(flags) + [f"Missing evidence: {', '.join(missing)}."]

    return {
        "answer": written,
        "chunks": chunks,
        "sql": sql,
        "graph": graph,
        "steps": steps,
        "planner": planner,
        "retried": retried,
        "missing": missing,
        "grounding": flags,
    }
