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
from app.rag.embeddings import DIM, embed_texts  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;

DROP TABLE IF EXISTS doc_chunks;

CREATE TABLE doc_chunks (
    id SERIAL PRIMARY KEY,
    doc_path TEXT NOT NULL,
    section TEXT NOT NULL,
    body TEXT NOT NULL,
    embedding vector({DIM}) NOT NULL
);
"""


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is missing. Copy .env.example to .env.")

    chunks = chunk_corpus()
    if not chunks:
        raise SystemExit("No markdown files found in corpus/.")

    vectors = embed_texts([c["body"] for c in chunks])

    with psycopg.connect(url) as conn:
        register_vector(conn)
        for statement in SCHEMA.split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(statement)

        for chunk, vector in zip(chunks, vectors):
            conn.execute(
                """
                INSERT INTO doc_chunks (doc_path, section, body, embedding)
                VALUES (%s, %s, %s, %s)
                """,
                (chunk["doc_path"], chunk["section"], chunk["body"], vector),
            )
        conn.commit()

    print(f"Indexed {len(chunks)} chunks from corpus/ into doc_chunks.")
    for chunk in chunks:
        print(f"  - {chunk['doc_path']} > {chunk['section']}")


if __name__ == "__main__":
    main()
