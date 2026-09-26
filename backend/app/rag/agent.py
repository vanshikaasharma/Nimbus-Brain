"""Let the chat model pick tools, look at the result, and pick again.

The keyword router is still the default. This loop is the other path.
It stops after a few steps so a small local model cannot run forever.
"""

from __future__ import annotations

import os
import re

from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent

from app.rag.generate import with_dollars
from app.rag.graph_tool import walk
from app.rag.naive import ask
from app.rag.sql_tool import run_question

# Each tool call is two graph steps (model, then tool). Graph, SQL, and a final
# sentence fit under this. The loop also stops if the model writes prose instead
# of a tool call; run_agent then calls at most the tools still missing.
MAX_STEPS = 12

SYSTEM = (
    "You are Nimbus Brain. Answer only from tool results. "
    "search_docs is for pricing, the SLA, the changelog, rate limits, and credits. "
    "lookup_invoices is for invoices, bills, what a customer paid, and which customers are on a plan. "
    "walk_graph is for incidents and which accounts an outage hit. It does not return invoices. "
    "Plan membership is lookup_invoices, not walk_graph. "
    "Call a tool when you need a fact. If the question still has an unanswered part, call the next tool. "
    "Do not say you will call a tool. Call it. Do not call a tool the question does not need. "
    "If a row has amount_dollars, that number is the invoice total. "
    "If the tools do not contain the answer, say you do not know and what is missing. "
    "Cite source ids from the tool text, such as [G1] or [S1], and the page number when one is shown. "
    "Do not invent customers, dollar amounts, pages, or SLA terms."
)


def _text(message: AIMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content.strip()
    parts = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("text"):
            parts.append(block["text"])
    return "\n".join(parts).strip()


def run_agent(database_url: str, question: str) -> dict:
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return {
            "route": "agent",
            "reason": "The loop needs a chat model. Set OPENAI_API_KEY.",
            "answer": None,
            "steps": [],
            "chunks": [],
            "sql": None,
            "graph": None,
        }

    found = {
        "steps": [],
        "chunks": [],
        "sql": None,
        "graph": None,
        "retried": False,
    }

    @tool
    def search_docs(query: str) -> str:
        """Search pricing, SLA, and changelog pages."""
        found["steps"].append("docs")
        result = ask(database_url, query, generate=False)
        found["retried"] = bool(result.get("retried"))
        chunks = result.get("chunks") or []
        found["chunks"] = chunks
        if result.get("abstained") or not chunks:
            return "No supporting passage in the Nimbus docs."
        from app.rag.generate import chunk_evidence

        lines = []
        for index, chunk in enumerate(chunks[:3], start=1):
            lines.append(f"[D{index}] {chunk_evidence(chunk)}")
        return "\n\n".join(lines)

    @tool
    def lookup_invoices(query: str) -> str:
        """Look up invoices, bills, or which customers are on a plan. Pass every account name."""
        from app.rag.dates import period_for_question
        from app.rag.mixed import invoices_for
        from app.rag.sql_tool import CUSTOMER_NAMES

        found["steps"].append("sql")
        names = [name for name in CUSTOMER_NAMES if name.lower() in query.lower()]
        if len(names) >= 2:
            result = invoices_for(database_url, names, period=period_for_question(query))
        else:
            result = run_question(database_url, query)
        found["sql"] = result
        if result.get("error"):
            return result["error"]
        rows = with_dollars(result.get("rows"))
        if not rows:
            return "No invoice rows."
        return "\n".join(f"[S{index}] {row}" for index, row in enumerate(rows, start=1))

    @tool
    def walk_graph(query: str) -> str:
        """Walk an incident to the accounts it hit. Does not return invoices."""
        found["steps"].append("graph")
        result = walk(database_url, query)
        found["graph"] = result
        if result.get("error"):
            return result["error"]
        paths = result.get("paths") or []
        if not paths:
            return "No path."
        return "\n".join(f"[G{index}] {path}" for index, path in enumerate(paths, start=1))

    model = ChatOpenAI(
        model=os.environ.get("OPENAI_CHAT_MODEL", "llama3.2"),
        api_key=api_key,
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        temperature=0,
    )
    agent = create_react_agent(
        model,
        [search_docs, lookup_invoices, walk_graph],
        prompt=SYSTEM,
    )

    messages = []
    stopped_early = False
    try:
        for event in agent.stream(
            {"messages": [("user", question)]},
            config={"recursion_limit": MAX_STEPS},
            stream_mode="values",
        ):
            messages = event["messages"]
    except GraphRecursionError:
        stopped_early = True

    answer = ""
    for message in messages:
        if isinstance(message, AIMessage) and not message.tool_calls:
            answer = _text(message)

    from app.rag.coverage import unanswered_tools
    from app.rag.generate import answer_with_sources, chunk_evidence, review_answer
    from app.rag.mixed import accounts_from_paths

    added = False
    for missing in unanswered_tools(question, found["steps"]):
        added = True
        if missing == "sql":
            names = accounts_from_paths((found.get("graph") or {}).get("paths") or [])
            query = question if not names else question + " Accounts: " + ", ".join(names)
            lookup_invoices.invoke({"query": query})
        elif missing == "docs":
            search_docs.invoke({"query": question})
        elif missing == "graph":
            walk_graph.invoke({"query": question})

    sources = []
    for index, path in enumerate((found.get("graph") or {}).get("paths") or [], start=1):
        sources.append((f"G{index}", path))
    for index, row in enumerate(with_dollars((found.get("sql") or {}).get("rows")), start=1):
        sources.append((f"S{index}", str(row)))
    for index, chunk in enumerate(found.get("chunks") or [], start=1):
        sources.append((f"D{index}", chunk_evidence(chunk)))

    grounding: list[str] = []
    cited = bool(re.search(r"\[[GSD]\d+\]", answer or ""))
    if sources and (added or not cited):
        written, grounding = answer_with_sources(question, sources)
        if written:
            answer = written
        elif added:
            answer = (
                "Retrieved the missing evidence, but no sentence was written. "
                "The tool results are the evidence."
            )
    elif sources and answer:
        answer, grounding = review_answer(
            answer,
            {sid for sid, _ in sources},
            "\n".join(f"[{sid}] {text}" for sid, text in sources),
        )

    steps = found["steps"]
    if steps:
        reason = "The model called " + " → ".join(steps) + "."
    else:
        reason = "The model did not call a tool."
    if added:
        reason += " A tool the question still needed was called once before the answer."
    if stopped_early:
        reason += " Stopped after the step limit."

    return {
        "route": "agent",
        "reason": reason,
        "answer": answer or "The model stopped before it wrote a sentence. The panel still has the tool results.",
        "steps": steps,
        "chunks": found["chunks"],
        "sql": found["sql"],
        "graph": found["graph"],
        "retried": found["retried"] or added,
        "grounding": grounding,
    }
