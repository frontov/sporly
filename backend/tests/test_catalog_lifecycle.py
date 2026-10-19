import asyncio
import tempfile
import time
import unittest
from pathlib import Path

from app.schemas.event import Event
from app.services.catalog import CatalogService, EventFilters
from app.settings import settings


def make_event(
    index: int,
    *,
    source: str = "A",
    status: str = "active",
    miss_count: int = 0,
) -> Event:
    return Event(
        id=f"{source}-{index}",
        title=f"Event {index}",
        city="Москва",
        region="Москва",
        category="Бег",
        starts_at="2026-11-01T00:00:00",
        date_text="01.11.2026",
        source_name=source,
        source_url=f"https://example.com/{source}/{index}",
        miss_count=miss_count,
        status=status,
    )


class CatalogLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_cache_file = settings.cache_file
        self.temp_dir = tempfile.TemporaryDirectory()
        settings.cache_file = Path(self.temp_dir.name) / "events_cache.json"
        self.service = CatalogService()
        self.service._cache = [make_event(1), make_event(2)]
        self.service._cache_created_at = 0

    def tearDown(self) -> None:
        settings.cache_file = self.original_cache_file
        self.temp_dir.cleanup()

    def test_confirmed_misses_mark_inactive_and_reactivate(self) -> None:
        fresh = [make_event(1)]
        for expected_miss_count in (1, 2):
            self.service._cache = self.service._merge_refreshed_events(
                fresh, f"2026-10-19T10:0{expected_miss_count}:00", {"A": 1}
            )
            event = next(e for e in self.service._cache if e.id == "A-2")
            self.assertEqual(event.miss_count, expected_miss_count)
            self.assertEqual(event.status, "active")

        self.service._cache = self.service._merge_refreshed_events(
            fresh, "2026-10-19T10:03:00", {"A": 1}
        )
        event = next(e for e in self.service._cache if e.id == "A-2")
        self.assertEqual(event.miss_count, 3)
        self.assertEqual(event.status, "inactive")

        self.service._cache = self.service._merge_refreshed_events(
            [make_event(1), make_event(2)], "2026-10-19T10:04:00", {"A": 2}
        )
        event = next(e for e in self.service._cache if e.id == "A-2")
        self.assertEqual(event.miss_count, 0)
        self.assertEqual(event.status, "active")

    def test_source_outage_does_not_count_as_miss(self) -> None:
        event = make_event(3, miss_count=2)
        self.service._cache = [event]

        self.service._cache = self.service._merge_refreshed_events(
            [], "2026-10-19T11:00:00", {"A": 0}
        )

        event = self.service._cache[0]
        self.assertEqual(event.miss_count, 2)
        self.assertEqual(event.status, "active")

    def test_new_events_are_always_added(self) -> None:
        self.service._cache = [make_event(4)]

        self.service._cache = self.service._merge_refreshed_events(
            [make_event(4), make_event(5)], "2026-10-19T12:00:00", {"A": 2}
        )

        self.assertEqual({event.id for event in self.service._cache}, {"A-4", "A-5"})
        new_event = next(e for e in self.service._cache if e.id == "A-5")
        self.assertEqual(new_event.status, "active")
        self.assertEqual(new_event.miss_count, 0)

    def test_inactive_events_are_hidden_from_public_api(self) -> None:
        self.service._cache = [
            make_event(6),
            make_event(7, status="inactive"),
        ]
        self.service._cache_created_at = time.time()

        visible = asyncio.run(self.service.get_events(EventFilters()))

        self.assertEqual([event.id for event in visible], ["A-6"])

    def test_first_seen_after_filter(self) -> None:
        older = make_event(1)
        older.first_seen_at = "2026-10-19T09:00:00"
        newer = make_event(2)
        newer.first_seen_at = "2026-10-19T11:00:00"

        filtered = self.service._apply_filters(
            [older, newer],
            EventFilters(first_seen_after="2026-10-19T10:00:00+00:00"),
        )

        self.assertEqual([event.id for event in filtered], ["A-2"])

    def test_first_seen_after_filter_keeps_missing_timestamps_out(self) -> None:
        no_timestamp = make_event(1)

        filtered = self.service._apply_filters(
            [no_timestamp],
            EventFilters(first_seen_after="2026-10-19T10:00:00+00:00"),
        )

        self.assertEqual(filtered, [])


if __name__ == "__main__":
    unittest.main()
