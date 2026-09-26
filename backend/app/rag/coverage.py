"""Which tools a question still needs after the ones already called.

This is not the router. It only decides whether the agent left part of the
question unanswered. It does not call every tool.
"""

from __future__ import annotations

DOC_WORDS = (
    "rate limit",
    "requests per second",
    "sla",
    "pricing",
    "changelog",
    "credit",
    "uptime",
    "owe",
)
SQL_WORDS = ("invoice", "bill", "charged", "how much", "pay", "paid", "spent", "spend")
GRAPH_WORDS = ("inc-", "incident", "outage")


def needed_tools(question: str) -> list[str]:
    q = question.lower()
    asks_docs = any(word in q for word in DOC_WORDS)
    asks_sql = any(word in q for word in SQL_WORDS)
    asks_graph = any(word in q for word in GRAPH_WORDS)
    if (
        not asks_graph
        and "enterprise" in q
        and any(word in q for word in ("who", "which", "customer", "account", "subscriber"))
    ):
        asks_sql = True
    tools = []
    if asks_graph:
        tools.append("graph")
    if asks_sql:
        tools.append("sql")
    if asks_docs:
        tools.append("docs")
    return tools


def unanswered_tools(question: str, steps: list[str]) -> list[str]:
    done = set(steps)
    return [tool for tool in needed_tools(question) if tool not in done]
