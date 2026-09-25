"""Score the keyword router against backend/eval/golden.json.

Also checks SQL rows and one docs-only miss on Acme's invoice.

Usage (from repo root, venv on):
    python backend/eval/run_eval.py
"""

from __future__ import annotations

import json
import os
import sys
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


if __name__ == "__main__":
    main()
