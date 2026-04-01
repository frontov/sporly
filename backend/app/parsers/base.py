from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import hashlib
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil import parser as date_parser
import httpx

from app.schemas.event import Event


@dataclass(slots=True)
class SourceFieldMap:
    item: str
    title: str
    link: str
    date: str | None = None
    city: str | None = None
    venue: str | None = None
    category: str | None = None
    description: str | None = None
    image: str | None = None


@dataclass(slots=True)
class SourceConfig:
    name: str
    base_url: str
    listing_urls: list[str]
    selectors: SourceFieldMap
    parser_type: str = "css"
    enabled: bool = True
    pagination_selector: str | None = None
    max_pages: int = 1


class CssDirectoryParser:
    def __init__(self, config: SourceConfig) -> None:
        self.config = config

    async def fetch_events(
        self, client: httpx.AsyncClient
    ) -> list[Event] | None:
        return None

    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(self.config.selectors.item)
        events: list[Event] = []

        for index, card in enumerate(cards):
            title = self._extract_text(card, self.config.selectors.title)
            href = self._extract_attr(card, self.config.selectors.link, "href")

            if not title or not href:
                continue

            date_text = self._extract_optional_text(card, self.config.selectors.date)
            city = self._extract_optional_text(card, self.config.selectors.city)
            venue = self._extract_optional_text(card, self.config.selectors.venue)
            category = self._extract_optional_text(card, self.config.selectors.category)
            description = self._extract_optional_text(card, self.config.selectors.description)
            image_url = self._extract_optional_attr(card, self.config.selectors.image, "src")

            starts_at = self._normalize_datetime(date_text)
            full_link = urljoin(page_url, href)
            full_image = urljoin(page_url, image_url) if image_url else None
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"{self.config.name.lower().replace(' ', '-')}-{index}-{stable_hash}",
                    title=title,
                    description=description,
                    city=city,
                    region=None,
                    federal_district=None,
                    venue=venue,
                    category=category,
                    date_text=date_text,
                    starts_at=starts_at,
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=full_image,
                )
            )

        return events

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        return events

    def extract_pagination_urls(self, html: str, page_url: str) -> list[str]:
        if not self.config.pagination_selector:
            return []

        soup = BeautifulSoup(html, "html.parser")
        urls: list[str] = []
        seen: set[str] = set()
        for element in soup.select(self.config.pagination_selector):
            href = element.get("href")
            if not isinstance(href, str):
                continue
            full_url = urljoin(page_url, href)
            if full_url in seen:
                continue
            seen.add(full_url)
            urls.append(full_url)
            if len(urls) >= max(self.config.max_pages - 1, 0):
                break
        return urls

    def _extract_text(self, node: Any, selector: str) -> str | None:
        element = node.select_one(selector)
        if not element:
            return None
        text = element.get_text(" ", strip=True)
        return text or None

    def _extract_optional_text(self, node: Any, selector: str | None) -> str | None:
        if not selector:
            return None
        return self._extract_text(node, selector)

    def _extract_attr(self, node: Any, selector: str, attr_name: str) -> str | None:
        element = node.select_one(selector)
        if not element:
            return None
        value = element.get(attr_name)
        return value.strip() if isinstance(value, str) else None

    def _extract_optional_attr(
        self, node: Any, selector: str | None, attr_name: str
    ) -> str | None:
        if not selector:
            return None
        return self._extract_attr(node, selector, attr_name)

    def _normalize_datetime(self, raw_value: str | None) -> str | None:
        if not raw_value:
            return None
        normalized = self._parse_russian_date(raw_value)
        if normalized:
            return normalized
        try:
            return date_parser.parse(raw_value, fuzzy=True).isoformat()
        except (ValueError, OverflowError, TypeError):
            return None

    def _parse_russian_date(self, raw_value: str) -> str | None:
        months = {
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
        match = re.search(
            r"(\d{1,2})(?:\s*[–—-]\s*\d{1,2})?\s+"
            r"(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
            r"(?:\s+(\d{4}))?",
            raw_value.lower(),
        )
        if not match:
            return None

        day = int(match.group(1))
        month = months[match.group(2)]
        year = int(match.group(3)) if match.group(3) else datetime.now().year

        try:
            return datetime(year, month, day).isoformat()
        except ValueError:
            return None


class RegPlaceParser(CssDirectoryParser):
    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(".b-event-card")
        events: list[Event] = []

        for index, card in enumerate(cards):
            title_element = card.select_one("h3 a")
            if not title_element:
                continue

            title = title_element.get_text(" ", strip=True)
            href = title_element.get("href")
            if not title or not isinstance(href, str):
                continue

            meta_text = self._extract_text(card, ".text-muted.mb-3")
            date_text, city, category = self._parse_meta(meta_text)
            description = self._extract_optional_text(card, "p.mb-3.text-secondary")
            image_url = self._extract_optional_attr(card, ".b-event-card__image", "src")
            full_link = urljoin(page_url, href)
            full_image = urljoin(page_url, image_url) if image_url else None
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"reg-place-{index}-{stable_hash}",
                    title=title,
                    description=description,
                    city=city,
                    region=None,
                    federal_district=None,
                    venue=None,
                    category=category,
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=full_image,
                )
            )

        return events

    def _parse_meta(self, meta_text: str | None) -> tuple[str | None, str | None, str | None]:
        if not meta_text:
            return None, None, None

        parts = [part.strip() for part in meta_text.split("•") if part.strip()]
        if not parts:
            return None, None, None
        if len(parts) == 1:
            return parts[0], None, None
        if len(parts) == 2:
            return parts[0], None, parts[1]
        return parts[0], parts[1], ", ".join(parts[2:])

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        enriched: list[Event] = []

        for event in events:
            if event.date_text and event.city:
                enriched.append(event)
                continue

            try:
                response = await client.get(str(event.source_url))
                response.raise_for_status()
            except httpx.HTTPError:
                enriched.append(
                    self._enrich_regplace_from_title(event)
                )
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            date_text = event.date_text or self._extract_optional_text(soup, "h2")
            lead_text = self._extract_optional_text(soup, "p.lead.text-muted")
            description_meta = soup.find("meta", attrs={"name": "description"})
            description_text = (
                description_meta.get("content")
                if description_meta and isinstance(description_meta.get("content"), str)
                else None
            )
            location_text = lead_text or description_text
            city = event.city or self._extract_regplace_city(location_text, event.title)
            venue = event.venue or self._extract_regplace_venue(location_text)

            enriched.append(
                self._enrich_regplace_from_title(
                    event.model_copy(
                        update={
                            "date_text": date_text,
                            "starts_at": self._normalize_datetime(date_text),
                            "city": city,
                            "venue": venue,
                        }
                    )
                )
            )

        return enriched

    def _enrich_regplace_from_title(self, event: Event) -> Event:
        city = event.city or self._extract_regplace_city(None, event.title)
        return event.model_copy(update={"city": city})

    def _extract_regplace_city(self, location_text: str | None, title: str) -> str | None:
        combined = " ".join(part for part in [location_text, title] if part)
        if not combined:
            return None

        city_patterns = [
            (r"\bКисловодск\b", "Кисловодск"),
            (r"\bМосква\b", "Москва"),
            (r"\bСанкт[-\s]?Петербург\b|\bСПБ\b", "Санкт-Петербург"),
            (r"\bЗеленоград\b", "Зеленоград"),
            (r"\bКрасногорск\b", "Красногорск"),
            (r"\bКотельники\b", "Котельники"),
            (r"\bСочи\b", "Сочи"),
            (r"\bКазань\b", "Казань"),
            (r"\bТрубино\b", "Трубино"),
            (r"\bБелая Дача\b", "Котельники"),
            (r"\bРаменск", "Раменское"),
            (r"\bРуза\b", "Руза"),
            (r"\bАлександров\b", "Александров"),
            (r"\bОр[её]л\b", "Орёл"),
            (r"\bИваново\b", "Иваново"),
            (r"\bКалязин\b", "Калязин"),
            (r"\bСтупино\b", "Ступино"),
            (r"\bПл[её]с\b", "Плес"),
            (r"\bКинешма\b", "Кинешма"),
            (r"\bЛюберц", "Люберцы"),
            (r"\bСпас-Каменк", "Спас-Каменка"),
            (r"\bДоброград\b", "Доброград"),
            (r"\bМорозовск\b", "Морозовск"),
            (r"\bГАБО\b", "ГАБО"),
            (r"\bПирогово\b", "Пирогово"),
            (r"\bБердигестях\b", "Бердигестях"),
            (r"\bАбзелиловск", "Абзелиловский район"),
        ]
        for pattern, city in city_patterns:
            if re.search(pattern, combined, flags=re.IGNORECASE):
                return city
        return None

    def _extract_regplace_venue(self, location_text: str | None) -> str | None:
        if not location_text:
            return None
        match = re.search(
            r"(МЕГА\s+Белая\s+Дача|торгово-развлекательного центра\s+МЕГА\s+Белая\s+Дача)",
            location_text,
            flags=re.IGNORECASE,
        )
        if match:
            return "МЕГА Белая Дача"
        return None


