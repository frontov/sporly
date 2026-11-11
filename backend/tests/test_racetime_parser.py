import unittest

from app.parsers.base import RaceTimeParser, SourceConfig, SourceFieldMap
from app.services.catalog import CatalogService


def _payload(**overrides):
    race = {
        "displayName": "Фиджитал велосоревнования KOMON",
        "publicUrl": "/scanEvent/fidzhital-komon",
        "startDateTime": "2026-12-05T00:00:00",
        "displayNameSecondary": "Велосипедный спорт",
        "organizationName": "KOM-On",
        "sportTypeId": 60,
    }
    race.update(overrides)
    return {"data": [race]}


class RaceTimeRegistrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = RaceTimeParser(
            SourceConfig(
                name="RaceTime",
                base_url="https://racetime.online",
                listing_urls=[
                    "https://racetime.online/api/afisha/races?type=Upcoming"
                ],
                selectors=SourceFieldMap(
                    item="a.race-card",
                    title=".name",
                    link="a.race-card",
                ),
                parser_type="racetime",
            )
        )
        # Methods that do not touch instance state.
        self.catalog = object.__new__(CatalogService)

    def parse(self, **overrides):
        return self.parser._parse_racetime_api_payload(
            _payload(**overrides),
            "https://racetime.online/api/afisha/races?type=Upcoming",
        )

    def test_register_url_marks_registration_open(self) -> None:
        events = self.parse(
            registerUrl="https://reg.place/events/komon-winter",
            postText=(
                "Этапы проходят по субботам. Регистрация открыта до "
                "15 января 2027; нужны пульсометр и умный станок."
            ),
        )

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.registration_status, "open")
        self.assertEqual(event.organizer_name, "KOM-On")
        self.assertIn("Регистрация открыта", event.description or "")
        self.assertEqual(
            self.catalog._extract_registration_deadline(event),
            "до 15 января 2027",
        )

    def test_closed_text_overrides_register_url(self) -> None:
        events = self.parse(
            registerUrl="https://reg.place/events/komon-winter",
            postText="Регистрация закрыта, мест больше нет.",
        )

        self.assertEqual(events[0].registration_status, "closed")

    def test_upcoming_text_is_not_treated_as_open(self) -> None:
        events = self.parse(
            registerUrl="https://reg.place/events/komon-winter",
            postText="Регистрация откроется 1 ноября 2026.",
        )

        self.assertEqual(events[0].registration_status, "upcoming")

    def test_open_text_without_register_url(self) -> None:
        events = self.parse(postText="Регистрация открыта на все дистанции.")

        self.assertEqual(events[0].registration_status, "open")

    def test_no_registration_signals(self) -> None:
        events = self.parse()

        self.assertIsNone(events[0].registration_status)
        self.assertEqual(events[0].description, "Велосипедный спорт • KOM-On")


if __name__ == "__main__":
    unittest.main()
