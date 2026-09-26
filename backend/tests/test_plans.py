"""Route parsing, mixed tool plans, and unanswered agent tools. No model."""

from __future__ import annotations

import unittest

from app.rag.coverage import unanswered_tools
from app.rag.mixed import order_steps, parse_steps
from app.rag.router import parse_route, widen_single_label


class ParseRouteTests(unittest.TestCase):
    def test_json_route(self):
        self.assertEqual(parse_route('Sure. {"route":"sql"}'), "sql")

    def test_labeled_route_when_json_is_broken(self):
        self.assertEqual(parse_route("route: unknown, because it is a private note"), "unknown")

    def test_single_word(self):
        self.assertEqual(parse_route("graph"), "graph")

    def test_prose_without_a_label_is_not_a_route(self):
        self.assertIsNone(parse_route("I think this is about billing but I am not sure"))


class MixedPlanTests(unittest.TestCase):
    def test_synonyms_and_graph_before_sql(self):
        parsed = parse_steps('{"steps":["lookup_invoices","walk_graph"]}')
        ordered = order_steps(parsed, "invoices for the accounts on the outage")
        self.assertEqual(ordered, ["graph", "sql"])

    def test_two_tool_pairs_keep_only_those_tools(self):
        self.assertEqual(parse_steps('{"steps":["graph","docs"]}'), ["graph", "docs"])
        self.assertEqual(parse_steps('{"steps":["sql","docs"]}'), ["sql", "docs"])
        self.assertEqual(parse_steps('{"steps":["graph","sql","docs"]}'), ["graph", "sql", "docs"])

    def test_prose_list_is_accepted(self):
        self.assertEqual(parse_steps("Use graph then sql."), ["graph", "sql"])

    def test_sql_and_docs_are_not_reordered_into_graph(self):
        self.assertEqual(order_steps(["sql", "docs"], "bill and sla"), ["sql", "docs"])


class WidenTests(unittest.TestCase):
    def test_graph_label_becomes_mixed_when_invoices_are_also_asked(self):
        question = "Which accounts did the outage affect, and what were their bills?"
        self.assertEqual(widen_single_label("graph", question), "mixed")

    def test_a_single_evidence_type_stays_single(self):
        self.assertEqual(widen_single_label("sql", "Which customers are on Enterprise?"), "sql")
        self.assertEqual(widen_single_label("unknown", "Did a private note promise a discount?"), "unknown")


class UnansweredToolTests(unittest.TestCase):
    def test_graph_only_question_does_not_require_sql(self):
        question = "Which Enterprise customers were on INC-104?"
        self.assertEqual(unanswered_tools(question, ["graph"]), [])

    def test_invoice_after_graph_still_needs_sql(self):
        question = "Which accounts did INC-104 affect, and what were their August 2026 invoices?"
        self.assertEqual(unanswered_tools(question, ["graph"]), ["sql"])

    def test_single_doc_question_does_not_call_other_tools(self):
        self.assertEqual(unanswered_tools("What is the Pro rate limit?", ["docs"]), [])

    def test_side_question_needs_nothing(self):
        self.assertEqual(unanswered_tools("Did someone text Hooli a private discount?", []), [])


if __name__ == "__main__":
    unittest.main()
