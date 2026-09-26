"""One extra lookup when the first tool comes back empty.

Docs still rewrite a question once inside ask(). Mixed retrieval still widens
one empty step. This module may call one other tool when the question names
that kind of evidence. It does not loop, and it does not fill gaps with guesses.
"""

from __future__ import annotations

from app.rag.generate import answer_with_sources, with_dollars


def gaps(route: str, result: dict) -> list[str]:
    if route == "mixed":
        return list(result.get("missing") or [])
    if route == "docs":
        if result.get("abstained") or not result.get("chunks"):
            return ["doc passage"]
        return []
    if route == "sql":
        sql = result.get("sql") or {}
        if sql.get("error") or not sql.get("rows"):
            return ["invoice rows"]
        return []
    if route == "graph":
        graph = result.get("graph") or {}
        if graph.get("error") or not graph.get("paths"):
            return ["graph path"]
        return []
    if route == "unknown":
        return ["a matching tool"]
    return []


def other_tool(question: str, route: str) -> str | None:
    """Another tool only when the question asks for one kind of evidence."""
    q = question.lower()
    asks_invoice = any(word in q for word in ("invoice", "bill", "charged", "pay", "paid", "spent", "spend"))
    asks_graph = any(word in q for word in ("inc-", "incident", "outage"))
    asks_docs = any(word in q for word in ("sla", "rate limit", "pricing", "credit", "owe"))
    kinds = sum([asks_invoice, asks_graph, asks_docs])
    if kinds != 1:
        return None
    if route == "docs" and asks_invoice:
        return "sql"
    if route == "sql" and asks_graph:
        return "graph"
    if route == "graph" and asks_docs:
        return "docs"
    if route == "graph" and asks_invoice:
        return "sql"
    if route == "docs" and asks_graph:
        return "graph"
    if route == "sql" and asks_docs:
        return "docs"
    return None


def run_tool(database_url: str, question: str, tool: str) -> dict:
    if tool == "docs":
        from app.rag.naive import ask

        return ask(database_url, question)
    if tool == "sql":
        from app.rag.sql_tool import run_question

        sql = run_question(database_url, question)
        rows = with_dollars(sql.get("rows"))
        if not rows:
            answer = "The tables returned no rows for that question."
            flags: list[str] = []
        else:
            sources = [(f"S{index}", str(row)) for index, row in enumerate(rows, start=1)]
            written, flags = answer_with_sources(question, sources)
            answer = written or "The rows are the answer. Set OPENAI_API_KEY to turn them into a sentence."
        return {"sql": sql, "answer": answer, "grounding": flags, "chunks": []}
    if tool == "graph":
        from app.rag.graph_tool import walk

        graph = walk(database_url, question)
        paths = graph.get("paths") or []
        if not paths:
            answer = "The graph returned no path for that question."
            flags = []
        else:
            sources = [(f"G{index}", path) for index, path in enumerate(paths, start=1)]
            written, flags = answer_with_sources(question, sources)
            answer = written or "The paths are the answer. Set OPENAI_API_KEY to turn them into a sentence."
        return {"graph": graph, "answer": answer, "grounding": flags, "chunks": []}
    return {
        "answer": "I don't know which tool fits that question.",
        "chunks": [],
    }


def _note_missing(result: dict, missing: list[str]) -> None:
    if not missing:
        return
    note = "Missing evidence: " + ", ".join(missing) + "."
    answer = (result.get("answer") or "").rstrip()
    if note not in answer:
        result["answer"] = (answer + " " + note).strip()
    flags = list(result.get("grounding") or [])
    if note not in flags:
        flags.append(note)
    result["grounding"] = flags


def with_fallback(database_url: str, question: str, route: str) -> dict:
    if route == "mixed":
        from app.rag.mixed import run_mixed

        result = run_mixed(database_url, question)
        result["tools"] = list(result.get("steps") or [])
        result["retries"] = (
            [{"tool": "mixed", "reason": "one empty result was looked up again"}]
            if result.get("retried")
            else []
        )
        result["missing"] = gaps("mixed", result)
        return result

    result = run_tool(database_url, question, route)
    result["tools"] = [route] if route in {"docs", "sql", "graph"} else []
    retries = []
    if route == "docs" and result.get("retried"):
        retries.append({"tool": "docs", "reason": "rewrote the question once"})
    missing = gaps(route, result)
    nxt = other_tool(question, route) if missing else None
    if nxt:
        second = run_tool(database_url, question, nxt)
        result["tools"].append(nxt)
        retries.append({"tool": nxt, "reason": "first lookup missed " + ", ".join(missing)})
        result["retried"] = True
        for key in ("sql", "graph", "chunks", "answer", "grounding", "abstained"):
            if key in second:
                result[key] = second[key]
        missing = gaps(nxt, second)
    result["retries"] = retries
    result["missing"] = missing
    _note_missing(result, missing)
    return result
