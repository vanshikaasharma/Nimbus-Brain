# Nimbus Brain

Internal Q&A for a **fake** usage-based API company (Nimbus). Employees will type a question; the copilot should answer from docs, SQL, or a knowledge graph — or say it does not know.

This is a school / portfolio project on seeded data, not a production support bot.

**Where we are:** Ask still uses the keyword router. “Ask with the loop” lets the local model pick docs, SQL, or the graph, look at the result, and pick again. It stops after a few steps.

## Why not just chat with PDFs?

A real company question can need three different kinds of lookup:

1. **Documents** — “What is the Pro rate limit?” (SLA / pricing text)
2. **Tables** — “What did Acme’s invoice look like last month?” (SQL)
3. **Links between entities** — “Which Enterprise accounts were on incident INC-104?” (a graph hop)

Naive RAG (embed chunks → top-k → LLM) only handles (1). That is the point of this project.

## Mixed question (this checkpoint)

If the router marks a question `mixed`, `mixed.py` always does three lookups:

1. Graph: INC-104 → impacted accounts → plan
2. SQL: August invoices for those account names
3. Docs: the Enterprise SLA credit section

If Ollama is running, one local model call writes the sentence from that evidence. The chunks, rows, and paths are still shown.

## Traffic cop

`POST /chat` runs `router.py` first. The rules are keywords, not an LLM:

- rate limit / SLA / pricing → docs
- invoice / bill, or “who is on Enterprise” → SQL
- INC-104 / incident / outage → graph
- two of those at once → `mixed`, which runs graph, then SQL, then docs

## Relationship map

`seed_graph.py` copies plans and customers into `nodes`, then adds incident **INC-104** and two edge types: `IMPACTS` (incident → account) and `SUBSCRIBED_TO` (account → plan). Acme and Soylent are the only accounts on the incident. Both are Enterprise.

`POST /graph` walks that path. It does not search markdown and it does not read invoices.

## Spreadsheet lookup

`POST /sql` turns a question into a `SELECT` over `plans`, `customers`, and `invoices` only. Writes are rejected. If `OPENAI_API_KEY` is missing, a small template matcher covers the demo questions so you can still see real rows.

Ask the **same** invoice question in both boxes: docs will miss `$3,470`; SQL will return it.

## Naive search

`ingest_docs.py` splits each markdown file on `##` headings, embeds the chunks with a local model (BAAI/bge-small-en-v1.5), and stores them in `doc_chunks` (pgvector). `retrieve.py` also keyword-searches the same rows (`tsvector`) and fuses the two ranked lists.

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
python backend/app/ingest/seed_graph.py
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

Try the routed box:

- “What is the Pro rate limit?” → **docs**
- “What was Acme’s invoice last month?” → **sql**, **$3,470.00**
- “Which Enterprise customers were on INC-104?” → **graph**, Acme and Soylent
- SLA + who was hit + the August invoice → **mixed**: Acme and Soylent, their August rows, and the SLA chunk

## Is this agentic RAG?

The **Ask** button is not. A keyword function picks `docs`, `sql`, `graph`, or `mixed`. Mixed always runs graph, then SQL, then docs.

**Ask with the loop** is the agent path. `POST /agent` uses LangGraph. The model chooses a tool, reads what came back, and may call another tool. It stops after a few steps. The report card still scores the keyword router, because that path is the stable one.

## Report card

`backend/eval/golden.json` has 10 questions. Run:

```bash
python backend/eval/run_eval.py
```

Last run on this seeded database:

| Check | Score |
| --- | --- |
| Routing (docs / sql / graph / mixed / unknown) | 10/10 |
| SQL row match (Acme $3,470, Soylent $2,180, Enterprise names) | 3/3 |
| Graph names on INC-104 | 2/2 |
| Expected doc file in the reranked passages | 3/3 |
| Vector-only search contains Acme’s $3,470 | no |

The last row is the point. Embedding search over the markdown does not see the invoice table. The SQL route does. These scores are on 10 hand-written questions that match the keyword rules, so routing at 10/10 is expected. It is not a claim about unseen questions.
