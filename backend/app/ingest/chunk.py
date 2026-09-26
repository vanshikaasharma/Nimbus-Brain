"""Split corpus markdown and text PDFs into chunks.

PDF text comes from PyMuPDF. A page with no extractable text is skipped.
Scanned PDFs need OCR, which this project does not do.
"""

from __future__ import annotations

import re
from pathlib import Path

CORPUS = Path(__file__).resolve().parents[3] / "corpus"


def source_id_for(doc_path: str, label: str, seen: set[str]) -> str:
    base = f"{doc_path}#{label}"
    source_id = base
    suffix = 2
    while source_id in seen:
        source_id = f"{base}-{suffix}"
        suffix += 1
    seen.add(source_id)
    return source_id


def chunk_markdown(path: Path) -> list[dict]:
    text = path.read_text()
    sections = re.split(r"(?=^## )", text, flags=re.M)
    chunks = []
    seen: set[str] = set()
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
                "page_number": None,
                "source_id": source_id_for(path.name, heading, seen),
                "body": section,
            }
        )
    return chunks


def chunk_pdf(path: Path) -> tuple[list[dict], int]:
    """Return text chunks and how many pages had no extractable text."""
    import fitz

    document = fitz.open(path)
    chunks = []
    skipped = 0
    seen: set[str] = set()
    try:
        for index, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            if not text:
                skipped += 1
                continue
            first_line = text.splitlines()[0].strip()
            if first_line and len(first_line) <= 80:
                section = first_line
            else:
                section = f"Page {index}"
            chunks.append(
                {
                    "doc_path": path.name,
                    "section": section,
                    "page_number": index,
                    "source_id": source_id_for(path.name, f"p{index}", seen),
                    "body": text,
                }
            )
    finally:
        document.close()
    return chunks, skipped


def chunk_corpus(root: Path | None = None) -> tuple[list[dict], int]:
    folder = root or CORPUS
    chunks: list[dict] = []
    skipped = 0
    for path in sorted(folder.glob("*.md")):
        chunks.extend(chunk_markdown(path))
    for path in sorted(folder.glob("*.pdf")):
        pdf_chunks, pdf_skipped = chunk_pdf(path)
        chunks.extend(pdf_chunks)
        skipped += pdf_skipped
    return chunks, skipped
