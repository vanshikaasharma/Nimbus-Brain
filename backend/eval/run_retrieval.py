"""Compare embedding and reranker pairs on the same chunks and questions.

Writes a text PDF into corpus/, rebuilds only the selected document table,
then scores hybrid search plus reranking. Customer, invoice, and graph rows
are not modified.

Usage (from repo root, venv on):
    python backend/eval/run_retrieval.py
    python backend/eval/run_retrieval.py --only bge+minilm
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import fitz
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

load_dotenv(ROOT / ".env")

CORPUS = ROOT / "corpus"
PDF_PATH = CORPUS / "eval-burst.pdf"
QUESTIONS = json.loads((Path(__file__).with_name("retrieval.json")).read_text())["questions"]
PAIRS = (
    ("bge", "minilm"),
    ("bge", "qwen3"),
    ("qwen3", "minilm"),
    ("qwen3", "qwen3"),
)


def write_burst_pdf() -> None:
    """Two similar pages. The ceiling is only on page 2."""
    document = fitz.open()
    first = document.new_page()
    first.insert_text(
        (72, 72),
        "Burst floor\n\nThe burst floor is 4,000 events. "
        "This page describes the floor, not the ceiling. "
        "Operators use the floor when deciding whether a short spike should be queued.",
        fontsize=12,
    )
    second = document.new_page()
    second.insert_text(
        (72, 72),
        "Burst ceiling\n\nThe burst ceiling is 40,000 events. "
        "Traffic above the ceiling is shed. "
        "The floor on the previous page is a different number.",
        fontsize=12,
    )
    document.save(PDF_PATH)
    document.close()


def rank_of(hits: list[dict], expected: str) -> int | None:
    for index, hit in enumerate(hits, start=1):
        source = hit.get("source_id") or ""
        if source == expected or source.startswith(expected):
            return index
    return None


def fused_hits(url: str, question: str) -> list[dict]:
    """Search, then close the connection before any slow local rerank."""
    import psycopg
    from pgvector.psycopg import register_vector
    from psycopg.rows import dict_row

    from app.rag.retrieve import hybrid_search

    last_error = None
    for _attempt in range(2):
        try:
            with psycopg.connect(url, row_factory=dict_row) as conn:
                register_vector(conn)
                return hybrid_search(conn, question)
        except psycopg.OperationalError as exc:
            last_error = exc
    raise last_error


def score_pair(embedding: str, reranker: str) -> dict:
    os.environ["EMBEDDING_MODEL"] = embedding
    os.environ["RERANKER"] = reranker
    from app.ingest.ingest_docs import main as ingest_main
    from app.rag.rerank import rerank

    started = time.perf_counter()
    ingest_main()
    ingest_seconds = time.perf_counter() - started

    url = os.environ["DATABASE_URL"]
    warmup = fused_hits(url, "warmup")
    rerank("warmup", warmup[:1])
    recalls = []
    mrr_fused = []
    mrr_reranked = []
    latencies = []
    rows = []
    for item in QUESTIONS:
        t0 = time.perf_counter()
        fused = fused_hits(url, item["question"])
        reranked = rerank(item["question"], fused)
        elapsed = time.perf_counter() - t0
        latencies.append(elapsed)
        fused_rank = rank_of(fused, item["expect_source"])
        final_rank = rank_of(reranked, item["expect_source"])
        recalls.append(int(final_rank is not None and final_rank <= 3))
        mrr_fused.append(0.0 if fused_rank is None else 1.0 / fused_rank)
        mrr_reranked.append(0.0 if final_rank is None else 1.0 / final_rank)
        rows.append(
                {
                    "id": item["id"],
                    "kind": item["kind"],
                    "fused_rank": fused_rank,
                    "rerank_rank": final_rank,
                    "seconds": round(elapsed, 3),
                }
            )
    count = len(QUESTIONS)
    return {
        "embedding": embedding,
        "reranker": reranker,
        "ingest_seconds": round(ingest_seconds, 1),
        "recall_at_3": sum(recalls) / count,
        "mrr_before_rerank": sum(mrr_fused) / count,
        "mrr_after_rerank": sum(mrr_reranked) / count,
        "mean_latency_seconds": sum(latencies) / count,
        "questions": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="One pair, such as bge+minilm")
    args = parser.parse_args()
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("DATABASE_URL is missing.")
    write_burst_pdf()
    selected = PAIRS
    if args.only:
        embedding, reranker = args.only.split("+", 1)
        selected = ((embedding, reranker),)
    out = Path(__file__).with_name("retrieval_results.json")
    results = []
    if args.only and out.exists():
        results = json.loads(out.read_text())
    for embedding, reranker in selected:
        label = f"{embedding}+{reranker}"
        print(f"\n=== {label} ===", flush=True)
        try:
            scored = score_pair(embedding, reranker)
        except Exception as exc:
            print(f"{label} failed: {type(exc).__name__}: {exc}")
            scored = {"embedding": embedding, "reranker": reranker, "error": f"{type(exc).__name__}: {exc}"}
        results = [
            item
            for item in results
            if not (item.get("embedding") == embedding and item.get("reranker") == reranker)
        ]
        results.append(scored)
        if "error" in scored:
            continue
        print(
            f"Recall@3 {scored['recall_at_3']:.2f}  "
            f"MRR before {scored['mrr_before_rerank']:.2f}  "
            f"MRR after {scored['mrr_after_rerank']:.2f}  "
            f"mean latency {scored['mean_latency_seconds']:.2f}s  "
            f"ingest {scored['ingest_seconds']}s"
        )
        for row in scored["questions"]:
            print(
                f"  {row['id']:<24} fused={row['fused_rank']} rerank={row['rerank_rank']} "
                f"{row['seconds']:.2f}s {row['kind']}"
            )
        out.write_text(json.dumps(results, indent=2))
        print(f"Wrote {out}", flush=True)
    if not args.only:
        out.write_text(json.dumps(results, indent=2))
        print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
