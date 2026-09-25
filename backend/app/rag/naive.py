from __future__ import annotations

"""Doc answers: hybrid search, then an optional sentence from those chunks.

This path never looks at invoices or the graph.
"""

import os

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from app.rag.retrieve import hybrid_search


def search_chunks(conn, question: str) -> list[dict]:
    return hybrid_search(conn, question)


def generate_answer(question: str, chunks: list[dict]) -> str:
    """Use OpenAI if a key is set; otherwise just point at the passages."""
    api_key = os.environ.get("OPENAI_API_KEY")
    passages = "\n\n".join(
        f"[{c['doc_path']} > {c['section']}]\n{c['body']}" for c in chunks
    )

    if not api_key:
        return (
            "Doc search looked at company docs, not invoices. "
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


def ask(database_url: str, question: str, generate: bool = True) -> dict:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        register_vector(conn)
        chunks = search_chunks(conn, question)

    if not chunks:
        return {
            "answer": "No document chunks are indexed yet. Run ingest_docs.py.",
            "chunks": [],
        }

    return {
        "answer": generate_answer(question, chunks) if generate else "",
        "chunks": chunks,
    }
