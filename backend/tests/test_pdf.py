"""Text PDF chunking. No database, no OCR, no model."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from app.ingest.chunk import chunk_corpus, chunk_markdown, chunk_pdf


class PdfChunkTests(unittest.TestCase):
    def test_synthetic_pdf_keeps_page_and_source_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "credit-policy.pdf"
            document = fitz.open()
            page = document.new_page()
            page.insert_text((72, 72), "Credits after an outage\nTen percent of the monthly fee.")
            document.new_page()
            document.save(path)
            document.close()

            chunks, skipped = chunk_pdf(path)

        self.assertEqual(skipped, 1)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["doc_path"], "credit-policy.pdf")
        self.assertEqual(chunks[0]["page_number"], 1)
        self.assertEqual(chunks[0]["section"], "Credits after an outage")
        self.assertEqual(chunks[0]["source_id"], "credit-policy.pdf#p1")
        self.assertIn("Ten percent", chunks[0]["body"])

    def test_markdown_ingestion_still_chunks_by_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "pricing.md").write_text("# Pricing\n\n## Pro\n\nOne thousand requests.\n")
            chunks, skipped = chunk_corpus(folder)

        self.assertEqual(skipped, 0)
        self.assertEqual([chunk["section"] for chunk in chunks], ["Pricing", "Pro"])
        self.assertTrue(all(chunk["page_number"] is None for chunk in chunks))
        self.assertEqual(chunks[1]["source_id"], "pricing.md#Pro")

    def test_markdown_file_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sla.md"
            path.write_text("## Credits\n\nTen percent.\n")
            chunks = chunk_markdown(path)
        self.assertEqual(chunks[0]["source_id"], "sla.md#Credits")


if __name__ == "__main__":
    unittest.main()
