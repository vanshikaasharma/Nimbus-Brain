"""Pick one tool for a question.

Llama 3.2 may choose docs, sql, graph, or mixed. The label is checked
against that list. If the model is missing or the label is not in the list,
the keyword rules choose instead.
"""

from __future__ import annotations

import json
import os
import re

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
ROUTES = {"docs", "sql", "graph", "mixed", "unknown"}

ROUTE_SYSTEM = """
Classify one Nimbus employee question. Reply with JSON only, like {"route":"sql"}.
route is exactly one of: docs, sql, graph, mixed, unknown.

docs: written product pages — rate limits, requests per second, pricing, SLA, credits, changelog.
sql: tables — invoices, bills, what a customer paid, spent, or was charged, and which customers are on a plan.
  Plan membership is sql. A plan name alone is not a graph walk.
graph: incidents and outages only — which accounts an incident hit, or which incident hit an account.
mixed: the question needs two or more of docs, sql, and graph.
unknown: anything else. Side emails, private texts, and custom promises are unknown even if they mention a customer.

Examples of the shape, not a list of answers to memorize:
{"route":"sql"} for who is on the Starter plan
{"route":"sql"} for what a customer paid in a named month
{"route":"graph"} for which incident touched an account
{"route":"unknown"} for a private email that promised a special uptime
{"route":"docs"} for how many requests per second a plan allows
{"route":"mixed"} for who an outage hit and what their invoices were
"""


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
                + ")."
            ),
            "tools": hits,
        }
    if hits == ["docs"]:
        return {
            "route": "docs",
            "reason": "Looks like a policy or product question, so search the docs.",
            "tools": hits,
        }
    if hits == ["sql"]:
        return {
            "route": "sql",
            "reason": "Looks like a number or membership question, so query the tables.",
            "tools": hits,
        }
    if hits == ["graph"]:
        return {
            "route": "graph",
            "reason": "Looks like an incident relationship, so walk the graph.",
            "tools": hits,
        }
    return {
        "route": "unknown",
        "reason": "No rule matched. Try a rate-limit, invoice, or INC-104 question.",
        "tools": hits,
    }


def parse_route(text: str) -> str | None:
    body = text.strip()
    if body.startswith("```"):
        body = re.sub(r"^```(?:json)?", "", body, flags=re.I).strip()
        body = re.sub(r"```$", "", body).strip()
    start = body.find("{")
    end = body.rfind("}")
    if start >= 0 and end > start:
        try:
            route = json.loads(body[start : end + 1]).get("route")
        except json.JSONDecodeError:
            route = None
        if isinstance(route, str):
            route = route.lower().strip()
            if route in ROUTES:
                return route
    labeled = re.search(r"\broute\b\s*[:=]\s*[\"']?(docs|sql|graph|mixed|unknown)\b", body, flags=re.I)
    if labeled:
        return labeled.group(1).lower()
    word = body.lower().strip().strip(".")
    return word if word in ROUTES else None


def draft_route(question: str) -> str | None:
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None
    from openai import APIConnectionError, APITimeoutError, OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        timeout=45.0,
    )
    model = os.environ.get("OPENAI_CHAT_MODEL", "llama3.2")
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=80,
            messages=[
                {"role": "system", "content": ROUTE_SYSTEM},
                {"role": "user", "content": question},
            ],
        )
    except (APITimeoutError, APIConnectionError):
        return None
    return parse_route(response.choices[0].message.content or "")


def widen_single_label(picked: str, question: str) -> str:
    """A graph/sql/docs label is mixed when the question names two evidence types."""
    from app.rag.coverage import needed_tools

    if picked in {"docs", "sql", "graph"} and len(needed_tools(question)) > 1:
        return "mixed"
    return picked


def choose_route(question: str) -> dict:
    """Llama picks the route. Keyword rules run when that pick is not usable."""
    keyword = classify(question)
    picked = draft_route(question)
    if picked is not None:
        widened = widen_single_label(picked, question)
        if widened != picked:
            return {
                "route": widened,
                "reason": (
                    f"Llama chose {picked}. The question names more than one evidence type, "
                    "so the route is mixed."
                ),
                "fallback": False,
            }
        picked = widened
    if picked is None:
        return {
            "route": keyword["route"],
            "reason": "Keyword fallback. " + keyword["reason"],
            "fallback": True,
        }
    if picked == keyword["route"]:
        return {
            "route": picked,
            "reason": f"Llama chose {picked}. Keyword rules agreed.",
            "fallback": False,
        }
    return {
        "route": picked,
        "reason": (
            f"Llama chose {picked}. Keyword rules would have chosen {keyword['route']}."
        ),
        "fallback": False,
    }
