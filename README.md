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

Invoice months are not hardcoded. “Last month”, “this month”, and a named month use the current date in `APP_TIMEZONE` (default `America/Vancouver`). “August 2026” still selects `period_start` 2026-08-01. One empty invoice or doc lookup can be widened once. The answer has to cite source ids. If evidence is missing, the reply says so.

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

Python 3.9+ and Node 20+. You need a Neon `DATABASE_URL` in a local `.env` (see `.env.example`). Chat uses local Ollama: `OPENAI_API_KEY=ollama`, `OPENAI_BASE_URL=http://127.0.0.1:11434/v1`, `OPENAI_CHAT_MODEL=llama3.2`. Optional `APP_TIMEZONE` defaults to `America/Vancouver`. Override it in the environment to use another zone. Without a chat model, templates and keyword rules still run, and `/ask` still returns passages.

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

**Ask with the loop** is separate. `POST /agent` uses LangGraph. The model chooses a tool, reads what came back, and may call another tool. If it writes a final sentence while part of the question is still unanswered, the server calls that missing tool once and then writes the answer from the combined evidence. It does not call every tool. Its score is not the keyword score.

## Checks on the answer

Answers are asked to cite `[S1]`, `[G1]`, or `[D1]`, and a PDF page when the passage has one. The checker flags unknown ids, missing citations, dollar amounts that are not in the evidence, customer names that are not in the evidence, a total assigned to the wrong customer, a partial list of totals, and two amounts for one customer when the answer does not say they disagree. If those flags fire, the answer is rewritten once from the same evidence. A clean check does not mean every sentence was verified. A dollar figure in a doc can still look like a second invoice total.

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

Llama comparison on those 10 plus 13 extended questions (`backend/eval/extended.json`): paraphrases the keyword list does not contain, Hooli, July 2026, a January 2019 invoice that does not exist, a reverse graph hop, graph+SQL, graph+docs, SQL+docs, and all three tools.

```bash
python backend/eval/run_eval.py --llm
```

Latest run on this machine, with local Llama 3.2 and the seeded Neon database:

| Check | Result |
| --- | --- |
| Keyword labels on all 23 | 19/23. The four misses are paraphrases with none of the keyword list (`unknown`). |
| Llama labels on all 23 | 23/23. Keyword fallback was used 0 times. |
| Extended docs | 1/1 (`pricing.md`) |
| Extended SQL | 6/6, including “pay” and “spend”, Enterprise subscribers, Hooli July, Acme July, and 0 rows for January 2019 |
| Reverse graph | Plan `Account Soylent ← IMPACTS ← Incident`. Names matched. |
| Mixed tool lists | Keyword list 4/4. Llama list 4/4: graph then SQL, graph+docs, SQL+docs, and all three. |
| Citation check | Acme July answer cited `[S1]` for $2100.00 with no flags. Graph+SQL mixed answer had no flags. |
| Evidence-check flags that remained | SQL+docs did not mention every dollar figure in the evidence. The three-tool answer was flagged because Acme was tied to more than one amount and not every total was repeated. |
| Slowest extended retrieval | 17.2s on the three-tool question |
| Agent loop, 4 questions | 4/4 called the expected tools. Docs cited `[D2]` and 200 requests per second. SQL cited `[S1]` and $3470.00. Graph cited `[G1]` and `[G2]` for Acme and Soylent. The mixed question called graph, then SQL, and cited both August invoices. |

Unit tests before these routing changes: 27 passed. After: 46 passed. They do not need Neon or Ollama. The table above does.

Unit tests cover dates, PDF chunking, retry choice, citation flags, and the extended keyword labels. They do not need Neon or Ollama:

```bash
cd backend
python -m unittest discover -s tests -v
```