class OrgeoParser(CssDirectoryParser):
    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("td.event_view_td.hidden-xs")
        events: list[Event] = []

        for index, row in enumerate(rows):
            container = row.find_next_sibling("td", class_="event_view_td")
            if container is None:
                continue

            link_element = container.select_one("td.td_block > a")
            if link_element is None:
                continue

            href = link_element.get("href")
            title_node = link_element.select_one("span[style]")
            title = title_node.get_text(" ", strip=True) if title_node else link_element.get_text(" ", strip=True)
            if not title or not isinstance(href, str):
                continue

            date_text = self._extract_text(container, "b.hidden-xs.no_wrap")
            place_text = self._extract_text(container, ".event-place")
            description = self._extract_optional_text(container, ".hint")
            image_url = self._extract_optional_attr(container, "img.logo-inline", "src")
            sport_icon = row.select_one(".icon_sport_i")
            category = sport_icon.get("title") if sport_icon else None
            region, city, venue = self._extract_orgeo_location(place_text)
            full_link = urljoin(page_url, href)
            full_image = urljoin(page_url, image_url) if image_url else None
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"orgeo-{index}-{stable_hash}",
                    title=title,
                    description=description,
                    city=city,
                    region=region,
                    federal_district=None,
                    venue=venue,
                    category=category,
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=full_image,
                )
            )

        return events

    def _extract_orgeo_location(
        self, place_text: str | None
    ) -> tuple[str | None, str | None, str | None]:
        if not place_text:
            return None, None, None
        parts = [part.strip() for part in place_text.split("»") if part.strip()]
        region = parts[0] if parts else None
        city = parts[1] if len(parts) >= 2 else None
        venue = parts[2] if len(parts) >= 3 else None
        return region, city, venue

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        semaphore = asyncio.Semaphore(8)
        tasks = [
            asyncio.create_task(self._enrich_orgeo_event(event, client, semaphore))
            for event in events
        ]
        return await asyncio.gather(*tasks)

    async def _enrich_orgeo_event(
        self,
        event: Event,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Event:
        if event.starts_at and event.city:
            return event

        async with semaphore:
            try:
                response = await client.get(str(event.source_url))
                response.raise_for_status()
            except httpx.HTTPError:
                return event

        soup = BeautifulSoup(response.text, "html.parser")
        starts_at = event.starts_at or self._extract_optional_attr(
            soup, '[itemprop="startDate"]', "content"
        )
        date_text = event.date_text or self._extract_orgeo_detail_date(soup)
        region, city, venue = self._extract_orgeo_detail_location(soup)

        return event.model_copy(
            update={
                "date_text": date_text or event.date_text,
                "starts_at": starts_at or self._normalize_datetime(date_text),
                "region": region or event.region,
                "city": city or event.city,
                "venue": venue or event.venue,
            }
        )

    def _extract_orgeo_detail_date(self, soup: BeautifulSoup) -> str | None:
        top_info = soup.select_one(".event_top_info")
        if top_info is not None:
            bold = top_info.select_one("b")
            if bold is not None:
                text = bold.get_text(" ", strip=True)
                if text:
                    return text
        return None

    def _extract_orgeo_detail_location(
        self, soup: BeautifulSoup
    ) -> tuple[str | None, str | None, str | None]:
        heading_location = self._extract_orgeo_heading_location(soup)
        if any(heading_location):
            return heading_location

        region = self._extract_optional_attr(soup, '[itemprop="addressRegion"]', "content")
        city = self._extract_optional_attr(soup, '[itemprop="addressLocality"]', "content")
        venue = self._extract_optional_attr(soup, '[itemprop="streetAddress"]', "content")
        country = self._extract_optional_attr(soup, '[itemprop="addressCountry"]', "content")

        if venue:
            extracted_city = self._extract_orgeo_city_from_venue(venue)
            if extracted_city:
                city = extracted_city

        if city and re.search(r"\bр-?н\b", city.lower()) and venue:
            extracted_city = self._extract_orgeo_city_from_venue(venue)
            if extracted_city:
                city = extracted_city

        if region or city or venue:
            return region, city, venue

        top_info = soup.select_one(".event_top_info")
        if top_info is not None:
            link = top_info.select_one('a[href*="#map"]')
            if link is not None:
                location_text = link.get_text(" ", strip=True)
                parts = [part.strip() for part in location_text.split(",") if part.strip()]
                if len(parts) >= 2:
                    return None, parts[0], ", ".join(parts[1:])
                if len(parts) == 1:
                    return None, parts[0], None

        if not city and region and country and country.lower() not in region.lower():
            city = region
            region = country

        return region, city, venue

    def _extract_orgeo_heading_location(
        self, soup: BeautifulSoup
    ) -> tuple[str | None, str | None, str | None]:
        for heading in soup.select("h2"):
            heading_text = heading.get_text(" ", strip=True).lower()
            if "место проведения" not in heading_text:
                continue

            parts = [
                part.get_text(" ", strip=True)
                for part in heading.select("small a")
                if part.get_text(" ", strip=True)
            ]
            if not parts:
                continue

            region = parts[0] if len(parts) >= 1 else None
            venue = parts[-1] if len(parts) >= 1 else None
            city = self._extract_orgeo_city_from_venue(venue)

            if city and len(parts) >= 2 and re.search(r"\bр-?н\b", parts[1].lower()):
                return region, city, venue

            if len(parts) >= 3:
                return region, city or parts[1], venue
            if len(parts) == 2:
                return region, city or parts[1], venue
            return region, city, venue

        return None, None, None

    def _extract_orgeo_city_from_venue(self, venue: str | None) -> str | None:
        if not venue:
            return None

        patterns = [
            r"\bг\.\s*([^,]+)",
            r"\bпос\.\s*([^,]+)",
            r"\bп\.\s*([^,]+)",
            r"\bс\.\s*([^,]+)",
            r"\bдер\.\s*([^,]+)",
            r"\bд\.\s*([^,]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, venue, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" ,")
        return None


class RuncParser(CssDirectoryParser):
    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        items = soup.select(".header-menu-sub-menu-race-item")
        if not items:
            items = soup.select(".responsive-left-runs-menu__item")

        events: list[Event] = []
        seen_links: set[str] = set()

        for index, item in enumerate(items):
            title_element = item.select_one(".header-menu-sub-menu-race-item__race-name")
            if title_element is None:
                title_element = item.select_one(".responsive-left-runs-menu__item-link")
            date_element = item.select_one(".header-menu-sub-menu-race-item__date")
            if date_element is None:
                date_element = item.select_one(".responsive-left-runs-menu__item-label")
            if title_element is None or date_element is None:
                continue

            href = title_element.get("href")
            title = title_element.get_text(" ", strip=True)
            date_text = date_element.get_text(" ", strip=True)
            if not title or not isinstance(href, str) or href == "#":
                continue

            full_link = urljoin(page_url, href)
            if full_link in seen_links:
                continue
            seen_links.add(full_link)
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]
            city = self._extract_runc_city(None, title, full_link)

            events.append(
                Event(
                    id=f"runc-{index}-{stable_hash}",
                    title=title,
                    description=None,
                    city=city,
                    region=None,
                    federal_district=None,
                    venue=None,
                    category="Бег",
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=None,
                )
            )

        return events

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        enriched: list[Event] = []

        for event in events:
            if event.starts_at and event.city:
                enriched.append(event)
                continue

            try:
                response = await client.get(str(event.source_url))
                response.raise_for_status()
            except httpx.HTTPError:
                enriched.append(self._apply_runc_title_hints(event))
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            date_text = event.date_text or self._extract_optional_text(soup, ".run-intro__date")
            location_block = soup.select_one("#locationhours")
            location_text = location_block.get_text(" ", strip=True) if location_block else None
            city = event.city or self._extract_runc_city(location_text, event.title, str(event.source_url))
            venue = event.venue or self._extract_runc_venue(location_text)

            enriched.append(
                self._apply_runc_title_hints(
                    event.model_copy(
                        update={
                            "date_text": date_text,
                            "starts_at": self._normalize_datetime(date_text),
                            "city": city,
                            "venue": venue,
                        }
                    )
                )
            )

        return enriched

    def _apply_runc_title_hints(self, event: Event) -> Event:
        city = event.city or self._extract_runc_city(None, event.title, str(event.source_url))
        return event.model_copy(update={"city": city})

    def _extract_runc_city(
        self, location_text: str | None, title: str, source_url: str
    ) -> str | None:
        combined = " ".join(part for part in [location_text, title, source_url] if part).lower()
        patterns = [
            (("санкт-петербург", "дворцовой площади", "белые ночи", "северная столица", "spb"), "Санкт-Петербург"),
            (("москва", "лужники", "садовому кольцу", "московский", "moscow"), "Москва"),
        ]
        for tokens, city in patterns:
            if any(token in combined for token in tokens):
                return city
        return None

    def _extract_runc_venue(self, location_text: str | None) -> str | None:
        if not location_text:
            return None
        venue_patterns = [
            r"Олимпийский комплекс «Лужники»",
            r"Дворцов[а-я\s]+площад[а-я]+",
            r"Центральн[а-я\s]+площад[а-я]+",
        ]
        for pattern in venue_patterns:
            match = re.search(pattern, location_text, flags=re.IGNORECASE)
            if match:
                return match.group(0)
        return None


class RussialoppetParser(CssDirectoryParser):
    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []
        seen_links: set[str] = set()
        index = 0

        for row in soup.select("tr.item[id]"):
            link_element = row.select_one(".item-name-cell a[href]")
            if link_element is None:
                continue

            href = link_element.get("href")
            title = link_element.get_text(" ", strip=True)
            if not isinstance(href, str) or not href.strip() or not title:
                continue

            full_link = urljoin(page_url, href)
            if full_link in seen_links:
                continue
            seen_links.add(full_link)

            meta_cell = row.select_one("td.but-cell")
            date_text = self._extract_optional_text(row, "span.date")
            federal_district, region, city = self._extract_russialoppet_location(meta_cell)
            description = self._extract_optional_text(row, ".preview_text")
            image_url = self._extract_optional_attr(row, ".foto-cell img", "src")
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"russialoppet-{index}-{stable_hash}",
                    title=title,
                    description=description or "Лыжный марафон Russialoppet",
                    city=city,
                    region=region,
                    federal_district=federal_district,
                    venue=None,
                    category="Лыжи",
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=urljoin(page_url, image_url) if image_url else None,
                )
            )
            index += 1

        return events

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        enriched: list[Event] = []

        for event in events:
            if event.starts_at and event.date_text and event.city:
                enriched.append(event)
                continue

            try:
                response = await client.get(str(event.source_url))
                response.raise_for_status()
            except httpx.HTTPError:
                enriched.append(event)
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            date_text = self._extract_detail_date(soup)
            if not date_text:
                enriched.append(event)
                continue

            enriched.append(
                event.model_copy(
                    update={
                        "date_text": date_text or event.date_text,
                        "starts_at": self._normalize_datetime(date_text),
                        "city": event.city or self._extract_russialoppet_city(soup),
                    }
                )
            )

        return enriched

    def _find_marathons_link(self, soup: BeautifulSoup, page_url: str) -> Any | None:
        expected_path = re.search(r"/events/\d{4}/?$", page_url)
        path_hint = expected_path.group(0) if expected_path else None

        for link in soup.find_all("a", href=True):
            href = link.get("href")
            text = link.get_text(" ", strip=True)
            if text != "МАРАФОНЫ" or not isinstance(href, str):
                continue
            if path_hint and href.rstrip("/") == path_hint.rstrip("/"):
                return link
        return None

    def _split_russialoppet_label(self, label: str) -> tuple[str, str | None]:
        match = re.match(r"^(.*?)\s*\((.*?)\)\s*$", label)
        if not match:
            return label, None
        return match.group(1).strip(), match.group(2).strip()

    def _extract_russialoppet_location(
        self, meta_cell: Any | None
    ) -> tuple[str | None, str | None, str | None]:
        if meta_cell is None:
            return None, None, None

        spans = [
            span.get_text(" ", strip=True)
            for span in meta_cell.select("span")
            if span.get_text(" ", strip=True)
        ]
        if not spans:
            return None, None, None

        federal_district = spans[0] if len(spans) > 0 else None
        region = spans[1] if len(spans) > 1 else None
        city = spans[2] if len(spans) > 2 else None
        return federal_district, region, city

    def _extract_russialoppet_city(self, soup: BeautifulSoup) -> str | None:
        for selector in (".item .but-cell span:last-of-type", ".but-cell span:last-of-type"):
            value = self._extract_optional_text(soup, selector)
            if value:
                return value
        return None

    def _extract_detail_date(self, soup: BeautifulSoup) -> str | None:
        for selector in (".start_info_date", "span.date"):
            value = self._extract_optional_text(soup, selector)
            if value:
                return value
        return None


