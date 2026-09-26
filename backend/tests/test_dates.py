"""Calendar phrases used by invoice SQL. No database and no model."""

from __future__ import annotations

import os
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.rag.dates import app_today, period_for_question
from app.rag.sql_tool import draft_sql_without_llm


class PeriodTests(unittest.TestCase):
    def test_last_month_from_september(self):
        got = period_for_question("What was Acme's invoice last month?", today=date(2026, 9, 25))
        self.assertEqual(got, date(2026, 8, 1))

    def test_year_boundary(self):
        got = period_for_question("invoice last month", today=date(2026, 1, 1))
        self.assertEqual(got, date(2025, 12, 1))

    def test_this_month_on_the_first(self):
        got = period_for_question("this month's invoice", today=date(2026, 3, 1))
        self.assertEqual(got, date(2026, 3, 1))

    def test_explicit_august_2026_from_a_later_year(self):
        got = period_for_question("invoice in August 2026", today=date(2027, 5, 1))
        self.assertEqual(got, date(2026, 8, 1))

    def test_explicit_historical_july(self):
        got = period_for_question("July 2026 bill", today=date(2026, 9, 1))
        self.assertEqual(got, date(2026, 7, 1))

    def test_named_month_without_a_year_uses_the_latest_past_one(self):
        got = period_for_question("December invoice", today=date(2026, 1, 10))
        self.assertEqual(got, date(2025, 12, 1))

    def test_timezone_can_move_the_calendar_day(self):
        previous = os.environ.get("APP_TIMEZONE")
        os.environ["APP_TIMEZONE"] = "America/Los_Angeles"
        try:
            # 06:30 UTC on 1 Sep is still 31 Aug in Los Angeles (UTC-7).
            got = app_today(now=datetime(2026, 9, 1, 6, 30, tzinfo=ZoneInfo("UTC")))
        finally:
            if previous is None:
                os.environ.pop("APP_TIMEZONE", None)
            else:
                os.environ["APP_TIMEZONE"] = previous
        self.assertEqual(got, date(2026, 8, 31))


class SqlTemplateTests(unittest.TestCase):
    def test_last_month_is_a_parameter(self):
        sql, _explanation, params = draft_sql_without_llm(
            "What was Acme's invoice last month?",
            today=date(2026, 9, 25),
        )
        self.assertIsNotNone(sql)
        self.assertNotIn("2026-08-01", sql)
        self.assertEqual(params, ["Acme", date(2026, 8, 1)])

    def test_explicit_august_2026_stays_selectable(self):
        _sql, _explanation, params = draft_sql_without_llm(
            "What was Soylent's invoice in August 2026?",
            today=date(2027, 2, 1),
        )
        self.assertEqual(params[1], date(2026, 8, 1))


if __name__ == "__main__":
    unittest.main()
