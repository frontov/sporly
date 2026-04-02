from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from app.schemas.event import EventsResponse
from app.services.catalog import CatalogService, EventFilters
from app.settings import settings


app = FastAPI(
    title="Sports Events Aggregator",
    version="0.1.0",
    description="Unified catalog of sports events collected from scraped websites.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

catalog_service = CatalogService()


@app.get("/api/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/events", response_model=EventsResponse)
async def list_events(
    q: str | None = None,
    city: list[str] | None = Query(default=None),
    category: list[str] | None = Query(default=None),
    source: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str | None = None,
    page: int = 1,
    page_size: int = 24,
) -> EventsResponse:
    all_events = await catalog_service.get_events(filters=EventFilters())
    filters = EventFilters(
        query=q,
        cities=city,
        categories=category,
        source=source,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
    )
    events = await catalog_service.get_events(filters=filters)
    safe_page_size = min(max(page_size, 1), 60)
    total = len(events)
    total_pages = max((total + safe_page_size - 1) // safe_page_size, 1)
    safe_page = min(max(page, 1), total_pages)
    start = (safe_page - 1) * safe_page_size
    end = start + safe_page_size
    paged_events = events[start:end]
    is_loading = catalog_service.is_loading()
    return EventsResponse(
        items=paged_events,
        is_loading=is_loading,
        total=total,
        total_regions=len({event.region for event in events if event.region}),
        total_categories=len({event.category for event in events if event.category}),
        page=safe_page,
        page_size=safe_page_size,
        total_pages=total_pages,
        available_cities=catalog_service.build_available_cities(all_events),
        available_categories=sorted({event.category for event in all_events if event.category}),
        available_sources=sorted({event.source_name for event in all_events if event.source_name}),
    )
