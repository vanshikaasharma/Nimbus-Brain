"""Write a short answer from evidence the tools already retrieved.

Uses any OpenAI-compatible chat API. Groq's free tier works if you set
OPENAI_BASE_URL to https://api.groq.com/openai/v1. No key means no sentence.
"""

from __future__ import annotations

import os
import re

SYSTEM = (
    "You answer Nimbus Brain questions for employees. "
    "Use only the evidence. Cite each fact with its source id, such as [G1] or [D1]. "
    "When a passage has a page number, mention that page. "
    "If the evidence does not contain the answer, say you do not know and what is missing. "
    "Do not invent customers, dollar amounts, pages, or SLA terms. "
    "If two sources disagree, say they disagree. "
    "If a row has amount_dollars, that is the invoice total. Use it. "
    "The rows are already filtered to the period the question asked about. "
    "Keep the answer to a few sentences."
)


def chunk_evidence(chunk: dict) -> str:
    """Stable source id, and a page number when the chunk came from a PDF."""
    source = chunk.get("source_id") or chunk.get("doc_path") or "doc"
    page = chunk.get("page_number")
    where = f"{source} page {page}" if page else str(source)
    section = chunk.get("section") or ""
    body = (chunk.get("body") or "")[:500]
    return f"{where} > {section}\n{body}"


def with_dollars(rows: list | None) -> list:
    """Copy rows and add amount_dollars so a small local model does not skip the total."""
    cleaned = []
    for row in rows or []:
        copy = dict(row)
        cents = copy.get("amount_cents")
        if isinstance(cents, int):
            copy["amount_dollars"] = f"{cents / 100:.2f}"
        cleaned.append(copy)
    return cleaned


def answer_from_evidence(question: str, evidence: str) -> str | None:
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None

    from openai import APIConnectionError, APITimeoutError, OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        timeout=45.0,
    )
    model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=220,
            messages=[
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": f"Evidence:\n{evidence}\n\nQuestion: {question}",
                },
            ],
        )
    except (APITimeoutError, APIConnectionError):
        return None
    text = (response.choices[0].message.content or "").strip()
    return text or None


def _money(text: str) -> set[str]:
    """Dollar totals only, so a rate limit or a date is not treated as an invoice."""
    found = set()
    patterns = (
        r"\$\s?\d[\d,]*(?:\.\d+)?",
        r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b",
        r"amount_dollars': '(\d+(?:\.\d+)?)'",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            raw = (match.group(1) if match.lastindex else match.group()).replace("$", "").replace(",", "").strip()
            if "." in raw:
                raw = raw.rstrip("0").rstrip(".")
            if raw:
                found.add(raw)
    return found


def _pages(text: str) -> set[int]:
    return {int(item) for item in re.findall(r"\bpage\s+(\d+)\b", text, flags=re.I)}


def _named_amounts(text: str) -> dict[str, set[str]]:
    """Customer name plus a dollar total mentioned soon after it."""
    from app.rag.sql_tool import CUSTOMER_NAMES

    found: dict[str, set[str]] = {}
    for name in CUSTOMER_NAMES:
        for match in re.finditer(re.escape(name), text, flags=re.I):
            window = text[match.start() : match.start() + 160]
            amounts = _money(window)
            if amounts:
                found.setdefault(name, set()).update(amounts)
    return found


def review_answer(answer: str, valid_ids: set[str], evidence: str) -> tuple[str, list[str]]:
    """Check citation ids and a few facts that can be compared to the evidence.

    A clean result is not proof that every sentence is right.
    """
    from app.rag.sql_tool import CUSTOMER_NAMES

    flags = []
    cited = re.findall(r"\[([GSD]\d+)\]", answer)
    unknown = [item for item in cited if item not in valid_ids]
    if unknown:
        flags.append("Citation check: cited source not in the evidence: " + ", ".join(unknown) + ".")
    if valid_ids and not cited and "do not know" not in answer.lower() and "don't know" not in answer.lower():
        flags.append("Citation check: the answer did not cite a source id.")

    extra_pages = _pages(answer) - _pages(evidence)
    if extra_pages:
        shown = ", ".join(str(page) for page in sorted(extra_pages))
        flags.append(f"Citation check: page {shown} is not in the evidence.")

    extra = _money(answer) - _money(evidence)
    for amount in sorted(extra):
        flags.append(f"Evidence check: amount {amount} is not in the evidence.")

    evidence_lower = evidence.lower()
    for name in CUSTOMER_NAMES:
        if name.lower() in answer.lower() and name.lower() not in evidence_lower:
            flags.append(f"Evidence check: {name} is not in the evidence.")

    evidence_named = _named_amounts(evidence)
    answer_named = _named_amounts(answer)
    for name, amounts in answer_named.items():
        known = evidence_named.get(name)
        if known and len(known) == 1 and len(amounts) == 1 and amounts != known:
            flags.append(
                f"Evidence check: the answer assigns {name} a total the evidence does not."
            )

    evidence_amounts = _money(evidence)
    answer_amounts = _money(answer)
    if len(evidence_amounts) > 1 and answer_amounts and answer_amounts < evidence_amounts:
        flags.append("Evidence check: evidence has more than one total, and the answer does not mention each one.")

    if flags:
        answer = (
            answer.rstrip()
            + "\n\nChecks: "
            + " ".join(flags)
            + " These checks cover source ids, pages, names, and amounts. They do not prove every sentence is right."
        )
    return answer, flags


def answer_with_sources(question: str, sources: list[tuple[str, str]]) -> tuple[str | None, list[str]]:
    if not sources:
        return None, ["No evidence was retrieved."]
    evidence = "\n".join(f"[{sid}] {text}" for sid, text in sources)
    written = answer_from_evidence(question, evidence)
    if not written:
        return None, []
    return review_answer(written, {sid for sid, _ in sources}, evidence)
