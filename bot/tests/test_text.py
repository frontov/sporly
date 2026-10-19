from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.text import countdown, days_until, format_date, pluralize


class TextTest(unittest.TestCase):
    def test_pluralize(self) -> None:
        self.assertEqual(pluralize(1, "старт", "старта", "стартов"), "старт")
        self.assertEqual(pluralize(2, "старт", "старта", "стартов"), "старта")
        self.assertEqual(pluralize(5, "старт", "старта", "стартов"), "стартов")
        self.assertEqual(pluralize(11, "старт", "старта", "стартов"), "стартов")
        self.assertEqual(pluralize(21, "старт", "старта", "стартов"), "старт")

    def test_format_date_drops_current_year(self) -> None:
        value = date.today().replace(month=1, day=15).isoformat()
        self.assertEqual(format_date(value), "15 января")

    def test_countdown(self) -> None:
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        self.assertEqual(countdown(tomorrow), "завтра")
        self.assertIsNone(countdown("2001-01-01T00:00:00"))

    def test_days_until(self) -> None:
        future = (date.today() + timedelta(days=7)).isoformat()
        self.assertEqual(days_until(future), 7)


if __name__ == "__main__":
    unittest.main()
