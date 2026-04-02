from __future__ import annotations

import asyncio
from collections import Counter
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from urllib.parse import urlparse, urlunparse

import httpx

from app.parsers.base import (
    ArtaSportParser,
    ArfCalendarParser,
    CyclingRaceParser,
    CssDirectoryParser,
    CityTrailParser,
    GaltropaParser,
    GoldenUltraParser,
    GranFondoParser,
    IronStarParser,
    BorisovoParser,
    LaStradaParser,
    MarzocchiCupParser,
    MarathonCupParser,
    MyRaceParser,
    NezhesteamParser,
    OTimeCalendarParser,
    OrgeoParser,
    RaceTimeParser,
    RegPlaceParser,
    RussiaRunningSeriesParser,
    RuncParser,
    RussialoppetParser,
    TriNitiCupParser,
    VelomarathonParser,
    XWatersParser,
    SourceConfig,
    SportidentParser,
    SwimcupParser,
    SourceFieldMap,
    VelogearanceParser,
    XCNewsParser,
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
    SOURCE_PRIORITY: dict[str, int] = {
        "MyRace": 6,
        "O-Time": 6,
        "REGPLACE": 5,
        "Russia Running": 5,
        "IRONSTAR": 5,
        "TRI NITI CUP": 5,
        "Orgeo": 4,
        "Golden Ultra": 4,
        "Velogearance": 4,
        "Velomarathon": 4,
        "XCnews": 4,
        "ARF": 4,
    }
    REGION_ALIASES: dict[str, tuple[str, ...]] = {
        "Москва": (
            "москва",
            "лужники",
            "крылатск",
            "садовое кольцо",
            "битца",
            "зеленоград",
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
            "чулково",
            "володарского",
            "руза",
            "раменское",
            "габо",
            "пирогово",
            "ступино",
            "спас-каменка",
            "люберцы",
            "реутов",
            "жуковский",
            "томилинский",
            "томилино",
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
            "красноозерное",
            "красноозёрное",
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
            "рыбинск",
        ),
        "Самарская область": (
            "самарская область",
            "самара",
            "сокольи горы",
        ),
        "Республика Татарстан": (
            "татарстан",
            "казань",
            "набережные челны",
            "нижнекамск",
        ),
        "Краснодарский край": (
            "краснодарский край",
            "краснодар",
            "сочи",
            "красная поляна",
            "эсто-садок",
            "курорт газпром",
            "роза хутор",
            "армавир",
        ),
        "Нижегородская область": (
            "нижегородская область",
            "нижний новгород",
        ),
        "Ханты-Мансийский автономный округ — Югра": (
            "ханты-мансийский автономный округ",
            "югра",
            "ханты-мансийск",
        ),
        "Ямало-Ненецкий автономный округ": (
            "ямало-ненецкий автономный округ",
            "полярный урал",
        ),
        "Камчатский край": (
            "камчат",
            "петропавловск-камчатский",
            "елизово",
        ),
        "Новгородская область": (
            "новгородская область",
            "великий новгород",
            "боровичи",
            "мстинские пороги",
        ),
        "Псковская область": (
            "псковская область",
            "псков",
        ),
        "Республика Беларусь": (
            "минск",
            "беларусь",
            "белоруссия",
        ),
        "Республика Карелия": (
            "карелия",
            "петрозаводск",
        ),
        "Новосибирская область": (
            "новосибирская область",
            "новосибирск",
        ),
        "Липецкая область": (
            "липецкая область",
            "липецк",
            "грязинский",
            "грязи",
            "каменка",
            "кудыкина гора",
        ),
        "Тверская область": (
            "тверская область",
            "тверь",
            "завидово",
            "калязин",
        ),
        "Рязанская область": (
            "рязанская область",
            "рязанская обл",
            "рязань",
            "варские",
        ),
        "Свердловская область": (
            "свердловская область",
            "екатеринбург",
            "нижний тагил",
            "среднеуральск",
            "ревда",
            "каменск-уральский",
            "каменский",
        ),
        "Тюменская область": (
            "тюменская область",
            "тюмень",
            "тобольск",
        ),
        "Республика Башкортостан": (
            "башкортостан",
            "уфа",
            "кумертау",
            "абзелиловский район",
            "ильчигулово",
            "отнурок",
            "стерлитамак",
            "сибай",
        ),
        "Владимирская область": (
            "владимирская область",
            "владимир",
            "александров",
            "красное эхо",
            "доброград",
        ),
        "Мурманская область": (
            "мурманская область",
            "кировск",
        ),
        "Вологодская область": (
            "вологодская область",
            "вологда",
            "череповец",
            "кириллов",
        ),
        "Республика Марий Эл": (
            "марий эл",
            "волжск",
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
            "полазна",
        ),
        "Волгоградская область": (
            "волгоградская область",
            "волгоград",
        ),
        "Тульская область": (
            "тульская область",
            "тула",
            "зарайск",
        ),
        "Саратовская область": (
            "саратовская область",
            "саратов",
            "хвалынск",
            "новые бурасы",
        ),
        "Омская область": (
            "омская область",
            "омск",
        ),
        "Челябинская область": (
            "челябинская область",
            "челябинск",
            "миасс",
            "златоуст",
            "кисегач",
            "чебаркуль",
            "зеленая поляна",
            "слюдорудник",
        ),
        "Ставропольский край": (
            "ставропольский край",
            "кисловодск",
            "железноводск",
            "лермонтов",
            "георгиевск",
            "пятигорск",
            "ставрополь",
            "светлоград",
        ),
        "Кировская область": (
            "кировская область",
            "киров",
        ),
        "Пензенская область": (
            "пензенская область",
            "пенза",
            "наровчат",
        ),
        "Республика Крым": (
            "республика крым",
            "крым",
            "симферополь",
        ),
        "Севастополь": (
            "севастополь",
            "балаклава",
        ),
        "Приморский край": (
            "приморский край",
            "владивосток",
        ),
        "Красноярский край": (
            "красноярский край",
            "красноярск",
        ),
        "Республика Саха (Якутия)": (
            "якутск",
            "саха",
            "якутия",
            "бердигестях",
        ),
        "Республика Дагестан": (
            "дагестан",
            "гуниб",
        ),
        "Кабардино-Балкарская Республика": (
            "кабардино-балкарская республика",
            "кбр",
            "терскол",
            "приэльбрусье",
        ),
        "Карачаево-Черкесская Республика": (
            "карачаево-черкесская республика",
            "кчр",
            "архыз",
        ),
        "Республика Адыгея": (
            "адыгея",
            "лаго-наки",
        ),
        "Республика Алтай": (
            "республика алтай",
            "алтай",
            "тюнгур",
        ),
        "Калужская область": (
            "калужская область",
            "никола-ленивец",
        ),
        "Иркутская область": (
            "иркутская область",
            "сахюрта",
        ),
        "Ульяновская область": (
            "ульяновская область",
            "ульяновск",
        ),
        "Ивановская область": (
            "ивановская область",
            "иваново",
            "фурманов",
            "плес",
            "кинешма",
        ),
        "Чувашская Республика": (
            "чувашская республика",
            "чебоксары",
        ),
        "Кемеровская область": (
            "кемеровская область",
            "кемерово",
        ),
        "Белгородская область": (
            "белгородская область",
            "белгород",
        ),
        "Хабаровский край": (
            "хабаровский край",
            "хабаровск",
        ),
        "Удмуртская Республика": (
            "удмуртия",
            "ижевск",
        ),
        "Орловская область": (
            "орловская область",
            "орел",
            "орёл",
        ),
        "Астраханская область": (
            "астраханская область",
            "астрахань",
            "камызякский район",
            "жан-аул",
        ),
        "Ростовская область": (
            "ростовская область",
            "ростов-на-дону",
            "морозовск",
        ),
        "Оренбургская область": (
            "оренбургская область",
            "оренбург",
        ),
        "Республика Северная Осетия — Алания": (
            "северная осетия",
            "алания",
            "стур-дигора",
            "рсо-алания",
        ),
        "Анталья": (
            "анталия",
        ),
        "Турция": (
            "турция",
            "стамбул",
            "анталия",
        ),
        "Армения": (
            "армения",
            "ереван",
            "севан",
        ),
        "Казахстан": (
            "казахстан",
            "костанай",
        ),
        "Грузия": (
            "грузия",
            "тбилиси",
            "кахетии",
        ),
        "Австрия": (
            "австрия",
            "вена",
        ),
        "Сербия": (
            "сербия",
            "белград",
        ),
        "Узбекистан": (
            "узбекистан",
            "самарканд",
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
        self._cache_version = 0
        self._available_cities: list[str] = []
        self._available_categories: list[str] = []
        self._available_sources: list[str] = []
        self._refresh_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[None] | None = None
        self._load_persistent_cache()

    async def get_events(self, filters: EventFilters) -> list[Event]:
        if not self._cache:
            self._ensure_background_refresh()
        elif self._is_cache_stale():
            self._ensure_background_refresh()
        return self._apply_sort(self._apply_filters(self._cache, filters), filters)

    def get_filter_metadata(self) -> tuple[list[str], list[str], list[str]]:
        return (
            list(self._available_cities),
            list(self._available_categories),
            list(self._available_sources),
        )

    def is_loading(self) -> bool:
        if self._cache:
            return False
        if self._refresh_task and not self._refresh_task.done():
            return True
        return self._refresh_lock.locked()

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
            self._cache_version = settings.cache_version
            self._rebuild_filter_metadata()
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
            items = payload.get("items", [])
            created_at = payload.get("created_at", 0.0)
            self._cache = self._normalize_events(
                [Event.model_validate(item) for item in items]
            )
            self._cache_created_at = (
                float(created_at)
                if cache_version == settings.cache_version
                else 0.0
            )
            self._cache_version = cache_version
            self._rebuild_filter_metadata()
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            self._cache = []
            self._cache_created_at = 0.0
            self._cache_version = 0
            self._available_cities = []
            self._available_categories = []
            self._available_sources = []

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
            return self._has_critical_source_drop(next_events)
        refresh_ratio = len(next_events) / max(len(self._cache), 1)
        return (
            refresh_ratio < settings.minimum_refresh_ratio
            or self._has_critical_source_drop(next_events)
        )

    def _has_critical_source_drop(self, next_events: list[Event]) -> bool:
        current_counts = Counter(
            event.source_name or "UNKNOWN" for event in self._cache
        )
        next_counts = Counter(
            event.source_name or "UNKNOWN" for event in next_events
        )

        for source_name, current_count in current_counts.items():
            if current_count < 20:
                continue
            next_count = next_counts.get(source_name, 0)
            if next_count == 0:
                return True
            if next_count / current_count < 0.5:
                return True

        return False

    def _rebuild_filter_metadata(self) -> None:
        self._available_cities = self.build_available_cities(self._cache)
        self._available_categories = sorted(
            {event.category for event in self._cache if event.category}
        )
        self._available_sources = sorted(
            {event.source_name for event in self._cache if event.source_name}
        )

    def _build_parser(self, source_config: SourceConfig) -> CssDirectoryParser:
        if source_config.parser_type == "reg_place":
            return RegPlaceParser(source_config)
        if source_config.parser_type == "arta_sport":
            return ArtaSportParser(source_config)
        if source_config.parser_type == "marzocchi_cup":
            return MarzocchiCupParser(source_config)
        if source_config.parser_type == "tri_niti_cup":
            return TriNitiCupParser(source_config)
        if source_config.parser_type == "granfondo":
            return GranFondoParser(source_config)
        if source_config.parser_type == "cyclingrace":
            return CyclingRaceParser(source_config)
        if source_config.parser_type == "city_trail":
            return CityTrailParser(source_config)
        if source_config.parser_type == "velomarathon":
            return VelomarathonParser(source_config)
        if source_config.parser_type == "otime_calendar":
            return OTimeCalendarParser(source_config)
        if source_config.parser_type == "marathoncup":
            return MarathonCupParser(source_config)
        if source_config.parser_type == "myrace":
            return MyRaceParser(source_config)
        if source_config.parser_type == "racetime":
            return RaceTimeParser(source_config)
        if source_config.parser_type == "ironstar":
            return IronStarParser(source_config)
        if source_config.parser_type == "lastrada":
            return LaStradaParser(source_config)
        if source_config.parser_type == "goldenultra":
            return GoldenUltraParser(source_config)
        if source_config.parser_type == "arf_calendar":
            return ArfCalendarParser(source_config)
        if source_config.parser_type == "sportident":
            return SportidentParser(source_config)
        if source_config.parser_type == "swimcup":
            return SwimcupParser(source_config)
        if source_config.parser_type == "velogearance":
            return VelogearanceParser(source_config)
        if source_config.parser_type == "xcnews":
            return XCNewsParser(source_config)
        if source_config.parser_type == "xwaters":
            return XWatersParser(source_config)
        if source_config.parser_type == "galtropa":
            return GaltropaParser(source_config)
        if source_config.parser_type == "nezhesteam":
            return NezhesteamParser(source_config)
        if source_config.parser_type == "borisovo":
            return BorisovoParser(source_config)
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
        unique_by_url: dict[str, Event] = {}
        fallback_seen: set[str] = set()
        result: list[Event] = []
        for event in events:
            canonical_url = self._canonical_source_url(str(event.source_url))
            if canonical_url:
                existing = unique_by_url.get(canonical_url)
                if existing is None or self._event_completeness_score(event) > self._event_completeness_score(existing):
                    unique_by_url[canonical_url] = event
                continue

            key = f"{event.title}|{event.starts_at}|{event.source_url}"
            if key in fallback_seen:
                continue
            fallback_seen.add(key)
            result.append(event)

        result.extend(unique_by_url.values())
        result = self._deduplicate_by_signature(result)
        return sorted(
            result,
            key=lambda item: (
                item.starts_at is None,
                item.starts_at or "",
                item.title.lower(),
            ),
        )

    def _deduplicate_by_signature(self, events: list[Event]) -> list[Event]:
        deduped: dict[tuple[str, str, str], Event] = {}
        passthrough: list[Event] = []

        for event in events:
            signature = self._semantic_dedupe_key(event)
            if not signature:
                passthrough.append(event)
                continue

            existing = deduped.get(signature)
            if existing is None or self._should_replace_duplicate(existing, event):
                deduped[signature] = event

        return [*passthrough, *deduped.values()]

    def _semantic_dedupe_key(self, event: Event) -> tuple[str, str, str] | None:
        normalized_title = self._normalize_title_for_dedupe(event.title)
        normalized_date = (event.starts_at or self._parse_date_text(event.date_text) or "")[:10]
        normalized_location = self._normalize_location_name(event.region) or self._normalize_location_name(event.city)
        tri_niti_stage = self._extract_tri_niti_stage_marker(event)
        if tri_niti_stage:
            if not normalized_date:
                return None
            return (tri_niti_stage, normalized_date, "tri-niti-cup")
        if not normalized_title or not normalized_date or not normalized_location:
            return None
        return (normalized_title, normalized_date, normalized_location.casefold())

    def _normalize_title_for_dedupe(self, title: str | None) -> str:
        if not title:
            return ""
        normalized = title.casefold().replace("ё", "е")
        normalized = re.sub(r"[\"'`«»„“”()]+", " ", normalized)
        normalized = re.sub(
            r"^\d+\s*[-йя]?\s*этап\s+tri\s*niti\s+cup\s*[-—–:]\s*",
            "",
            normalized,
        )
        normalized = re.sub(
            r"\s+\d+\s*[-йя]?\s*этап\s+tri\s*niti\s+cup(?:\s+\d{4})?$",
            "",
            normalized,
        )
        normalized = re.sub(
            r"^\d+\s*[-йя]?\s*этап\s+",
            "",
            normalized,
        )
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _extract_tri_niti_stage_marker(self, event: Event) -> str | None:
        haystack = " ".join(
            part for part in [event.title, event.description, event.venue] if part
        ).casefold().replace("ё", "е")
        if "tri niti cup" not in haystack:
            return None
        match = re.search(r"(\d+)\s*[-йя]?\s*этап", haystack)
        if not match:
            return None
        return f"tri niti cup stage {match.group(1)}"

    def _should_replace_duplicate(self, existing: Event, candidate: Event) -> bool:
        existing_score = self._event_completeness_score(existing)
        candidate_score = self._event_completeness_score(candidate)
        if candidate_score != existing_score:
            return candidate_score > existing_score
        return self._source_priority(candidate.source_name) > self._source_priority(existing.source_name)

    def _source_priority(self, source_name: str | None) -> int:
        if not source_name:
            return 0
        return self.SOURCE_PRIORITY.get(source_name, 1)

    def _canonical_source_url(self, source_url: str | None) -> str:
        if not source_url:
            return ""

        normalized = source_url.strip()
        if not normalized:
            return ""

        parsed_with_fragment = urlparse(normalized)
        host_with_fragment = parsed_with_fragment.netloc.lower()
        fragment_value = parsed_with_fragment.fragment.strip()
        preserve_fragment = ""
        fragment_match = re.search(r"#(stage-\d+|event-\d+)$", normalized)
        if fragment_match:
            preserve_fragment = f"#{fragment_match.group(1).lower()}"
        elif host_with_fragment in {"city-trail.ru", "www.city-trail.ru", "stradarace.ru", "www.stradarace.ru"} and fragment_value:
            preserve_fragment = f"#{fragment_value.lower()}"

        normalized = re.sub(r"#.*$", "", normalized)
        normalized = normalized.rstrip("/")
        parsed = urlparse(normalized)
        host = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        query = ""

        if host == "nezhesteam.ru" and path == "/race":
            date_match = re.search(r"(?:^|[?&])date=(\d{8})(?:&|$)", source_url)
            if date_match:
                query = f"date={date_match.group(1)}"

        if host == "sportident.online" and path == "/entry":
            id_match = re.search(r"(?:^|[?&])id=(\d+)(?:&|$)", source_url)
            if id_match:
                query = f"id={id_match.group(1)}"

        if host == "www.xcnews.ru" and path == "/index.php":
            type_match = re.search(r"(?:^|[?&])type=([^&]+)(?:&|$)", source_url)
            if type_match:
                query = f"type={type_match.group(1)}"

        if host == "iron-star.com" and path.startswith("/en/"):
            path = path[3:]

        normalized = urlunparse(
            (
                parsed.scheme.lower(),
                host,
                path.lower(),
                "",
                query,
                "",
            )
        )
        return f"{normalized}{preserve_fragment}"

    def _event_completeness_score(self, event: Event) -> int:
        return sum(
            1
            for value in (
                event.starts_at,
                event.date_text,
                event.city,
                event.region,
                event.venue,
                event.category,
                event.description,
                event.image_url,
            )
            if value
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
        normalized_city = re.sub(r"^\d+\s*,\s*", "", normalized_city).strip(" ,")
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
            "gatchina": "гатчина",
            "saint petersburg": "санкт-петербург",
            "st. petersburg": "санкт-петербург",
            "moscow": "москва",
            "perm": "пермь",
            "sochi": "сочи",
            "minsk": "минск",
            "vladivostok": "владивосток",
            "ивановская": "ивановская область",
            "приморский": "приморский край",
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
        normalized_event_region = self._normalize_location_name(event.region)

        if self._matches_location_group(event, normalized_selected):
            return True

        if normalized_event_region and normalized_event_region == normalized_selected:
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

        if any(token in normalized for token in ["триатлон", "дуатлон", "swimrun", "акватлон"]):
            return "Триатлон"
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
        if any(token in normalized for token in ["водный спорт", "sup", "сап", "греб", "каяк", "байдар"]):
            return "Плавание"
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
        if any(token in normalized for token in ["гонки с препятствиями", "ocr", "ниндзя", "obstacle"]):
            return "Другие"
        if any(token in normalized for token in ["фестиваль", "лагерь", "тур", "перезагрузка"]):
            return "Другие"
        if "скайран" in normalized:
            return "Бег"
        if any(
            token in normalized
            for token in ["детский спорт", "самокат", "беговел", "подвижные игры"]
        ):
            return "Детские старты"
        if normalized in {"другое", "другие"} or "другой вид" in normalized:
            return "Другие"

        return category.strip()

    def _apply_filters(self, events: list[Event], filters: EventFilters) -> list[Event]:
        filtered = events

        if filters.query:
            query = filters.query.casefold().strip()
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
                ).casefold()
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
