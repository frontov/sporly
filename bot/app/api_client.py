from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.text import local_today


logger = logging.getLogger(__name__)


def join_location(city: str | None, region: str | None) -> str:
    city = (city or "").strip()
    region = (region or "").strip()
    if city and region:
        if region.casefold() in city.casefold():
            return city
        if city.casefold() in region.casefold():
            return region
    return ", ".join(part for part in (city, region) if part)


class Event(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    description: str | None = None
    series_slug: str | None = None
    series_name: str | None = None
    source_label: str | None = None
    source_type: str | None = None
    registration_status: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    distance_summary: str | None = None
    participation_format: str | None = None
    kids_available: bool | None = None
    organizer_name: str | None = None
    price_from: str | None = None
    registration_deadline: str | None = None
    slots_status: str | None = None
    surface_type: str | None = None
    difficulty_level: str | None = None
    city: str | None = None
    region: str | None = None
    federal_district: str | None = None
    venue: str | None = None
    category: str | None = None
    date_text: str | None = None
    starts_at: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    image_url: str | None = None

    @property
    def location(self) -> str:
        return join_location(self.city, self.region)

    def ref_payload(self) -> dict[str, Any]:
        data = self.model_dump()
        data["event_id"] = self.id
        return data


class EventsPage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[Event] = Field(default_factory=list)
    is_loading: bool = False
    total: int = 0
    total_regions: int = 0
    total_categories: int = 0
    page: int = 1
    page_size: int = 24
    total_pages: int = 1
    available_cities: list[str] = Field(default_factory=list)
    available_categories: list[str] = Field(default_factory=list)
    available_sources: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class EventQuery:
    query: str | None = None
    cities: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    date_from: str | None = None
    first_seen_after: str | None = None
    page: int = 1
    page_size: int = 4
    sort_by: str = "date_asc"

    def params(self) -> list[tuple[str, str]]:
        params: list[tuple[str, str]] = [
            ("page", str(self.page)),
            ("page_size", str(self.page_size)),
            ("sort_by", self.sort_by),
        ]
        if self.query:
            params.append(("q", self.query))
        for city in self.cities:
            params.append(("city", city))
        for category in self.categories:
            params.append(("category", category))
        if self.date_from:
            params.append(("date_from", self.date_from))
        if self.first_seen_after:
            params.append(("first_seen_after", self.first_seen_after))
        return params

    def cache_key(self) -> str:
        return repr(self.params())


class ApiClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.api_base_url.rstrip("/"),
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": "SporlyTelegramBot/1.0"},
        )
        self._cache: dict[str, tuple[float, EventsPage]] = {}
        self._options: tuple[float, list[str], list[str]] | None = None

    async def close(self) -> None:
        await self._client.aclose()

    async def get_events(self, query: EventQuery) -> EventsPage:
        key = query.cache_key()
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached is not None and cached[0] > now:
            return cached[1]

        response = await self._client.get("/api/events", params=query.params())
        response.raise_for_status()
        page = EventsPage.model_validate(response.json())
        self._cache[key] = (now + settings.api_cache_ttl_seconds, page)

        # Keep the cache bounded: it is only a short-lived helper for the
        # notification fan-out, not a second source of truth.
        if len(self._cache) > 250:
            for stale_key in sorted(
                self._cache, key=lambda item: self._cache[item][0]
            )[:100]:
                self._cache.pop(stale_key, None)
        return page

    async def get_filter_options(self, *, force: bool = False) -> tuple[list[str], list[str]]:
        now = time.monotonic()
        if not force and self._options and self._options[0] > now:
            return self._options[1], self._options[2]

        try:
            page = await self.get_events(EventQuery(page=1, page_size=1))
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("Cannot load filter options: %s", error)
            if self._options:
                return self._options[1], self._options[2]
            return [], []

        cities = sorted(
            {city for city in page.available_cities if city and city.strip()},
            key=lambda value: value.casefold(),
        )
        categories = sorted(
            {category for category in page.available_categories if category and category.strip()},
            key=lambda value: value.casefold(),
        )
        self._options = (now + settings.filter_cache_ttl_seconds, cities, categories)
        return cities, categories

    async def health(self) -> dict[str, Any]:
        response = await self._client.get("/api/health")
        response.raise_for_status()
        return response.json()

    async def total_events(self) -> tuple[int, bool]:
        page = await self.get_events(EventQuery(page=1, page_size=1))
        return page.total, page.is_loading

    def clear_cache(self) -> None:
        self._cache.clear()
        self._options = None


def today_iso() -> str:
    return local_today().isoformat()


api_client = ApiClient()
