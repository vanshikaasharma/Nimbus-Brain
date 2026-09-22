from __future__ import annotations

"""Naive RAG: embed the question, take top-k chunks, optionally ask an LLM.

This path never looks at invoices or the graph. That is the point.
"""

import os

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from app.rag.embeddings import embed_texts

TOP_K = 3


def search_chunks(conn, question: str) -> list[dict]:
    query_vec = embed_texts([question])[0]
    rows = conn.execute(
        """
        SELECT
            doc_path,
            section,
            body,
            1 - (embedding <=> %s::vector) AS score
        FROM doc_chunks
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (query_vec, query_vec, TOP_K),
    ).fetchall()
    return [
        {
            "doc_path": row["doc_path"],
            "section": row["section"],
            "body": row["body"],
            "score": float(row["score"]),
        }
        for row in rows
    ]


def generate_answer(question: str, chunks: list[dict]) -> str:
    """Use OpenAI if a key is set; otherwise just point at the passages."""
    api_key = os.environ.get("OPENAI_API_KEY")
    passages = "\n\n".join(
        f"[{c['doc_path']} > {c['section']}]\n{c['body']}" for c in chunks
    )

    if not api_key:
        return (
            "Naive search only looked at company docs, not invoices. "
            "Closest passages are below. I did not invent a number. "
            "Set OPENAI_API_KEY if you want a generated answer from these chunks."
        )

    from openai import OpenAI

    base_url = os.environ.get("OPENAI_BASE_URL") or None
    model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Answer using only the passages. If they do not contain the "
                    "answer, say you do not know. Do not invent numbers."
                ),
            },
            {
                "role": "user",
                "content": f"Passages:\n{passages}\n\nQuestion: {question}",
            },
        ],
    )
    return response.choices[0].message.content or "No answer returned."


def ask(database_url: str, question: str) -> dict:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        register_vector(conn)
        chunks = search_chunks(conn, question)

    if not chunks:
        return {
            "answer": "No document chunks are indexed yet. Run ingest_docs.py.",
            "chunks": [],
        }

    return {
        "answer": generate_answer(question, chunks),
        "chunks": chunks,
    }
