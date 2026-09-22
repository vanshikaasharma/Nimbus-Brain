"""Split corpus markdown into heading-sized chunks."""

from __future__ import annotations

import re
from pathlib import Path

CORPUS = Path(__file__).resolve().parents[3] / "corpus"


def chunk_corpus() -> list[dict]:
    chunks = []
    for path in sorted(CORPUS.glob("*.md")):
        text = path.read_text()
        sections = re.split(r"(?=^## )", text, flags=re.M)
        for section in sections:
            section = section.strip()
            if not section:
                continue
            first_line = section.splitlines()[0]
            if first_line.startswith("#"):
                heading = first_line.lstrip("# ").strip()
            else:
                heading = path.stem
            chunks.append(
                {
                    "doc_path": path.name,
                    "section": heading,
                    "body": section,
                }
            )
    return chunks
