from datetime import datetime
from html import escape
import json

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response

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
app.add_middleware(GZipMiddleware, minimum_size=500)

catalog_service = CatalogService()

CYRILLIC_TO_LATIN = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def _format_seo_date(starts_at: str | None, fallback: str | None) -> str:
    if not starts_at:
        return fallback or "Дата уточняется"
    try:
        parsed = datetime.fromisoformat(starts_at)
    except ValueError:
        return fallback or starts_at
    return parsed.strftime("%d.%m.%Y")


def _seo_location(event: object) -> str:
    city = getattr(event, "city", None)
    region = getattr(event, "region", None)
    venue = getattr(event, "venue", None)
    if city and region:
        return f"{city}, {region}"
    if city:
        return city
    if venue and region:
        return f"{venue}, {region}"
    if venue:
        return venue
    if region:
        return region
    return "Локация уточняется"


def _slugify_text(value: str) -> str:
    transliterated = "".join(
        CYRILLIC_TO_LATIN.get(char, char) for char in value.casefold()
    )
    normalized = "".join(
        char if char.isalnum() else "-" for char in transliterated
    )
    return "-".join(part for part in normalized.split("-") if part)


def _resolve_slug(slug: str, values: list[str]) -> str | None:
    for value in values:
        if _slugify_text(value) == slug:
            return value
    return None


def _is_pure_region_option(value: str) -> bool:
    normalized = value.strip()
    if not normalized or "," in normalized or " и " in normalized:
        return False
    return (
        normalized.endswith("область")
        or normalized.endswith("край")
        or normalized.endswith("республика")
        or normalized.endswith("автономный округ")
        or normalized in {"Москва", "Санкт-Петербург", "Севастополь"}
    )


