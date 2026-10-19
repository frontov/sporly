import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

from app.schemas.event import Event
from app.services.catalog import CatalogService, EventFilters
from app.settings import settings


def make_event(
    index: int,
    *,
    source: str = "A",
    starts_at: str = "2026-11-01T00:00:00",
    featured: bool = False,
    priority: int = 0,
) -> Event:
    return Event(
        id=f"{source}-{index}",
        title=f"Event {index}",
        city="Москва",
        region="Москва",
        category="Бег",
        starts_at=starts_at,
        date_text=starts_at[:10],
        source_name=source,
        source_url=f"https://example.com/{source}/{index}",
        is_featured=featured,
        featured_priority=priority,
        status="active",
    )


class FeaturedEventsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_cache_file = settings.cache_file
        self.original_featured_file = settings.featured_events_file
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        settings.cache_file = base / "events_cache.json"
        settings.featured_events_file = base / "featured_events.json"
        self.service = CatalogService()
        self.service._cache = [make_event(1), make_event(2)]
        self.service._cache_created_at = time.time()

    def tearDown(self) -> None:
        settings.cache_file = self.original_cache_file
        settings.featured_events_file = self.original_featured_file
        self.temp_dir.cleanup()

    def test_feature_event_applies_flags_and_persists(self) -> None:
        entry, event = self.service.feature_event(
            event_id="A-1",
            source_url=None,
            label="Рекомендовано Sporly",
            priority=50,
            until=None,
        )

        self.assertEqual(entry.event_id, "A-1")
        self.assertTrue(event.is_featured)
        self.assertEqual(event.featured_label, "Рекомендовано Sporly")
        self.assertEqual(event.featured_priority, 50)

        reloaded = CatalogService()
        featured_event = next(e for e in reloaded._cache if e.id == "A-1")
        self.assertTrue(featured_event.is_featured)
        self.assertEqual(featured_event.featured_priority, 50)

        self.assertTrue(reloaded.unfeature_event(entry.id))
        reloaded = CatalogService()
        featured_event = next(e for e in reloaded._cache if e.id == "A-1")
        self.assertFalse(featured_event.is_featured)

    def test_expired_featured_entry_is_not_applied(self) -> None:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.service.feature_event(
            event_id="A-1",
            source_url=None,
            label="Рекомендовано Sporly",
            priority=50,
            until=yesterday,
        )

        event = next(e for e in self.service._cache if e.id == "A-1")
        self.assertFalse(event.is_featured)

    def test_featured_events_are_sorted_first_by_priority(self) -> None:
        events = [
            make_event(1, starts_at="2026-10-20T00:00:00"),
            make_event(2, starts_at="2026-11-20T00:00:00", featured=True, priority=10),
            make_event(3, starts_at="2026-12-20T00:00:00", featured=True, priority=100),
        ]

        sorted_events = self.service._apply_sort(
            events, EventFilters(sort_by="date_asc")
        )

        self.assertEqual([event.id for event in sorted_events], ["A-3", "A-2", "A-1"])

    def test_featured_only_filter(self) -> None:
        events = [
            make_event(1),
            make_event(2, featured=True, priority=10),
        ]

        filtered = self.service._apply_filters(
            events, EventFilters(featured_only=True)
        )

        self.assertEqual([event.id for event in filtered], ["A-2"])


if __name__ == "__main__":
    unittest.main()
