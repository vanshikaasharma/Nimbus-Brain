"""Retry decisions. No database and no model."""

from __future__ import annotations

import unittest

from app.rag.fallback import gaps, other_tool


class OtherToolTests(unittest.TestCase):
    def test_invoice_miss_on_docs_may_try_sql(self):
        self.assertEqual(other_tool("What was Acme's invoice last month?", "docs"), "sql")

    def test_doc_question_does_not_call_sql(self):
        self.assertIsNone(other_tool("What is the Pro rate limit?", "docs"))

    def test_outage_miss_on_sql_may_try_graph(self):
        self.assertEqual(other_tool("Who was hit by the ingest outage?", "sql"), "graph")

    def test_two_evidence_types_do_not_pick_a_third_tool(self):
        question = "What was the August invoice, and what does the SLA say we owe?"
        self.assertIsNone(other_tool(question, "docs"))

    def test_no_second_switch_when_the_first_tool_already_has_evidence(self):
        self.assertEqual(gaps("sql", {"sql": {"rows": [{"amount_cents": 1}]}}), [])
        self.assertEqual(gaps("docs", {"chunks": [{"body": "pro"}], "abstained": False}), [])
        self.assertEqual(gaps("docs", {"chunks": [], "abstained": True}), ["doc passage"])
        self.assertEqual(gaps("graph", {"graph": {"paths": []}}), ["graph path"])


if __name__ == "__main__":
    unittest.main()
