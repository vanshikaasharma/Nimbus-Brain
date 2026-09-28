"""Score routing and retrieval.

The default command scores the keyword router on golden.json.
`--llm` also scores Llama routing, dynamic mixed steps, and a separate agent loop.
Those are different scores. A keyword 10/10 is not an agent score.

Usage (from repo root, venv on):
    python backend/eval/run_eval.py
    python backend/eval/run_eval.py --llm
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import psycopg  # noqa: E402
from pgvector.psycopg import register_vector  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.rag.graph_tool import walk  # noqa: E402
from app.rag.naive import ask  # noqa: E402
from app.rag.retrieve import vector_search  # noqa: E402
from app.rag.router import classify  # noqa: E402
from app.rag.sql_tool import run_question  # noqa: E402

load_dotenv(ROOT / ".env")
GOLDEN = Path(__file__).with_name("golden.json")
EXTENDED = Path(__file__).with_name("extended.json")


def names_in_rows(rows: list[dict]) -> set[str]:
    found = set()
    for row in rows:
        if "name" in row:
            found.add(row["name"])
    return found


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is missing.")

    questions = json.loads(GOLDEN.read_text())["questions"]
    route_ok = 0
    sql_ok = 0
    sql_total = 0
    graph_ok = 0
    graph_total = 0
    doc_ok = 0
    doc_total = 0

    print(f"{'id':<22} {'expected':<8} {'got':<8} ok")
    for item in questions:
        got = classify(item["question"])["route"]
        ok = got == item["route"]
        route_ok += int(ok)
        print(f"{item['id']:<22} {item['route']:<8} {got:<8} {ok}")

        if item["route"] == "sql" and ("expect_cents" in item or "expect_names" in item):
            sql_total += 1
            result = run_question(url, item["question"])
            rows = result.get("rows") or []
            if "expect_cents" in item:
                match = any(row.get("amount_cents") == item["expect_cents"] for row in rows)
            else:
                match = names_in_rows(rows) == set(item["expect_names"])
            sql_ok += int(match)
            print(f"  sql match: {match}")

        if item["route"] == "graph":
            graph_total += 1
            result = walk(url, item["question"])
            blob = " ".join(result.get("paths") or [])
            match = all(name in blob for name in item["expect_names"])
            graph_ok += int(match)
            print(f"  graph match: {match}")

        if item["route"] == "docs" and "expect_doc" in item:
            doc_total += 1
            result = ask(url, item["question"], generate=False)
            match = any(chunk["doc_path"] == item["expect_doc"] for chunk in result.get("chunks") or [])
            doc_ok += int(match)
            print(f"  doc match: {match} abstained={result.get('abstained')}")

    invoice = next(item for item in questions if item["id"] == "acme-invoice")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        register_vector(conn)
        vector_chunks = vector_search(conn, invoice["question"])
    vector_blob = "\n".join(chunk["body"] for chunk in vector_chunks)
    vector_misses = "347000" not in vector_blob and "3,470" not in vector_blob

    print()
    print(f"routing: {route_ok}/{len(questions)}")
    print(f"sql exact: {sql_ok}/{sql_total}")
    print(f"graph names: {graph_ok}/{graph_total}")
    print(f"doc file in reranked hits: {doc_ok}/{doc_total}")
    print(f"vector-only misses Acme $3,470: {vector_misses}")


def load_questions(*paths: Path) -> list[dict]:
    questions = []
    for path in paths:
        questions.extend(json.loads(path.read_text())["questions"])
    return questions


def sql_match(item: dict, result: dict) -> bool:
    rows = result.get("rows") or []
    if "expect_rows" in item:
        return len(rows) == item["expect_rows"]
    if "expect_cents" in item:
        if any(row.get("amount_cents") == item["expect_cents"] for row in rows):
            return True
        return any(item["expect_cents"] in row.values() for row in rows)
    if "expect_names" in item:
        return names_in_rows(rows) == set(item["expect_names"])
    return False


def graph_direction_ok(item: dict, result: dict) -> bool | None:
    expected = item.get("expect_direction")
    if not expected:
        return None
    plan = result.get("plan") or {}
    hops = plan.get("hops") or []
    return any(hop.get("direction") == expected for hop in hops)


def run_llm(url: str) -> None:
    """Compare keyword labels with the configured chat model, then check the extended questions."""
    from app.rag.chat import RATE_LIMITS, chat_model
    from app.rag.mixed import draft_steps, fallback_steps, run_mixed
    from app.rag.router import choose_route

    print(f"chat model: {chat_model()}")
    questions = load_questions(GOLDEN, EXTENDED)
    print(f"LLM comparison sample: {len(questions)} questions")
    keyword_ok = 0
    model_ok = 0
    model_scored = 0
    fallback_used = 0
    rate_limited = 0
    unavailable = 0
    failures = []
    latencies = []
    routing_rows = []

    for item in questions:
        started = time.perf_counter()
        keyword = classify(item["question"])["route"]
        picked = choose_route(item["question"])
        elapsed = time.perf_counter() - started
        latencies.append(elapsed)
        keyword_ok += int(keyword == item["route"])
        if picked.get("rate_limited"):
            rate_limited += 1
            routing_rows.append({"id": item["id"], "status": "rate_limit", "seconds": round(elapsed, 3)})
            print(f"{item['id']:<22} RATE LIMIT {elapsed:.1f}s (not scored as the chat model)")
            continue
        if picked.get("unavailable"):
            unavailable += 1
            routing_rows.append({"id": item["id"], "status": "unavailable", "seconds": round(elapsed, 3)})
            print(f"{item['id']:<22} UNAVAILABLE {elapsed:.1f}s (not scored as the chat model)")
            continue
        model = picked["route"]
        model_scored += 1
        model_ok += int(model == item["route"])
        if picked.get("fallback"):
            fallback_used += 1
        mark = "ok" if model == item["route"] else "MISS"
        print(
            f"{item['id']:<22} keyword={keyword:<8} model={model:<8} "
            f"{mark} {elapsed:.1f}s"
        )
        routing_rows.append(
            {
                "id": item["id"],
                "status": "scored",
                "keyword": keyword,
                "model": model,
                "fallback": bool(picked.get("fallback")),
                "ok": model == item["route"],
                "seconds": round(elapsed, 3),
            }
        )
        if model != item["route"]:
            failures.append(f"{item['id']}: model {model}, expected {item['route']}")

    extended = json.loads(EXTENDED.read_text())["questions"]
    print()
    print(f"Extended retrieval sample: {len(extended)} questions")
    sql_ok = sql_total = 0
    graph_ok = graph_total = 0
    direction_ok = direction_total = 0
    doc_ok = doc_total = 0
    mixed_fixed_ok = mixed_dynamic_ok = mixed_total = 0
    grounding_rows = []

    for item in extended:
        started = time.perf_counter()
        if item["route"] == "sql":
            sql_total += 1
            result = run_question(url, item["question"])
            match = sql_match(item, result)
            sql_ok += int(match)
            rows = result.get("rows") or []
            if item.get("expect_rows") == 0:
                print(f"  {item['id']}: rows={len(rows)} missing_ok={match}")
            else:
                print(f"  {item['id']}: sql match={match} error={result.get('error')}")
            if item["id"] == "acme-july-2026" and rows and not result.get("error"):
                from app.rag.generate import answer_with_sources, with_dollars

                sources = [
                    (f"S{index}", str(row))
                    for index, row in enumerate(with_dollars(rows), start=1)
                ]
                written, flags = answer_with_sources(item["question"], sources)
                grounding_rows.append({"id": item["id"], "flags": flags, "answer": written})
                print(f"    model answer: {written}")
                print(f"    citation/evidence flags: {flags or 'none'}")
            if not match:
                failures.append(f"{item['id']}: sql rows did not match")
        elif item["route"] == "graph":
            graph_total += 1
            result = walk(url, item["question"])
            blob = " ".join(result.get("paths") or [])
            match = all(name in blob for name in item.get("expect_names") or [])
            graph_ok += int(match)
            direction = graph_direction_ok(item, result)
            if direction is not None:
                direction_total += 1
                direction_ok += int(direction)
            plan = result.get("plan")
            print(
                f"  {item['id']}: names={match} plan={bool(plan)} "
                f"direction={direction} note={result.get('explanation')}"
            )
            if not match:
                failures.append(f"{item['id']}: graph names missed")
            if direction is False:
                failures.append(f"{item['id']}: graph plan was not {item['expect_direction']}")
        elif item["route"] == "docs":
            doc_total += 1
            result = ask(url, item["question"], generate=False)
            match = any(chunk["doc_path"] == item["expect_doc"] for chunk in result.get("chunks") or [])
            doc_ok += int(match)
            print(f"  {item['id']}: doc match={match} abstained={result.get('abstained')}")
            if not match:
                failures.append(f"{item['id']}: expected doc was not retrieved")
        elif item["route"] == "mixed":
            mixed_total += 1
            fixed = fallback_steps(item["question"])
            before_limits = len(RATE_LIMITS)
            dynamic = draft_steps(item["question"])
            if len(RATE_LIMITS) > before_limits:
                mixed_total -= 1
                print(f"  {item['id']}: RATE LIMIT during planning (not scored as the chat model)")
                elapsed = time.perf_counter() - started
                latencies.append(elapsed)
                continue
            expected = item.get("expect_tools") or []
            fixed_match = fixed == expected
            dynamic_match = dynamic == expected
            mixed_fixed_ok += int(fixed_match)
            mixed_dynamic_ok += int(dynamic_match)
            result = run_mixed(url, item["question"])
            grounding_rows.append(
                {
                    "id": item["id"],
                    "flags": result.get("grounding") or [],
                    "planner": result.get("planner"),
                    "steps": result.get("steps"),
                    "missing": result.get("missing"),
                }
            )
            print(
                f"  {item['id']}: fixed={fixed} dynamic={dynamic} "
                f"planner={result.get('planner')} ran={result.get('steps')} "
                f"missing={result.get('missing')} flags={result.get('grounding')}"
            )
            if not dynamic_match:
                failures.append(f"{item['id']}: dynamic steps {dynamic}, expected {expected}")
        elapsed = time.perf_counter() - started
        latencies.append(elapsed)
        print(f"    retrieval {elapsed:.1f}s")

    print()
    print(f"keyword labels: {keyword_ok}/{len(questions)}")
    print(
        f"chat model labels: {model_ok}/{model_scored} scored "
        f"(fallbacks to keywords: {fallback_used}, rate limits: {rate_limited}, "
        f"unavailable: {unavailable}, recorded rate-limit events: {len(RATE_LIMITS)})"
    )
    print(f"extended sql: {sql_ok}/{sql_total}")
    print(f"extended graph names: {graph_ok}/{graph_total}")
    print(f"extended reverse plans: {direction_ok}/{direction_total}")
    print(f"extended docs: {doc_ok}/{doc_total}")
    print(f"mixed fixed tool list: {mixed_fixed_ok}/{mixed_total}")
    print(f"mixed dynamic tool list: {mixed_dynamic_ok}/{mixed_total}")
    if latencies:
        print(f"latency seconds: min {min(latencies):.1f} max {max(latencies):.1f}")
    if failures:
        print("failures:")
        for item in failures:
            print(f"  - {item}")
    else:
        print("failures: none")
    return {
        "model": chat_model(),
        "routing": {
            "keyword_ok": keyword_ok,
            "keyword_total": len(questions),
            "model_ok": model_ok,
            "model_scored": model_scored,
            "fallbacks": fallback_used,
            "rate_limits": rate_limited,
            "unavailable": unavailable,
            "rate_limit_events": len(RATE_LIMITS),
            "latency_min": round(min(latencies), 3) if latencies else None,
            "latency_max": round(max(latencies), 3) if latencies else None,
            "failures": failures,
            "rows": routing_rows,
        },
        "extended": {
            "sql_ok": sql_ok,
            "sql_total": sql_total,
            "graph_ok": graph_ok,
            "graph_total": graph_total,
            "reverse_ok": direction_ok,
            "reverse_total": direction_total,
            "docs_ok": doc_ok,
            "docs_total": doc_total,
            "mixed_fixed_ok": mixed_fixed_ok,
            "mixed_dynamic_ok": mixed_dynamic_ok,
            "mixed_total": mixed_total,
            "grounding": grounding_rows,
        },
    }


AGENT_QUESTIONS = [
    {
        "id": "agent-docs",
        "question": "What is the Pro rate limit?",
        "expect_tool": "docs",
    },
    {
        "id": "agent-sql",
        "question": "What was Acme's invoice in August 2026?",
        "expect_tool": "sql",
    },
    {
        "id": "agent-graph",
        "question": "Which accounts did INC-104 affect?",
        "expect_tool": "graph",
    },
    {
        "id": "agent-mixed",
        "question": "Which accounts did INC-104 affect, and what were their August 2026 invoices?",
        "expect_tools": ["graph", "sql"],
    },
]


UNSEEN = [
    {
        "id": "unseen-overage",
        "question": "What does Pro charge for each extra million events?",
        "route": "docs",
    },
    {
        "id": "unseen-initech",
        "question": "What did Initech spend in July 2026?",
        "route": "sql",
        "expect_cents": 49900,
    },
    {
        "id": "unseen-incident-acme",
        "question": "Which incident touched the Acme account?",
        "route": "graph",
        "expect_names": ["INC-104", "Acme"],
    },
    {
        "id": "unseen-limit-and-hooli",
        "question": "What is the Pro rate limit, and what did Hooli pay in July 2026?",
        "route": "mixed",
        "expect_tools": ["sql", "docs"],
    },
]


def run_unseen(url: str) -> None:
    """Questions that are not in the 23-question routing set."""
    from app.rag.chat import RATE_LIMITS
    from app.rag.mixed import draft_steps
    from app.rag.router import choose_route

    print(f"Unseen routing sample: {len(UNSEEN)} questions")
    scored = 0
    ok = 0
    skipped = []
    rows = []
    for item in UNSEEN:
        before = len(RATE_LIMITS)
        picked = choose_route(item["question"])
        if picked.get("rate_limited") or picked.get("unavailable") or len(RATE_LIMITS) > before:
            skipped.append({"id": item["id"], "reason": picked.get("reason")})
            print(f"  {item['id']}: not scored ({picked.get('reason')})")
            continue
        scored += 1
        match = picked["route"] == item["route"]
        detail = ""
        if item["route"] == "sql" and match:
            result = run_question(url, item["question"])
            row_ok = sql_match(item, result)
            match = row_ok
            detail = f" sql={row_ok}"
        if item["route"] == "graph" and match:
            result = walk(url, item["question"])
            blob = " ".join(result.get("paths") or [])
            name_ok = all(name in blob for name in item["expect_names"])
            match = name_ok
            detail = f" names={name_ok} plan={bool(result.get('plan'))}"
        if item["route"] == "mixed":
            steps = draft_steps(item["question"])
            match = set(steps or []) == set(item["expect_tools"])
            detail = f" steps={steps}"
        ok += int(match)
        rows.append({"id": item["id"], "route": picked["route"], "ok": match, "detail": detail.strip()})
        print(f"  {item['id']}: route={picked['route']} ok={match}{detail}")
    print(f"unseen chat-model items: {ok}/{scored}")
    return {"ok": ok, "scored": scored, "skipped": skipped, "rows": rows}


def run_agent_eval(url: str) -> dict:
    """Score the LangGraph loop on its own. Not the keyword report card."""
    from app.rag.agent import run_agent

    print(f"Agent sample: {len(AGENT_QUESTIONS)} questions")
    ok = 0
    failures = []
    skipped = 0
    rows = []
    for item in AGENT_QUESTIONS:
        started = time.perf_counter()
        try:
            result = run_agent(url, item["question"])
        except Exception as exc:
            skipped += 1
            elapsed = time.perf_counter() - started
            print(f"{item['id']:<22} ERROR {type(exc).__name__}: {exc} {elapsed:.1f}s")
            failures.append(f"{item['id']}: {type(exc).__name__}: {exc}")
            rows.append(
                {
                    "id": item["id"],
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "seconds": round(elapsed, 3),
                }
            )
            continue
        elapsed = time.perf_counter() - started
        steps = result.get("steps") or []
        expected = item.get("expect_tools") or [item["expect_tool"]]
        match = all(tool in steps for tool in expected)
        ok += int(match)
        rows.append(
            {
                "id": item["id"],
                "steps": steps,
                "ok": match,
                "seconds": round(elapsed, 3),
                "grounding": result.get("grounding") or [],
                "answer": result.get("answer"),
            }
        )
        print(
            f"{item['id']:<22} steps={steps} tool_ok={match} "
            f"{elapsed:.1f}s answer={result.get('answer')}"
        )
        if not match:
            failures.append(f"{item['id']}: steps {steps}, expected {expected}")
    print(f"agent tool choice: {ok}/{len(AGENT_QUESTIONS) - skipped} scored, {skipped} errors")
    if failures:
        print("agent failures:")
        for item in failures:
            print(f"  - {item}")
    else:
        print("agent failures: none")
    return {
        "ok": ok,
        "scored": len(AGENT_QUESTIONS) - skipped,
        "errors": skipped,
        "failures": failures,
        "rows": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true", help="Also score the chat model, unseen questions, and the agent loop")
    parser.add_argument("--chat", choices=("ollama", "groq"), default=None)
    args = parser.parse_args()
    if args.chat == "ollama":
        os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:11434/v1"
        os.environ["OPENAI_CHAT_MODEL"] = "llama3.2"
        os.environ["OPENAI_API_KEY"] = "ollama"
    elif args.chat == "groq":
        os.environ["OPENAI_BASE_URL"] = "https://api.groq.com/openai/v1"
        os.environ["OPENAI_CHAT_MODEL"] = "openai/gpt-oss-120b"
    main()
    if args.llm:
        database = os.environ.get("DATABASE_URL")
        if not database:
            raise SystemExit("DATABASE_URL is missing.")
        print()
        from app.rag.chat import RATE_LIMITS, chat_model

        RATE_LIMITS.clear()
        report = {
            "model": chat_model(),
            "routing_and_extended": run_llm(database),
            "unseen": run_unseen(database),
            "agent": run_agent_eval(database),
            "rate_limit_events": len(RATE_LIMITS),
        }
        slug = chat_model().replace("/", "_")
        report_path = Path(__file__).with_name(f"chat_{slug}.json")
        report_path.write_text(json.dumps(report, indent=2))
        print(f"\nWrote {report_path}")
