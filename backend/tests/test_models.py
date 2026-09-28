"""Model switches. These tests do not download Qwen or call Groq."""

from __future__ import annotations

import os
import unittest

from app.ingest.ingest_docs import schema_for
from app.rag.embeddings import doc_table, embedding_backend, embedding_dim
from app.rag.rerank import reranker_name


class ModelSwitchTests(unittest.TestCase):
    def test_default_embedding_stays_on_bge(self):
        previous = os.environ.pop("EMBEDDING_MODEL", None)
        try:
            self.assertEqual(embedding_backend(), "bge")
            self.assertEqual(doc_table(), "doc_chunks")
            self.assertEqual(embedding_dim(), 384)
        finally:
            if previous is not None:
                os.environ["EMBEDDING_MODEL"] = previous

    def test_qwen_uses_a_separate_1024_table(self):
        previous = os.environ.get("EMBEDDING_MODEL")
        os.environ["EMBEDDING_MODEL"] = "qwen3"
        try:
            self.assertEqual(doc_table(), "doc_chunks_qwen3")
            self.assertEqual(embedding_dim(), 1024)
            schema = schema_for("doc_chunks_qwen3", 1024)
            self.assertIn("vector(1024)", schema)
            self.assertNotIn("plans", schema)
        finally:
            if previous is None:
                os.environ.pop("EMBEDDING_MODEL", None)
            else:
                os.environ["EMBEDDING_MODEL"] = previous

    def test_unknown_embedding_name_is_rejected(self):
        previous = os.environ.get("EMBEDDING_MODEL")
        os.environ["EMBEDDING_MODEL"] = "other"
        try:
            with self.assertRaises(ValueError):
                embedding_backend()
        finally:
            if previous is None:
                os.environ.pop("EMBEDDING_MODEL", None)
            else:
                os.environ["EMBEDDING_MODEL"] = previous

    def test_reranker_names(self):
        previous = os.environ.pop("RERANKER", None)
        try:
            self.assertEqual(reranker_name(), "minilm")
        finally:
            if previous is not None:
                os.environ["RERANKER"] = previous
        os.environ["RERANKER"] = "qwen3"
        try:
            self.assertEqual(reranker_name(), "qwen3")
        finally:
            os.environ.pop("RERANKER", None)
            if previous is not None:
                os.environ["RERANKER"] = previous

    def test_schema_rejects_an_unknown_table(self):
        with self.assertRaises(ValueError):
            schema_for("invoices", 384)


if __name__ == "__main__":
    unittest.main()
