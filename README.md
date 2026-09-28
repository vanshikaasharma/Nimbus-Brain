# Nimbus Brain

Internal Q&A for a **fake** usage-based API company (Nimbus). Employees will type a question; the copilot should answer from docs, SQL, or a knowledge graph — or say it does not know.

This is a school / portfolio project on seeded data, not a production support bot.

**Where we are:** Ask uses the chat model in `.env` to pick a route, and the keyword rules still run when that pick is missing, invalid, or the endpoint is down. Groq `openai/gpt-oss-120b` and local Ollama `llama3.2` are both supported. A rate limit is recorded and is not filled in from the other model. “Ask with the loop” is a separate LangGraph path. It is scored on its own, not as the keyword report card. Document search defaults to BGE-small plus MiniLM. Qwen3-Embedding-0.6B and Qwen3-Reranker-0.6B can be turned on for a comparison; they use a separate vector table.

## Why not just chat with PDFs?

A real company question can need three different kinds of lookup:

1. **Documents** — “What is the Pro rate limit?” (SLA / pricing text)
2. **Tables** — “What did Acme’s invoice look like last month?” (SQL)
3. **Links between entities** — “Which Enterprise accounts were on incident INC-104?” (a graph hop)

Naive RAG (embed chunks → top-k → LLM) only handles (1). That is the point of this project.

## Mixed question

If the route is `mixed`, the chat model returns a JSON list of the tools to run (`graph`, `sql`, `docs`), with no duplicates and at most three. Graph can run before SQL so invoice lookup uses the account names from the paths. If the list is invalid or the model times out, the keyword tool list is used instead, in the order graph, then SQL, then docs.

Invoice months are not hardcoded. “Last month”, “this month”, and a named month use the current date in `APP_TIMEZONE` (default `America/Vancouver`). “August 2026” still selects `period_start` 2026-08-01. One empty invoice or doc lookup can be widened once. The answer has to cite source ids. If evidence is missing, the reply says so.

## One extra lookup

A single-tool question that comes back empty may call one other tool when the question asks for that kind of evidence. A docs question does not also query invoices. Two evidence types in one question are left to the mixed route instead of guessing a third call. The response includes `tools`, `retries`, and `missing`.

## Traffic cop

`POST /chat` calls `choose_route()`. The chat model must return one of `docs`, `sql`, `graph`, `mixed`, or `unknown`. Anything else, a timeout, or a rate limit uses the keyword rules. A rate-limited call is marked and is not counted as the chat model’s own label:

- rate limit / SLA / pricing → docs
- invoice / bill, or “who is on Enterprise” → SQL
- INC-104 / incident / outage → graph
- two of those at once → `mixed`

## Relationship map

`seed_graph.py` copies plans and customers into `nodes`, then adds incident **INC-104** and two edge types: `IMPACTS` (incident → account) and `SUBSCRIBED_TO` (account → plan). Acme and Soylent are the only accounts on the incident. Both are Enterprise.

`POST /graph` walks that path. It does not search markdown and it does not read invoices.

## Spreadsheet lookup

`POST /sql` turns a question into a `SELECT` over `plans`, `customers`, and `invoices` only. Writes are rejected. A template covers named customers and invoice months with bound parameters. If it misses and a chat model is configured, the model may write one `SELECT`, which is still checked against the allowlist. A rate limit returns an error instead of switching models. The tables hold names, fees, dates, and cent amounts. There is no prose column, so embedding those fields would not answer anything the SQL filter does not already answer. That is a possible later addition if a notes column shows up, not part of this build.

Ask the **same** invoice question in both boxes: docs will miss `$3,470`; SQL will return it.

## Naive search

`ingest_docs.py` splits each markdown file on `##` headings. Text PDFs in `corpus/` are read with PyMuPDF, one chunk per page, with `source_id` and `page_number`. A page with no extractable text is skipped. Scanned PDFs are not supported, because there is no OCR. Re-running ingest deletes and reinserts chunks for those filenames, so the same file is not stored twice. Markdown and PDF chunks then use local embeddings, pgvector, hybrid search, and a reranker. The default is BGE-small (`doc_chunks`, 384 dimensions) and the MiniLM cross-encoder. `EMBEDDING_MODEL=qwen3` embeds with Qwen3-Embedding-0.6B into `doc_chunks_qwen3` (1024 dimensions). Queries use the model card’s `query` prompt; documents do not. `RERANKER=qwen3` scores Qwen3-Reranker-0.6B with the documented yes/no log-softmax, not MiniLM’s cross-encoder API. The two embedding tables are never mixed. Qwen reranking uses a 2048-token context on CPU; the model card allows 8192.

`POST /ask` embeds the question, returns the top chunks, and (if a chat model is configured) writes an answer from those chunks only. It never runs SQL.

## Fake company (this checkpoint)

Docs live in `corpus/`:

- `pricing.md` — Starter / Pro / Enterprise fees and rate limits
- `sla-enterprise.md` — credit after a long ingest outage
- `changelog.md` — Pro rate-limit change and outage INC-104
- `eval-retention.md` and `eval-burst.pdf` — extra passages used by the retrieval comparison. The PDF is rewritten when `backend/eval/run_retrieval.py` runs.

Postgres (Neon) has three tables: `plans`, `customers`, `invoices`. Six accounts, two months of bills. Acme’s August invoice is higher on purpose.

## How to run

Python 3.9+ and Node 20+. You need a Neon `DATABASE_URL` in a local `.env` (see `.env.example`). Do not commit `.env`.

Chat, Groq GPT-OSS 120B:

