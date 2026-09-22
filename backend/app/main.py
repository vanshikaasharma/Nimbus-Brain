"""Nimbus Brain API.

Checkpoint 3: naive doc search plus the customer spreadsheet from checkpoint 2.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import psycopg
from psycopg.rows import dict_row

from app.rag.naive import ask

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL")

app = FastAPI(title="Nimbus Brain")

# The Vite app runs on 5173. Without this, the browser blocks API requests.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str = Field(min_length=1)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/customers")
def list_customers():
    """Read the seeded spreadsheet. Not a chatbot — just proof the DB is real."""
    if not DATABASE_URL:
        return {"error": "DATABASE_URL is not set"}

    try:
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
            rows = conn.execute(
                """
                SELECT
                    c.id,
                    c.name,
                    p.name AS plan,
                    i.period_start,
                    i.period_end,
                    i.amount_cents
                FROM customers c
                JOIN plans p ON p.id = c.plan_id
                JOIN invoices i ON i.customer_id = c.id
                ORDER BY c.name, i.period_start
                """
            ).fetchall()
    except psycopg.Error as exc:
        return {"error": f"Could not read the database: {exc}"}

    return {"customers": rows}


@app.post("/ask")
def ask_docs(req: AskRequest):
    """Naive RAG: nearest doc chunks only. Does not query invoices."""
    if not DATABASE_URL:
        return {"error": "DATABASE_URL is not set"}
    try:
        return ask(DATABASE_URL, req.question.strip())
    except psycopg.Error as exc:
        return {"error": f"Could not search docs: {exc}"}
