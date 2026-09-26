# Nimbus Brain

Internal Q&A for a **fake** usage-based API company (Nimbus). Employees will type a question; the copilot should answer from docs, SQL, or a knowledge graph — or say it does not know.

This is a school / portfolio project on seeded data, not a production support bot.

**Where we are:** Ask uses Llama 3.2 through local Ollama to pick a route, and the keyword rules still run when that pick is missing or invalid. “Ask with the loop” is a separate LangGraph path. It is scored on its own, not as the keyword report card.

## Why not just chat with PDFs?

A real company question can need three different kinds of lookup:

1. **Documents** — “What is the Pro rate limit?” (SLA / pricing text)
2. **Tables** — “What did Acme’s invoice look like last month?” (SQL)
3. **Links between entities** — “Which Enterprise accounts were on incident INC-104?” (a graph hop)

Naive RAG (embed chunks → top-k → LLM) only handles (1). That is the point of this project.

## Mixed question

If the route is `mixed`, Llama returns a JSON list of the tools to run (`graph`, `sql`, `docs`), with no duplicates and at most three. Graph can run before SQL so invoice lookup uses the account names from the paths. If the list is invalid or the model times out, the keyword tool list is used instead, in the order graph, then SQL, then docs.

Invoice months are not hardcoded. “Last month”, “this month”, and a named month use the current date in `APP_TIMEZONE` (default `America/Los_Angeles`). “August 2026” still selects `period_start` 2026-08-01. One empty invoice or doc lookup can be widened once. The answer has to cite source ids. If evidence is missing, the reply says so.

## One extra lookup

A single-tool question that comes back empty may call one other tool when the question asks for that kind of evidence. A docs question does not also query invoices. Two evidence types in one question are left to the mixed route instead of guessing a third call. The response includes `tools`, `retries`, and `missing`.

## Traffic cop

`POST /chat` calls `choose_route()`. Llama must return one of `docs`, `sql`, `graph`, `mixed`, or `unknown`. Anything else, or a timeout, uses the keyword rules:

- rate limit / SLA / pricing → docs
- invoice / bill, or “who is on Enterprise” → SQL
- INC-104 / incident / outage → graph
- two of those at once → `mixed`

## Relationship map

`seed_graph.py` copies plans and customers into `nodes`, then adds incident **INC-104** and two edge types: `IMPACTS` (incident → account) and `SUBSCRIBED_TO` (account → plan). Acme and Soylent are the only accounts on the incident. Both are Enterprise.

`POST /graph` walks that path. It does not search markdown and it does not read invoices.

## Spreadsheet lookup

`POST /sql` turns a question into a `SELECT` over `plans`, `customers`, and `invoices` only. Writes are rejected. A template covers named customers and invoice months with bound parameters. If it misses and Ollama is configured, the model may write one `SELECT`, which is still checked against the allowlist. The tables hold names, fees, dates, and cent amounts. There is no prose column, so embedding those fields would not answer anything the SQL filter does not already answer. That is a possible later addition if a notes column shows up, not part of this build.

Ask the **same** invoice question in both boxes: docs will miss `$3,470`; SQL will return it.

## Naive search

`ingest_docs.py` splits each markdown file on `##` headings. Text PDFs in `corpus/` are read with PyMuPDF, one chunk per page, with `source_id` and `page_number`. A page with no extractable text is skipped. Scanned PDFs are not supported, because there is no OCR. Re-running ingest deletes and reinserts chunks for those filenames, so the same file is not stored twice. Markdown and PDF chunks then use the same local BGE embeddings, pgvector storage, hybrid search, and MiniLM rerank.

`POST /ask` embeds the question, returns the top chunks, and (if Ollama is configured) writes an answer from those chunks only. It never runs SQL.

## Fake company (this checkpoint)

Docs live in `corpus/`:

