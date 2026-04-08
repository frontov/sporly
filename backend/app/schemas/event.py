from pydantic import BaseModel, HttpUrl


class Event(BaseModel):
    id: str
    title: str
    description: str | None = None
    series_slug: str | None = None
    series_name: str | None = None
    source_label: str | None = None
    source_type: str | None = None
    registration_status: str | None = None
    last_checked_at: str | None = None
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
    source_name: str
    source_url: HttpUrl | str
    image_url: HttpUrl | str | None = None


class EventsResponse(BaseModel):
    items: list[Event]
    is_loading: bool = False
    total: int
    total_regions: int
    total_categories: int
    page: int
    page_size: int
    total_pages: int
    available_cities: list[str]
    available_categories: list[str]
    available_sources: list[str]
