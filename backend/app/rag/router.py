"""Pick one tool for a question.

Checkpoint 6. Keyword rules, not an LLM. If the question needs more than
one tool, we stop and say so. The agent that combines them comes later.
"""

from __future__ import annotations

DOC_WORDS = (
    "rate limit",
    "sla",
    "pricing",
    "changelog",
    "credit",
    "policy",
    "uptime",
    "owe",
)
SQL_WORDS = ("invoice", "bill", "charged", "how much")
GRAPH_WORDS = ("inc-104", "incident", "outage")


def classify(question: str) -> dict:
    q = question.lower()
    wants_docs = any(word in q for word in DOC_WORDS)
    wants_sql = any(word in q for word in SQL_WORDS)
    wants_graph = any(word in q for word in GRAPH_WORDS)

    # "Which customers are on Enterprise?" is a table question
    # unless the question is really about an incident.
    if (
        not wants_graph
        and "enterprise" in q
        and any(word in q for word in ("who", "which", "customer", "account"))
    ):
        wants_sql = True

    hits = []
    if wants_docs:
        hits.append("docs")
    if wants_sql:
        hits.append("sql")
    if wants_graph:
        hits.append("graph")

    if len(hits) > 1:
        return {
            "route": "mixed",
            "reason": (
                "This question needs more than one tool ("
                + " + ".join(hits)
                + "). The combiner comes in a later checkpoint."
            ),
        }
    if hits == ["docs"]:
        return {
            "route": "docs",
            "reason": "Looks like a policy or product question, so search the docs.",
        }
    if hits == ["sql"]:
        return {
            "route": "sql",
            "reason": "Looks like a number or membership question, so query the tables.",
        }
    if hits == ["graph"]:
        return {
            "route": "graph",
            "reason": "Looks like an incident relationship, so walk the graph.",
        }
    return {
        "route": "unknown",
        "reason": "No rule matched. Try a rate-limit, invoice, or INC-104 question.",
    }