def _extract_numeric_price(price: str | None) -> int | None:
    if not price:
        return None
    digits = "".join(char for char in price if char.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _schema_availability(registration_status: str | None) -> str | None:
    if registration_status == "open":
        return "https://schema.org/InStock"
    if registration_status == "limited":
        return "https://schema.org/LimitedAvailability"
    if registration_status == "closed":
        return "https://schema.org/SoldOut"
    return None


def _build_event_schema(event: object) -> dict[str, object]:
    location_name = _seo_location(event)
    schema_event: dict[str, object] = {
        "@type": "Event",
        "name": event.title,
        "description": event.description or event.title,
        "startDate": event.starts_at or event.date_text,
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "eventStatus": "https://schema.org/EventScheduled",
        "inLanguage": "ru-RU",
        "url": str(event.source_url),
        "keywords": ", ".join(
            part for part in (event.category, event.series_name, event.surface_type) if part
        ),
        "location": {
            "@type": "Place",
            "name": location_name,
            "address": {
                "@type": "PostalAddress",
                "addressLocality": event.city or event.venue or location_name,
                "addressRegion": event.region or event.city or location_name,
                "addressCountry": "RU",
            },
        },
        "organizer": {
            "@type": "Organization",
            "name": event.organizer_name or event.source_name,
            "url": str(event.source_url),
        },
    }

    if event.image_url:
        schema_event["image"] = [event.image_url]

    price_value = _extract_numeric_price(event.price_from)
    availability = _schema_availability(event.registration_status)
    if (
        price_value is not None
        or availability is not None
        or event.registration_deadline
    ):
        offer: dict[str, object] = {
            "@type": "Offer",
            "url": str(event.source_url),
            "priceCurrency": "RUB",
        }
        if price_value is not None:
            offer["price"] = price_value
        if availability is not None:
            offer["availability"] = availability
        if event.registration_deadline:
            offer["validThrough"] = event.registration_deadline.removeprefix("до ").strip()
        schema_event["offers"] = offer

    if price_value == 0:
        schema_event["isAccessibleForFree"] = True

    return schema_event


def _build_sitemap_xml(regions: list[str], categories: list[str]) -> str:
    urls = [
        ("https://sporly.ru/", "daily", "1.0"),
    ]

    for region in regions:
        urls.append(
            (
                f"https://sporly.ru/seo/region/{_slugify_text(region)}",
                "daily",
                "0.8",
            )
        )

    for category in categories:
        urls.append(
            (
                f"https://sporly.ru/seo/sport/{_slugify_text(category)}",
                "daily",
                "0.8",
            )
        )

    body = "".join(
        f"""
  <url>
    <loc>{escape(loc)}</loc>
    <changefreq>{changefreq}</changefreq>
    <priority>{priority}</priority>
  </url>"""
        for loc, changefreq, priority in urls
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}
</urlset>
"""


def _build_itemlist_schema(
    events: list[object],
    *,
    page_url: str,
    itemlist_name: str,
) -> dict[str, object]:
    item_list = []
    for index, event in enumerate(events, start=1):
        item = {
            "@type": "ListItem",
            "position": index,
            "url": str(event.source_url),
            "item": _build_event_schema(event),
        }
        item_list.append(item)

    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": "https://sporly.ru/#website",
                "name": "Sporly",
                "url": "https://sporly.ru/",
                "inLanguage": "ru-RU",
                "description": "Календарь спортивных событий по регионам и видам спорта.",
            },
            {
                "@type": "Organization",
                "@id": "https://sporly.ru/#organization",
                "name": "Sporly",
                "url": "https://sporly.ru/",
                "logo": "https://sporly.ru/logo-mark.svg",
                "image": "https://sporly.ru/og-image.svg",
                "description": "Sporly — единый каталог спортивных мероприятий, забегов, велогонок, лыжных марафонов и других стартов.",
                "email": "fronteno@yandex.ru",
                "sameAs": ["https://t.me/fronteno"],
            },
            {
                "@type": "ItemList",
                "@id": f"{page_url}#itemlist",
                "name": itemlist_name,
                "numberOfItems": len(item_list),
                "itemListElement": item_list,
            },
        ],
    }


def _render_seo_page(
    *,
    page_title: str,
    page_description: str,
    canonical_url: str,
    heading: str,
    intro: str,
    section_title: str,
    events: list[object],
    total: int,
) -> str:
    cards_html = []
    for event in events:
        category = escape(event.category or "Спорт")
        title = escape(event.title)
        url = escape(str(event.source_url), quote=True)
        location = escape(_seo_location(event))
        date_value = escape(_format_seo_date(event.starts_at, event.date_text))
        description = escape(event.description or "")
        distance = escape(event.distance_summary or "")
        surface = escape(event.surface_type or "")
        registration = escape(event.registration_deadline or "")
        details = " • ".join(part for part in (distance, surface, registration) if part)
        details_html = f"<p class='fact'>{escape(details)}</p>" if details else ""
        description_html = f"<p class='description'>{description}</p>" if description else ""
        cards_html.append(
            f"""
            <li class="event">
              <article>
                <p class="category">{category}</p>
                <h3><a href="{url}" rel="nofollow noopener noreferrer">{title}</a></h3>
                <p class="meta">{date_value} • {location}</p>
                {details_html}
                {description_html}
              </article>
            </li>
            """
        )

    schema_json = json.dumps(
        _build_itemlist_schema(
            events,
            page_url=canonical_url,
            itemlist_name=section_title,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return f"""<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{escape(page_title)}</title>
    <meta name="description" content="{escape(page_description, quote=True)}" />
    <meta name="robots" content="index, follow, max-image-preview:large" />
    <link rel="canonical" href="{escape(canonical_url, quote=True)}" />
    <meta property="og:locale" content="ru_RU" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="Sporly" />
    <meta property="og:title" content="{escape(page_title, quote=True)}" />
    <meta property="og:description" content="{escape(page_description, quote=True)}" />
    <meta property="og:url" content="{escape(canonical_url, quote=True)}" />
    <meta property="og:image" content="https://sporly.ru/og-image.svg" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{escape(page_title, quote=True)}" />
    <meta name="twitter:description" content="{escape(page_description, quote=True)}" />
    <script type="application/ld+json">{schema_json}</script>
    <style>
      :root {{ color-scheme: light; }}
      body {{ margin: 0; font-family: Inter, system-ui, sans-serif; background: #f6f7f3; color: #13211c; }}
      main {{ max-width: 1120px; margin: 0 auto; padding: 32px 20px 56px; }}
      .eyebrow {{ margin: 0 0 12px; color: #476457; font-size: 14px; text-transform: uppercase; letter-spacing: .14em; font-weight: 700; }}
      h1 {{ margin: 0; font-size: clamp(2rem, 4vw, 3rem); line-height: 1.02; letter-spacing: -.04em; }}
      .lead {{ max-width: 72ch; margin: 16px 0 0; color: #5f7168; font-size: 1.02rem; line-height: 1.65; }}
      .stats {{ margin: 18px 0 0; color: #476457; font-size: .95rem; }}
      h2 {{ margin: 40px 0 18px; font-size: 1.15rem; letter-spacing: -.02em; }}
      .events {{ list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }}
      .event article {{ height: 100%; padding: 18px; border-radius: 22px; background: rgba(255,255,255,.96); box-shadow: 0 10px 30px rgba(19,33,28,.06); border: 1px solid rgba(19,33,28,.06); }}
      .category {{ margin: 0 0 10px; color: #476457; font-size: .73rem; text-transform: uppercase; letter-spacing: .14em; font-weight: 700; }}
      h3 {{ margin: 0; font-size: 1.25rem; line-height: 1.15; }}
      h3 a {{ color: inherit; text-decoration: none; }}
      .meta {{ margin: 12px 0 0; color: #36501a; font-weight: 600; }}
      .fact {{ margin: 12px 0 0; color: #42582f; font-size: .92rem; }}
      .description {{ margin: 12px 0 0; color: #5f7168; line-height: 1.58; }}
    </style>
  </head>
  <body>
    <main>
      <p class="eyebrow">sporly</p>
      <h1>{escape(heading)}</h1>
      <p class="lead">{escape(intro)}</p>
      <p class="stats">Сейчас в каталоге {total} событий. Ниже — ближайшие старты, которые поисковик может увидеть как обычный HTML, без клиентского рендера.</p>
      <h2>{escape(section_title)}</h2>
      <ul class="events">
        {''.join(cards_html)}
      </ul>
    </main>
  </body>
</html>"""


@app.get("/api/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/sitemap.xml")
async def sitemap_xml() -> Response:
    available_cities, available_categories, _ = catalog_service.get_filter_metadata()
    regions = sorted(
        region
        for region in available_cities
        if region and _is_pure_region_option(region)
    )
    xml = _build_sitemap_xml(regions, available_categories)
    return Response(content=xml, media_type="application/xml")


@app.get("/seo/home", response_class=HTMLResponse)
async def seo_home() -> HTMLResponse:
    today = datetime.now().date().isoformat()
    events = await catalog_service.get_events(
        filters=EventFilters(
            date_from=today,
            sort_by="date_asc",
        )
    )
    top_events = events[:24]
    return HTMLResponse(
        _render_seo_page(
            page_title="Sporly — календарь спортивных событий, забегов и стартов по регионам",
            page_description="Sporly — календарь спортивных событий по регионам и видам спорта. Находите забеги, велогонки, лыжные марафоны, триатлон и другие старты в одном каталоге.",
            canonical_url="https://sporly.ru/",
            heading="Календарь спортивных событий по регионам и видам спорта",
            intro="Sporly помогает находить спортивные мероприятия по всей России и ближнему зарубежью: забеги, велогонки, лыжные марафоны, триатлон, ориентирование и другие старты в одном каталоге. Мы собираем события из разных сайтов и приводим их к единому формату, чтобы поиск стартов был проще и понятнее.",
            section_title="Ближайшие старты",
            events=top_events,
            total=len(events),
        )
    )


@app.get("/seo/region/{region_slug}", response_class=HTMLResponse)
async def seo_region(region_slug: str) -> HTMLResponse:
    available_cities, _, _ = catalog_service.get_filter_metadata()
    region = _resolve_slug(region_slug, available_cities)
    if not region:
        raise HTTPException(status_code=404, detail="Region not found")

    today = datetime.now().date().isoformat()
    events = await catalog_service.get_events(
        filters=EventFilters(
            cities=[region],
            date_from=today,
            sort_by="date_asc",
        )
    )
    return HTMLResponse(
        _render_seo_page(
            page_title=f"{region} — спортивные события и старты | Sporly",
            page_description=f"Спортивные события в регионе {region}: забеги, велогонки, лыжные марафоны, триатлон и другие старты в одном каталоге Sporly.",
            canonical_url=f"https://sporly.ru/seo/region/{region_slug}",
            heading=f"Спортивные события в регионе {region}",
            intro=f"Подборка стартов по региону {region}: ближайшие соревнования, фестивали и спортивные мероприятия из разных источников в одном каталоге.",
            section_title=f"Ближайшие старты в регионе {region}",
            events=events[:24],
            total=len(events),
        )
    )


@app.get("/seo/sport/{category_slug}", response_class=HTMLResponse)
async def seo_sport(category_slug: str) -> HTMLResponse:
    _, available_categories, _ = catalog_service.get_filter_metadata()
    category = _resolve_slug(category_slug, available_categories)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    today = datetime.now().date().isoformat()
    events = await catalog_service.get_events(
        filters=EventFilters(
            categories=[category],
            date_from=today,
            sort_by="date_asc",
        )
    )
    return HTMLResponse(
        _render_seo_page(
            page_title=f"{category} — спортивные события и старты | Sporly",
            page_description=f"{category} в каталоге Sporly: ближайшие спортивные события, старты и соревнования по датам и регионам.",
            canonical_url=f"https://sporly.ru/seo/sport/{category_slug}",
            heading=f"{category}: ближайшие спортивные события",
            intro=f"Подборка ближайших стартов в категории «{category}». Здесь собраны спортивные события из разных источников с датами, локациями и ссылками на регистрацию.",
            section_title=f"Ближайшие события: {category}",
            events=events[:24],
            total=len(events),
        )
    )


@app.get("/api/events", response_model=EventsResponse)
async def list_events(
    q: str | None = None,
    city: list[str] | None = Query(default=None),
    category: list[str] | None = Query(default=None),
    recommended: bool = False,
    registration_status: str | None = None,
    kids_only: bool = False,
    surface_type: str | None = None,
    difficulty_level: str | None = None,
    source: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str | None = None,
    page: int = 1,
    page_size: int = 24,
) -> EventsResponse:
    filters = EventFilters(
        query=q,
        cities=city,
        categories=category,
        recommended=recommended,
        registration_status=registration_status,
        kids_only=kids_only,
        surface_type=surface_type,
        difficulty_level=difficulty_level,
        source=source,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
    )
    events = await catalog_service.get_events(filters=filters)
    available_cities, available_categories, available_sources = (
        catalog_service.get_filter_metadata()
    )
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
        available_cities=available_cities,
        available_categories=available_categories,
        available_sources=available_sources,
    )
