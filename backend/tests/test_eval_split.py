"""Keyword labels on the extended questions. No database and no model."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.rag.router import classify

EXTENDED = Path(__file__).resolve().parents[1] / "eval" / "extended.json"


class ExtendedLabelTests(unittest.TestCase):
    def test_paraphrases_miss_the_keyword_router(self):
        questions = json.loads(EXTENDED.read_text())["questions"]
        by_id = {item["id"]: item["question"] for item in questions}
        self.assertEqual(classify(by_id["paraphrase-pro"])["route"], "unknown")
        self.assertEqual(classify(by_id["paraphrase-acme-pay"])["route"], "unknown")

    def test_historical_and_missing_dates_still_look_like_sql(self):
        questions = json.loads(EXTENDED.read_text())["questions"]
        by_id = {item["id"]: item["question"] for item in questions}
        self.assertEqual(classify(by_id["acme-july-2026"])["route"], "sql")
        self.assertEqual(classify(by_id["acme-missing-2019"])["route"], "sql")
        self.assertEqual(classify(by_id["hooli-july"])["route"], "sql")

if __name__ == "__main__":
    unittest.main()
