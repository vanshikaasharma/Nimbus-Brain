"""Write a short answer from evidence the tools already retrieved.

Uses any OpenAI-compatible chat API. Groq's free tier works if you set
OPENAI_BASE_URL to https://api.groq.com/openai/v1. No key means no sentence.
"""

from __future__ import annotations

import os

SYSTEM = (
    "You answer Nimbus Brain questions for employees. "
    "Use only the evidence. If it does not contain the answer, say you do not know. "
    "Do not invent customers, dollar amounts, or SLA terms. "
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

    from openai import OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
    )
    model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": f"Evidence:\n{evidence}\n\nQuestion: {question}",
            },
        ],
    )
    text = (response.choices[0].message.content or "").strip()
    return text or None