class RussiaRunningSeriesParser(CssDirectoryParser):
    DATE_FROM_TITLE_PATTERN = re.compile(r"\b(\d{1,2}\.\d{2}\.\d{4})\b")
    DATE_FROM_TITLE_COMPACT_PATTERN = re.compile(r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)")
    API_URL = "https://reg.russiarunning.com/api/events/list"
    PAGE_SIZE = 100

    async def fetch_events(
        self, client: httpx.AsyncClient
    ) -> list[Event] | None:
        events: list[Event] = []
        seen_codes: set[str] = set()
        skip = 0
        total_count: int | None = None

        while total_count is None or skip < total_count:
            payload = {
                "page": {
                    "take": self.PAGE_SIZE,
                    "skip": skip,
                },
                "language": "ru",
                "filter": {
                    "eventsLoaderType": 0,
                    "search": "",
                    "championshipIds": [],
                },
            }
            try:
                response = await client.post(self.API_URL, json=payload)
                response.raise_for_status()
            except httpx.HTTPError:
                break

            data = response.json()
            items = data.get("list")
            if not isinstance(items, list) or not items:
                break

            if total_count is None:
                raw_total = data.get("totalCount")
                total_count = raw_total if isinstance(raw_total, int) else None

            for item in items:
                if not isinstance(item, dict):
                    continue
                event = self._build_russiarunning_api_event(item)
                if not event or event.id in seen_codes:
                    continue
                seen_codes.add(event.id)
                events.append(event)

            skip += self.PAGE_SIZE
            if len(items) < self.PAGE_SIZE:
                break

        return events

    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []
        seen_links: set[str] = set()

        for index, link_element in enumerate(soup.select(".event-info li a[href]")):
            href = link_element.get("href")
            title = link_element.get_text(" ", strip=True)
            if not title or not isinstance(href, str):
                continue
            full_link = urljoin(page_url, href)
            if full_link in seen_links:
                continue
            seen_links.add(full_link)
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]
            inferred_date = self._extract_russiarunning_date_from_title(title)
            inferred_city = self._extract_russiarunning_city(title)
            events.append(
                Event(
                    id=f"russiarunning-{index}-{stable_hash}",
                    title=title,
                    description="Источник получен со страницы серий RussiaRunning; дата и город могут потребовать дополнительного парсинга карточки события.",
                    city=inferred_city,
                    region=None,
                    federal_district=None,
                    venue=None,
                    category=self._infer_russiarunning_category(title),
                    date_text=inferred_date,
                    starts_at=self._normalize_datetime(inferred_date),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=None,
                )
            )

        return events

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        semaphore = asyncio.Semaphore(10)
        tasks = [
            asyncio.create_task(
                self._enrich_russiarunning_event(event, client, semaphore)
            )
            for event in events
        ]
        return await asyncio.gather(*tasks)

    async def _enrich_russiarunning_event(
        self,
        event: Event,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Event:
        inferred_date = event.date_text or self._extract_russiarunning_date_from_title(event.title)
        inferred_city = event.city or self._extract_russiarunning_city(event.title)

        if inferred_date and inferred_city:
            return event.model_copy(
                update={
                    "date_text": inferred_date,
                    "starts_at": self._normalize_datetime(inferred_date),
                    "city": inferred_city,
                }
            )

        async with semaphore:
            fetched_date, fetched_city, fetched_venue = await self._fetch_russiarunning_details(
                str(event.source_url),
                client,
            )

        date_text = inferred_date or fetched_date
        return event.model_copy(
            update={
                "date_text": date_text,
                "starts_at": self._normalize_datetime(date_text),
                "city": inferred_city or fetched_city,
                "venue": fetched_venue,
            }
        )

    def _infer_russiarunning_category(self, title: str) -> str | None:
        normalized = title.lower()
        if any(
            keyword in normalized
            for keyword in ["вело", "велогон", "cycling", "велозаезд", "байк", "mtb", "три горы"]
        ):
            return "Велоспорт"
        if any(keyword in normalized for keyword in ["плаван", "swim"]):
            return "Плавание"
        if any(keyword in normalized for keyword in ["трейл", "trail"]):
            return "Трейл"
        if any(keyword in normalized for keyword in ["марафон", "полумарафон", "забег", "run"]):
            return "Бег"
        return None

    async def _fetch_russiarunning_details(
        self, source_url: str, client: httpx.AsyncClient
    ) -> tuple[str | None, str | None, str | None]:
        slug = source_url.rstrip("/").split("/")[-1]
        candidate_urls: list[str] = []
        if slug:
            candidate_urls.append(f"https://events.run-rus.com/event/{slug}")
        candidate_urls.append(source_url)
        slug = source_url.rstrip("/").split("/")[-1]
        if slug:
            candidate_urls.append(urljoin(source_url, f"/{slug}/shop/Register"))

        for candidate_url in candidate_urls:
            try:
                response = await client.get(candidate_url)
                response.raise_for_status()
            except httpx.HTTPError:
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            date_text = self._extract_optional_text(soup, ".event-date")
            place_text = self._extract_optional_text(soup, ".place")
            if date_text or place_text:
                city, venue = self._extract_russiarunning_place(place_text)
                if date_text and self._looks_like_russiarunning_date(date_text):
                    return self._cleanup_russiarunning_date(date_text), city, venue
                if city or venue:
                    return None, city, venue

            for selector in (
                "p.text-medium-semibold.mb-0-75",
                ".text-medium-semibold.mb-0-75",
                ".event-date",
                "[data-testid='event-date']",
            ):
                value = self._extract_optional_text(soup, selector)
                if value and self._looks_like_russiarunning_date(value):
                    return self._cleanup_russiarunning_date(value), None, None

        return None, None, None

    def _looks_like_russiarunning_date(self, value: str) -> bool:
        normalized = value.lower()
        return bool(
            re.search(
                r"(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)",
                normalized,
            )
            or re.search(r"\d{1,2}\.\d{2}\.\d{4}", normalized)
        )

    def _cleanup_russiarunning_date(self, value: str) -> str:
        cleaned = re.sub(r"^(пн|вт|ср|чт|пт|сб|вс)\s*[·•]?\s*", "", value.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(
            r"^(понедельник|вторник|среда|четверг|пятница|суббота|воскресенье)\s*,?\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned.strip()

    def _extract_russiarunning_date_from_title(self, title: str) -> str | None:
        match = self.DATE_FROM_TITLE_PATTERN.search(title)
        if match:
            return match.group(1)
        compact_match = self.DATE_FROM_TITLE_COMPACT_PATTERN.search(title)
        if compact_match:
            day = compact_match.group(1)
            month = compact_match.group(2)
            year = compact_match.group(3)
            return f"{day}.{month}.{year}"
        return None

    def _extract_russiarunning_city(self, title: str) -> str | None:
        patterns = [
            (r"\bмоск(овск|ва)\b|битцевск|ромашково", "Москва"),
            (r"\bуф(им|а)\b", "Уфа"),
            (r"\bсанкт[-\s]?петербург\b|\bспб\b|\bленинград\b|\bпискар[её]в", "Санкт-Петербург"),
            (r"\bказан", "Казань"),
            (r"\bтюм", "Тюмень"),
            (r"\bсамар", "Самара"),
            (r"\bпетровск\b", "Петровск"),
            (r"\bкисловодск\b", "Кисловодск"),
            (r"\bкраснодар\b", "Краснодар"),
            (r"\bсочи\b", "Сочи"),
            (r"\bомск\b", "Омск"),
            (r"\bперм", "Пермь"),
            (r"\bворонеж", "Воронеж"),
            (r"\bростов", "Ростов-на-Дону"),
            (r"\bярослав", "Ярославль"),
            (r"\bсмолен", "Смоленск"),
            (r"\bекатеринбург\b", "Екатеринбург"),
            (r"\bчелябин", "Челябинск"),
            (r"\bкалининград\b", "Калининград"),
            (r"\bволгоград\b", "Волгоград"),
            (r"\bтула\b", "Тула"),
            (r"\bнекрасов", "Некрасовское"),
            (r"\bстамбул", "Стамбул"),
        ]
        for pattern, city in patterns:
            if re.search(pattern, title, flags=re.IGNORECASE):
                return city
        return None

    def _extract_russiarunning_place(
        self, place_text: str | None
    ) -> tuple[str | None, str | None]:
        if not place_text:
            return None, None
        cleaned = re.sub(r"\s+", " ", place_text).strip(" ,")
        city = None
        venue = None

        city_match = re.match(r"г\.\s*([^,]+)", cleaned, flags=re.IGNORECASE)
        if city_match:
            city = city_match.group(1).strip()
            venue = cleaned[city_match.end() :].strip(" ,") or None
            return city, venue

        parts = [part.strip() for part in cleaned.split(",") if part.strip()]
        if parts:
            city = parts[0]
            venue = ", ".join(parts[1:]) or None
        return city, venue

    def _build_russiarunning_api_event(self, item: dict[str, Any]) -> Event | None:
        code = item.get("code")
        title = item.get("title")
        if not isinstance(code, str) or not code.strip():
            return None
        if not isinstance(title, str) or not title.strip():
            return None

        begin_date = item.get("beginDate")
        starts_at = begin_date.strip() if isinstance(begin_date, str) else None
        date_text = self._format_russiarunning_date_text(starts_at)

        place = item.get("place") if isinstance(item.get("place"), str) else None
        address = item.get("address") if isinstance(item.get("address"), str) else None
        city_name = item.get("cityName") if isinstance(item.get("cityName"), str) else None
        city = self._normalize_russiarunning_city_name(city_name)
        if not city:
            city = self._extract_russiarunning_city_from_location(place, address, title)

        category = self._infer_russiarunning_api_category(item, title)
        image_url = item.get("imageUrl")
        source_url = f"https://reg.russiarunning.com/event/{code}"
        description = self._build_russiarunning_description(item)

        return Event(
            id=f"russiarunning-{code}",
            title=title.strip(),
            description=description,
            city=city,
            region=None,
            federal_district=None,
            venue=place,
            category=category,
            date_text=date_text,
            starts_at=starts_at,
            source_name=self.config.name,
            source_url=source_url,
            image_url=image_url.strip() if isinstance(image_url, str) else None,
        )

    def _format_russiarunning_date_text(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            parsed = date_parser.isoparse(value)
        except (ValueError, TypeError):
            return None
        return parsed.strftime("%d.%m.%Y")

    def _normalize_russiarunning_city_name(self, value: str | None) -> str | None:
        if not value:
            return None
        normalized = value.strip()
        aliases = {
            "Moscow": "Москва",
            "Moskva": "Москва",
            "Saint Petersburg": "Санкт-Петербург",
            "St. Petersburg": "Санкт-Петербург",
            "Sankt-Peterburg": "Санкт-Петербург",
            "Sochi": "Сочи",
            "Sirius": "Сочи",
            "Krasnodar Krai": "Краснодарский край",
            "Krasnodarskiy Kray": "Краснодарский край",
            "Krasnaya Polyana": "Красная Поляна",
            "Esto-Sadok": "Эсто-Садок",
            "Kazan": "Казань",
            "Tyumen": "Тюмень",
            "Yekaterinburg": "Екатеринбург",
            "Ekaterinburg": "Екатеринбург",
            "Chelyabinsk": "Челябинск",
            "Krasnodar": "Краснодар",
            "Ufa": "Уфа",
            "Kaliningrad": "Калининград",
            "Omsk": "Омск",
            "Perm": "Пермь",
            "Smolensk": "Смоленск",
            "Volgograd": "Волгоград",
            "Voronezh": "Воронеж",
            "Yaroslavl": "Ярославль",
            "Rostov-on-Don": "Ростов-на-Дону",
            "Petrovsk": "Петровск",
            "Kislovodsk": "Кисловодск",
            "Antalya": "Анталия",
            "Khanty-Mansiysk": "Ханты-Мансийск",
            "Stavropol": "Ставрополь",
            "Sibay": "Сибай",
            "Cheboksary": "Чебоксары",
            "Tobolsk": "Тобольск",
            "Lipetsk": "Липецк",
            "Vologda": "Вологда",
            "Cherepovets": "Череповец",
            "Khabarovsk": "Хабаровск",
            "Yamal": "Ямало-Ненецкий автономный округ",
            "Belgrade": "Белград",
            "Yerevan": "Ереван",
            "Vienna": "Вена",
            "Tbilisi": "Тбилиси",
            "Samarkand": "Самарканд",
        }
        return aliases.get(normalized, normalized)

    def _extract_russiarunning_city_from_location(
        self,
        place: str | None,
        address: str | None,
        title: str,
    ) -> str | None:
        for candidate in (place, address):
            if not candidate:
                continue
            detected = self._extract_russiarunning_city(candidate)
            if detected:
                return detected
            cleaned = candidate.strip()
            direct_patterns = [
                (r"\bкрасная поляна\b|\bэсто[-\s]?садок\b|\bкурорт газпром\b|\bроза хутор\b", "Красная Поляна"),
                (r"\bсириус\b", "Сочи"),
                (r"\bсочи\b", "Сочи"),
                (r"\bмоскв", "Москва"),
                (r"\bсанкт[-\s]?петербург\b|\bспб\b", "Санкт-Петербург"),
                (r"\bкраснодар", "Краснодар"),
                (r"\bантал", "Анталия"),
                (r"\bодинцов", "Одинцово"),
                (r"\bзеленоград", "Зеленоград"),
            ]
            for pattern, city in direct_patterns:
                if re.search(pattern, cleaned, flags=re.IGNORECASE):
                    return city
            parts = [part.strip() for part in re.split(r",|;", cleaned) if part.strip()]
            for part in parts:
                part = re.sub(
                    r"^(г\.|город|пгт|пос\.|поселок|посёлок|с\.|село|дер\.|деревня)\s*",
                    "",
                    part,
                    flags=re.IGNORECASE,
                ).strip()
                if part and re.search(r"[А-Яа-яA-Za-z]", part):
                    return self._normalize_russiarunning_city_name(part)

        return self._extract_russiarunning_city(title)

    def _infer_russiarunning_api_category(
        self, item: dict[str, Any], title: str
    ) -> str | None:
        discipline_name = item.get("disciplineName")
        if isinstance(discipline_name, str) and discipline_name.strip():
            return discipline_name.strip()
        discipline_code = item.get("disciplineCode")
        if isinstance(discipline_code, str):
            code = discipline_code.strip().lower()
            mapping = {
                "run": "Бег",
                "trail": "Трейл",
                "ski": "Лыжи",
                "bike": "Велоспорт",
                "velo": "Велоспорт",
                "swim": "Плавание",
                "triathlon": "Триатлон",
                "walk": "Ходьба",
            }
            if code in mapping:
                return mapping[code]
        event_code = item.get("code")
        if isinstance(event_code, str):
            normalized_code = event_code.strip().lower()
            if any(token in normalized_code for token in ["bike", "velo", "cycle", "mtb", "3mountains"]):
                return "Велоспорт"
        return self._infer_russiarunning_category(title)

    def _build_russiarunning_description(self, item: dict[str, Any]) -> str | None:
        organizer = item.get("organizerName")
        series = item.get("sportSeriesTitle")
        parts = [
            value.strip()
            for value in (organizer, series)
            if isinstance(value, str) and value.strip()
        ]
        if not parts:
            return None
        return " • ".join(parts)


class ArtaSportParser(CssDirectoryParser):
    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []

        for index, item in enumerate(soup.select("ul.bl_mer > li.item")):
            detail_link = item.select_one("a[href]:not(.reg_btn)")
            if detail_link is None:
                continue

            href = detail_link.get("href")
            if not isinstance(href, str):
                continue

            title = self._extract_text(item, ".caption")
            date_text = self._extract_text(item, ".data")
            venue = self._extract_text(item, ".adr")
            image_url = self._extract_image_from_style(item.select_one(".pic"))
            if not title:
                continue

            full_link = urljoin(page_url, href)
            full_image = urljoin(page_url, image_url) if image_url else None
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"arta-sport-{index}-{stable_hash}",
                    title=title,
                    description=None,
                    city=self._extract_arta_city(venue),
                    region=self._extract_arta_region(venue),
                    federal_district=None,
                    venue=venue,
                    category=self._infer_arta_category(title, venue),
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=full_image,
                )
            )

        return events

    def _extract_image_from_style(self, node: Any) -> str | None:
        if node is None:
            return None
        style = node.get("style")
        if not isinstance(style, str):
            return None
        match = re.search(r"url\((['\"]?)(.*?)\1\)", style)
        return match.group(2) if match else None

    def _extract_arta_city(self, venue: str | None) -> str | None:
        if not venue:
            return None
        if "Москва" in venue:
            return "Москва"
        if "Московская область" in venue:
            return "Московская область"
        return venue.split(",")[0].strip() if "," in venue else venue.strip()

    def _infer_arta_category(self, title: str, venue: str | None) -> str | None:
        normalized = f"{title} {venue or ''}".lower()
        if "лыж" in normalized:
            return "Лыжи"
        if "плав" in normalized:
            return "Плавание"
        if "беговел" in normalized or "самокат" in normalized:
            return "Другой вид"
        if "кросс" in normalized or "забег" in normalized:
            return "Бег"
        return None

    def _extract_arta_region(self, venue: str | None) -> str | None:
        if not venue:
            return None
        if "Московская область" in venue:
            return "Московская область"
        if "Москва" in venue:
            return "Москва"
        return None


class MarzocchiCupParser(CssDirectoryParser):
    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []
        seen_links: set[str] = set()
        current_group: str | None = None

        tournaments_header = soup.find("h2", string=lambda text: isinstance(text, str) and "ТУРНИРЫ" in text)
        if tournaments_header is None:
            return events

        index = 0
        for node in tournaments_header.find_all_next():
            if node.name == "h2" and node is not tournaments_header:
                break

            if node.name == "h3":
                current_group = node.get_text(" ", strip=True)
                continue

            if node.name != "a":
                continue

            href = node.get("href")
            if not isinstance(href, str) or "Подробнее" not in node.get_text(" ", strip=True):
                continue

            card = node.parent
            if card is None:
                continue

            description_block = card.select_one("span")
            if description_block is None:
                continue

            lines = [
                line.strip(" .")
                for line in description_block.get_text("\n", strip=True).splitlines()
                if line.strip()
            ]
            if not lines:
                continue

            full_link = urljoin(page_url, href)
            if full_link in seen_links:
                continue
            seen_links.add(full_link)

            title = lines[0]
            city, venue = self._extract_marzocchi_location(lines)
            date_text = self._extract_marzocchi_date(lines)
            description = " ".join(line for line in lines[1:] if line != date_text)
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"marzocchi-cup-{index}-{stable_hash}",
                    title=title,
                    description=(f"{current_group}. {description}" if current_group and description else description or current_group),
                    city=city,
                    region=self._extract_marzocchi_region(venue),
                    federal_district=None,
                    venue=venue,
                    category=self._infer_marzocchi_category(title, current_group),
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=None,
                )
            )
            index += 1

        return events

    def _extract_marzocchi_date(self, lines: list[str]) -> str | None:
        for line in lines:
            if re.search(r"\d{1,2}\s+[а-яА-Я]+\s+\d{4}", line) or re.search(r"\d{2}\.\d{2}\.\d{4}", line):
                return line
        return None

    def _extract_marzocchi_location(self, lines: list[str]) -> tuple[str | None, str | None]:
        for line in lines[1:]:
            if self._extract_marzocchi_date([line]):
                continue
            lowered = line.lower()
            if any(keyword in lowered for keyword in ["обл", "область", "москва", "красногорск", "планерная", "головино", "филино", "смолен"]):
                city = "Москва" if "москва" in lowered or "красногорск" in lowered else None
                return city or line.split(",")[0].strip(), line
        return None, None

    def _infer_marzocchi_category(self, title: str, current_group: str | None) -> str | None:
        normalized = f"{title} {current_group or ''}".lower()
        if "junior" in normalized or "детск" in normalized:
            return "Детский спорт"
        if "вел" in normalized or "cup" in normalized or "race" in normalized or "trophy" in normalized:
            return "Велоспорт"
        return None

    def _extract_marzocchi_region(self, venue: str | None) -> str | None:
        if not venue:
            return None
        lowered = venue.lower()
        if "московская область" in lowered:
            return "Московская область"
        if "смоленская обл" in lowered or "смоленская область" in lowered:
            return "Смоленская область"
        if "москва" in lowered or "красногорск" in lowered:
            return "Москва"
        return None

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        enriched: list[Event] = []

        for event in events:
            if event.starts_at and event.city:
                enriched.append(event)
                continue

            try:
                response = await client.get(str(event.source_url))
                response.raise_for_status()
            except httpx.HTTPError:
                enriched.append(event)
                continue

            text = BeautifulSoup(response.text, "html.parser").get_text("\n", strip=True)
            date_text = event.date_text or self._extract_marzocchi_text_date(text)
            venue = event.venue or self._extract_marzocchi_text_venue(text)
            city = event.city or self._extract_marzocchi_text_city(text, venue)
            region = event.region or self._extract_marzocchi_region(venue)

            enriched.append(
                event.model_copy(
                    update={
                        "date_text": date_text,
                        "starts_at": self._normalize_datetime(date_text),
                        "city": city,
                        "region": region,
                        "venue": venue,
                    }
                )
            )

        return enriched

    def _extract_marzocchi_text_date(self, text: str) -> str | None:
        match = re.search(
            r"\b\d{1,2}\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4}\b",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(0)
        return None

    def _extract_marzocchi_text_venue(self, text: str) -> str | None:
        patterns = [
            r"Московская область[^.\n]*Красногорск[^.\n]*",
            r"Московская область[^.\n]*Филино[^.\n]*",
            r"Смоленская обл[^.\n]*",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(0).strip(" ,.")
        return None

    def _extract_marzocchi_text_city(self, text: str, venue: str | None) -> str | None:
        combined = " ".join(part for part in [venue, text] if part)
        patterns = [
            (r"\bКрасногорск\b", "Красногорск"),
            (r"\bФилино\b", "Филино"),
            (r"\bСмоленск\b", "Смоленск"),
        ]
        for pattern, city in patterns:
            if re.search(pattern, combined, flags=re.IGNORECASE):
                return city
        return None


class GranFondoParser(CssDirectoryParser):
    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []

        for index, item in enumerate(
            soup.select("section.events-main-page .thumbnail-list-main > li")
        ):
            title_block = item.select_one(".caption h4")
            if title_block is None:
                continue

            date_node = title_block.select_one("small")
            date_text = date_node.get_text(" ", strip=True) if date_node else None
            title = title_block.get_text(" ", strip=True)
            if date_text:
                title = title.replace(date_text, "").strip()

            link_node = item.select_one("a.thumbnail[href]")
            image_url = self._extract_optional_attr(item, "img", "src")
            status = self._extract_optional_text(item, ".caption_action")

            href = link_node.get("href") if link_node is not None else page_url
            if not isinstance(href, str) or not title:
                continue

            full_link = urljoin(page_url, href)
            full_image = urljoin(page_url, image_url) if image_url else None
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"granfondo-{index}-{stable_hash}",
                    title=title,
                    description=status,
                    city=title.split(",")[0].strip(),
                    region=None,
                    federal_district=None,
                    venue=None,
                    category="Велоспорт",
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=full_image,
                )
            )

        return events


