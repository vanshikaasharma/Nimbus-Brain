"""Hybrid doc search: vector similarity plus Postgres keyword search.

Ranks from each list are combined with reciprocal rank fusion.
A chunk that is high on both lists rises. Keyword-only hits are not dropped.
"""

from __future__ import annotations

import psycopg

from app.rag.embeddings import embed_texts

CANDIDATES = 10
RRF_K = 60


def ensure_keyword_column(conn) -> None:
    conn.execute(
        """
        ALTER TABLE doc_chunks
        ADD COLUMN IF NOT EXISTS tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('english', coalesce(body, ''))) STORED
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS doc_chunks_tsv_idx
        ON doc_chunks USING GIN (tsv)
        """
    )


def hybrid_search(conn, question: str) -> list[dict]:
    ensure_keyword_column(conn)
    query_vec = embed_texts([question])[0]
    rows = conn.execute(
        """
        WITH vector_hits AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> %(vec)s::vector) AS rank
            FROM doc_chunks
            ORDER BY embedding <=> %(vec)s::vector
            LIMIT %(n)s
        ),
        keyword_hits AS (
            SELECT id, ROW_NUMBER() OVER (
                ORDER BY ts_rank(tsv, plainto_tsquery('english', %(q)s)) DESC
            ) AS rank
            FROM doc_chunks
            WHERE tsv @@ plainto_tsquery('english', %(q)s)
            ORDER BY ts_rank(tsv, plainto_tsquery('english', %(q)s)) DESC
            LIMIT %(n)s
        ),
        fused AS (
            SELECT id, SUM(1.0 / (%(k)s + rank)) AS score
            FROM (
                SELECT id, rank FROM vector_hits
                UNION ALL
                SELECT id, rank FROM keyword_hits
            ) hits
            GROUP BY id
        )
        SELECT c.doc_path, c.section, c.body, f.score
        FROM fused f
        JOIN doc_chunks c ON c.id = f.id
        ORDER BY f.score DESC
        LIMIT %(n)s
        """,
        {
            "vec": query_vec,
            "q": question,
            "n": CANDIDATES,
            "k": RRF_K,
        },
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
