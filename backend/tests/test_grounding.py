"""Citation and evidence checks. No model and no database."""

from __future__ import annotations

import unittest

from app.rag.generate import chunk_evidence, review_answer


EVIDENCE = (
    "[S1] {'name': 'Acme', 'amount_dollars': '3470.00'}\n"
    "[D1] sla-enterprise.md#Credits > Credits\nTen percent."
)


class GroundingTests(unittest.TestCase):
    def test_pdf_chunk_keeps_source_id_and_page(self):
        text = chunk_evidence(
            {
                "source_id": "credit-policy.pdf#p1",
                "page_number": 1,
                "section": "Credits",
                "body": "Ten percent.",
            }
        )
        self.assertIn("credit-policy.pdf#p1", text)
        self.assertIn("page 1", text)

    def test_unknown_source_id_is_flagged(self):
        _answer, flags = review_answer("Acme owes $3470 [D9].", {"S1", "D1"}, EVIDENCE)
        self.assertTrue(any("D9" in flag for flag in flags))

    def test_missing_citation_is_a_format_check(self):
        _answer, flags = review_answer("Acme owes $3470.", {"S1"}, EVIDENCE)
        self.assertTrue(any(flag.startswith("Citation check:") for flag in flags))

    def test_page_not_in_evidence_is_flagged(self):
        _answer, flags = review_answer("See page 9 [D1].", {"D1"}, EVIDENCE)
        self.assertTrue(any("page 9" in flag for flag in flags))

    def test_customer_missing_from_evidence_is_flagged(self):
        _answer, flags = review_answer("Globex owes $3470 [S1].", {"S1"}, EVIDENCE)
        self.assertTrue(any("Globex" in flag for flag in flags))

    def test_wrong_total_for_a_named_customer_is_a_contradiction(self):
        evidence = "[S1] {'name': 'Acme', 'amount_dollars': '3470.00'}"
        _answer, flags = review_answer("Acme was $2180 [S1].", {"S1"}, evidence)
        self.assertTrue(any("assigns Acme" in flag for flag in flags))

    def test_cent_figure_next_to_the_dollar_total_is_not_a_second_amount(self):
        evidence = "[S1] {'name': 'Acme', 'amount_cents': 210000, 'amount_dollars': '2100.00'}"
        answer = (
            "Acme's invoice in July 2026 was 210,000 cents, which is $2100. [S1]"
        )
        _text, flags = review_answer(answer, {"S1"}, evidence)
        self.assertEqual(flags, [])

    def test_partial_answer_leaves_out_a_second_total(self):
        evidence = (
            "[S1] {'name': 'Acme', 'amount_dollars': '3470.00'}\n"
            "[S2] {'name': 'Soylent', 'amount_dollars': '2180.00'}"
        )
        _answer, flags = review_answer("Acme was $3470 [S1].", {"S1", "S2"}, evidence)
        self.assertTrue(any("more than one total" in flag for flag in flags))
        self.assertFalse(any("disagree" in flag for flag in flags))

    def test_contradictory_evidence_must_be_mentioned(self):
        evidence = (
            "[S1] {'name': 'Acme', 'amount_dollars': '3470.00'}\n"
            "[S2] {'name': 'Acme', 'amount_dollars': '2100.00'}"
        )
        _answer, flags = review_answer("Acme was $3470 [S1].", {"S1", "S2"}, evidence)
        self.assertTrue(any("disagree" in flag for flag in flags))

    def test_one_rewrite_uses_the_same_evidence(self):
        from app.rag.generate import answer_with_sources

        calls = []

        def write(question, evidence):
            calls.append((question, evidence))
            if len(calls) == 1:
                return "Acme owes $9999."
            return "Acme was $3470 [S1]."

        evidence_row = "{'name': 'Acme', 'amount_dollars': '3470.00'}"
        answer, flags = answer_with_sources("What was Acme's invoice?", [("S1", evidence_row)], write=write)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1], calls[1][1])
        self.assertIn("[S1]", answer)
        self.assertEqual(flags, [])

    def test_a_cited_answer_is_not_called_fully_verified(self):
        answer, flags = review_answer("Acme was $3470 [S1].", {"S1"}, EVIDENCE)
        self.assertEqual(flags, [])
        self.assertNotIn("hallucination", answer.lower())


if __name__ == "__main__":
    unittest.main()