class CyclingRaceParser(CssDirectoryParser):
    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []
        seen_links: set[str] = set()

        for index, link_node in enumerate(soup.select("#race section a[href]")):
            title = self._extract_optional_text(link_node, "div.weight-normal p:nth-of-type(1)")
            date_text = self._extract_optional_text(link_node, "div.weight-normal p:nth-of-type(2)")
            location_text = self._extract_optional_text(link_node, "div.weight-normal p:nth-of-type(3)")
            image_url = self._extract_optional_attr(link_node, "img[alt][src]", "src")
            href = link_node.get("href")
            if not title or not date_text or not isinstance(href, str):
                continue

            full_link = urljoin(page_url, href)
            if full_link in seen_links:
                continue
            seen_links.add(full_link)

            city, venue = self._extract_cyclingrace_location(location_text)
            full_image = urljoin(page_url, image_url) if image_url else None
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"cyclingrace-{index}-{stable_hash}",
                    title=title.strip(),
                    description=None,
                    city=city,
                    region="Москва" if city and "москва" in city.lower() else None,
                    federal_district=None,
                    venue=venue,
                    category="Велоспорт",
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=full_image,
                )
            )

        return events

    def _extract_cyclingrace_location(
        self, location_text: str | None
    ) -> tuple[str | None, str | None]:
        if not location_text:
            return None, None
        parts = [part.strip() for part in location_text.split(",") if part.strip()]
        if len(parts) == 1:
            return parts[0], None
        return parts[0], ", ".join(parts[1:])


