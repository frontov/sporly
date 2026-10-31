import unittest

from app.services.catalog import CatalogService


class CanonicalCategoryTest(unittest.TestCase):
    def assert_category(
        self, source: str, expected: str, *, title: str | None = None
    ) -> None:
        with self.subTest(source=source, title=title):
            self.assertEqual(
                CatalogService._normalize_category(None, source, title=title),
                expected,
            )

    def test_moves_small_categories_to_raznoe(self) -> None:
        cases = {
            "Ходьба": "Разное",
            "Скайсноу": "Разное",
            "Фастпакинг": "Разное",
            "ARDF, радиоспорт": "Разное",
            "Боевые искусства": "Разное",
            "Единоборства": "Разное",
            "Бадминтон": "Разное",
            "Ездовой спорт": "Разное",
            "Гонки приключенческие; с препятствиями": "Разное",
            "Детские старты": "Разное",
            "Фиджитал": "Разное",
            "Другие": "Разное",
            "Легкая атлетика": "Разное",
        }
        for source, expected in cases.items():
            self.assert_category(source, expected)

    def test_splits_orienteering_and_tourism(self) -> None:
        self.assert_category(
            "Ориентирование и туризм",
            "Ориентирование",
            title="Кубок парков Самары по спортивному ориентированию",
        )
        self.assert_category(
            "Ориентирование и туризм",
            "Разное",
            title="Чемпионат области по спортивному туризму",
        )
        self.assert_category(
            "Ориентирование и туризм",
            "Разное",
            title="Соревнования по северной ходьбе",
        )
        self.assert_category(
            "Ориентирование и туризм",
            "Разное",
            title="Первенство по скалолазанию",
        )
        self.assert_category(
            "Ориентирование и туризм",
            "Разное",
            title="Фестиваль отчетов о пройденных походах",
        )

    def test_keeps_existing_sections(self) -> None:
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
            self.assert_category(value, value)

    def test_unknown_category_falls_back_to_raznoe(self) -> None:
        self.assert_category("Стрельба из лука", "Разное")

    def test_empty_category_stays_empty(self) -> None:
        self.assertIsNone(CatalogService._normalize_category(None, None))
        self.assertIsNone(CatalogService._normalize_category(None, "   "))
