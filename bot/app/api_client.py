from __future__ import annotations

from dataclasses import dataclass, field

import httpx
from pydantic import BaseModel

from app.config import settings


class EventItem(BaseModel):
    id: str
    title: str
    description: str | None = None
    city: str | None = None
    region: str | None = None
    venue: str | None = None
    category: str | None = None
    date_text: str | None = None
    starts_at: str | None = None
    price_from: str | None = None
    registration_status: str | None = None
    source_name: str
    source_url: str


class EventsPage(BaseModel):
    items: list[EventItem]
    total: int
    page: int
    total_pages: int
    available_cities: list[str]
    available_categories: list[str]


@dataclass(slots=True)
class EventQuery:
    query: str | None = None
    cities: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    date_from: str | None = None
    sort_by: str | None = "date_asc"
    page: int = 1
    page_size: int = 8


class ApiClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.api_base_url,
            timeout=settings.request_timeout_seconds,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def get_events(self, query: EventQuery) -> EventsPage:
        params: list[tuple[str, str]] = []
        if query.query:
            params.append(("q", query.query))
        for city in query.cities:
            params.append(("city", city))
        for category in query.categories:
            params.append(("category", category))
        if query.date_from:
            params.append(("date_from", query.date_from))
        if query.sort_by:
            params.append(("sort_by", query.sort_by))
        params.append(("page", str(query.page)))
        params.append(("page_size", str(query.page_size)))

        response = await self._client.get("/api/events", params=params)
        response.raise_for_status()
        return EventsPage.model_validate(response.json())

    async def get_filter_options(self) -> tuple[list[str], list[str]]:
        page = await self.get_events(EventQuery(page=1, page_size=1))
        return page.available_cities, page.available_categories

    async def admin_status(self) -> dict:
        response = await self._client.get(
            "/api/admin/status",
            headers={"X-Admin-Token": settings.admin_token},
        )
        response.raise_for_status()
        return response.json()

    async def admin_refresh(self) -> dict:
        response = await self._client.post(
            "/api/admin/refresh",
            headers={"X-Admin-Token": settings.admin_token},
        )
        response.raise_for_status()
        return response.json()


api_client = ApiClient()
