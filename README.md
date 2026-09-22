# Nimbus Brain

Internal Q&A for a **fake** usage-based API company (Nimbus). Employees will type a question; the copilot should answer from docs, SQL, or a knowledge graph — or say it does not know.

This is a school / portfolio project on seeded data, not a production support bot.

**Where we are:** checkpoint 3. Naive RAG over the markdown docs. It does not query invoices.

## Why not just chat with PDFs?

A real company question can need three different kinds of lookup:

1. **Documents** — “What is the Pro rate limit?” (SLA / pricing text)
2. **Tables** — “What did Acme’s invoice look like last month?” (SQL)
3. **Links between entities** — “Which Enterprise accounts were on incident INC-104?” (a graph hop)

Naive RAG (embed chunks → top-k → LLM) only handles (1). That is the point of this project.

## Naive search (this checkpoint)

`ingest_docs.py` splits each markdown file on `##` headings, embeds the chunks with a local model (BAAI/bge-small-en-v1.5), and stores them in `doc_chunks` on the same Neon database (pgvector).

`POST /ask` embeds the question, returns the top 3 chunks, and (if you set `OPENAI_API_KEY`) writes an answer from those chunks only. It never runs SQL.

## Fake company (this checkpoint)

Docs live in `corpus/`:

- `pricing.md` — Starter / Pro / Enterprise fees and rate limits
- `sla-enterprise.md` — credit after a long ingest outage
- `changelog.md` — Pro rate-limit change and outage INC-104

Postgres (Neon) has three tables: `plans`, `customers`, `invoices`. Six accounts, two months of bills. Acme’s August invoice is higher on purpose.

## How to run

Python 3.9+ and Node 20+. You need a Neon `DATABASE_URL` in a local `.env` (see `.env.example`). `OPENAI_API_KEY` is optional; without it, `/ask` still returns the nearest passages.

```bash
# one-time: install and seed
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python backend/app/ingest/seed.py
python backend/app/ingest/ingest_docs.py
```

```bash
# terminal 1 — API
source .venv/bin/activate
cd backend
uvicorn app.main:app --reload --port 8000
```

```bash
# terminal 2 — UI
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

Try:

- “What is the Pro rate limit?” — should quote `pricing.md` (200 requests / second).
- “What was Acme’s invoice last month?” — docs do not have that number (`$3,470` lives in Neon invoices). Naive RAG cannot look it up.

## What’s next

Checkpoint 4: text-to-SQL so invoice questions hit tables, not chunks.
