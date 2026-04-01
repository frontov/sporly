from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

import httpx

from app.parsers.base import (
    ArtaSportParser,
    CyclingRaceParser,
    CssDirectoryParser,
    GaltropaParser,
    GranFondoParser,
    MarzocchiCupParser,
    MarathonCupParser,
    NezhesteamParser,
    OTimeCalendarParser,
    OrgeoParser,
    RegPlaceParser,
    RussiaRunningSeriesParser,
    RuncParser,
    RussialoppetParser,
    SourceConfig,
    SourceFieldMap,
)
from app.schemas.event import Event
from app.settings import settings


@dataclass(slots=True)
class EventFilters:
    query: str | None = None
    cities: list[str] | None = None
    categories: list[str] | None = None
    source: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    sort_by: str | None = None


class CatalogService:
    REGION_ALIASES: dict[str, tuple[str, ...]] = {
        "Москва": (
            "москва",
            "лужники",
            "крылатск",
            "садовое кольцо",
            "битца",
        ),
        "Санкт-Петербург": (
            "санкт-петербург",
            "спб",
            "питер",
            "пискарев",
            "елагин",
            "александрино",
            "пушкин",
        ),
        "Московская область": (
            "московская область",
            "подмосков",
            "истра",
            "ромашково",
            "волоколамск",
            "бородино",
            "красногорск",
            "котельники",
            "химки",
            "мытищи",
            "трубино",
            "коломна",
            "дмитров",
            "сергиев посад",
            "одинцово",
            "можайск",
            "серпухов",
        ),
        "Ленинградская область": (
            "ленинградская область",
            "ленобласть",
            "токсово",
            "лемболово",
            "кавголово",
            "петяярви",
            "орехово",
            "мичуринск",
            "мичуринское",
            "цвелодубово",
            "семиозерье",
            "гарболово",
            "кобона",
            "яппиля",
            "гатчина",
            "выборг",
            "приозерск",
            "лемболово",
            "сосново",
        ),
        "Костромская область": (
            "костромская область",
            "костромская",
            "костромской",
            "кострома",
            "галич",
        ),
        "Ярославская область": (
            "ярославская область",
            "ярославль",
            "переславль",
            "тутаев",
            "некрасовск",
            "некрасовское",
        ),
        "Самарская область": (
            "самарская область",
            "самара",
            "сокольи горы",
        ),
        "Республика Татарстан": (
            "татарстан",
            "казань",
        ),
        "Краснодарский край": (
            "краснодарский край",
            "краснодар",
            "сочи",
            "красная поляна",
            "эсто-садок",
            "курорт газпром",
            "роза хутор",
        ),
        "Нижегородская область": (
            "нижегородская область",
            "нижний новгород",
        ),
        "Камчатский край": (
            "камчат",
            "петропавловск-камчатский",
        ),
        "Новгородская область": (
            "новгородская область",
            "боровичи",
            "мстинские пороги",
        ),
        "Псковская область": (
            "псковская область",
            "псков",
        ),
        "Республика Карелия": (
            "карелия",
            "петрозаводск",
        ),
        "Новосибирская область": (
            "новосибирская область",
            "новосибирск",
        ),
        "Тверская область": (
            "тверская область",
            "тверь",
        ),
        "Свердловская область": (
            "свердловская область",
            "екатеринбург",
        ),
        "Тюменская область": (
            "тюменская область",
            "тюмень",
        ),
        "Республика Башкортостан": (
            "башкортостан",
            "уфа",
        ),
        "Калининградская область": (
            "калининградская область",
            "калининград",
        ),
        "Воронежская область": (
            "воронежская область",
            "воронеж",
        ),
        "Пермский край": (
            "пермский край",
            "пермь",
        ),
        "Волгоградская область": (
            "волгоградская область",
            "волгоград",
        ),
        "Тульская область": (
            "тульская область",
            "тула",
        ),
        "Омская область": (
            "омская область",
            "омск",
        ),
        "Челябинская область": (
            "челябинская область",
            "челябинск",
            "миасс",
        ),
        "Ставропольский край": (
            "ставропольский край",
            "кисловодск",
        ),
        "Анталья": (
            "анталия",
        ),
    }
    LOCATION_GROUPS: dict[str, tuple[str, ...]] = {
        "Санкт-Петербург и Ленинградская область": (
            "санкт-петербург",
            "ленинградская область",
            "ленобласть",
            "токсово",
            "лемболово",
            "гатчина",
            "петяярви",
            "цвелодубово",
            "мичуринское",
        ),
        "Москва и Московская область": (
            "москва",
            "московская область",
            "подмосковье",
            "истра",
            "ромашково",
            "красногорск",
            "химки",
            "мытищи",
            "волоколамск",
            "бородино",
        ),
        "Краснодар и Краснодарский край": (
            "краснодар",
            "краснодарский край",
            "сочи",
            "красная поляна",
            "эсто-садок",
            "курорт газпром",
            "роза хутор",
        ),
        "Казань и Республика Татарстан": (
            "казань",
            "республика татарстан",
            "татарстан",
        ),
        "Екатеринбург и Свердловская область": (
            "екатеринбург",
            "свердловская область",
        ),
        "Новосибирск и Новосибирская область": (
            "новосибирск",
            "новосибирская область",
        ),
        "Нижний Новгород и Нижегородская область": (
            "нижний новгород",
            "нижегородская область",
        ),
        "Самара и Самарская область": (
            "самара",
            "самарская область",
            "сокольи горы",
        ),
        "Тюмень и Тюменская область": (
            "тюмень",
            "тюменская область",
        ),
        "Уфа и Республика Башкортостан": (
            "уфа",
            "башкортостан",
            "республика башкортостан",
        ),
        "Ярославль и Ярославская область": (
            "ярославль",
            "ярославская область",
            "тутаев",
            "переславль",
            "некрасовское",
        ),
        "Псков и Псковская область": (
            "псков",
            "псковская область",
        ),
        "Тверь и Тверская область": (
            "тверь",
            "тверская область",
        ),
        "Воронеж и Воронежская область": (
            "воронеж",
            "воронежская область",
        ),
        "Пермь и Пермский край": (
            "пермь",
            "пермский край",
        ),
        "Омск и Омская область": (
            "омск",
            "омская область",
        ),
        "Челябинск и Челябинская область": (
            "челябинск",
            "челябинская область",
        ),
        "Калининград и Калининградская область": (
            "калининград",
            "калининградская область",
        ),
        "Кострома и Костромская область": (
            "кострома",
            "костромская область",
            "галич",
        ),
        "Петрозаводск и Республика Карелия": (
            "петрозаводск",
            "карелия",
            "республика карелия",
        ),
        "Кисловодск и Ставропольский край": (
            "кисловодск",
            "ставропольский край",
        ),
        "Петропавловск-Камчатский и Камчатский край": (
            "петропавловск-камчатский",
            "камчатский край",
            "камчатка",
        ),
    }

    def __init__(self) -> None:
        self._cache: list[Event] = []
        self._cache_created_at = 0.0
        self._refresh_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[None] | None = None
        self._load_persistent_cache()

    async def get_events(self, filters: EventFilters) -> list[Event]:
        if not self._cache:
            await self._refresh_cache()
        elif self._is_cache_stale():
            self._ensure_background_refresh()
        return self._apply_sort(self._apply_filters(self._normalize_events(self._cache), filters), filters)

    def _is_cache_stale(self) -> bool:
        return (time.time() - self._cache_created_at) > settings.cache_ttl_seconds

    async def _collect_events(self) -> list[Event]:
        source_configs = self._load_source_configs(settings.sources_file)
        if not source_configs:
            return []

        async with httpx.AsyncClient(
            headers={"User-Agent": settings.user_agent},
            timeout=settings.request_timeout_seconds,
            follow_redirects=True,
        ) as client:
            semaphore = asyncio.Semaphore(settings.max_concurrent_sources)
            tasks = [
                asyncio.create_task(
                    self._collect_source_events(source_config, client, semaphore)
                )
                for source_config in source_configs
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            collected: list[Event] = []
            for result in results:
                if isinstance(result, Exception):
                    continue
                collected.extend(result)
            return self._deduplicate(collected)

    async def _collect_source_events(
        self,
        source_config: SourceConfig,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> list[Event]:
        async with semaphore:
            try:
                source_events = await asyncio.wait_for(
                    self._load_source_events(source_config, client),
                    timeout=settings.source_timeout_seconds,
                )
            except TimeoutError:
                return []
            except Exception:
                return []

            if not source_events:
                return []

            parser = self._build_parser(source_config)
            events_to_enrich, remaining_events = self._split_events_for_enrichment(
                source_events,
                settings.max_enrich_events_per_source,
            )
            try:
                enriched_events = await asyncio.wait_for(
                    parser.enrich_events(events_to_enrich, client),
                    timeout=settings.enrich_timeout_seconds,
                )
            except TimeoutError:
                enriched_events = events_to_enrich
            except Exception:
                enriched_events = events_to_enrich

            return [*enriched_events, *remaining_events]

    def _split_events_for_enrichment(
        self,
        events: list[Event],
        limit: int,
    ) -> tuple[list[Event], list[Event]]:
        if limit <= 0 or not events:
            return [], events

        prioritized = sorted(
            enumerate(events),
            key=lambda item: (
                self._enrichment_priority(item[1]),
                item[0],
            ),
        )
        selected_indexes = {
            index
            for index, _event in prioritized[: min(limit, len(events))]
        }
        events_to_enrich = [
            event for index, event in enumerate(events) if index in selected_indexes
        ]
        remaining_events = [
            event for index, event in enumerate(events) if index not in selected_indexes
        ]
        return events_to_enrich, remaining_events

    def _enrichment_priority(self, event: Event) -> tuple[int, int]:
        missing_date = event.starts_at is None or not event.date_text
        missing_location = event.city is None
        return (
            0 if missing_date else 1,
            0 if missing_location else 1,
        )

    async def _load_source_events(
        self,
        source_config: SourceConfig,
        client: httpx.AsyncClient,
    ) -> list[Event]:
        parser = self._build_parser(source_config)
        custom_events = await parser.fetch_events(client)
        if custom_events is not None:
            return custom_events

        source_events: list[Event] = []
        for listing_url in source_config.listing_urls:
            pages_to_load = [listing_url]
            loaded_pages: set[str] = set()

            while pages_to_load:
                current_url = pages_to_load.pop(0)
                if current_url in loaded_pages:
                    continue
                loaded_pages.add(current_url)

                try:
                    response = await client.get(current_url)
                    response.raise_for_status()
                except httpx.HTTPError:
                    continue

                source_events.extend(parser.parse(response.text, str(response.url)))
                if len(loaded_pages) == 1:
                    for next_url in parser.extract_pagination_urls(
                        response.text, str(response.url)
                    ):
                        if next_url not in loaded_pages:
                            pages_to_load.append(next_url)

        return source_events

    async def _refresh_cache(self) -> None:
        async with self._refresh_lock:
            if self._cache and not self._is_cache_stale():
                return

            collected_events = await self._collect_events()
            if not collected_events:
                return

            normalized_events = self._normalize_events(collected_events)
            if self._should_preserve_existing_cache(normalized_events):
                return

            self._cache = normalized_events
            self._cache_created_at = time.time()
            self._write_persistent_cache()

    def _ensure_background_refresh(self) -> None:
        if self._refresh_task and not self._refresh_task.done():
            return

        self._refresh_task = asyncio.create_task(self._run_background_refresh())

    async def _run_background_refresh(self) -> None:
        try:
            await self._refresh_cache()
        finally:
            self._refresh_task = None

    def _load_persistent_cache(self) -> None:
        cache_file = settings.cache_file
        if not cache_file.exists():
            return

        try:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            cache_version = int(payload.get("version", 0))
            if cache_version != settings.cache_version:
                self._cache = []
                self._cache_created_at = 0.0
                return
            items = payload.get("items", [])
            created_at = payload.get("created_at", 0.0)
            self._cache = self._normalize_events(
                [Event.model_validate(item) for item in items]
            )
            self._cache_created_at = float(created_at)
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            self._cache = []
            self._cache_created_at = 0.0

    def _write_persistent_cache(self) -> None:
        cache_file = settings.cache_file
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": settings.cache_version,
            "created_at": self._cache_created_at,
            "items": [event.model_dump(mode="json") for event in self._cache],
        }
        cache_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _should_preserve_existing_cache(self, next_events: list[Event]) -> bool:
        if not self._cache:
            return False
        if len(next_events) >= len(self._cache):
            return False
        refresh_ratio = len(next_events) / max(len(self._cache), 1)
        return refresh_ratio < settings.minimum_refresh_ratio

    def _build_parser(self, source_config: SourceConfig) -> CssDirectoryParser:
        if source_config.parser_type == "reg_place":
            return RegPlaceParser(source_config)
        if source_config.parser_type == "arta_sport":
            return ArtaSportParser(source_config)
        if source_config.parser_type == "marzocchi_cup":
            return MarzocchiCupParser(source_config)
        if source_config.parser_type == "granfondo":
            return GranFondoParser(source_config)
        if source_config.parser_type == "cyclingrace":
            return CyclingRaceParser(source_config)
        if source_config.parser_type == "otime_calendar":
            return OTimeCalendarParser(source_config)
        if source_config.parser_type == "marathoncup":
            return MarathonCupParser(source_config)
        if source_config.parser_type == "galtropa":
            return GaltropaParser(source_config)
        if source_config.parser_type == "nezhesteam":
            return NezhesteamParser(source_config)
        if source_config.parser_type == "orgeo":
            return OrgeoParser(source_config)
        if source_config.parser_type == "runc":
            return RuncParser(source_config)
        if source_config.parser_type == "russialoppet":
            return RussialoppetParser(source_config)
        if source_config.parser_type == "russiarunning_series":
            return RussiaRunningSeriesParser(source_config)
        return CssDirectoryParser(source_config)

    def _load_source_configs(self, config_path: Path) -> list[SourceConfig]:
        if not config_path.exists():
            return []

        raw_data = json.loads(config_path.read_text(encoding="utf-8"))
        configs: list[SourceConfig] = []

        for item in raw_data.get("sources", []):
            if not item.get("enabled", True):
                continue
            selectors = item["selectors"]
            configs.append(
                SourceConfig(
                    name=item["name"],
                    base_url=item["base_url"],
                    listing_urls=item["listing_urls"],
                    selectors=SourceFieldMap(
                        item=selectors["item"],
                        title=selectors["title"],
                        link=selectors["link"],
                        date=selectors.get("date"),
                        city=selectors.get("city"),
                        venue=selectors.get("venue"),
                        category=selectors.get("category"),
                        description=selectors.get("description"),
                        image=selectors.get("image"),
                    ),
                    parser_type=item.get("parser_type", "css"),
                    enabled=item.get("enabled", True),
                    pagination_selector=item.get("pagination_selector"),
                    max_pages=item.get("max_pages", 1),
                )
            )
        return configs

    def _deduplicate(self, events: list[Event]) -> list[Event]:
        seen: set[str] = set()
        result: list[Event] = []
        for event in events:
            key = f"{event.title}|{event.starts_at}|{event.source_url}"
            if key in seen:
                continue
            seen.add(key)
            result.append(event)
        return sorted(
            result,
            key=lambda item: (
                item.starts_at is None,
                item.starts_at or "",
                item.title.lower(),
            ),
        )

    def _normalize_events(self, events: list[Event]) -> list[Event]:
        return [
            self._normalize_event(event)
            for event in events
        ]

    def _normalize_event(self, event: Event) -> Event:
        normalized_region = self._infer_region(event.city, event.region, event.venue, event.title)
        return event.model_copy(
            update={
                "region": normalized_region,
                "city": self._normalize_city(event.city, normalized_region),
                "category": self._normalize_category(event.category),
                "starts_at": self._normalize_starts_at(event.date_text, event.starts_at),
            }
        )

    def build_available_cities(self, events: list[Event]) -> list[str]:
        major_cities = {
            "москва",
            "санкт-петербург",
            "казань",
            "екатеринбург",
            "новосибирск",
            "нижний новгород",
            "краснодар",
            "сочи",
            "ростов-на-дону",
            "самара",
            "уфа",
            "омск",
            "пермь",
            "воронеж",
            "красноярск",
            "тюмень",
            "владивосток",
            "калининград",
            "ярославль",
            "тверь",
            "рязань",
            "туль",
            "ижевск",
            "хабаровск",
            "иркутск",
        }
        counts: dict[str, int] = {}
        region_counts: dict[str, int] = {}
        for event in events:
            if not event.city:
                if event.region:
                    region_counts[event.region] = region_counts.get(event.region, 0) + 1
                continue
            counts[event.city] = counts.get(event.city, 0) + 1
            if event.region:
                region_counts[event.region] = region_counts.get(event.region, 0) + 1

        group_counts = {
            label: sum(
                1 for event in events if self._matches_location_group(event, label)
            )
            for label in self.LOCATION_GROUPS
        }

        filtered = [
            city
            for city, count in counts.items()
            if count >= 3 or any(token in city.lower() for token in major_cities)
        ]
        grouped = [label for label, count in group_counts.items() if count >= 3]
        city_items = sorted(
            filtered,
            key=lambda city: (-counts[city], city.lower()),
        )[:60]
        region_items = sorted(
            [region for region, count in region_counts.items() if count >= 3],
            key=lambda region: (-region_counts[region], region.lower()),
        )[:40]
        group_items = sorted(
            grouped,
            key=lambda city: (-group_counts[city], city.lower()),
        )
        result: list[str] = []
        seen: set[str] = set()
        for item in [*group_items, *region_items, *city_items]:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def _normalize_starts_at(self, date_text: str | None, starts_at: str | None) -> str | None:
        normalized_from_text = self._parse_date_text(date_text)
        return normalized_from_text or starts_at

    def _normalize_city(self, city: str | None, region: str | None) -> str | None:
        normalized_city = self._normalize_location_name(city)
        normalized_region = self._normalize_location_name(region)
        if not normalized_city:
            return None
        if not normalized_region:
            return normalized_city

        city_lower = normalized_city.lower()
        region_lower = normalized_region.lower()
        federal_cities = {"москва", "санкт-петербург", "севастополь"}
        if city_lower in federal_cities or city_lower == region_lower:
            return normalized_city
        if city_lower in region_lower or region_lower in city_lower:
            return normalized_city
        return f"{normalized_city}, {normalized_region}"

    def _infer_region(
        self,
        city: str | None,
        region: str | None,
        venue: str | None,
        title: str | None,
    ) -> str | None:
        normalized_region = self._normalize_location_name(region)
        haystack = " ".join(
            part
            for part in [
                self._normalize_location_name(city),
                normalized_region,
                self._normalize_location_name(venue),
                title,
            ]
            if part
        ).lower()

        for canonical_region, aliases in self.REGION_ALIASES.items():
            if any(self._contains_location_token(haystack, alias) for alias in aliases):
                return canonical_region

        return normalized_region

    def _normalize_location_name(self, value: str | None) -> str | None:
        if not value:
            return None
        normalized = re.sub(r"\s+", " ", value).strip(" ,")
        replacements = {
            " обл.": " область",
            "обл.": "область",
            "респ.": "республика",
            "г. ": "",
        }
        for source, target in replacements.items():
            normalized = normalized.replace(source, target)
        return normalized.strip(" ,") or None

    def _matches_location_group(self, event: Event, group_label: str) -> bool:
        aliases = self.LOCATION_GROUPS.get(group_label)
        if not aliases:
            return False
        haystack = self._build_location_haystack(event)
        return any(self._contains_location_token(haystack, alias) for alias in aliases)

    def _matches_selected_location(self, event: Event, selected_location: str) -> bool:
        normalized_selected = self._normalize_location_name(selected_location) or selected_location
        haystack = self._build_location_haystack(event)

        if self._matches_location_group(event, normalized_selected):
            return True

        region_aliases = self.REGION_ALIASES.get(normalized_selected)
        if region_aliases and any(
            self._contains_location_token(haystack, alias) for alias in region_aliases
        ):
            return True

        return self._contains_location_token(haystack, normalized_selected)

    def _build_location_haystack(self, event: Event) -> str:
        return " ".join(
            filter(
                None,
                [
                    self._normalize_location_name(event.city),
                    self._normalize_location_name(event.region),
                    self._normalize_location_name(event.venue),
                    event.title,
                ],
            )
        ).lower()

    def _contains_location_token(self, haystack: str, needle: str) -> bool:
        escaped = re.escape(needle.lower())
        return bool(re.search(rf"(?<![а-яa-z]){escaped}(?![а-яa-z])", haystack))

    def _parse_date_text(self, date_text: str | None) -> str | None:
        if not date_text:
            return None

        text = date_text.strip().lower()

        dot_match = re.search(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", text)
        if dot_match:
            day = int(dot_match.group(1))
            month = int(dot_match.group(2))
            year = int(dot_match.group(3))
            try:
                return datetime(year, month, day).isoformat()
            except ValueError:
                return None

        month_map = {
            "января": 1,
            "февраля": 2,
            "марта": 3,
            "апреля": 4,
            "мая": 5,
            "июня": 6,
            "июля": 7,
            "августа": 8,
            "сентября": 9,
            "октября": 10,
            "ноября": 11,
            "декабря": 12,
        }
        month_match = re.search(
            r"(\d{1,2})(?:\s*[–—-]\s*\d{1,2})?\s+"
            r"(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
            r"(?:\s+(\d{4}))?",
            text,
        )
        if month_match:
            day = int(month_match.group(1))
            month = month_map[month_match.group(2)]
            year = int(month_match.group(3)) if month_match.group(3) else datetime.now().year
            try:
                return datetime(year, month, day).isoformat()
            except ValueError:
                return None

        return None

    def _normalize_category(self, category: str | None) -> str | None:
        if not category:
            return None

        normalized = category.strip().lower()

        if any(token in normalized for token in ["вело", "велогон", "gravel", "bmx"]):
            return "Велоспорт"
        if any(
            token in normalized
            for token in ["бег", "trail", "трейл", "кросс", "полумарафон", "марафон", "экиден", "ekiden"]
        ):
            return "Бег"
        if any(token in normalized for token in ["лыж", "ski", "биатлон"]):
            return "Лыжи"
        if any(token in normalized for token in ["плав", "swim"]):
            return "Плавание"
        if any(token in normalized for token in ["триатлон", "дуатлон", "swimrun", "акватлон"]):
            return "Триатлон"
        if any(
            token in normalized
            for token in ["ориентирование", "туризм", "скалолаз", "альпинизм", "rogaine", "рогейн"]
        ):
            return "Ориентирование и туризм"
        if any(token in normalized for token in ["ходьба", "nordic walking", "спортивная ходьба"]):
            return "Ходьба"
        if any(token in normalized for token in ["борьба", "дзюдо"]):
            return "Единоборства"
        if any(token in normalized for token in ["легкая атлетика", "атлетик"]):
            return "Легкая атлетика"
        if any(
            token in normalized
            for token in ["детский спорт", "самокат", "беговел", "подвижные игры"]
        ):
            return "Детские старты"
        if "другой вид" in normalized:
            return "Другие"

        return category.strip()

    def _apply_filters(self, events: list[Event], filters: EventFilters) -> list[Event]:
        filtered = events

        if filters.query:
            query = filters.query.lower()
            filtered = [
                event
                for event in filtered
                if query in " ".join(
                    filter(
                        None,
                        [
                            event.title,
                            event.description,
                            event.city,
                            event.venue,
                            event.category,
                        ],
                    )
                ).lower()
            ]

        if filters.cities:
            selected_cities = [city.strip() for city in filters.cities if city.strip()]
            filtered = [
                event
                for event in filtered
                if any(
                    self._matches_selected_location(event, city)
                    for city in selected_cities
                )
            ]

        if filters.categories:
            selected_categories = {
                category.lower() for category in filters.categories if category.strip()
            }
            filtered = [
                event
                for event in filtered
                if (event.category or "").lower() in selected_categories
            ]

        if filters.source:
            source = filters.source.lower()
            filtered = [
                event for event in filtered if (event.source_name or "").lower() == source
            ]

        if filters.date_from:
            filtered = [
                event
                for event in filtered
                if event.starts_at is None or event.starts_at[:10] >= filters.date_from
            ]

        if filters.date_to:
            filtered = [
                event
                for event in filtered
                if event.starts_at is None or event.starts_at[:10] <= filters.date_to
            ]

        return filtered

    def _apply_sort(self, events: list[Event], filters: EventFilters) -> list[Event]:
        sort_by = filters.sort_by or "date_asc"
        sorted_events = sorted(
            events,
            key=lambda item: (
                item.starts_at is None,
                item.starts_at or "",
                item.title.lower(),
            ),
        )
        if sort_by == "date_desc":
            sorted_events.reverse()
        return sorted_events
