import asyncio
import json
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
    event_id: str | None = None,
    title: str | None = None,
    city: str = "Москва",
    region: str | None = "Москва",
    source_url: str | None = None,
    starts_at: str = "2026-11-01T00:00:00",
) -> Event:
    return Event(
        id=event_id or f"{source}-{index}",
        title=title or f"Event {index}",
        city=city,
        region=region,
        category="Бег",
        starts_at=starts_at,
        date_text="01.11.2026",
        source_name=source,
        source_url=source_url or f"https://example.com/{source}/{index}",
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

    def test_event_id_drops_listing_index(self) -> None:
        event = make_event(
            0,
            event_id="myrace-95-4ab3bb1a6722",
            title="6 Колец Кондратовских полей",
        )

        normalized = self.service._normalize_event(event)

        self.assertEqual(normalized.id, "myrace-4ab3bb1a6722")

    def test_title_variants_are_merged_across_sources(self) -> None:
        first = make_event(
            1,
            source="Russia Running",
            event_id="russiarunning-abcdef123456",
            title="IХ Полумарафон «Бегущая Вологда» (05.12-06.12)",
            city="Вологда",
            region="Вологодская область",
        )
        second = make_event(
            2,
            source="Get.run",
            event_id="getrun-123456abcdef",
            title="Бегущая Вологда 2026",
            city="Вологда",
            region="Вологодская область",
        )

        deduped = self.service._deduplicate([first, second])

        self.assertEqual(len(deduped), 1)

    def test_variant_distances_are_not_merged(self) -> None:
        first = make_event(
            1,
            source="IRONSTAR",
            event_id="ironstar-abcdef123456",
            title="IRONSTAR 1/4 ЗАВИДОВО 2027",
            city="Завидово",
            region="Тверская область",
        )
        second = make_event(
            2,
            source="IRONSTAR",
            event_id="ironstar-123456abcdef",
            title="IRONSTAR 1/8 ЗАВИДОВО 2027",
            city="Завидово",
            region="Тверская область",
        )

        deduped = self.service._deduplicate([first, second])

        self.assertEqual(len(deduped), 2)

    def test_kids_race_is_not_merged_with_adult_race(self) -> None:
        first = make_event(
            1,
            source="Gran Fondo",
            event_id="granfondo-abcdef123456",
            title="Granfondo Волоколамск",
            city="Волоколамск",
            region="Московская область",
        )
        second = make_event(
            2,
            source="Gran Fondo",
            event_id="granfondo-123456abcdef",
            title="Granfondo Волоколамск Дети",
            city="Волоколамск",
            region="Московская область",
        )

        deduped = self.service._deduplicate([first, second])

        self.assertEqual(len(deduped), 2)

    def test_synthetic_calendar_fragments_are_removed(self) -> None:
        fpr = make_event(
            1,
            source="ФПР",
            source_url="https://fpr-info.ru/kalendar.htm#event-123",
        )
        wrpf = make_event(
            2,
            source="СПР/WRPF",
            source_url=(
                "https://russia-powerlifting.ru/kalendar/"
                "kalendar-sorevnovanij-2026#event-456"
            ),
        )

        self.assertEqual(
            str(self.service._normalize_event(fpr).source_url),
            "https://fpr-info.ru/kalendar.htm",
        )
        self.assertEqual(
            str(self.service._normalize_event(wrpf).source_url),
            "https://russia-powerlifting.ru/kalendar/kalendar-sorevnovanij-2026",
        )

    def test_fpr_rows_with_same_title_city_and_close_dates_are_merged(self) -> None:
        first = make_event(
            1,
            source="ФПР",
            event_id="fpr-1-aaaaaaaaaaaa",
            title="Чемпионат Азии",
            city="Улан-Батор, Монголия",
            region=None,
            source_url="https://fpr-info.ru/kalendar.htm#event-1",
            starts_at="2026-11-30T00:00:00",
        )
        second = make_event(
            2,
            source="ФПР",
            event_id="fpr-2-bbbbbbbbbbbb",
            title="Чемпионат Азии",
            city="Улан-Батор, Монголия",
            region=None,
            source_url="https://fpr-info.ru/kalendar.htm#event-2",
            starts_at="2026-12-01T00:00:00",
        )

        deduped = self.service._deduplicate([first, second])

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].starts_at, "2026-11-30T00:00:00")

    def test_fpr_same_title_on_distant_dates_is_kept(self) -> None:
        first = make_event(
            1,
            source="ФПР",
            title="Чемпионат Азии",
            city="Улан-Батор, Монголия",
            region=None,
            starts_at="2026-11-30T00:00:00",
        )
        second = make_event(
            2,
            source="ФПР",
            title="Чемпионат Азии",
            city="Улан-Батор, Монголия",
            region=None,
            starts_at="2026-12-20T00:00:00",
        )

        deduped = self.service._deduplicate([first, second])

        self.assertEqual(len(deduped), 2)

    def test_persistent_cache_is_deduplicated_on_load(self) -> None:
        duplicate_one = make_event(
            1,
            source="A",
            event_id="A-10-aaaaaaaaaaaa",
            title="Томилинский веломарафон",
            region="Московская область",
        )
        duplicate_two = make_event(
            2,
            source="B",
            event_id="B-20-bbbbbbbbbbbb",
            title="Томилинский веломарафон 2026",
            region="Московская область",
        )
        settings.cache_file.write_text(
            json.dumps(
                {
                    "version": settings.cache_version,
                    "created_at": time.time(),
                    "items": [
                        duplicate_one.model_dump(mode="json"),
                        duplicate_two.model_dump(mode="json"),
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        loaded = CatalogService()

        self.assertEqual(len(loaded._cache), 1)
        self.assertEqual(loaded._cache[0].id, "A-aaaaaaaaaaaa")


if __name__ == "__main__":
    unittest.main()