class OTimeCalendarParser(CssDirectoryParser):
    MONTHS_EN = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    SPORT_CATEGORY_MAP = {
        "1": "Лыжи",
        "2": "Бег",
        "8": "Ориентирование и туризм",
        "9": "Триатлон",
        "11": "Плавание",
        "12": "Водный спорт",
    }

    async def fetch_events(
        self, client: httpx.AsyncClient
    ) -> list[Event] | None:
        events: list[Event] = []

        for listing_url in self.config.listing_urls:
            try:
                response = await client.get(listing_url)
                response.raise_for_status()
            except httpx.HTTPError:
                continue

            html = response.content.decode("cp1251", errors="ignore")
            events.extend(self.parse(html, str(response.url)))

        return events

    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []
        seen_links: set[str] = set()
        current_year = datetime.now().year
        previous_month = datetime.now().month
        index = 0

        for block in soup.select("div.all"):
            date_node = block.select_one("article.alldate")
            if date_node is None:
                continue

            date_parts = self._extract_otime_date_parts(date_node.get_text(" ", strip=True))
            if not date_parts:
                continue
            day, month = date_parts
            if month < previous_month:
                current_year += 1
            previous_month = month
            date_text = f"{day:02d}.{month:02d}.{current_year}"

            for item in block.select(".allbutton > div.allinner1, .allbutton > div.allinner2"):
                link_node = item.select_one("article.allname a[href]")
                if link_node is None:
                    continue

                href = link_node.get("href")
                title = link_node.get_text(" ", strip=True)
                if not isinstance(href, str) or not href.strip() or not title:
                    continue

                full_link = urljoin(page_url, href)
                if full_link in seen_links:
                    continue
                seen_links.add(full_link)

                place_node = item.select_one("article.allplace")
                region, city, venue = self._extract_otime_location(place_node)
                image_alt = self._extract_optional_attr(item, "article.alllogo img", "alt")
                category = self._infer_otime_category(title, self.SPORT_CATEGORY_MAP.get(image_alt or ""))
                stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

                events.append(
                    Event(
                        id=f"otime-{index}-{stable_hash}",
                        title=title,
                        description=None,
                        city=city,
                        region=region,
                        federal_district=None,
                        venue=venue,
                        category=category,
                        date_text=date_text,
                        starts_at=self._normalize_datetime(date_text),
                        source_name=self.config.name,
                        source_url=full_link,
                        image_url=None,
                    )
                )
                index += 1

        return events

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        semaphore = asyncio.Semaphore(8)
        tasks = [
            asyncio.create_task(self._enrich_otime_event(event, client, semaphore))
            for event in events
        ]
        return await asyncio.gather(*tasks)

    def _extract_otime_date_parts(self, raw_text: str) -> tuple[int, int] | None:
        match = re.search(r"(\d{1,2})\s*([A-Za-z]{3})", raw_text)
        if not match:
            return None
        day = int(match.group(1))
        month = self.MONTHS_EN.get(match.group(2).lower())
        if not month:
            return None
        return day, month

    def _extract_otime_location(
        self, place_node: Any | None
    ) -> tuple[str | None, str | None, str | None]:
        if place_node is None:
            return None, None, None

        full_text = place_node.get_text(" ", strip=True)
        if not full_text:
            return None, None, None

        region_node = place_node.select_one("b")
        region = region_node.get_text(" ", strip=True) if region_node else None
        venue_part = full_text
        if region:
            venue_part = re.sub(rf"^\s*{re.escape(region)}\s*", "", full_text).strip(" ,")

        normalized_region = self._normalize_otime_region(region)
        city = self._extract_otime_city(venue_part, normalized_region)
        venue = venue_part or None

        if not city and normalized_region in {"Санкт-Петербург", "Москва"}:
            city = normalized_region

        return normalized_region, city, venue

    def _normalize_otime_region(self, value: str | None) -> str | None:
        if not value:
            return None
        normalized = re.sub(r"\s+", " ", value).strip(" ,.")
        replacements = {
            " обл": " область",
            "обл.": "область",
            " обл.": " область",
            "АО": "автономный округ",
        }
        for source, target in replacements.items():
            normalized = normalized.replace(source, target)
        return normalized.strip(" ,.") or None

    def _extract_otime_city(
        self,
        venue_part: str | None,
        region: str | None,
    ) -> str | None:
        if not venue_part:
            return None

        patterns = [
            r"\bг\.\s*([^,]+)",
            r"\bпос\.\s*([^,]+)",
            r"\bп\.\s*([^,]+)",
            r"\bдер\.\s*([^,]+)",
            r"\bд\.\s*([^,]+)",
            r"\bс\.\s*([^,]+)",
            r"\bж/д\s*ст\.?\s*([^,]+)",
            r"\bжд/ст\.?\s*([^,]+)",
            r"\bжд\s*ст\.?\s*([^,]+)",
            r"\bст\.?\s*([^,]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, venue_part, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" ,.")

        first_part = venue_part.split(",")[0].strip(" ,.")
        if not first_part:
            return None
        if region and first_part.lower().startswith(region.lower()):
            tail = venue_part[len(first_part):].strip(" ,.")
            return self._extract_otime_city(tail, region)
        if re.match(r"^[А-ЯЁA-Z][А-ЯЁA-Za-zё\- ]+$", first_part):
            return first_part
        return None

    def _infer_otime_category(
        self,
        title: str,
        fallback: str | None,
    ) -> str | None:
        normalized = title.lower()
        if any(token in normalized for token in ["вело", "bike", "mtb", "cycling"]):
            return "Велоспорт"
        if any(token in normalized for token in ["лыж", "ski"]):
            return "Лыжи"
        if any(token in normalized for token in ["swimrun", "триатлон", "дуатлон"]):
            return "Триатлон"
        if any(token in normalized for token in ["плав", "swim", "sup"]):
            return "Плавание"
        if any(token in normalized for token in ["trail", "трейл", "забег", "полумарафон", "марафон", "кросс"]):
            return "Бег"
        return fallback

    async def _enrich_otime_event(
        self,
        event: Event,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Event:
        if event.city:
            return event

        async with semaphore:
            try:
                response = await client.get(str(event.source_url))
                response.raise_for_status()
            except httpx.HTTPError:
                return event

        html = response.content.decode("cp1251", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        location_text = self._extract_otime_detail_location(soup, event.title)
        city = self._extract_otime_city(location_text or event.venue, event.region)
        venue = location_text or event.venue

        return event.model_copy(
            update={
                "city": city or event.city,
                "venue": venue,
            }
        )

    def _extract_otime_detail_location(
        self,
        soup: BeautifulSoup,
        title: str,
    ) -> str | None:
        hero = self._extract_optional_text(soup, ".logonameback3")
        if hero and "::" in hero:
            location_part = hero.split("::", 1)[1]
            normalized_title = re.sub(r"\s+", " ", title).strip()
            if normalized_title:
                location_part = location_part.split(normalized_title, 1)[0]
            location_part = re.split(r"(?:\b[A-ZА-ЯЁ0-9].*202\d\b)", location_part, maxsplit=1)[0]
            cleaned = location_part.strip(" :")
            if cleaned:
                return cleaned

        geolink = self._extract_optional_text(soup, ".ymaps-geolink")
        if geolink and not re.fullmatch(r"[\d.,\s]+", geolink):
            return geolink

        return None


class MarathonCupParser(CssDirectoryParser):
    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []
        seen_links: set[str] = set()

        for index, card in enumerate(soup.select("a.elementor-cta")):
            title = self._extract_optional_text(card, ".elementor-cta__title")
            date_text = self._extract_optional_text(card, ".elementor-cta__button")
            description = self._extract_optional_text(card, ".elementor-cta__description")
            href = card.get("href")
            if not title or not date_text or not isinstance(href, str):
                continue
            if "абонемент" in title.lower():
                continue

            full_link = urljoin(page_url, href)
            if full_link in seen_links:
                continue
            seen_links.add(full_link)
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"marathoncup-{index}-{stable_hash}",
                    title=re.sub(r"\s+", " ", title).strip(),
                    description=description,
                    city=self._extract_marathoncup_city(title),
                    region="Ленинградская область",
                    federal_district=None,
                    venue=None,
                    category="Велоспорт",
                    date_text=f"{date_text} {datetime.now().year}",
                    starts_at=self._normalize_datetime(f"{date_text} {datetime.now().year}"),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=None,
                )
            )

        return events

    def _extract_marathoncup_city(self, title: str) -> str | None:
        normalized = title.lower()
        cities = {
            "петяярви": "Петяярви",
            "ореховый": "Орехово",
            "мичуринский": "Мичуринское",
            "токсов": "Токсово",
            "лемболов": "Лемболово",
            "цвелодубов": "Цвелодубово",
        }
        for token, city in cities.items():
            if token in normalized:
                return city
        return None


class GaltropaParser(CssDirectoryParser):
    async def fetch_events(
        self, client: httpx.AsyncClient
    ) -> list[Event] | None:
        events: list[Event] = []
        seen_urls: set[str] = set()

        for listing_url in self.config.listing_urls:
            try:
                response = await client.get(listing_url)
                response.raise_for_status()
            except httpx.HTTPError:
                continue

            for event in self.parse(response.text, str(response.url)):
                if str(event.source_url) in seen_urls:
                    continue
                seen_urls.add(str(event.source_url))
                events.append(event)

        return events

    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        title = self._extract_optional_text(soup, "h1.t338__title")
        if not title:
            return []
        if re.search(r"дата .*в разработке|августе/сентябре", html, flags=re.IGNORECASE):
            return []

        date_text = self._extract_galtropa_date(title)
        if not date_text:
            return []

        title_text = re.sub(r"\s+", " ", title).strip()
        image_url = self._extract_optional_attr(soup, 'meta[property="og:image"]', "content")
        registration_url = self._extract_galtropa_registration_url(soup, page_url)
        full_link = registration_url or page_url
        stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

        return [
            Event(
                id=f"galtropa-0-{stable_hash}",
                title=title_text,
                description=self._extract_optional_attr(soup, 'meta[name="description"]', "content"),
                city="Галич",
                region="Костромская область",
                federal_district=None,
                venue=None,
                category=self._infer_galtropa_category(page_url, title_text),
                date_text=date_text,
                starts_at=self._normalize_datetime(date_text),
                source_name=self.config.name,
                source_url=full_link,
                image_url=image_url,
            )
        ]

    def _extract_galtropa_registration_url(
        self, soup: BeautifulSoup, page_url: str
    ) -> str | None:
        for link in soup.select('a[href*="myrace.info"], a[href*="orgeo.ru/event"], a[href*="reg.place"]'):
            href = link.get("href")
            if isinstance(href, str):
                return urljoin(page_url, href)
        return None

    def _extract_galtropa_date(self, text: str) -> str | None:
        match = re.search(
            r"(\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+20\d{2})",
            text.lower(),
        )
        if not match:
            return None
        return match.group(1)

    def _infer_galtropa_category(self, page_url: str, title: str) -> str:
        combined = f"{page_url} {title}".lower()
        if "velo" in combined or "вело" in combined:
            return "Велоспорт"
        if "ski" in combined or "лыж" in combined:
            return "Лыжи"
        if "rogaine" in combined or "рогейн" in combined:
            return "Ориентирование и туризм"
        if "snow-kite" in combined or "сноукайт" in combined:
            return "Другие"
        return "Бег"


class NezhesteamParser(CssDirectoryParser):
    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []

        for index, card in enumerate(soup.select("#content .col-lg-4")):
            title = self._extract_optional_text(card, "h3")
            date_text = self._extract_optional_text(card, "p.mb-4")
            href = self._extract_optional_attr(card, 'a[href*="race/?date="]', "href")
            image_url = self._extract_optional_attr(card, "img[src]", "src")
            if not title or not date_text or not href:
                continue

            full_link = urljoin(page_url, href)
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"nezhesteam-{index}-{stable_hash}",
                    title=title,
                    description="Кросс-кантри гонка NEZHESTEAM в Ромашково",
                    city="Ромашково",
                    region="Московская область",
                    federal_district=None,
                    venue=None,
                    category="Велоспорт",
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=urljoin(page_url, image_url) if image_url else None,
                )
            )

        return events


