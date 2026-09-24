"""Read-only text-to-SQL over plans / customers / invoices.

Checkpoint 4. No router yet — the UI calls this path on purpose.
Writes are rejected in Python; we only allow SELECT on three tables.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

ALLOWED_TABLES = {"plans", "customers", "invoices"}
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|copy|execute|call)\b",
    re.I,
)
FROM_JOIN = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.I)

SCHEMA = """
plans(id, name, monthly_fee_cents, rate_limit_rps)
customers(id, name, plan_id)  -- names: Acme, Soylent, Globex, Initech, Umbrella, Hooli
invoices(id, customer_id, period_start, period_end, amount_cents)
Money is stored as cents. Last month relative to Sep 2026 is August 2026 (period_start = 2026-08-01).
"""

CUSTOMER_NAMES = ["Acme", "Soylent", "Globex", "Initech", "Umbrella", "Hooli"]


def ensure_select_only(sql: str) -> str:
    sql = sql.strip()
    if sql.startswith("```"):
        sql = re.sub(r"^```(?:sql)?", "", sql, flags=re.I).strip()
        sql = re.sub(r"```$", "", sql).strip()

    sql = sql.strip().rstrip(";")
    if ";" in sql:
        raise ValueError("Only one SQL statement is allowed.")
    if not sql.lower().startswith("select"):
        raise ValueError("Only SELECT is allowed.")
    if FORBIDDEN.search(sql):
        raise ValueError("That SQL is not read-only.")

    tables = [name.lower() for name in FROM_JOIN.findall(sql)]
    if not tables:
        raise ValueError("Could not find a table in the SQL.")
    for table in tables:
        if table not in ALLOWED_TABLES:
            raise ValueError(f"Table {table!r} is not on the allowlist.")

    if "limit" not in sql.lower():
        sql += " LIMIT 50"
    return sql


def draft_sql_without_llm(question: str) -> tuple[str, str] | None:
    """Tiny matcher so the demo works without an API key."""
    q = question.lower()
    customer = next((name for name in CUSTOMER_NAMES if name.lower() in q), None)

    if customer and any(word in q for word in ("invoice", "bill", "charged", "usage")):
        sql = f"""
SELECT c.name, i.period_start, i.period_end, i.amount_cents
FROM invoices i
JOIN customers c ON c.id = i.customer_id
WHERE c.name = '{customer}'
""".strip()
        if "last month" in q or "august" in q:
            sql += "\nAND i.period_start = DATE '2026-08-01'"
        sql += "\nORDER BY i.period_start DESC"
        return sql, f"Matched the invoice template for {customer}."

    if "enterprise" in q and any(word in q for word in ("who", "which", "customer", "account")):
        sql = """
SELECT c.name, p.name AS plan
FROM customers c
JOIN plans p ON p.id = c.plan_id
WHERE p.name = 'Enterprise'
ORDER BY c.name
""".strip()
        return sql, "Matched the Enterprise membership template."

    return None


def draft_sql_with_llm(question: str) -> tuple[str, str]:
    from openai import OpenAI

    api_key = os.environ["OPENAI_API_KEY"]
    client = OpenAI(
        api_key=api_key,
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
    )
    model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Write one PostgreSQL SELECT for the Nimbus tables. "
                    "No markdown. No comments. SELECT only.\n"
                    f"Schema:\n{SCHEMA}\n"
                    "Example: What was Acme's invoice last month?\n"
                    "SELECT c.name, i.period_start, i.period_end, i.amount_cents "
                    "FROM invoices i JOIN customers c ON c.id = i.customer_id "
                    "WHERE c.name = 'Acme' AND i.period_start = DATE '2026-08-01'"
                ),
            },
            {"role": "user", "content": question},
        ],
    )
    sql = (response.choices[0].message.content or "").strip()
    return sql, "LLM wrote this SELECT from the schema + question."


def jsonish(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def run_question(database_url: str, question: str) -> dict:
    drafted = draft_sql_without_llm(question)
    if drafted is None:
        if not os.environ.get("OPENAI_API_KEY"):
            return {
                "error": (
                    "No SQL template matched, and OPENAI_API_KEY is not set. "
                    "Try: What was Acme's invoice last month?"
                )
            }
        drafted = draft_sql_with_llm(question)

    raw_sql, explanation = drafted
    try:
        sql = ensure_select_only(raw_sql)
    except ValueError as exc:
        return {"error": str(exc), "sql": raw_sql}

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(sql).fetchall()

    return {
        "sql": sql,
        "explanation": explanation,
        "rows": [{k: jsonish(v) for k, v in row.items()} for row in rows],
    }