```env
OPENAI_BASE_URL=https://api.groq.com/openai/v1
OPENAI_CHAT_MODEL=openai/gpt-oss-120b
OPENAI_API_KEY=<Groq key>
```

Chat, local Ollama Llama 3.2, instead of the Groq lines:

```env
OPENAI_BASE_URL=http://127.0.0.1:11434/v1
OPENAI_CHAT_MODEL=llama3.2
OPENAI_API_KEY=ollama
```

Retrieval defaults are `EMBEDDING_MODEL=bge` and `RERANKER=minilm`. Optional `APP_TIMEZONE` defaults to `America/Vancouver`. Without a chat model, templates and keyword rules still run, and `/ask` still returns passages.

Reindex documents only. This does not change `plans`, `customers`, `invoices`, or the graph. Run one command per embedding model so the vectors stay in their own table:

```bash
EMBEDDING_MODEL=bge python backend/app/ingest/ingest_docs.py
EMBEDDING_MODEL=qwen3 python backend/app/ingest/ingest_docs.py
```

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

**Ask** plans a route with the configured chat model, then runs that tool (or the mixed list). The keyword function is the fallback, and it is still the stable score below.

**Ask with the loop** is separate. `POST /agent` uses LangGraph. The model chooses a tool, reads what came back, and may call another tool. If it writes a final sentence while part of the question is still unanswered, the server calls that missing tool once and then writes the answer from the combined evidence. It does not call every tool. Its score is not the keyword score.

## Checks on the answer

Answers are asked to cite `[S1]`, `[G1]`, or `[D1]`, and a PDF page when the passage has one. The checker flags unknown ids, missing ASCII citations, dollar amounts that are not in the evidence, customer names that are not in the evidence, a total assigned to the wrong customer, and two invoice rows for one customer when the answer does not say they disagree. A platform fee in a document is not treated as a second invoice for that customer. Leaving out another customer’s invoice total is a validation note. Validation notes do not use the one rewrite. Factual flags do, once. A clean check does not mean every sentence was verified. The checker only recognizes ASCII brackets, so a fullwidth marker such as `【S1】` is flagged as a missing citation.

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

Chat-model comparison on those 10 plus 13 extended questions (`backend/eval/extended.json`), four unseen questions, and four agent questions. Each model is a separate process. A rate limit or a dead endpoint is left out of that model’s accuracy.

```bash
python backend/eval/run_eval.py --llm --chat ollama
python backend/eval/run_eval.py --llm --chat groq
```

Results are written to `backend/eval/chat_llama3.2.json` and `backend/eval/chat_openai_gpt-oss-120b.json`. The runs below had 0 rate-limit events and 0 keyword fallbacks. In those files a plan labeled `llama` means the configured chat model returned the plan. The code now stores that as `chat`.

| Check | Llama 3.2 (Ollama) | GPT-OSS 120B (Groq) |
| --- | --- | --- |
| Routing labels, 23 scored | 23/23 | 23/23 |
| Keyword labels on the same 23 | 19/23 | 19/23 |
| Fallbacks / rate limits / unavailable | 0 / 0 / 0 | 0 / 0 / 0 |
| Extended SQL | 6/6 | 6/6 |
| Extended docs | 1/1 | 1/1 |
| Reverse graph plan | 1/1, `Account Soylent ← IMPACTS ← Incident` | 1/1, same direction |
| Mixed tool lists | Keyword 4/4. Model 4/4 | Keyword 4/4. Model 4/4 |
| Unseen questions | 3/4. The Pro-limit plus Hooli July question returned only `docs` | 4/4, including SQL then docs for that question |
| Agent tool choice | 4/4. Graph then SQL on the mixed question. 0 errors | 4/4. Graph then SQL, with a second SQL call. 0 errors |
| Grounding | Acme July cited `[S1]` and $2100.00 with no flags. Mixed answers had no flags. Agent cited both August invoices | Acme July was $2,100.00 but cited with `【S1】`, which the ASCII checker flags. The mixed agent answer said Acme had no August invoice and reported only Soylent’s $2,180.00 |
| Slowest extended call | 74.9s on the three-tool question | 22.4s on the three-tool question |

Retrieval comparison uses the same six questions in `backend/eval/retrieval.json`: a paraphrase, exact terms, two similar sections, and a two-page PDF (`corpus/eval-burst.pdf`, generated by the eval script). Hybrid search runs in Postgres, then the selected reranker. The connection is closed before reranking so a slow local model does not idle out Neon. Recall@3 is whether the expected passage is in the top 3 after reranking.

```bash
python backend/eval/run_retrieval.py
```

| Pair | Recall@3 | MRR before rerank | MRR after rerank | Mean latency |
| --- | --- | --- | --- | --- |
| BGE + MiniLM | 1.00 | 0.92 | 0.83 | 1.16s |
| BGE + Qwen3 reranker | 1.00 | 0.92 | 0.83 | 31.8s |
| Qwen3 embedding + MiniLM | 1.00 | 0.83 | 0.83 | 0.36s |
| Qwen3 embedding + Qwen3 reranker | 1.00 | 0.83 | 0.83 | 69.8s |

On this set every pair found the right passage in the top 3. MiniLM and the Qwen3 reranker both moved the Starter section from rank 1 to rank 2 for BGE. Qwen3 embeddings ranked that section 2 before reranking. The Qwen3 reranker did not raise MRR and was much slower on CPU. The default stays BGE + MiniLM. The first BGE + Qwen3 attempt failed because Neon closed an idle connection; the table is the rerun after the connection is released.

Unit tests: 56 passed. They do not need Neon, Ollama, or Groq. The tables above do.

```bash
cd backend
python -m unittest discover -s tests -v
```
