from __future__ import annotations

import unittest

from app.scheduler import reminder_offset


class ReminderTest(unittest.TestCase):
    def test_exact_threshold(self) -> None:
        self.assertEqual(reminder_offset(7, set()), 7)
        self.assertEqual(reminder_offset(3, {"7"}), 3)
        self.assertEqual(reminder_offset(1, {"7", "3"}), 1)
        self.assertEqual(reminder_offset(0, {"7", "3", "1"}), 0)

    def test_missed_thresholds_send_only_once(self) -> None:
        self.assertEqual(reminder_offset(2, set()), 7)
        self.assertEqual(reminder_offset(2, {"7", "3"}), None)
        self.assertEqual(reminder_offset(5, {"7"}), None)

    def test_after_start_returns_none(self) -> None:
        self.assertEqual(reminder_offset(-1, set()), None)


if __name__ == "__main__":
    unittest.main()


class NewEventTest(unittest.TestCase):
    def test_new_since(self) -> None:
        from app.scheduler import is_new_since

        self.assertTrue(is_new_since("2026-10-19T12:00:00", "2026-10-19T11:00:00"))
        self.assertFalse(is_new_since("2026-10-19T10:00:00", "2026-10-19T11:00:00"))
        self.assertTrue(is_new_since(None, "2026-10-19T11:00:00"))
        self.assertTrue(is_new_since("2026-10-19T12:00:00", None))

    def test_new_since_timezone(self) -> None:
        from app.scheduler import is_new_since

        self.assertTrue(
            is_new_since(
                "2026-10-19T12:00:00+00:00",
                "2026-10-19T14:00:00+03:00",
            )
        )
