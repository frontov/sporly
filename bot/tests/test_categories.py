import unittest

from app.categories import normalize_categories, normalize_category


class CategoryNormalizationTest(unittest.TestCase):
    def test_maps_legacy_categories_to_sections(self) -> None:
        cases = {
            "Ориентирование и туризм": "Ориентирование",
            "ARDF, радиоспорт": "Разное",
            "Фастпакинг": "Разное",
            "Скайсноу": "Разное",
            "Ходьба": "Разное",
            "Боевые искусства": "Разное",
            "Единоборства": "Разное",
            "Бадминтон": "Разное",
            "Ездовой спорт": "Разное",
            "Детские старты": "Разное",
            "Фиджитал": "Разное",
            "Другие": "Разное",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(normalize_category(source), expected)

    def test_keeps_canonical_categories(self) -> None:
        for value in (
            "Бег",
            "Велоспорт",
            "Плавание",
            "Триатлон",
            "Лыжи",
            "Ориентирование",
            "Силовые виды",
            "ГТО",
            "Разное",
        ):
            self.assertEqual(normalize_category(value), value)

    def test_deduplicates_after_merging(self) -> None:
        self.assertEqual(
            normalize_categories(
                ["Ориентирование", "Ориентирование и туризм", "Разное"]
            ),
            ["Ориентирование", "Разное"],
        )

    def test_empty_values(self) -> None:
        self.assertIsNone(normalize_category(None))
        self.assertIsNone(normalize_category("   "))
