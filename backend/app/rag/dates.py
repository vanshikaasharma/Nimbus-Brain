"""Turn 'last month' and named months into an invoice period_start.

APP_TIMEZONE defaults to America/Vancouver. Set the env var to use another zone.
Tests pass an explicit day so they do not depend on the clock.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def timezone_name() -> str:
    return os.environ.get("APP_TIMEZONE", "America/Vancouver")


def app_today(today: date | None = None, now: datetime | None = None) -> date:
    if today is not None:
        return today
    zone = ZoneInfo(timezone_name())
    moment = now if now is not None else datetime.now(zone)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    return moment.astimezone(zone).date()


def shift_month(day: date, delta: int) -> date:
    month_index = day.month - 1 + delta
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def period_for_question(question: str, today: date | None = None) -> date | None:
    """First day of the month the question is about, or None if it names none."""
    q = question.lower()
    current = app_today(today)
    for name, month in MONTHS.items():
        if not re.search(rf"\b{name}\b", q):
            continue
        year_match = re.search(rf"\b{name}\b\s+(?:of\s+)?(20\d{{2}})\b", q)
        if year_match:
            return date(int(year_match.group(1)), month, 1)
        year = current.year if month <= current.month else current.year - 1
        return date(year, month, 1)
    if "last month" in q:
        return shift_month(current.replace(day=1), -1)
    if "this month" in q:
        return shift_month(current.replace(day=1), 0)
    return None
