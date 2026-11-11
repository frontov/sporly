from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from urllib.parse import urlparse, urlunparse

import httpx

from app.parsers.base import (
    ArtaSportParser,
    ArfCalendarParser,
    BikeEventsParser,
    CyclingRaceParser,
    CssDirectoryParser,
    CityTrailParser,
    FbbrCalendarParser,
    FprCalendarParser,
    GaltropaParser,
    GetRunParser,
    GoldenUltraParser,
    GranFondoParser,
    GravelSeriesParser,
    GryadkaCampsParser,
    IronStarParser,
    NapCalendarParser,
    NbcEventsParser,
    RfwfCalendarParser,
    SpswProgramParser,
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
    WpcCalendarParser,
    WrpfCalendarParser,
    XCNewsParser,
)
from app.schemas.event import Event
from app.services.featured import FeaturedEntry, FeaturedEventStore
from app.settings import settings


logger = logging.getLogger(__name__)


REGISTRATION_MONTHS: dict[str, int] = {
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

REGISTRATION_DATE_TOKEN = (
    r"(\d{1,2}[./]\d{1,2}[./]\d{2,4}"
    r"|\d{1,2}\s+[а-яё]+(?:\s+\d{4})?)"
)


# Events from the combined "Ориентирование и туризм" source category are
# split by title: hiking, climbing, tourism and Nordic walking go to
# "Разное", the rest stays in "Ориентирование".
TOURISM_TITLE_MARKERS = (
    "туризм",
    "турист",
    "поход",
    "турслет",
    "турслёт",
    "маршрут",
    "экспедиц",
    "скалолаз",
    "скалодром",
    "альпинизм",
    "ледолаз",
    "ходьб",
    "северн",
    "скандинав",
)


_EVENT_ID_WITH_INDEX_RE = re.compile(
    r"^(?P<prefix>.+?)-(?P<index>\d+)-(?P<stable>[0-9a-f]{12})$"
)

# Tokens that are common enough to be added to an event title by one source
# without making it a different event (e.g. "Полумарафон «Бегущая Вологда»"
# vs "Бегущая Вологда").
GENERIC_TITLE_TOKENS: frozenset[str] = frozenset(
    {
        "чемпионат",
        "первенство",
        "кубок",
        "турнир",
        "соревнование",
        "соревнования",
        "фестиваль",
        "серия",
        "марафон",
        "полумарафон",
        "веломарафон",
        "забег",
        "пробег",
        "трейл",
        "гонка",
        "открытый",
        "открытая",
        "открытое",
        "всероссийский",
        "всероссийская",
        "всероссийское",
        "международный",
        "международная",
        "международное",
        "городской",
        "городская",
        "городское",
        "спортивный",
        "спортивная",
        "спортивное",
        "официальный",
        "annual",
        "race",
        "run",
        "running",
        "marathon",
        "half",
        "trail",
        "cup",
        "championship",
        "festival",
        "series",
        "event",
    }
)

# Extra words that mean the two cards are related but not the same start:
# a kids race, another distance, a stage, a relay, etc.
VARIANT_TITLE_MARKERS: tuple[str, ...] = (
    "дет",
    "kids",
    "child",
    "семейн",
    "family",
    "эстафет",
    "relay",
    "мил",
    "mile",
    "час",
    "hour",
    "групп",
    "group",
    "этап",
    "stage",
    "дистанц",
    "мужчин",
    "женщин",
    "юниор",
    "юнош",
    "девуш",
    "ветеран",
    "master",
)


@dataclass(slots=True)
class EventFilters:
    query: str | None = None
    cities: list[str] | None = None
    categories: list[str] | None = None
    featured_only: bool = False
    registration_status: str | None = None
    kids_only: bool = False
    surface_type: str | None = None
    difficulty_level: str | None = None
    source: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    first_seen_after: str | None = None
    sort_by: str | None = None


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


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
    SERIES_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("mvm", "МВМ", ("серия мвм 2026", " мвм", "velomarathon", "московорецкий гребной марафон")),
        ("tri_niti", "TRI NITI", ("tri niti", "tri_niti", "triniti", "tri nity", "tri niti cup")),
        ("open_band", "OPEN BAND", ("open band", "openband.run", "openband")),
        ("russialoppet", "RUSSIALOPPET", ("russialoppet", "руссиалоппет", "серия лыжных марафонов")),
        ("running_community", "RUNC", ("running community", "runc.run", "московский марафон", "беговое сообщество")),
        ("gryadka", "GRYADKA", ("gryadka", "грядка")),
    )
    OFFICIAL_SOURCE_NAMES: frozenset[str] = frozenset(
        {
            "Russia Running",
            "Russialoppet",
            "Running Community",
            "Marzocchi Cup",
            "TRI NITI CUP",
            "Golden Ultra",
            "IRONSTAR",
            "Gran Fondo",
            "Marathon Cup",
            "Galtropa",
            "Nezhesteam",
            "X-WATERS",
            "Swimcup",
            "La Strada",
            "City Trail",
            "Borisovo.cluB",
            "НАП Россия",
            "WPC/WPO",
            "ФТАР",
            "ФПР",
            "СПР/WRPF",
            "ФББР",
            "NBC",
            "Siberian Power Show",
            "Gryadka",
        }
    )
    REGISTRATION_SOURCE_NAMES: frozenset[str] = frozenset(
        {
            "REGPLACE",
            "Orgeo",
            "O-Time",
            "MyRace",
            "RaceTime",
            "Sportident",
        }
    )
    CALENDAR_SOURCE_NAMES: frozenset[str] = frozenset(
        {
            "Velogearance",
            "Velomarathon",
            "XCnews",
            "ARF",
            "Arta Sport",
            "CyclingRace",
        }
    )
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
            "долгопрудный",
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
            "новороссийск",
            "анапа",
            "геленджик",
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
        self._scheduler_task: asyncio.Task[None] | None = None
        self._featured_store = FeaturedEventStore(settings.featured_events_file)
        self._load_persistent_cache()

    async def get_events(self, filters: EventFilters) -> list[Event]:
        if not self._cache:
            self._ensure_background_refresh()
        elif self._is_cache_stale():
            self._ensure_background_refresh()
        active_events = [
            self._with_current_registration_status(event)
            for event in self._cache
            if event.status != "inactive"
        ]
        return self._apply_sort(
            self._apply_filters(active_events, filters), filters
        )

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
        events, _, _ = await self._collect_events_with_source_counts()
        return events

    async def _collect_events_with_source_counts(
        self,
    ) -> tuple[list[Event], dict[str, int], set[str]]:
        source_configs = self._load_source_configs(settings.sources_file)
        if not source_configs:
            return [], {}, set()

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
        source_counts: dict[str, int] = {}
        configured_sources = {config.name for config in source_configs}
        for source_config, result in zip(source_configs, results):
            if isinstance(result, Exception):
                source_counts[source_config.name] = 0
                continue
            source_counts[source_config.name] = len(result)
            collected.extend(result)

        return self._deduplicate(collected), source_counts, configured_sources

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

    async def _refresh_cache(self, force: bool = False) -> None:
        async with self._refresh_lock:
            if not force and self._cache and not self._is_cache_stale():
                return

            logger.info(
                "Refreshing catalog cache: %s cached events, force=%s",
                len(self._cache),
                force,
            )
            (
                collected_events,
                source_counts,
                configured_sources,
            ) = await self._collect_events_with_source_counts()
            if not collected_events:
                logger.warning("No events collected; retrying once in 5s")
                await asyncio.sleep(5)
                (
                    collected_events,
                    source_counts,
                    configured_sources,
                ) = await self._collect_events_with_source_counts()

            if not collected_events:
                logger.warning("Skipping catalog refresh: no events collected")
                return

            empty_sources = sorted(
                name
                for name in configured_sources
                if source_counts.get(name, 0) == 0
            )
            if empty_sources:
                logger.info(
                    "Sources with no events in this run: %s",
                    ", ".join(empty_sources),
                )

            normalized_events = self._deduplicate(
                self._normalize_events(collected_events)
            )
            active_cached_count = sum(
                1 for event in self._cache if event.status != "inactive"
            )
            if (
                active_cached_count
                and len(normalized_events)
                < active_cached_count * settings.minimum_refresh_ratio
            ):
                logger.warning(
                    "Collected %s fresh events vs %s active cached events; "
                    "proceeding with event-level merge",
                    len(normalized_events),
                    active_cached_count,
                )

            previous_count = len(self._cache)
            self._cache_created_at = time.time()
            checked_at = datetime.fromtimestamp(self._cache_created_at).isoformat()
            next_events = self._merge_refreshed_events(
                normalized_events,
                checked_at,
                source_counts,
            )
            next_events = self._deduplicate(next_events)
            next_events = self._apply_featured_flags(next_events)

            self._cache = next_events
            self._cache_version = settings.cache_version
            self._rebuild_filter_metadata()
            self._write_persistent_cache()
            active_count = sum(
                1 for event in next_events if event.status != "inactive"
            )
            logger.info(
                "Catalog cache refreshed: %s events "
                "(active=%s, inactive=%s, was=%s)",
                len(next_events),
                active_count,
                len(next_events) - active_count,
                previous_count,
            )

    def _ensure_background_refresh(self) -> None:
        if self._refresh_task and not self._refresh_task.done():
            return

        self._refresh_task = asyncio.create_task(self._run_background_refresh())

    async def _run_background_refresh(self) -> None:
        logger.info("Starting catalog cache refresh")
        try:
            await self._refresh_cache()
        except Exception:
            logger.exception("Catalog cache refresh failed")
        finally:
            self._refresh_task = None

    def start_refresh_scheduler(self) -> None:
        if not settings.refresh_scheduler_enabled:
            logger.info("Catalog refresh scheduler is disabled")
            return
        if self._scheduler_task and not self._scheduler_task.done():
            return
        self._scheduler_task = asyncio.create_task(self._run_refresh_scheduler())

    async def stop_refresh_scheduler(self) -> None:
        task = self._scheduler_task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            self._scheduler_task = None

    async def _run_refresh_scheduler(self) -> None:
        interval = max(int(settings.refresh_interval_seconds), 60)
        logger.info("Catalog refresh scheduler started (interval=%ss)", interval)
        try:
            try:
                if self._is_cache_stale():
                    await self._refresh_cache()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Initial scheduled catalog refresh failed")

            while True:
                await asyncio.sleep(interval)
                if self._refresh_lock.locked():
                    logger.info(
                        "Skipping scheduled refresh: another refresh is already running"
                    )
                    continue
                try:
                    await self._refresh_cache(force=True)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Scheduled catalog refresh failed")
        except asyncio.CancelledError:
            logger.info("Catalog refresh scheduler stopped")
            raise

    def _load_persistent_cache(self) -> None:
        cache_file = settings.cache_file
        if not cache_file.exists():
            return

        try:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            cache_version = int(payload.get("version", 0))
            if cache_version != settings.cache_version:
                return
            items = payload.get("items", [])
            created_at = payload.get("created_at", 0.0)
            self._cache = self._deduplicate(
                self._normalize_events(
                    [Event.model_validate(item) for item in items]
                )
            )
            self._cache_created_at = float(created_at)
            if self._cache_created_at:
                self._cache = self._apply_cache_metadata(self._cache, self._cache_created_at)
            self._cache = self._apply_featured_flags(self._cache)
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
        temp_file = cache_file.with_name(f"{cache_file.name}.tmp")
        try:
            temp_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temp_file, cache_file)
        finally:
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)

    def _merge_refreshed_events(
        self,
        fresh_events: list[Event],
        checked_at: str,
        source_counts: dict[str, int],
    ) -> list[Event]:
        previous = self._cache
        if not previous:
            return [
                event.model_copy(
                    update={
                        "first_seen_at": checked_at,
                        "last_seen_at": checked_at,
                        "last_checked_at": checked_at,
                        "miss_count": 0,
                        "status": "active",
                    }
                )
                for event in fresh_events
            ]

        threshold = max(settings.event_miss_threshold, 1)
        old_by_url: dict[tuple[str, str], Event] = {}
        old_by_signature: dict[tuple[str, str, str], Event] = {}
        old_by_title_date: dict[tuple[str, str, str], Event] = {}
        for event in previous:
            source_url = self._canonical_source_url(str(event.source_url))
            if source_url:
                old_by_url.setdefault((source_url, event.id), event)
            signature = self._semantic_dedupe_key(event)
            if signature:
                old_by_signature.setdefault(signature, event)
            title_date = self._title_date_key(event)
            if title_date:
                old_by_title_date.setdefault(title_date, event)

        fresh_keys = {
            (self._canonical_source_url(str(event.source_url)), event.id)
            for event in fresh_events
        }
        fresh_signatures = {
            signature
            for event in fresh_events
            if (signature := self._semantic_dedupe_key(event))
        }
        fresh_title_dates = {
            title_date
            for event in fresh_events
            if (title_date := self._title_date_key(event))
        }

        matched_old_ids: set[int] = set()
        merged: list[Event] = []

        for event in fresh_events:
            source_url = self._canonical_source_url(str(event.source_url))
            old = (
                old_by_url.get((source_url, event.id))
                if source_url
                else None
            )
            if old is None:
                signature = self._semantic_dedupe_key(event)
                if signature:
                    old = old_by_signature.get(signature)
            if old is None:
                title_date = self._title_date_key(event)
                if title_date:
                    old = old_by_title_date.get(title_date)
            if old is not None:
                matched_old_ids.add(id(old))

            merged.append(
                event.model_copy(
                    update={
                        "first_seen_at": (
                            old.first_seen_at
                            if old is not None and old.first_seen_at
                            else checked_at
                        ),
                        "last_seen_at": checked_at,
                        "last_checked_at": checked_at,
                        "miss_count": 0,
                        "status": "active",
                    }
                )
            )

        for event in previous:
            source_url = self._canonical_source_url(str(event.source_url))
            signature = self._semantic_dedupe_key(event)
            title_date = self._title_date_key(event)
            if (source_url, event.id) in fresh_keys or (
                signature is not None and signature in fresh_signatures
            ) or (title_date is not None and title_date in fresh_title_dates):
                matched_old_ids.add(id(event))
                continue

            if id(event) in matched_old_ids:
                continue

            if event.status == "inactive":
                merged.append(event)
                continue

            source_name = event.source_name or "UNKNOWN"
            if source_counts.get(source_name, 0) <= 0:
                merged.append(event)
                continue

            miss_count = (event.miss_count or 0) + 1
            status = "inactive" if miss_count >= threshold else "active"
            merged.append(
                event.model_copy(
                    update={"miss_count": miss_count, "status": status}
                )
            )

        return merged

    def _apply_featured_flags(self, events: list[Event]) -> list[Event]:
        updated: list[Event] = []
        for event in events:
            canonical_url = self._canonical_source_url(str(event.source_url))
            semantic_key = self._semantic_dedupe_key(event)
            entry = self._featured_store.match(
                event, canonical_url, semantic_key
            )
            if entry is None:
                updated.append(
                    event.model_copy(
                        update={
                            "is_featured": False,
                            "featured_label": None,
                            "featured_priority": 0,
                        }
                    )
                )
                continue
            updated.append(
                event.model_copy(
                    update={
                        "is_featured": True,
                        "featured_label": entry.label,
                        "featured_priority": entry.priority,
                    }
                )
            )
        return updated

    def find_cached_event(
        self,
        event_id: str | None = None,
        source_url: str | None = None,
    ) -> Event | None:
        canonical_url = (
            self._canonical_source_url(source_url) if source_url else ""
        )
        for event in self._cache:
            if event_id and event.id == event_id:
                return event
            if (
                canonical_url
                and self._canonical_source_url(str(event.source_url))
                == canonical_url
            ):
                return event
        return None

    def feature_event(
        self,
        *,
        event_id: str | None,
        source_url: str | None,
        label: str,
        priority: int,
        until: str | None,
        enabled: bool = True,
    ) -> tuple[FeaturedEntry, Event]:
        event = self.find_cached_event(event_id=event_id, source_url=source_url)
        if event is None:
            raise ValueError("event not found")

        canonical_url = self._canonical_source_url(str(event.source_url))
        semantic_key = self._semantic_dedupe_key(event)
        entry = self._featured_store.upsert(
            event,
            canonical_url,
            semantic_key,
            label=label,
            priority=priority,
            until=until or None,
            enabled=enabled,
        )
        self._cache = self._apply_featured_flags(self._cache)
        self._write_persistent_cache()
        featured_event = self.find_cached_event(event_id=event.id) or event
        return entry, featured_event

    def unfeature_event(self, entry_id: str) -> bool:
        if not self._featured_store.delete(entry_id):
            return False
        self._cache = self._apply_featured_flags(self._cache)
        self._write_persistent_cache()
        return True

    def list_featured(self) -> list[FeaturedEntry]:
        return self._featured_store.all()

    async def force_refresh(self) -> None:
        await self._refresh_cache(force=True)

    def cache_age_seconds(self) -> float | None:
        if not self._cache_created_at:
            return None
        return time.time() - self._cache_created_at

    def _rebuild_filter_metadata(self) -> None:
        active_events = [
            event for event in self._cache if event.status != "inactive"
        ]
        self._available_cities = self.build_available_cities(active_events)
        self._available_categories = sorted(
            {event.category for event in active_events if event.category}
        )
        self._available_sources = sorted(
            {event.source_name for event in active_events if event.source_name}
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
        if source_config.parser_type == "gryadka_camps":
            return GryadkaCampsParser(source_config)
        if source_config.parser_type == "getrun":
            return GetRunParser(source_config)
        if source_config.parser_type == "bike_events":
            return BikeEventsParser(source_config)
        if source_config.parser_type == "gravel_series":
            return GravelSeriesParser(source_config)
        if source_config.parser_type == "fpr_calendar":
            return FprCalendarParser(source_config)
        if source_config.parser_type == "rfwf_calendar":
            return RfwfCalendarParser(source_config)
        if source_config.parser_type == "nap_calendar":
            return NapCalendarParser(source_config)
        if source_config.parser_type == "wpc_calendar":
            return WpcCalendarParser(source_config)
        if source_config.parser_type == "wrpf_calendar":
            return WrpfCalendarParser(source_config)
        if source_config.parser_type == "fbbr_calendar":
            return FbbrCalendarParser(source_config)
        if source_config.parser_type == "nbc_events":
            return NbcEventsParser(source_config)
        if source_config.parser_type == "spsw_program":
            return SpswProgramParser(source_config)
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
        unique_by_key: dict[tuple[str, str], Event] = {}
        fallback_seen: set[str] = set()
        result: list[Event] = []
        for event in events:
            canonical_url = self._canonical_source_url(str(event.source_url))
            if canonical_url:
                key = (canonical_url, event.id)
                existing = unique_by_key.get(key)
                if existing is None or self._event_completeness_score(event) > self._event_completeness_score(existing):
                    unique_by_key[key] = event
                continue

            key = f"{event.title}|{event.starts_at}|{event.source_url}"
            if key in fallback_seen:
                continue
            fallback_seen.add(key)
            result.append(event)

        result.extend(unique_by_key.values())
        result = self._deduplicate_by_signature(result)
        result = self._deduplicate_related(result)
        result = self._deduplicate_same_source_near_dates(result)
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

    def _deduplicate_related(self, events: list[Event]) -> list[Event]:
        """Collapse obvious cross-source title variants.

        The strict signature above needs the titles to match exactly. Different
        sources often add a sponsor, a year, a generic word or an emoji. This
        pass only compares events from different sources, on the same date and
        in the same region, and refuses to merge titles that differ by a
        distance, stage, kids race, relay, etc.
        """

        removed: set[int] = set()
        buckets: dict[tuple[str, str], list[Event]] = {}

        for event in events:
            scope = self._dedupe_scope_key(event)
            if scope is None:
                continue

            bucket = buckets.setdefault(scope, [])
            match_index: int | None = None
            for index, existing in enumerate(bucket):
                if existing.source_name == event.source_name:
                    continue
                if self._titles_describe_same_event(
                    existing.title, event.title
                ):
                    match_index = index
                    break

            if match_index is None:
                bucket.append(event)
                continue

            existing = bucket[match_index]
            if self._should_replace_duplicate(existing, event):
                removed.add(id(existing))
                bucket[match_index] = event
            else:
                removed.add(id(event))

        if not removed:
            return events
        return [event for event in events if id(event) not in removed]

    def _deduplicate_same_source_near_dates(
        self,
        events: list[Event],
        *,
        source_name: str = "ФПР",
        window_days: int = 3,
    ) -> list[Event]:
        """Collapse split table rows from the FPR calendar.

        FPR publishes one competition as several rows (men/women, age groups,
        adjacent date ranges). The rows get different stable ids, so the regular
        URL/signature dedupe keeps them apart. Group by title, city and region,
        then merge dates within a few days.
        """

        passthrough: list[Event] = []
        buckets: dict[tuple[str, str, str], list[Event]] = {}

        for event in events:
            if event.source_name != source_name or not event.starts_at:
                passthrough.append(event)
                continue

            title = self._normalize_title_for_dedupe(event.title)
            if not title:
                passthrough.append(event)
                continue

            key = (
                title,
                self._normalize_location_name(event.city) or "",
                self._normalize_location_name(event.region) or "",
            )
            try:
                current_date = datetime.fromisoformat(event.starts_at)
            except ValueError:
                passthrough.append(event)
                continue

            bucket = buckets.setdefault(key, [])
            duplicate_index = None
            for index, existing in enumerate(bucket):
                if not existing.starts_at:
                    continue
                try:
                    existing_date = datetime.fromisoformat(existing.starts_at)
                except ValueError:
                    continue
                if abs((existing_date - current_date).total_seconds()) <= window_days * 86400:
                    duplicate_index = index
                    break

            if duplicate_index is None:
                bucket.append(event)
                continue

            existing = bucket[duplicate_index]
            existing_date = datetime.fromisoformat(existing.starts_at)
            if current_date < existing_date or (
                current_date == existing_date
                and self._event_completeness_score(event)
                > self._event_completeness_score(existing)
            ):
                bucket[duplicate_index] = event

        return [
            *passthrough,
            *(event for bucket in buckets.values() for event in bucket),
        ]

    def _dedupe_scope_key(self, event: Event) -> tuple[str, str] | None:
        normalized_date = (
            event.starts_at or self._parse_date_text(event.date_text) or ""
        )[:10]
        normalized_location = self._normalize_location_name(
            event.region
        ) or self._normalize_location_name(event.city)
        if not normalized_date or not normalized_location:
            return None
        return (normalized_date, normalized_location.casefold())

    def _titles_describe_same_event(
        self, first: str | None, second: str | None
    ) -> bool:
        first_tokens = set(
            self._normalize_title_for_dedupe(first).split()
        )
        second_tokens = set(
            self._normalize_title_for_dedupe(second).split()
        )
        if not first_tokens or not second_tokens:
            return False
        if first_tokens == second_tokens:
            return True

        if len(first_tokens) <= len(second_tokens):
            smaller, larger = first_tokens, second_tokens
        else:
            smaller, larger = second_tokens, first_tokens

        if not smaller < larger:
            return False

        # "Забег" / "Кубок" without any concrete token is too generic to merge.
        if not any(token not in GENERIC_TITLE_TOKENS for token in smaller):
            return False

        extra = larger - smaller
        if len(extra) > 3:
            return False

        for token in extra:
            if token in GENERIC_TITLE_TOKENS:
                continue
            if any(marker in token for marker in VARIANT_TITLE_MARKERS):
                return False
            if any(character.isdigit() for character in token):
                return False
        return True

    def _stabilize_event_id(self, event_id: str | None) -> str:
        if not event_id:
            return ""
        match = _EVENT_ID_WITH_INDEX_RE.match(str(event_id))
        if match is None:
            return str(event_id)
        return f"{match.group('prefix')}-{match.group('stable')}"

    def _title_date_key(self, event: Event) -> tuple[str, str, str] | None:
        title = self._normalize_title_for_dedupe(event.title)
        date = (event.starts_at or self._parse_date_text(event.date_text) or "")[:10]
        if not title or not date or not event.source_name:
            return None
        return (event.source_name, title, date)

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

        # "Бегущая Вологда (05.12-06.12)" and "... 17 мая 2026" are the same
        # race as "Бегущая Вологда" / "Галичское Заозерье".
        normalized = re.sub(
            r"\(\s*\d{1,2}[./-]\d{1,2}"
            r"(?:\s*[-–—]\s*\d{1,2}[./-]\d{1,2})?\s*\)",
            " ",
            normalized,
        )
        normalized = re.sub(
            r"\b\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|"
            r"июля|августа|сентября|октября|ноября|декабря)"
            r"(?:\s+20\d{2})?\b",
            " ",
            normalized,
        )

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

        # Strip quotes, emoji and other punctuation; keep letters/digits.
        normalized = re.sub(r"[^\w\s]+", " ", normalized)
        normalized = re.sub(r"\b(?:19|20)\d{2}\b", " ", normalized)
        normalized = re.sub(
            r"^\s*[ivxlcdmіх]+\s*(?:[-–—.:]\s*)?(?:й|я)?\s+",
            "",
            normalized,
        )
        # Stylised "МарафонЪ" from one source vs "Марафон" from another.
        normalized = re.sub(r"ъ\b", "", normalized)
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

    def _clean_public_source_url(self, source_url: str | None) -> str | None:
        if not source_url:
            return source_url
        value = str(source_url).strip()
        if not value:
            return source_url
        host = urlparse(value).netloc.lower()
        if host in {
            "fpr-info.ru",
            "www.fpr-info.ru",
            "russia-powerlifting.ru",
            "www.russia-powerlifting.ru",
        }:
            value = re.sub(r"#event-\d+$", "", value)
        return value

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
        elif host_with_fragment in {"city-trail.ru", "www.city-trail.ru", "stradarace.ru", "www.stradarace.ru", "myrace.info", "www.myrace.info"} and fragment_value:
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
                event.registration_status,
                event.registration_opens_at,
                event.registration_deadline,
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
        series_slug, series_name = self._detect_series(event)
        registration_opens_at = (
            event.registration_opens_at or self._extract_registration_opens_at(event)
        )
        registration_status = self._resolve_registration_status(
            event,
            event.registration_status or self._detect_registration_status(event),
            opens_at_value=registration_opens_at,
        )
        return event.model_copy(
            update={
                # The parser-level id used to contain the row index. That made
                # the same event change identity whenever a source reordered
                # its listing. Keep only source + stable URL hash from now on.
                "id": self._stabilize_event_id(event.id),
                "source_url": self._clean_public_source_url(event.source_url),
                "region": normalized_region,
                "city": self._normalize_city(event.city, normalized_region),
                "category": self._normalize_category(
                    event.category, title=event.title
                ),
                "starts_at": self._normalize_starts_at(event.date_text, event.starts_at),
                "series_slug": series_slug,
                "series_name": series_name,
                "source_label": event.source_label or self._build_source_label(event),
                "source_type": event.source_type or self._detect_source_type(event),
                "registration_status": registration_status,
                "registration_opens_at": registration_opens_at,
                "distance_summary": event.distance_summary or self._extract_distance_summary(event),
                "participation_format": event.participation_format or self._detect_participation_format(event),
                "kids_available": event.kids_available if event.kids_available is not None else self._detect_kids_available(event),
                "organizer_name": event.organizer_name or self._detect_organizer_name(event),
                "price_from": event.price_from or self._extract_price_from(event),
                "registration_deadline": event.registration_deadline or self._extract_registration_deadline(event),
                "slots_status": event.slots_status or self._detect_slots_status(event),
                "surface_type": event.surface_type or self._detect_surface_type(event),
                "difficulty_level": event.difficulty_level or self._detect_difficulty_level(event),
            }
        )

    def _apply_cache_metadata(self, events: list[Event], checked_at: float) -> list[Event]:
        checked_at_iso = datetime.fromtimestamp(checked_at).isoformat() if checked_at else None
        if not checked_at_iso:
            return events
        return [
            event.model_copy(
                update={
                    "last_checked_at": event.last_checked_at or checked_at_iso,
                    "first_seen_at": (
                        event.first_seen_at
                        or event.last_checked_at
                        or checked_at_iso
                    ),
                    "last_seen_at": (
                        event.last_seen_at
                        or event.last_checked_at
                        or checked_at_iso
                    ),
                    "miss_count": event.miss_count or 0,
                    "status": (
                        event.status
                        if event.status in {"active", "inactive"}
                        else "active"
                    ),
                }
            )
            for event in events
        ]

    def _detect_series(self, event: Event) -> tuple[str | None, str | None]:
        # Strip the fragment: it can hold a disambiguation slug (e.g. Galtropa's
        # page slug) that isn't part of the event's real identity and shouldn't
        # be matched against series keywords.
        source_url_without_fragment = str(event.source_url).split("#", 1)[0]
        haystack = " ".join(
            part
            for part in [
                event.title,
                event.description,
                source_url_without_fragment,
                event.source_name,
            ]
            if part
        ).casefold()
        for slug, name, markers in self.SERIES_DEFINITIONS:
            if any(marker in haystack for marker in markers):
                return slug, name
        return None, None

    def _build_source_label(self, event: Event) -> str:
        return event.source_name

    def _detect_source_type(self, event: Event) -> str:
        source_name = (event.source_name or "").strip()
        source_url = str(event.source_url).casefold()
        if source_name in self.OFFICIAL_SOURCE_NAMES:
            return "official"
        if source_name in self.REGISTRATION_SOURCE_NAMES:
            return "registration"
        if source_name in self.CALENDAR_SOURCE_NAMES:
            return "calendar"
        if any(marker in source_url for marker in ("reg.", "/event/", "/entry/", "/race/")):
            return "registration"
        return "official"

    def _detect_registration_status(self, event: Event, now: datetime | None = None) -> str | None:
        haystack = " ".join(
            part
            for part in (
                event.title,
                event.description,
                str(event.source_url),
            )
            if part
        ).casefold()

        closed_markers = (
            "регистрация закрыта",
            "registration closed",
            "мест нет",
            "sold out",
            "слоты законч",
            "регистрация завершена",
            "заявки не принимаются",
            "регистрация недоступна",
        )
        upcoming_markers = (
            "регистрация еще не открыта",
            "регистрация ещё не открыта",
            "регистрация не открыта",
            "регистрация скоро откроется",
            "регистрация откроется",
            "регистрация начнется",
            "регистрация начнётся",
            "открытие регистрации",
            "скоро открытие",
            "прием заявок откроется",
            "приём заявок откроется",
            "заявка откроется",
            "заявки откроются",
            "registration opens",
            "registration not open",
            "not yet open",
            "coming soon",
        )
        open_markers = (
            "регистрация открыта",
            "online регистрация",
            "онлайн регистрация",
            "open registration",
            "зарегистрироваться",
            "открыта регистрация",
        )
        waitlist_markers = (
            "лист ожидания",
            "waiting list",
            "предзапись",
        )

        if any(marker in haystack for marker in closed_markers):
            return "closed"

        window_status = self._registration_window_status(event, now=now)
        if window_status:
            return window_status

        if any(marker in haystack for marker in waitlist_markers):
            return "limited"
        if any(marker in haystack for marker in upcoming_markers):
            return "upcoming"
        if any(marker in haystack for marker in open_markers):
            return "open"
        return None

    def _with_current_registration_status(self, event: Event) -> Event:
        status = self._resolve_registration_status(event, event.registration_status)
        if status == event.registration_status:
            return event
        return event.model_copy(update={"registration_status": status})

    def _resolve_registration_status(
        self,
        event: Event,
        status: str | None,
        now: datetime | None = None,
        opens_at_value: str | None = None,
    ) -> str | None:
        now = now or datetime.now()
        base_status = (status or "").casefold() or None
        opens_at = self._parse_registration_datetime(
            opens_at_value or event.registration_opens_at
        )
        deadline = self._parse_registration_datetime(
            event.registration_deadline, end_of_day=True
        )

        if base_status == "closed":
            return "closed"
        if deadline is not None and now > deadline:
            return "closed"
        if opens_at is not None and now < opens_at:
            return "upcoming"
        if base_status == "upcoming":
            if opens_at is not None:
                return "open"
            if deadline is None and self._event_already_started(event, now):
                return "closed"
            return "upcoming"
        if base_status in {"open", "limited"}:
            if deadline is None and self._event_already_started(event, now):
                return "closed"
            return base_status
        if deadline is not None:
            return "open"
        if opens_at is not None:
            return "open"
        window_status = self._registration_window_status(event, now=now)
        if window_status:
            return window_status
        return base_status

    def _event_already_started(self, event: Event, now: datetime) -> bool:
        starts_at = _parse_iso_datetime(event.starts_at)
        return starts_at is not None and now.date() > starts_at.date()

    def _registration_window_status(
        self,
        event: Event,
        now: datetime | None = None,
    ) -> str | None:
        start, end, _ = self._match_registration_window(event)
        if start is None and end is None:
            return None
        now = now or datetime.now()
        if start is not None and now < start:
            return "upcoming"
        if end is not None and now > end:
            return "closed"
        if end is not None:
            return "open"
        return None

    def _match_registration_window(
        self,
        event: Event,
    ) -> tuple[datetime | None, datetime | None, str | None]:
        text = " ".join(
            part for part in (event.title, event.description) if part
        )
        if not text:
            return None, None, None

        match = re.search(
            r"(?:регистрац[а-яё]*|при[её]м\s+заявок|заявк[а-яё]*)"
            r"[^.!?\n]{0,30}?\s+с\s+" + REGISTRATION_DATE_TOKEN +
            r"\s+(?:по|до)\s+" + REGISTRATION_DATE_TOKEN,
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return None, None, None

        start = self._parse_registration_datetime(match.group(1))
        end = self._parse_registration_datetime(match.group(2), end_of_day=True)
        if start is None and end is None:
            return None, None, None
        return start, end, match.group(2)

    def _extract_registration_opens_at(self, event: Event) -> str | None:
        window_start, _, _ = self._match_registration_window(event)
        if window_start is not None:
            return window_start.isoformat()

        text = " ".join(
            part for part in (event.title, event.description) if part
        )
        if not text:
            return None

        match = re.search(
            r"(?:регистрац[а-яё]*|при[её]м\s+заявок|заявк[а-яё]*)"
            r"[^.!?\n]{0,40}?"
            r"(?:откро[а-яё]*|открытие|начн[а-яё]*|старту[а-яё]*)"
            r"[^.!?\n]{0,30}?" + REGISTRATION_DATE_TOKEN,
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        opens_at = self._parse_registration_datetime(match.group(1))
        return opens_at.isoformat() if opens_at is not None else None

    def _parse_registration_datetime(
        self,
        value: str | None,
        *,
        end_of_day: bool = False,
    ) -> datetime | None:
        if not value:
            return None

        text = re.sub(
            r"\s+", " ", value.replace("\xa0", " ").replace("ё", "е")
        ).strip().casefold()
        if not text:
            return None

        iso_candidate = text.removeprefix("до ").strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[t ]\d{2}:\d{2}(?::\d{2})?)?", iso_candidate):
            try:
                parsed = datetime.fromisoformat(iso_candidate.replace(" ", "T"))
            except ValueError:
                parsed = None
            if parsed is not None:
                return parsed

        text = re.sub(r"^(?:до|с|по)\s+", "", text).strip()
        has_time = False

        dot_match = re.search(
            r"(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?"
            r"(?:\s+(\d{1,2}):(\d{2}))?",
            text,
        )
        if dot_match:
            day = int(dot_match.group(1))
            month = int(dot_match.group(2))
            year_raw = dot_match.group(3)
            year = int(year_raw) if year_raw else datetime.now().year
            if year < 100:
                year += 2000
            hour = int(dot_match.group(4)) if dot_match.group(4) else 0
            minute = int(dot_match.group(5)) if dot_match.group(5) else 0
            has_time = dot_match.group(4) is not None
        else:
            month_match = re.search(
                r"(\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?"
                r"(?:\s+(\d{1,2}):(\d{2}))?",
                text,
            )
            month = REGISTRATION_MONTHS.get(month_match.group(2)) if month_match else None
            if month_match is None or month is None:
                return None
            day = int(month_match.group(1))
            year = int(month_match.group(3)) if month_match.group(3) else datetime.now().year
            hour = int(month_match.group(4)) if month_match.group(4) else 0
            minute = int(month_match.group(5)) if month_match.group(5) else 0
            has_time = month_match.group(4) is not None

        if end_of_day and not has_time:
            hour, minute = 23, 59
        try:
            return datetime(year, month, day, hour, minute)
        except ValueError:
            return None


    def _extract_distance_summary(self, event: Event) -> str | None:
        text = " ".join(
            part
            for part in (
                event.title,
                event.description,
            )
            if part
        )
        if not text:
            return None

        distances: list[str] = []
        group_match = re.search(
            r"(\d+(?:[.,]\d+)?(?:\s*(?:/|и|-|•|;|,\s+)\s*\d+(?:[.,]\d+)?)+)\s*(км|km)\b",
            text,
            flags=re.IGNORECASE,
        )
        if group_match:
            for value in re.findall(r"\d+(?:[.,]\d+)?", group_match.group(1)):
                normalized = self._normalize_distance_value(value)
                label = f"{normalized} км"
                if normalized and label not in distances:
                    distances.append(label)

        km_matches = re.findall(r"(\d+(?:[.,]\d+)?)\s*(км|km)\b", text, flags=re.IGNORECASE)
        meter_matches = re.findall(r"(\d{3,5})\s*(м)\b", text, flags=re.IGNORECASE)

        for value, _unit in km_matches:
            normalized = self._normalize_distance_value(value)
            label = f"{normalized} км"
            if label not in distances:
                distances.append(label)

        for value, _unit in meter_matches:
            meters = int(value)
            if meters >= 1000 and f"{meters} м" not in distances:
                distances.append(f"{meters} м")

        if not distances:
            return None
        return " • ".join(distances)

    def _normalize_distance_value(self, value: str) -> str:
        cleaned = value.strip().replace(",", ".")
        if cleaned.endswith(".0"):
            cleaned = cleaned[:-2]
        return cleaned

    def _detect_participation_format(self, event: Event) -> str | None:
        haystack = " ".join(
            part
            for part in (
                event.title,
                event.description,
            )
            if part
        ).casefold()
        if not haystack:
            return None

        if any(marker in haystack for marker in ("эстафет", "relay")):
            return "Эстафета"
        if any(marker in haystack for marker in ("команд", "team")):
            return "Командный"
        if any(marker in haystack for marker in ("семейн", "family")):
            return "Семейный"
        if any(marker in haystack for marker in ("индивиду", "личный зачет", "личный зачёт")):
            return "Индивидуальный"
        return None

    def _detect_kids_available(self, event: Event) -> bool | None:
        haystack = " ".join(
            part
            for part in (
                event.title,
                event.description,
                event.category,
            )
            if part
        ).casefold()
        if not haystack:
            return None
        if any(marker in haystack for marker in ("детск", "kids", "family", "семейн")):
            return True
        if event.category and event.category.casefold() == "детские старты":
            return True
        return None

    def _detect_organizer_name(self, event: Event) -> str | None:
        description = (event.description or "").strip()
        if " • " in description:
            first_part = description.split(" • ", 1)[0].strip()
            if first_part and len(first_part) > 2 and not re.search(r"\d", first_part):
                return first_part

        if event.series_name:
            return event.series_name

        source_name = (event.source_name or "").strip()
        if source_name in self.OFFICIAL_SOURCE_NAMES:
            return source_name
        return None

    def _extract_price_from(self, event: Event) -> str | None:
        text = " ".join(
            part
            for part in (
                event.title,
                event.description,
            )
            if part
        )
        if not text:
            return None

        prices: list[int] = []
        for match in re.finditer(r"(?:от\s*)?(\d[\d\s]{2,6})\s*(?:₽|руб\.?|рублей)", text, flags=re.IGNORECASE):
            raw = re.sub(r"\s+", "", match.group(1))
            try:
                value = int(raw)
            except ValueError:
                continue
            if 100 <= value <= 200000:
                prices.append(value)

        if not prices:
            return None
        return f"от {min(prices)} ₽"

    def _extract_registration_deadline(self, event: Event) -> str | None:
        text = " ".join(
            part
            for part in (
                event.title,
                event.description,
            )
            if part
        )
        if not text:
            return None

        _, window_end, window_end_raw = self._match_registration_window(event)
        if window_end is not None and window_end_raw:
            return f"до {window_end_raw}"

        numeric_match = re.search(
            r"(?:до|deadline|регистрация до)\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
            text,
            flags=re.IGNORECASE,
        )
        if numeric_match:
            return f"до {numeric_match.group(1)}"

        month_match = re.search(
            r"(?:до|deadline|регистрация до)\s+(\d{1,2}\s+[а-яё]+(?:\s+\d{4})?)",
            text,
            flags=re.IGNORECASE,
        )
        if month_match:
            return f"до {month_match.group(1)}"

        return None

    def _detect_slots_status(self, event: Event) -> str | None:
        text = " ".join(
            part
            for part in (
                event.title,
                event.description,
            )
            if part
        ).casefold()
        if not text:
            return None

        if any(marker in text for marker in ("мест нет", "sold out", "слоты законч", "нет слотов")):
            return "Нет мест"
        if any(marker in text for marker in ("лист ожидания", "waiting list")):
            return "Лист ожидания"

        slots_match = re.search(r"остал(?:ось|ось)\s+(\d+)\s+(?:мест|слотов)", text)
        if slots_match:
            return f"Осталось {slots_match.group(1)} мест"

        if event.registration_status == "open":
            return "Слоты доступны"
        return None

    def _detect_surface_type(self, event: Event) -> str | None:
        haystack = " ".join(
            part
            for part in (
                event.title,
                event.description,
                event.category,
                event.venue,
            )
            if part
        ).casefold()
        if not haystack:
            return None

        if any(token in haystack for token in ("открытая вода", "open water", "заплыв", "озеро", "река", "море")):
            return "Открытая вода"
        if any(token in haystack for token in ("асфальт", "шоссе", "road", "критериум")):
            return "Асфальт"
        if any(token in haystack for token in ("грейвел", "gravel")):
            return "Грейвел"
        if any(token in haystack for token in ("mtb", "кросс-кантри", "лесн", "трейл", "trail", "пересеч", "бездорож", "офф-роуд", "offroad", "грунт")):
            return "Грунт / трейл"
        if any(token in haystack for token in ("лыжероллер", "роллер")):
            return "Роллерная трасса"
        if any(token in haystack for token in ("лыж", "снег")):
            return "Снежная трасса"
        if any(token in haystack for token in ("городск", "парк", "набереж")):
            return "Городская трасса"
        return None

    def _detect_difficulty_level(self, event: Event) -> str | None:
        haystack = " ".join(
            part
            for part in (
                event.title,
                event.description,
                event.category,
            )
            if part
        ).casefold()
        if not haystack:
            return None

        if any(token in haystack for token in ("для опытных", "профи", "элит", "сложн", "ультра", "горн", "технич")):
            return "Высокая сложность"
        if any(token in haystack for token in ("для начинающих", "нович", "семейн", "детск", "спринт", "короткая")):
            return "Подойдёт новичкам"
        if any(token in haystack for token in ("пересечённая местность", "пересеченная местность", "trail", "трейл", "mtb")):
            return "Средняя сложность"
        return None

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

    def _normalize_category(
        self, category: str | None, *, title: str | None = None
    ) -> str | None:
        """Map any source category to one of the public catalog sections.

        Sources use very different labels ("Пауэрлифтинг", "ARDF, радиоспорт",
        "Детские старты", "Фастпакинг"). The public UI exposes a short, stable
        list of sections; everything without a matching section goes to
        "Разное". The combined "Ориентирование и туризм" category is split by
        title: tourism, hiking, climbing and Nordic walking go to "Разное".
        """

        if not category:
            return None

        normalized = category.strip().casefold()
        if not normalized:
            return None

        if "гто" in normalized or "вфск" in normalized:
            return "ГТО"
        if any(
            token in normalized
            for token in [
                "силов",
                "пауэрлифтинг",
                "powerlifting",
                "тяжелая атлетика",
                "тяжёлая атлетика",
                "weightlifting",
                "бодибилдинг",
                "bodybuilding",
                "кроссфит",
                "crossfit",
                "гирев",
                "kettlebell",
                "стронгмен",
                "strongman",
                "армлифтинг",
                "стритлифтинг",
                "пауэрспорт",
                "становая тяга",
                "становой тяге",
                "приседан",
                "бицепс",
                "логлифт",
                "hip thrust",
                "хип-траст",
            ]
        ) or re.search(r"\bжим\b", normalized):
            return "Силовые виды"
        if any(token in normalized for token in ["триатлон", "дуатлон", "swimrun", "акватлон"]):
            return "Триатлон"
        if any(token in normalized for token in ["вело", "велогон", "gravel", "bmx"]):
            return "Велоспорт"
        if "скайсноу" in normalized:
            return "Разное"
        if any(
            token in normalized
            for token in ["лыж", "ski", "биатлон", "snow"]
        ):
            return "Лыжи"
        if any(
            token in normalized
            for token in [
                "ходьба",
                "nordic walking",
                "спортивная ходьба",
                "скандинав",
            ]
        ):
            return "Разное"
        if any(
            token in normalized
            for token in [
                "бег",
                "trail",
                "трейл",
                "кросс",
                "полумарафон",
                "марафон",
                "экиден",
                "ekiden",
                "скайран",
            ]
        ):
            return "Бег"
        if any(
            token in normalized
            for token in [
                "плав",
                "swim",
                "водный спорт",
                "sup",
                "сап",
                "греб",
                "каяк",
                "байдар",
            ]
        ):
            return "Плавание"
        if (
            "ориентирование" in normalized
            or "рогейн" in normalized
            or "rogaine" in normalized
        ):
            title_text = (title or "").casefold()
            if title and any(
                marker in title_text for marker in TOURISM_TITLE_MARKERS
            ):
                return "Разное"
            return "Ориентирование"

        return "Разное"

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
                normalized.lower()
                for category in filters.categories
                if category.strip()
                and (normalized := self._normalize_category(category))
            }
            filtered = [
                event
                for event in filtered
                if (event.category or "").lower() in selected_categories
            ]

        if filters.featured_only:
            filtered = [
                event for event in filtered if event.is_featured
            ]

        if filters.registration_status:
            status = filters.registration_status.casefold().strip()
            filtered = [
                event
                for event in filtered
                if (event.registration_status or "").casefold() == status
            ]

        if filters.kids_only:
            filtered = [
                event
                for event in filtered
                if event.kids_available is True
            ]

        if filters.surface_type:
            surface = filters.surface_type.casefold().strip()
            filtered = [
                event
                for event in filtered
                if (event.surface_type or "").casefold() == surface
            ]

        if filters.difficulty_level:
            difficulty = filters.difficulty_level.casefold().strip()
            filtered = [
                event
                for event in filtered
                if (event.difficulty_level or "").casefold() == difficulty
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

        if filters.first_seen_after:
            cutoff = _parse_iso_datetime(filters.first_seen_after)
            if cutoff is not None:
                filtered = [
                    event
                    for event in filtered
                    if (seen_at := _parse_iso_datetime(event.first_seen_at))
                    is not None
                    and seen_at >= cutoff
                ]

        return filtered

    def _apply_sort(self, events: list[Event], filters: EventFilters) -> list[Event]:
        sort_by = filters.sort_by or "date_asc"
        reverse = sort_by == "date_desc"

        def date_key(item: Event) -> tuple[bool, str, str]:
            return (
                item.starts_at is None,
                item.starts_at or "",
                item.title.lower(),
            )

        featured = [event for event in events if event.is_featured]
        regular = [event for event in events if not event.is_featured]
        featured.sort(key=date_key, reverse=reverse)
        featured.sort(key=lambda event: -(event.featured_priority or 0))
        regular.sort(key=date_key, reverse=reverse)
        return [*featured, *regular]
