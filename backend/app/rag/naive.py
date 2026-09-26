from __future__ import annotations

"""Doc answers: hybrid search, rerank, then one grade-and-retry.

This path never looks at invoices or the graph.
"""

import os

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from app.rag.grade import grade, rewrite_once
from app.rag.rerank import rerank
from app.rag.retrieve import hybrid_search


def search_chunks(conn, question: str) -> list[dict]:
    return rerank(question, hybrid_search(conn, question))


def generate_answer(question: str, chunks: list[dict]) -> str:
    """Use OpenAI if a key is set; otherwise just point at the passages."""
    api_key = os.environ.get("OPENAI_API_KEY")
    passages = "\n\n".join(
        f"[D{index}] {chunk['doc_path']} > {chunk['section']}\n{chunk['body']}"
        for index, chunk in enumerate(chunks, start=1)
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
                    "Answer using only the passages. Cite each fact with its source id, "
                    "such as [D1]. If they do not contain the answer, say you do not know. "
                    "Do not invent numbers."
                ),
            },
            {
                "role": "user",
                "content": f"Passages:\n{passages}\n\nQuestion: {question}",
            },
        ],
    )
    from app.rag.generate import review_answer

    text = (response.choices[0].message.content or "").strip() or "No answer returned."
    checked, _flags = review_answer(
        text,
        {f"D{index}" for index in range(1, len(chunks) + 1)},
        passages,
    )
    return checked


def ask(database_url: str, question: str, generate: bool = True) -> dict:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        register_vector(conn)
        chunks = search_chunks(conn, question)
        verdict = grade(question, chunks)
        retried = False
        used_question = question

        if verdict == "irrelevant":
            rewritten = rewrite_once(question)
            retried = True
            if rewritten.lower() != question.lower():
                used_question = rewritten
                chunks = search_chunks(conn, rewritten)
                verdict = grade(rewritten, chunks)

    if not chunks:
        return {
            "answer": "No document chunks are indexed yet. Run ingest_docs.py.",
            "chunks": [],
            "retried": retried,
            "abstained": True,
        }

    if verdict == "irrelevant":
        return {
            "answer": "I don't have evidence for that in the Nimbus docs.",
            "chunks": [],
            "retried": retried,
            "abstained": True,
        }

    return {
        "answer": generate_answer(used_question, chunks) if generate else "",
        "chunks": chunks,
        "retried": retried,
        "abstained": False,
    }
