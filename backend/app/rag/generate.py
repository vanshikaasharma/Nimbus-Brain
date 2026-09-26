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
    "If the evidence does not contain the answer, say you do not know. "
    "Do not invent customers, dollar amounts, or SLA terms. "
    "If two sources disagree, say they disagree. "
    "If a row has amount_dollars, that is the invoice total. Use it. "
    "The rows are already filtered to the period the question asked about. "
    "Keep the answer to a few sentences."
)


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


def review_answer(answer: str, valid_ids: set[str], evidence: str) -> tuple[str, list[str]]:
    """Flag citations that were not retrieved, amounts that were not retrieved, and split totals."""
    flags = []
    cited = re.findall(r"\[([GSD]\d+)\]", answer)
    unknown = [item for item in cited if item not in valid_ids]
    if unknown:
        flags.append("Cited source not in the evidence: " + ", ".join(unknown) + ".")
    if valid_ids and not cited and "do not know" not in answer.lower() and "don't know" not in answer.lower():
        flags.append("The answer did not cite a source id.")

    extra = _money(answer) - _money(evidence)
    for amount in sorted(extra):
        flags.append(f"Amount {amount} is not in the evidence.")

    evidence_amounts = _money(evidence)
    answer_amounts = _money(answer)
    if len(evidence_amounts) > 1 and answer_amounts and answer_amounts < evidence_amounts:
        flags.append("Evidence has more than one total, and the answer does not mention each one.")

    if flags:
        answer = answer.rstrip() + "\n\nGrounding: " + " ".join(flags)
    return answer, flags


def answer_with_sources(question: str, sources: list[tuple[str, str]]) -> tuple[str | None, list[str]]:
    if not sources:
        return None, ["No evidence was retrieved."]
    evidence = "\n".join(f"[{sid}] {text}" for sid, text in sources)
    written = answer_from_evidence(question, evidence)
    if not written:
        return None, []
    return review_answer(written, {sid for sid, _ in sources}, evidence)
