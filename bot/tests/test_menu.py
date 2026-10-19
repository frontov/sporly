from __future__ import annotations

import unittest

from app.keyboards import menu_callback_for_text


class MenuTextTest(unittest.TestCase):
    def test_new_buttons(self) -> None:
        self.assertEqual(menu_callback_for_text("🔍 Найти старт"), "menu:find")
        self.assertEqual(menu_callback_for_text("⚙️ Настройки"), "menu:more")
        self.assertEqual(menu_callback_for_text("⚙️ Ещё"), "menu:more")

    def test_legacy_buttons(self) -> None:
        self.assertEqual(menu_callback_for_text("🔍 Найти события"), "menu:find")
        self.assertEqual(menu_callback_for_text("Ближайшие"), "menu:soon")
        self.assertEqual(menu_callback_for_text("Мои события"), "menu:sub")
        self.assertEqual(menu_callback_for_text("Мои интересы"), "menu:sub")

    def test_regular_query_is_not_a_menu(self) -> None:
        self.assertIsNone(menu_callback_for_text("забег в Казани"))


if __name__ == "__main__":
    unittest.main()
