from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.config import settings
from app.partners import PartnerRegistry
from app.storage import Database


PARTNERS = {
    "partners": [
        {
            "id": "global",
            "title": "Партнёр",
            "text": "Текст",
            "button_text": "Перейти",
            "url": "https://example.com/?uid={uid}",
            "placements": ["search", "digest"],
            "weight": 1,
        },
        {
            "id": "moscow-run",
            "title": "Московский забег",
            "text": "Текст",
            "button_text": "Регистрация",
            "url": "https://example.com/moscow",
            "placements": ["search"],
            "cities": ["Москва"],
            "categories": ["Бег"],
        },
        {
            "id": "disabled",
            "enabled": False,
            "title": "Выключен",
            "text": "Текст",
            "button_text": "Перейти",
            "url": "https://example.com/disabled",
            "placements": ["search"],
        },
    ]
}


class PartnerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.db = Database(root / "test.db")
        await self.db.init()
        await self.db.ensure_user(1)
        self.config = root / "partners.json"
        self.config.write_text(json.dumps(PARTNERS, ensure_ascii=False), "utf-8")
        self.registry = PartnerRegistry(self.config, self.db)
        self.previous_base = settings.public_base_url
        self.previous_cap = settings.partner_impression_per_user_day

    async def asyncTearDown(self) -> None:
        settings.public_base_url = self.previous_base
        settings.partner_impression_per_user_day = self.previous_cap
        self.tempdir.cleanup()

    def test_matching(self) -> None:
        partner = self.registry.get("moscow-run")
        assert partner is not None
        self.assertTrue(
            partner.matches(placement="search", cities=["Москва"], categories=["Бег"])
        )
        self.assertFalse(
            partner.matches(placement="search", cities=["Казань"], categories=["Бег"])
        )
        self.assertFalse(
            partner.matches(placement="digest", cities=["Москва"], categories=["Бег"])
        )

    async def test_impression_cap(self) -> None:
        settings.partner_impression_per_user_day = 1
        first = await self.registry.choose(
            1, placement="search", cities=["Казань"], categories=["Лыжи"]
        )
        self.assertIsNotNone(first)
        second = await self.registry.choose(
            1, placement="search", cities=["Казань"], categories=["Лыжи"]
        )
        self.assertIsNone(second)

    async def test_tracked_url(self) -> None:
        partner = self.registry.get("global")
        assert partner is not None
        settings.public_base_url = "https://sporly.ru/"
        self.assertEqual(
            self.registry.tracked_url(partner, 42),
            "https://sporly.ru/go/global?uid=42",
        )
        settings.public_base_url = ""
        self.assertEqual(
            self.registry.tracked_url(partner, 42),
            "https://example.com/?uid=42",
        )


if __name__ == "__main__":
    unittest.main()
