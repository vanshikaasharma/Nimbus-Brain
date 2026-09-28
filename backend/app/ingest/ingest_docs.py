"""Chunk + embed corpus/ into doc_chunks (pgvector).

Does not touch plans / customers / invoices.

Usage (from repo root, venv on):
    python backend/app/ingest/ingest_docs.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.ingest.chunk import chunk_corpus  # noqa: E402
from app.rag.embeddings import doc_table, embed_texts, embedding_dim  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

def schema_for(table: str, dim: int) -> str:
    if table not in {"doc_chunks", "doc_chunks_qwen3"}:
        raise ValueError("Unknown document table.")
    return f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS {table} (
    id SERIAL PRIMARY KEY,
    doc_path TEXT NOT NULL,
    section TEXT NOT NULL,
    body TEXT NOT NULL,
    embedding vector({dim}) NOT NULL,
    page_number INTEGER,
    source_id TEXT,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(body, ''))) STORED
);

ALTER TABLE {table} ADD COLUMN IF NOT EXISTS page_number INTEGER;
ALTER TABLE {table} ADD COLUMN IF NOT EXISTS source_id TEXT;

CREATE INDEX IF NOT EXISTS {table}_tsv_idx ON {table} USING GIN (tsv);
"""


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is missing. Copy .env.example to .env.")

    table = doc_table()
    chunks, skipped = chunk_corpus()
    if not chunks:
        raise SystemExit("No markdown or text PDF files found in corpus/.")

    vectors = embed_texts([c["body"] for c in chunks])
    paths = sorted({chunk["doc_path"] for chunk in chunks})

    with psycopg.connect(url) as conn:
        register_vector(conn)
        for statement in schema_for(table, embedding_dim()).split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(statement)

        conn.execute(
            f"DELETE FROM {table} WHERE doc_path = ANY(%s)",
            (paths,),
        )
        for chunk, vector in zip(chunks, vectors):
            conn.execute(
                f"""
                INSERT INTO {table} (doc_path, section, body, embedding, page_number, source_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    chunk["doc_path"],
                    chunk["section"],
                    chunk["body"],
                    vector,
                    chunk["page_number"],
                    chunk["source_id"],
                ),
            )
        conn.commit()

    print(f"Indexed {len(chunks)} chunks from corpus/ into {table}.")
    if skipped:
        print(
            f"Skipped {skipped} PDF page(s) with no extractable text. "
            "Scanned PDFs are not supported."
        )
    for chunk in chunks:
        page = f" p.{chunk['page_number']}" if chunk["page_number"] else ""
        print(f"  - {chunk['source_id']}{page} > {chunk['section']}")


if __name__ == "__main__":
    main()