- `pricing.md` — Starter / Pro / Enterprise fees and rate limits
- `sla-enterprise.md` — credit after a long ingest outage
- `changelog.md` — Pro rate-limit change and outage INC-104

Postgres (Neon) has three tables: `plans`, `customers`, `invoices`. Six accounts, two months of bills. Acme’s August invoice is higher on purpose.

## How to run

Python 3.9+ and Node 20+. You need a Neon `DATABASE_URL` in a local `.env` (see `.env.example`). Chat uses local Ollama: `OPENAI_API_KEY=ollama`, `OPENAI_BASE_URL=http://127.0.0.1:11434/v1`, `OPENAI_CHAT_MODEL=llama3.2`. Optional `APP_TIMEZONE` defaults to `America/Los_Angeles`. Without a chat model, templates and keyword rules still run, and `/ask` still returns passages.

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

**Ask** plans a route with Llama, then runs that tool (or the mixed list). The keyword function is the fallback, and it is still the stable score below.

**Ask with the loop** is separate. `POST /agent` uses LangGraph. The model chooses a tool, reads what came back, and may call another tool. It stops after a few steps. Its score is not the keyword score.

## Checks on the answer

Answers are asked to cite `[S1]`, `[G1]`, or `[D1]`, and a PDF page when the passage has one. The checker flags unknown ids, missing citations, dollar amounts that are not in the evidence, customer names that are not in the evidence, and a total assigned to the wrong customer when both sides name one amount. A clean check does not mean every sentence was verified. The model can still omit a citation or phrase a true cent value in a way the checker flags.

## Report card

Keyword baseline, 10 questions in `backend/eval/golden.json`, run before the extended set was added:

```bash
python backend/eval/run_eval.py
```

| Check | Score |
| --- | --- |
| Routing (docs / sql / graph / mixed / unknown) | 10/10 |
| SQL row match (Acme $3,470, Soylent $2,180, Enterprise names) | 3/3 |
| Graph names on INC-104 | 2/2 |
| Expected doc file in the reranked passages | 3/3 |
| Vector-only search contains Acme’s $3,470 | no |

Those 10 questions match the keyword rules, so 10/10 routing is expected. Embedding search over the markdown does not see the invoice table.

Llama comparison on those 10 plus 7 extended questions (`backend/eval/extended.json`): paraphrases without the keyword list, Hooli (not in the original 10), July 2026, a January 2019 invoice that does not exist, a reverse graph hop, and a mixed question that needs graph and SQL only.

```bash
python backend/eval/run_eval.py --llm
```

| Check | Result |
| --- | --- |
| Keyword labels on all 17 | 15/17 (the two paraphrases are `unknown`) |
| Llama labels on all 17 | 14/17, with 5 falling back to keywords |
| Llama misses | Enterprise customers labeled `graph`; side email labeled `docs`; “what did Acme pay in August 2026” labeled `unknown` |
| Extended docs | 1/1 (`pricing.md` for the Pro paraphrase) |
| Extended SQL | Hooli July $99 and Acme July $2,100 matched. January 2019 returned 0 rows. The “pay” paraphrase was written as `SUM(amount_cents)` and returned 347000, but the scorer looked for a column named `amount_cents`, so that run printed a miss. |
| Reverse graph | Plan `Account Soylent ← IMPACTS ← Incident`. Names matched. |
| Mixed tool list | Keyword list was `graph`, `sql`. Llama returned no usable list (`None`); the keyword list ran. The sentence did not cite a source id. |
| Slowest extended retrieval | 14.6s on that mixed question |
| Agent loop, 3 single-tool questions | 3/3 tool choice. Docs said 200 requests per second. SQL said $3470.00. Graph named Acme and Soylent. |
| Agent mixed follow-up | Called `graph` only, then said it still needed the August invoices and did not call SQL. |

Unit tests cover dates, PDF chunking, retry choice, citation flags, and the extended keyword labels. They do not need Neon or Ollama:

```bash
cd backend
python -m unittest discover -s tests -v
```
