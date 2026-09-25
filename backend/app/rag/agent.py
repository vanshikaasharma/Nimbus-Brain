"""Let the chat model pick tools, look at the result, and pick again.

The keyword router is still the default. This loop is the other path.
It stops after a few steps so a small local model cannot run forever.
"""

from __future__ import annotations

import os

from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent

from app.rag.generate import with_dollars
from app.rag.graph_tool import walk
from app.rag.naive import ask
from app.rag.sql_tool import run_question

# Each tool call is two graph steps (model, then tool). Three calls fit under this.
MAX_STEPS = 10

SYSTEM = (
    "You are Nimbus Brain. Answer only from tool results. "
    "search_docs is for pricing, the SLA, the changelog, rate limits, and credits. "
    "lookup_invoices is for invoices, bills, and which customers are on a plan. "
    "walk_graph is for incidents and which accounts an outage hit. "
    "Call a tool when you need a fact. You may call more than one, then stop. "
    "If a row has amount_dollars, that number is the invoice total. "
    "If the tools do not contain the answer, say you do not know. "
    "Do not invent customers, dollar amounts, or SLA terms."
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
        lines = []
        for chunk in chunks[:3]:
            lines.append(f"{chunk['doc_path']} > {chunk['section']}\n{chunk['body'][:500]}")
        return "\n\n".join(lines)

    @tool
    def lookup_invoices(query: str) -> str:
        """Look up invoices or which customers are on a plan. Read-only."""
        found["steps"].append("sql")
        result = run_question(database_url, query)
        found["sql"] = result
        if result.get("error"):
            return result["error"]
        rows = with_dollars(result.get("rows"))
        return f"SQL:\n{result.get('sql')}\nRows:\n{rows}"

    @tool
    def walk_graph(query: str) -> str:
        """Walk incident INC-104 to the accounts it hit and their plans."""
        found["steps"].append("graph")
        result = walk(database_url, query)
        found["graph"] = result
        if result.get("error"):
            return result["error"]
        paths = result.get("paths") or []
        return "\n".join(paths) if paths else "No path."

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

    steps = found["steps"]
    if steps:
        reason = "The model called " + " → ".join(steps) + "."
    else:
        reason = "The model did not call a tool."
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
        "retried": found["retried"],
    }
