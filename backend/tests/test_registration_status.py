import unittest
from datetime import datetime

from app.parsers.base import RussiaRunningSeriesParser, SourceConfig, SourceFieldMap
from app.schemas.event import Event
from app.services.catalog import CatalogService


def make_event(**overrides: object) -> Event:
    payload: dict[str, object] = {
        "id": "event-1",
        "title": "Тестовый старт",
        "starts_at": "2026-12-20T00:00:00",
        "date_text": "20.12.2026",
        "source_name": "Test",
        "source_url": "https://example.com/event",
    }
    payload.update(overrides)
    return Event(**payload)


class RegistrationStatusTest(unittest.TestCase):
    service: CatalogService

    @classmethod
    def setUpClass(cls) -> None:
        cls.service = CatalogService()

    def setUp(self) -> None:
        self.now = datetime(2026, 11, 11, 12, 0)

    def test_deadline_in_past_closes_cached_open_status(self) -> None:
        event = make_event(
            registration_status="open",
            registration_deadline="до 01.11.2026",
        )

        self.assertEqual(
            self.service._resolve_registration_status(event, event.registration_status, now=self.now),
            "closed",
        )

    def test_deadline_in_future_keeps_registration_open(self) -> None:
        event = make_event(
            registration_status="open",
            registration_deadline="до 01.12.2026",
        )

        self.assertEqual(
            self.service._resolve_registration_status(event, event.registration_status, now=self.now),
            "open",
        )

    def test_upcoming_status_becomes_open_after_open_date(self) -> None:
        future = make_event(
            registration_status="upcoming",
            registration_opens_at="2026-12-01T10:00:00",
        )
        past = make_event(
            registration_status="upcoming",
            registration_opens_at="2026-11-01T10:00:00",
        )

        self.assertEqual(
            self.service._resolve_registration_status(future, future.registration_status, now=self.now),
            "upcoming",
        )
        self.assertEqual(
            self.service._resolve_registration_status(past, past.registration_status, now=self.now),
            "open",
        )

    def test_open_date_from_registration_window_is_upcoming(self) -> None:
        event = make_event(
            description="Регистрация участников с 1 декабря 2026 по 10 декабря 2026",
        )

        self.assertEqual(
            self.service._detect_registration_status(event, now=self.now),
            "upcoming",
        )

    def test_registration_window_is_open_inside_range(self) -> None:
        event = make_event(
            description="Регистрация участников с 1 ноября 2026 по 10 декабря 2026",
        )

        self.assertEqual(
            self.service._detect_registration_status(event, now=self.now),
            "open",
        )

    def test_registration_window_is_closed_after_range(self) -> None:
        event = make_event(
            description="Регистрация участников с 1 октября 2026 по 10 ноября 2026",
        )

        self.assertEqual(
            self.service._detect_registration_status(event, now=self.now),
            "closed",
        )

    def test_explicit_upcoming_wording_is_detected(self) -> None:
        event = make_event(description="Регистрация ещё не открыта")

        self.assertEqual(
            self.service._detect_registration_status(event, now=self.now),
            "upcoming",
        )

    def test_deadline_without_status_implies_open(self) -> None:
        event = make_event(registration_deadline="до 10 декабря 2026")

        self.assertEqual(
            self.service._resolve_registration_status(event, None, now=self.now),
            "open",
        )

    def test_open_status_closes_after_event_date_without_deadline(self) -> None:
        event = make_event(
            registration_status="open",
            starts_at="2026-11-01T00:00:00",
        )

        self.assertEqual(
            self.service._resolve_registration_status(event, event.registration_status, now=self.now),
            "closed",
        )

    def test_normalize_event_extracts_opens_at_from_description(self) -> None:
        event = make_event(
            description="Регистрация откроется 1 декабря 2026",
        )

        normalized = self.service._normalize_event(event)

        self.assertEqual(normalized.registration_status, "upcoming")
        self.assertEqual(normalized.registration_opens_at, "2026-12-01T00:00:00")


class RussiaRunningRegistrationStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = RussiaRunningSeriesParser(
            SourceConfig(
                name="Russia Running",
                base_url="https://russiarunning.com",
                listing_urls=["https://russiarunning.com/fs/series"],
                selectors=SourceFieldMap(item="li", title="a", link="a"),
                parser_type="russiarunning_series",
            )
        )

    def test_state_numbers_map_to_registration_states(self) -> None:
        expected = {
            1: "upcoming",
            2: "open",
            3: "closed",
        }

        for state, status in expected.items():
            with self.subTest(state=state):
                item = {
                    "raceItems": [
                        {
                            "registrationDateState": state,
                            "registrationOpenDate": "2026-12-01T10:00:00",
                            "registrationCloseDate": "2026-12-10T23:59:00",
                        }
                    ]
                }

                detected, opens_at, deadline = (
                    self.parser._extract_russiarunning_registration_details(item)
                )

                self.assertEqual(detected, status)
                self.assertEqual(opens_at, "2026-12-01T10:00:00")
                self.assertEqual(deadline, "до 10.12.2026")

    def test_disabled_registration_is_closed(self) -> None:
        item = {
            "raceItems": [
                {
                    "registrationDateState": 2,
                    "disableRegistration": True,
                }
            ]
        }

        detected, _, _ = self.parser._extract_russiarunning_registration_details(item)

        self.assertEqual(detected, "closed")


if __name__ == "__main__":
    unittest.main()
