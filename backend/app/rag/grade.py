"""Grade retrieved doc chunks, and rewrite the question once if they miss.

This is not an agent loop. One check, one rewrite, then accept or refuse.
"""

from __future__ import annotations

import re

STOP = {
    "what",
    "whats",
    "is",
    "the",
    "a",
    "an",
    "our",
    "for",
    "of",
    "to",
    "do",
    "we",
    "did",
    "on",
    "in",
    "after",
    "how",
    "does",
    "say",
    "about",
    "and",
    "or",
}

# Small rewrite so a synonym can hit the docs on the second try.
REPLACEMENTS = (
    ("professional", "pro"),
    ("request cap", "rate limit"),
)


def content_words(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [word for word in words if word not in STOP and len(word) >= 3]


def grade(question: str, chunks: list[dict]) -> str:
    """useful if the longest question word actually appears in a chunk."""
    words = content_words(question)
    if not words or not chunks:
        return "irrelevant"
    blob = " ".join(chunk["body"].lower() for chunk in chunks)
    longest = max(words, key=len)
    if longest not in blob:
        return "irrelevant"
    return "useful"


def rewrite_once(question: str) -> str:
    rewritten = question
    for source, target in REPLACEMENTS:
        rewritten = re.sub(source, target, rewritten, flags=re.I)
    return rewritten