class MyRaceParser(CssDirectoryParser):
    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []

        for index, card in enumerate(soup.select("a.events-list__item.row")):
            href = card.get("href")
            if not isinstance(href, str):
                continue

            title_element = card.select_one("h2")
            if not title_element:
                continue

            title_copy = BeautifulSoup(str(title_element), "html.parser")
            for nested in title_copy.select(".registration-status"):
                nested.decompose()
            title = title_copy.get_text(" ", strip=True)
            if not title:
                continue

            date_text = self._extract_optional_text(card, ".date")
            city = self._extract_optional_text(card, ".flag")
            category = self._extract_optional_text(card, ".type")
            participants = self._extract_optional_text(card, ".counter")
            registration_status = self._extract_optional_text(card, ".registration-status")

            description_parts = [
                f"Участников: {participants}" if participants else None,
                registration_status,
            ]
            description = " • ".join(part for part in description_parts if part) or None

            normalized_city = None if city in {None, "-", "—"} else city
            full_link = urljoin(page_url, href)
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"myrace-{index}-{stable_hash}",
                    title=title,
                    description=description,
                    city=normalized_city,
                    region=None,
                    federal_district=None,
                    venue=None,
                    category=category,
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=None,
                )
            )

        return events

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        tasks = [
            self._enrich_myrace_event(event, client)
            for event in events
            if not event.city or not event.venue
        ]
        if not tasks:
            return events

        enriched_events = await asyncio.gather(*tasks, return_exceptions=True)
        updates = {
            enriched.id: enriched
            for enriched in enriched_events
            if isinstance(enriched, Event)
        }
        return [updates.get(event.id, event) for event in events]

    async def _enrich_myrace_event(
        self, event: Event, client: httpx.AsyncClient
    ) -> Event:
        try:
            response = await client.get(str(event.source_url))
            response.raise_for_status()
        except httpx.HTTPError:
            return event

        soup = BeautifulSoup(response.text, "html.parser")
        hero_city, hero_venue = self._extract_myrace_header_location(soup)
        location_text = self._extract_myrace_location_text(soup)
        venue, city = self._split_myrace_location(location_text)

        return event.model_copy(
            update={
                "city": hero_city or city or event.city,
                "venue": hero_venue or venue or event.venue,
            }
        )

    def _extract_myrace_header_location(
        self, soup: BeautifulSoup
    ) -> tuple[str | None, str | None]:
        header = soup.select_one(".mt-5.text-large")
        if not header:
            return None, None

        city = self._extract_text(header, ".text-strong")
        venue = self._extract_text(header, ".text-muted.text-regular")
        normalized_city = None if city in {None, "-", "—"} else city
        normalized_venue = None if venue in {None, "-", "—"} else venue
        return normalized_city, normalized_venue

    def _extract_myrace_location_text(self, soup: BeautifulSoup) -> str | None:
        for paragraph in soup.select(".event-about p"):
            text = paragraph.get_text(" ", strip=True)
            match = re.search(
                r"Место проведения:\s*(.+?)(?:Дата проведения:|Карта:|$)",
                text,
                re.IGNORECASE,
            )
            if match:
                return match.group(1).strip(" ,")

        for paragraph in soup.select(".event-about p"):
            text = paragraph.get_text(" ", strip=True)
            match = re.search(r"Локация:\s*(.+?)(?:Карта:|$)", text, re.IGNORECASE)
            if match:
                return match.group(1).strip(" ,")

        header_location = soup.select_one(".text-muted.text-regular")
        if header_location:
            return header_location.get_text(" ", strip=True)
        return None

    def _split_myrace_location(self, raw_location: str | None) -> tuple[str | None, str | None]:
        if not raw_location:
            return None, None

        cleaned = re.sub(r"\s+", " ", raw_location).strip(" ,")
        parts = [part.strip(" ,") for part in cleaned.split(",") if part.strip(" ,")]
        if len(parts) >= 2:
            return parts[0], parts[-1]
        return None, cleaned


