"""Graph walk over nodes and edges.

Llama 3.2 may name the start node and up to two hops. The server checks
that plan, then runs parameterized SQL. It does not execute SQL the model wrote.
If the plan is empty or missing, the fixed INC-104 walk still runs.
"""

from __future__ import annotations

import json
import os
import re

import psycopg
from psycopg.rows import dict_row

NODE_TYPES = {"Incident", "Account", "Plan"}
EDGE_TYPES = {"IMPACTS", "SUBSCRIBED_TO"}

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

PLAN_SYSTEM = """
You plan a walk on a small graph. Reply with JSON only. Do not write SQL.
Node types: Incident, Account, Plan.
Edges:
- IMPACTS points Incident -> Account. Reverse walks Account -> Incident.
- SUBSCRIBED_TO points Account -> Plan. Reverse walks Plan -> Account.
Use 1 or 2 hops. direction is "forward" or "reverse".
end_name is optional and only when the question names that node.
Example for Enterprise customers on INC-104:
{"start_type":"Incident","start_name":"INC-104","hops":[{"edge":"IMPACTS","direction":"forward","end_type":"Account"},{"edge":"SUBSCRIBED_TO","direction":"forward","end_type":"Plan","end_name":"Enterprise"}]}
Example for accounts on the Enterprise plan. Enterprise is a Plan, not an Account:
{"start_type":"Plan","start_name":"Enterprise","hops":[{"edge":"SUBSCRIBED_TO","direction":"reverse","end_type":"Account"}]}
"""


def _clean_name(value) -> str | None:
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not name or len(name) > 80:
        return None
    return name


def validate_plan(raw: dict) -> dict | None:
    """Keep only a start node plus one or two allowlisted hops."""
    if not isinstance(raw, dict):
        return None
    start_type = raw.get("start_type")
    start_name = _clean_name(raw.get("start_name"))
    hops = raw.get("hops")
    if start_type not in NODE_TYPES or not start_name:
        return None
    if not isinstance(hops, list) or not 1 <= len(hops) <= 2:
        return None

    cleaned = []
    for hop in hops:
        if not isinstance(hop, dict):
            return None
        edge = hop.get("edge")
        direction = hop.get("direction")
        end_type = hop.get("end_type")
        if edge not in EDGE_TYPES or direction not in {"forward", "reverse"}:
            return None
        if end_type not in NODE_TYPES:
            return None
        item = {"edge": edge, "direction": direction, "end_type": end_type}
        if hop.get("end_name") not in (None, ""):
            end_name = _clean_name(hop.get("end_name"))
            if not end_name:
                return None
            item["end_name"] = end_name
        cleaned.append(item)
    return {"start_type": start_type, "start_name": start_name, "hops": cleaned}


def parse_plan(text: str) -> dict | None:
    body = text.strip()
    if body.startswith("```"):
        body = re.sub(r"^```(?:json)?", "", body, flags=re.I).strip()
        body = re.sub(r"```$", "", body).strip()
    start = body.find("{")
    end = body.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return validate_plan(json.loads(body[start : end + 1]))
    except json.JSONDecodeError:
        return None


def draft_plan(question: str) -> dict | None:
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
            max_tokens=180,
            messages=[
                {"role": "system", "content": PLAN_SYSTEM},
                {"role": "user", "content": question},
            ],
        )
    except (APITimeoutError, APIConnectionError):
        return None
    return parse_plan(response.choices[0].message.content or "")


def execute_plan(conn, plan: dict) -> list[dict]:
    """Turn a checked plan into parameterized SQL. Values never get pasted in."""
    params = {
        "start_type": plan["start_type"],
        "start_name": plan["start_name"],
    }
    select = ["n0.name AS n0_name", "n0.type AS n0_type"]
    joins = []
    for index, hop in enumerate(plan["hops"], start=1):
        edge_key = f"edge{index}"
        type_key = f"type{index}"
        params[edge_key] = hop["edge"]
        params[type_key] = hop["end_type"]
        prev = f"n{index - 1}"
        node = f"n{index}"
        edge = f"e{index}"
        if hop["direction"] == "forward":
            link = f"{edge}.src = {prev}.id"
            land = f"{node}.id = {edge}.dst"
        else:
            link = f"{edge}.dst = {prev}.id"
            land = f"{node}.id = {edge}.src"
        joins.append(
            f"JOIN edges {edge} ON {link} AND {edge}.type = %({edge_key})s "
            f"JOIN nodes {node} ON {land} AND {node}.type = %({type_key})s"
        )
        if hop.get("end_name"):
            name_key = f"name{index}"
            params[name_key] = hop["end_name"]
            joins[-1] += f" AND {node}.name = %({name_key})s"
        select.append(f"{edge}.type AS e{index}_type")
        select.append(f"{node}.name AS n{index}_name")
        select.append(f"{node}.type AS n{index}_type")

    sql = (
        f"SELECT {', '.join(select)} FROM nodes n0 "
        + " ".join(joins)
        + " WHERE n0.type = %(start_type)s AND n0.name = %(start_name)s "
        + "ORDER BY n0.name LIMIT 50"
    )
    return list(conn.execute(sql, params).fetchall())


def rows_to_paths(rows: list[dict], hops: list[dict]) -> tuple[list[str], list[str]]:
    paths = []
    triples = []
    for row in rows:
        parts = [row["n0_name"]]
        for index, hop in enumerate(hops, start=1):
            left = row[f"n{index - 1}_name"]
            right = row[f"n{index}_name"]
            if hop["direction"] == "forward":
                parts.append(f"→ {right}")
                triples.append(f"{left} {hop['edge']} {right}")
            else:
                parts.append(f"← {right}")
                triples.append(f"{right} {hop['edge']} {left}")
        paths.append(" ".join(parts))
    unique_triples = list(dict.fromkeys(triples))
    return paths, unique_triples


def describe(plan: dict) -> str:
    steps = [f"{plan['start_type']} {plan['start_name']}"]
    for hop in plan["hops"]:
        arrow = "→" if hop["direction"] == "forward" else "←"
        label = f"{arrow} {hop['edge']} {arrow} {hop['end_type']}"
        if hop.get("end_name"):
            label += f" {hop['end_name']}"
        steps.append(label)
    return "Plan: " + " ".join(steps)


def template_walk(question: str) -> dict:
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
    return {"sql": sql, "fallback": True}


def walk(database_url: str, question: str) -> dict:
    plan = draft_plan(question)
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        if plan:
            rows = execute_plan(conn, plan)
            paths, triples = rows_to_paths(rows, plan["hops"])
            if paths:
                return {
                    "paths": paths,
                    "triples": triples,
                    "plan": plan,
                    "explanation": describe(plan),
                }

        templated = template_walk(question)
        if templated.get("error"):
            if plan:
                return {
                    "paths": [],
                    "triples": [],
                    "plan": plan,
                    "explanation": describe(plan) + " That plan returned no rows.",
                    "error": "The plan returned no rows.",
                }
            return templated

        rows = conn.execute(templated["sql"]).fetchall()

    paths = [
        f"{row['incident']} → {row['account']} → {row['plan']}" for row in rows
    ]
    triples = []
    for row in rows:
        triples.append(f"{row['incident']} IMPACTS {row['account']}")
        triples.append(f"{row['account']} SUBSCRIBED_TO {row['plan']}")
    note = "Used the fixed INC-104 walk."
    if plan:
        note = describe(plan) + " That plan returned no rows, so the fixed INC-104 walk ran."
    return {
        "paths": paths,
        "triples": triples,
        "explanation": note,
    }