class IronStarParser(CssDirectoryParser):
    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []

        for index, card in enumerate(soup.select("a.event-item")):
            href = card.get("href")
            if not isinstance(href, str):
                continue

            title = self._extract_ironstar_title(card)
            if not title:
                continue

            date_text = self._extract_optional_text(card, ".event-head-info .date")
            city = self._extract_optional_text(card, ".event-head-info .place")
            image_url = self._extract_optional_attr(card, ".event-image img", "src")
            category = self._infer_ironstar_category(title, href)
            full_link = urljoin(page_url, href)
            full_image = urljoin(page_url, image_url) if image_url else None
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]
            normalized_city = None if city in {None, "-", "—"} else city

            events.append(
                Event(
                    id=f"ironstar-{index}-{stable_hash}",
                    title=title,
                    description=None,
                    city=normalized_city,
                    region=None,
                    federal_district=None,
                    venue=None,
                    category=category,
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=full_image,
                )
            )

        return events

    def _extract_ironstar_title(self, card: Any) -> str | None:
        raw_title = card.get("title")
        if isinstance(raw_title, str):
            normalized = raw_title.strip()
            normalized = re.sub(
                r"\s*-\s*\d{1,2}\.\d{1,2}\.\d{4}(?:\s*-\s*.+)?$",
                "",
                normalized,
            )
            if normalized:
                return normalized
        return self._extract_optional_text(card, ".title")

    def _infer_ironstar_category(self, title: str, href: str) -> str:
        combined = f"{title} {href}".lower()
        if "swimstar" in combined or "swim" in combined:
            return "Плавание"
        if "starkids" in combined or "kids" in combined:
            return "Детские старты"
        return "Триатлон"


class GoldenUltraParser(CssDirectoryParser):
    EXCLUDED_PATHS = {
        "/legend",
        "/legend/",
    }

    async def fetch_events(
        self, client: httpx.AsyncClient
    ) -> list[Event] | None:
        if not self.config.listing_urls:
            return []

        try:
            response = await client.get(self.config.listing_urls[0])
            response.raise_for_status()
        except httpx.HTTPError:
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        page_urls = self._extract_goldenultra_page_urls(soup, self.config.listing_urls[0])
        events: list[Event] = []

        for index, page_url in enumerate(page_urls):
            event = await self._fetch_goldenultra_event(page_url, index, client)
            if event:
                events.append(event)

        return events

    def _extract_goldenultra_page_urls(self, soup: BeautifulSoup, page_url: str) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()

        for link in soup.select('a[href*="goldenultra.ru"], a[href*="ultras.goldenultra.ru"]'):
            href = link.get("href")
            if not isinstance(href, str):
                continue

            full_url = urljoin(page_url, href)
            parsed = httpx.URL(full_url)
            host = parsed.host or ""
            path = parsed.path or "/"

            if host not in {"goldenultra.ru", "www.goldenultra.ru", "ultras.goldenultra.ru"}:
                continue
            if "/en" in path or "lang=en" in href:
                continue
            if path in self.EXCLUDED_PATHS:
                continue
            if any(
                blocked in path
                for blocked in ("/store", "/favs", "/files", "/images", "/index", "/css", "/js")
            ):
                continue
            if path in {"/", ""}:
                continue

            normalized = f"{parsed.scheme}://{host}{path}".rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            urls.append(normalized)

        return urls

    async def _fetch_goldenultra_event(
        self, page_url: str, index: int, client: httpx.AsyncClient
    ) -> Event | None:
        try:
            response = await client.get(page_url)
            response.raise_for_status()
        except httpx.HTTPError:
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        title = self._extract_goldenultra_title(soup, page_url)
        if not title:
            return None

        page_text = soup.get_text(" ", strip=True)
        date_text = self._extract_goldenultra_date(page_text)
        city = self._extract_goldenultra_city(page_text, page_url)
        image_url = self._extract_goldenultra_image(soup, page_url)
        category = self._infer_goldenultra_category(title, page_url)
        stable_hash = hashlib.sha1(page_url.encode("utf-8")).hexdigest()[:12]

        return Event(
            id=f"goldenultra-{index}-{stable_hash}",
            title=title,
            description=None,
            city=city,
            region=None,
            federal_district=None,
            venue=None,
            category=category,
            date_text=date_text,
            starts_at=self._normalize_datetime(date_text),
            source_name=self.config.name,
            source_url=page_url,
            image_url=image_url,
        )

    def _extract_goldenultra_title(self, soup: BeautifulSoup, page_url: str) -> str | None:
        heading = soup.select_one("title")
        if heading:
            text = heading.get_text(" ", strip=True)
            text = re.sub(r"\s*\|\s*Running Heroes Russia.*$", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*\|\s*MyRace.*$", "", text, flags=re.IGNORECASE)
            if text:
                return text

        header = soup.select_one("h1, h2")
        if header:
            return header.get_text(" ", strip=True)
        return page_url.rstrip("/").split("/")[-1]

    def _extract_goldenultra_date(self, text: str) -> str | None:
        match = re.search(
            r"(\d{1,2}(?:\s*-\s*\d{1,2})?(?:\s*-\s*\d{1,2})?\s+"
            r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
            r"\s+20\d{2})",
            text.lower(),
        )
        if match:
            return match.group(1)

        numeric_match = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})", text)
        return numeric_match.group(1) if numeric_match else None

    def _extract_goldenultra_city(self, text: str, page_url: str) -> str | None:
        slug = page_url.rstrip("/").split("/")[-1].lower()
        known_locations = {
            "grut": "Суздаль",
            "madfox": "Переславль-Залесский",
            "crazyowl": "Тутаев",
            "wbu": "Геленджик",
            "kuge": "Териберка",
            "krcs": "Чара",
            "cameltrophy": "Калмыкия",
            "vmr": "Гимолы",
            "plogging": "Москва",
        }
        if slug in known_locations:
            return known_locations[slug]

        for candidate in (
            "суздаль",
            "переславль-залесский",
            "геленджик",
            "териберка",
            "чара",
            "калмыкия",
            "гимолы",
            "тутаев",
            "москва",
        ):
            if candidate in text.lower():
                return candidate.title() if candidate != "переславль-залесский" else "Переславль-Залесский"
        return None

    def _extract_goldenultra_image(self, soup: BeautifulSoup, page_url: str) -> str | None:
        og_image = soup.select_one('meta[property="og:image"]')
        if og_image and og_image.get("content"):
            return urljoin(page_url, str(og_image.get("content")))

        hero_image = soup.select_one('div[style*="background-image"]')
        if hero_image:
            style = hero_image.get("style")
            if isinstance(style, str):
                match = re.search(r'url\(["\']?(.+?)["\']?\)', style)
                if match:
                    return urljoin(page_url, match.group(1))
        return None

    def _infer_goldenultra_category(self, title: str, page_url: str) -> str:
        combined = f"{title} {page_url}".lower()
        if "plogging" in combined:
            return "Ходьба"
        return "Бег"


class ArfCalendarParser(CssDirectoryParser):
    async def fetch_events(
        self, client: httpx.AsyncClient
    ) -> list[Event] | None:
        if not self.config.listing_urls:
            return []

        try:
            response = await client.get(self.config.listing_urls[0])
            response.raise_for_status()
        except httpx.HTTPError:
            return []

        html = response.content.decode("cp1251", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []

        for index, card in enumerate(soup.select("#short-links-section-events-future .nav-item")):
            link = card.select_one("a.short-news-link")
            if not link:
                continue

            href = link.get("href")
            title = link.get_text(" ", strip=True)
            if not isinstance(href, str) or not title:
                continue

            date_text = self._extract_optional_text(card, "[id^='event-date-']")
            meta_text = self._extract_optional_text(card, ".subhead.event-add-strings")
            city, venue = self._extract_arf_location(meta_text)
            category = self._infer_arf_category(title, meta_text)
            full_link = urljoin(self.config.base_url, href)
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"arf-{index}-{stable_hash}",
                    title=title,
                    description=None,
                    city=city,
                    region=None,
                    federal_district=None,
                    venue=venue,
                    category=category,
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=None,
                )
            )

        return events

    def _extract_arf_location(self, meta_text: str | None) -> tuple[str | None, str | None]:
        if not meta_text:
            return None, None

        lines = [line.strip(" ,") for line in meta_text.splitlines() if line.strip()]
        cleaned_lines = [line for line in lines if "arf.by" not in line.lower()]
        venue = cleaned_lines[-1] if cleaned_lines else None

        city = None
        search_pool = " ".join(cleaned_lines).lower()
        for candidate in ("минск", "логойск", "полоцк", "гродно", "гомель", "витебск", "могилев", "брест"):
            if candidate in search_pool:
                city = candidate.title()
                break

        return city or venue, venue

    def _infer_arf_category(self, title: str, meta_text: str | None) -> str:
        combined = f"{title} {meta_text or ''}".lower()
        if any(token in combined for token in ("вел", "bike", "mtb", "velo")):
            return "Велоспорт"
        if any(token in combined for token in ("бег", "trail", "кросс", "run")):
            return "Бег"
        return "Другие"


class VelogearanceParser(CssDirectoryParser):
    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []

        for index, card in enumerate(soup.select("article.post")):
            title_element = card.select_one(".entry-title a")
            if not title_element:
                continue

            href = title_element.get("href")
            title = title_element.get_text(" ", strip=True)
            if not isinstance(href, str) or not title:
                continue

            date_text = self._extract_velogearance_date(title)
            city = self._extract_velogearance_city(title)
            image_url = self._extract_optional_attr(card, ".grid-box-img img", "src")
            description = self._extract_optional_text(card, ".entry-content")
            full_link = urljoin(page_url, href)
            full_image = urljoin(page_url, image_url) if image_url else None
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"velogearance-{index}-{stable_hash}",
                    title=title,
                    description=description,
                    city=city,
                    region=None,
                    federal_district=None,
                    venue=None,
                    category="Велоспорт",
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=full_image,
                )
            )

        return events

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        tasks = [
            self._enrich_velogearance_event(event, client)
            for event in events
            if not event.city or not event.date_text or not event.starts_at or not event.venue
        ]
        if not tasks:
            return events

        enriched_events = await asyncio.gather(*tasks, return_exceptions=True)
        updates = {
            enriched.id: enriched
            for enriched in enriched_events
            if isinstance(enriched, Event)
        }
        return [updates.get(event.id, event) for event in events]

    async def _enrich_velogearance_event(
        self, event: Event, client: httpx.AsyncClient
    ) -> Event:
        try:
            response = await client.get(str(event.source_url))
            response.raise_for_status()
        except httpx.HTTPError:
            return event

        soup = BeautifulSoup(response.text, "html.parser")
        page_title = self._extract_optional_text(soup, "title") or event.title
        content_text = self._extract_optional_text(soup, ".entry-content") or ""
        combined = f"{page_title} {event.title} {content_text}"

        date_text = event.date_text or self._extract_velogearance_date(combined)
        city, venue = self._extract_velogearance_location(combined)

        return event.model_copy(
            update={
                "date_text": date_text or event.date_text,
                "starts_at": self._normalize_datetime(date_text) or event.starts_at,
                "city": city or event.city,
                "venue": venue or event.venue,
            }
        )

    def _extract_velogearance_date(self, title: str) -> str | None:
        compact = re.search(r"(\d{1,2})\|(\d{1,2})\|(\d{4})", title)
        if compact:
            day, month, year = compact.groups()
            return f"{day.zfill(2)}.{month.zfill(2)}.{year}"

        slash = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", title)
        if slash:
            day, month, year = slash.groups()
            return f"{day.zfill(2)}.{month.zfill(2)}.{year}"

        match = re.search(
            r"(\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4})",
            title.lower(),
        )
        if match:
            return match.group(1)
        return None

    def _extract_velogearance_city(self, title: str) -> str | None:
        lowered = title.lower()
        if "чулково" in lowered:
            return "Чулково"
        if "битц" in lowered or "битца" in lowered:
            return "Москва"
        if "московская область" in lowered:
            return "Московская область"
        return None

    def _extract_velogearance_location(self, text: str) -> tuple[str | None, str | None]:
        lowered = text.lower()
        if "чулково" in lowered:
            return "Чулково", "Чулково"
        if "битц" in lowered or "битца" in lowered:
            return "Москва", "Битца"
        if "поселок володарского" in lowered:
            return "Московская область", "поселок Володарского"
        if "московская область" in lowered:
            return "Московская область", "Московская область"
        return self._extract_velogearance_city(text), None


class XCNewsParser(CssDirectoryParser):
    async def fetch_events(
        self, client: httpx.AsyncClient
    ) -> list[Event] | None:
        if not self.config.listing_urls:
            return []

        try:
            response = await client.get(self.config.listing_urls[0])
            response.raise_for_status()
        except httpx.HTTPError:
            return []

        html = response.content.decode("cp1251", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []

        for index, row in enumerate(soup.select("table tr")):
            cells = row.select("td")
            if len(cells) < 4:
                continue

            link = cells[1].select_one("a")
            if not link:
                continue

            href = link.get("href")
            title = link.get_text(" ", strip=True)
            date_text = cells[0].get_text(" ", strip=True)
            location_text = cells[2].get_text(" ", strip=True)
            race_type = cells[3].get_text(" ", strip=True)
            if not isinstance(href, str) or not title or not re.match(r"\d{2}\.\d{2}\.\d{4}", date_text):
                continue

            city, venue = self._extract_xcnews_location(location_text)
            category = self._infer_xcnews_category(title, race_type)
            full_link = urljoin(self.config.base_url, href)
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"xcnews-{index}-{stable_hash}",
                    title=title,
                    description=None,
                    city=city,
                    region=None,
                    federal_district=None,
                    venue=venue,
                    category=category,
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=None,
                )
            )

        return events

    def _extract_xcnews_location(self, raw_location: str | None) -> tuple[str | None, str | None]:
        if not raw_location:
            return None, None

        cleaned = re.sub(r"\s+", " ", raw_location).strip(" ,")
        parts = [part.strip(" ,") for part in cleaned.split(",") if part.strip(" ,")]
        if len(parts) >= 2:
            return parts[0], cleaned
        return cleaned, cleaned

    def _infer_xcnews_category(self, title: str, race_type: str | None) -> str:
        combined = f"{title} {race_type or ''}".lower()
        if any(token in combined for token in ("xco", "xcm", "xcc", "mtb", "вело", "кросс-кантри")):
            return "Велоспорт"
        return "Другие"
