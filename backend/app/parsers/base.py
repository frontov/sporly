from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
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
            if full_url == page_url:
                continue
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

    def _extract_distance_summary_from_text(self, text: str | None) -> str | None:
        if not text:
            return None

        normalized = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
        if not normalized:
            return None

        distances: list[str] = []

        group_match = re.search(
            r"(\d+(?:[.,]\d+)?(?:\s*(?:/|и|-|•|;|,\s+)\s*\d+(?:[.,]\d+)?)+)\s*(км|km)\b",
            normalized,
            flags=re.IGNORECASE,
        )
        if group_match:
            for value in re.findall(r"\d+(?:[.,]\d+)?", group_match.group(1)):
                value = self._normalize_distance_value(value)
                if value:
                    label = f"{value} км"
                    if label not in distances:
                        distances.append(label)

        for value, _unit in re.findall(r"(\d+(?:[.,]\d+)?)\s*(км|km)\b", normalized, flags=re.IGNORECASE):
            label = f"{self._normalize_distance_value(value)} км"
            if label not in distances:
                distances.append(label)

        for value, _unit in re.findall(r"(\d{3,5})\s*(м)\b", normalized, flags=re.IGNORECASE):
            meters = int(value)
            if meters >= 200 and meters <= 10000:
                label = f"{meters} м"
                if label not in distances:
                    distances.append(label)

        if not distances:
            return None
        return " • ".join(distances)

    def _normalize_distance_value(self, value: str) -> str:
        cleaned = value.strip().replace(",", ".")
        if cleaned.endswith(".0"):
            cleaned = cleaned[:-2]
        return cleaned

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
    async def fetch_events(
        self, client: httpx.AsyncClient
    ) -> list[Event] | None:
        if not self.config.listing_urls:
            return []

        first_url = self.config.listing_urls[0]
        try:
            first_response = await client.get(first_url)
            first_response.raise_for_status()
        except httpx.HTTPError:
            return []

        listing_pages = [str(first_response.url), *self.extract_pagination_urls(first_response.text, str(first_response.url))]
        event_urls = self._extract_regplace_event_urls(first_response.text, str(first_response.url))

        for page_url in listing_pages[1:]:
            try:
                response = await client.get(page_url)
                response.raise_for_status()
            except httpx.HTTPError:
                continue
            event_urls.extend(self._extract_regplace_event_urls(response.text, str(response.url)))

        unique_urls: list[str] = []
        seen_urls: set[str] = set()
        for event_url in event_urls:
            if event_url in seen_urls:
                continue
            seen_urls.add(event_url)
            unique_urls.append(event_url)

        semaphore = asyncio.Semaphore(10)
        tasks = [
            asyncio.create_task(self._fetch_regplace_detail_event(url, client, semaphore))
            for url in unique_urls
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        events: list[Event] = []
        for result in results:
            if isinstance(result, Event):
                events.append(result)
        return events

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
                    description=self._merge_regplace_description(description, full_link, title),
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

    def _extract_regplace_event_urls(self, html: str, page_url: str) -> list[str]:
        matches = re.findall(r'/(events/[a-z0-9\-]+)', html)
        urls: list[str] = []
        seen: set[str] = set()
        for match in matches:
            full_url = urljoin(page_url, match)
            if full_url in seen:
                continue
            seen.add(full_url)
            urls.append(full_url)
        return urls

    async def _fetch_regplace_detail_event(
        self,
        event_url: str,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Event | None:
        async with semaphore:
            try:
                response = await client.get(event_url)
                response.raise_for_status()
            except httpx.HTTPError:
                return None

        return self._parse_regplace_detail_page(response.text, str(response.url))

    def _parse_regplace_detail_page(self, html: str, page_url: str) -> Event | None:
        soup = BeautifulSoup(html, "html.parser")
        title = self._extract_optional_text(soup, "h1")
        if not title:
            return None

        date_text = self._extract_optional_text(soup, "h2")
        lead_text = self._extract_optional_text(soup, "p.lead.text-muted")
        description_text = self._extract_optional_text(soup, ".event-description")
        description_meta = soup.find("meta", attrs={"name": "description"})
        description_meta_text = (
            description_meta.get("content")
            if description_meta and isinstance(description_meta.get("content"), str)
            else None
        )
        keywords_meta = soup.find("meta", attrs={"name": "keywords"})
        keywords_text = (
            keywords_meta.get("content")
            if keywords_meta and isinstance(keywords_meta.get("content"), str)
            else None
        )
        image_url = self._extract_optional_attr(soup, ".cover .logo", "src")
        page_location_text, venue = self._extract_regplace_location_block(soup)
        location_text = " ".join(
            part
            for part in [lead_text, description_meta_text, keywords_text, page_location_text]
            if part
        ) or None
        city = self._extract_regplace_city(location_text, title)
        venue = venue or self._extract_regplace_venue(location_text)
        category = self._extract_regplace_category(location_text or description_text or title)
        organizer_name = self._extract_regplace_organizer(soup)
        registration_status, registration_deadline = self._extract_regplace_registration_details(soup)
        price_from = self._extract_regplace_price(soup)
        distance_summary = self._extract_regplace_distance_summary(
            soup,
            title,
            lead_text,
            description_text,
            description_meta_text,
            keywords_text,
            page_location_text,
        )
        full_image = urljoin(page_url, image_url) if image_url else None
        stable_hash = hashlib.sha1(page_url.encode("utf-8")).hexdigest()[:12]

        return self._enrich_regplace_from_title(
            Event(
                id=f"reg-place-detail-{stable_hash}",
                title=title,
                description=self._merge_regplace_description(
                    description_text or description_meta_text,
                    page_url,
                    title,
                ),
                city=city,
                region=None,
                federal_district=None,
                venue=venue,
                category=category,
                date_text=date_text,
                starts_at=self._normalize_datetime(date_text),
                organizer_name=organizer_name,
                registration_status=registration_status,
                registration_deadline=registration_deadline,
                price_from=price_from,
                distance_summary=distance_summary,
                source_name=self.config.name,
                source_url=page_url,
                image_url=full_image,
            )
        )

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
        semaphore = asyncio.Semaphore(8)
        tasks = [
            asyncio.create_task(self._enrich_regplace_event(event, client, semaphore))
            for event in events
        ]
        return await asyncio.gather(*tasks)

    async def _enrich_regplace_event(
        self,
        event: Event,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Event:
        if (
            event.date_text
            and event.city
            and event.organizer_name
            and event.registration_status
            and event.price_from
        ):
            return event

        async with semaphore:
            try:
                response = await client.get(str(event.source_url))
                response.raise_for_status()
            except httpx.HTTPError:
                return self._enrich_regplace_from_title(event)

        soup = BeautifulSoup(response.text, "html.parser")
        date_text = event.date_text or self._extract_optional_text(soup, "h2")
        lead_text = self._extract_optional_text(soup, "p.lead.text-muted")
        description_meta = soup.find("meta", attrs={"name": "description"})
        description_text = (
            description_meta.get("content")
            if description_meta and isinstance(description_meta.get("content"), str)
            else None
        )
        keywords_meta = soup.find("meta", attrs={"name": "keywords"})
        keywords_text = (
            keywords_meta.get("content")
            if keywords_meta and isinstance(keywords_meta.get("content"), str)
            else None
        )
        page_location_text, page_venue = self._extract_regplace_location_block(soup)
        location_text = " ".join(
            part
            for part in [lead_text, description_text, keywords_text, page_location_text]
            if part
        ) or None
        city = event.city or self._extract_regplace_city(location_text, event.title)
        venue = event.venue or page_venue or self._extract_regplace_venue(location_text)
        category = event.category or self._extract_regplace_category(location_text)
        organizer_name = event.organizer_name or self._extract_regplace_organizer(soup)
        registration_status, registration_deadline = self._extract_regplace_registration_details(soup)
        price_from = self._extract_regplace_price(soup)
        distance_summary = self._extract_regplace_distance_summary(
            soup,
            event.title,
            lead_text,
            description_text,
            keywords_text,
            page_location_text,
        )

        return self._enrich_regplace_from_title(
            event.model_copy(
                update={
                    "date_text": date_text,
                    "starts_at": self._normalize_datetime(date_text),
                    "city": city,
                    "venue": venue,
                    "category": category,
                    "organizer_name": organizer_name,
                    "registration_status": registration_status or event.registration_status,
                    "registration_deadline": registration_deadline or event.registration_deadline,
                    "price_from": price_from or event.price_from,
                    "distance_summary": distance_summary or event.distance_summary,
                    "description": self._merge_regplace_description(
                        event.description, str(event.source_url), event.title
                    ),
                }
            )
        )

    def _enrich_regplace_from_title(self, event: Event) -> Event:
        city = event.city or self._extract_regplace_city(None, event.title)
        return event.model_copy(update={"city": city})

    def _extract_regplace_location_block(
        self,
        soup: BeautifulSoup,
    ) -> tuple[str | None, str | None]:
        location_parts: list[str] = []
        venue: str | None = None

        location_map = soup.select_one("event-location-map[address]")
        if location_map and isinstance(location_map.get("address"), str):
            address = location_map.get("address", "").strip()
            if address:
                location_parts.append(address)
                venue = address

        place_heading = soup.find(id="place")
        if place_heading:
            place_paragraph = place_heading.find_next("p")
            if place_paragraph:
                place_text = place_paragraph.get_text(" ", strip=True)
                if place_text:
                    location_parts.append(place_text)
                    if not venue:
                        venue = re.split(r"\.\s+", place_text, maxsplit=1)[-1].strip()

        location_text = " ".join(part for part in location_parts if part).strip() or None
        return location_text, venue

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
            (r"\bРязань\b", "Рязань"),
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
            (r"\bСергиев[-\s]?Посад\b", "Сергиев Посад"),
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
            (r"\bПетропавловск[-\s]?Камчатск", "Петропавловск-Камчатский"),
            (r"\bОдинцово\b", "Одинцово"),
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

    def _extract_regplace_organizer(self, soup: BeautifulSoup) -> str | None:
        title = self._extract_optional_text(soup, ".organizer-card .card-title")
        return title or None

    def _extract_regplace_registration_details(
        self,
        soup: BeautifulSoup,
    ) -> tuple[str | None, str | None]:
        cta = self._extract_optional_text(soup, ".btn-cta")
        deadline_text = self._extract_optional_text(soup, ".links .small.text-center")
        status = None
        if cta:
            normalized = cta.casefold()
            if "закрыт" in normalized:
                status = "closed"
            elif "зарегистр" in normalized:
                status = "open"

        deadline = None
        if deadline_text:
            normalized_deadline = re.sub(r"\s+", " ", deadline_text).strip()
            deadline = (
                normalized_deadline
                if normalized_deadline.casefold().startswith("до ")
                else f"до {normalized_deadline}"
            )
        return status, deadline

    def _extract_regplace_price(self, soup: BeautifulSoup) -> str | None:
        values: list[int] = []
        for cta in soup.select(".race-card__actions .btn-cta"):
            text = cta.get_text(" ", strip=True)
            if "бесплатн" in text.casefold():
                return "от 0 ₽"
            match = re.search(r"(\d[\d\s]{2,6})\s*₽", text)
            if not match:
                continue
            try:
                values.append(int(re.sub(r"\s+", "", match.group(1))))
            except ValueError:
                continue
        if not values:
            return None
        return f"от {min(values)} ₽"

    def _extract_regplace_distance_summary(
        self,
        soup: BeautifulSoup,
        *texts: str | None,
    ) -> str | None:
        values: list[str] = []
        seen: set[str] = set()

        for node in soup.select(".race-card__title, .race-card__limits, .race-card__meta-item"):
            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip(" ,.")
            if not text:
                continue
            normalized = self._extract_distance_summary_from_text(text)
            candidate = normalized
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            values.append(candidate)

        if values:
            return " • ".join(values)

        race_card_text = " ".join(
            node.get_text(" ", strip=True)
            for node in soup.select(".race-card, .card-race, [class*='race-card']")
        )
        combined = " ".join(part for part in [*texts, race_card_text] if part)
        return self._extract_distance_summary_from_text(combined)

    def _extract_regplace_category(self, text: str | None) -> str | None:
        if not text:
            return None
        category_patterns = [
            (r"\bвеломарафон\b|\bвелогонк|\bmtb\b|\bgravel\b|\bвелокросс\b", "Велоспорт"),
            (r"\bзабег\b|\bбег\b|\bтрейл\b|\bкросс\b|\bмарафон\b|\bполумарафон\b", "Бег"),
            (r"\bплаван", "Плавание"),
            (r"\bлыж", "Лыжи"),
            (r"\bтриатлон\b|\bдуатлон\b|\bакватлон\b", "Триатлон"),
        ]
        for pattern, category in category_patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return category
        return None

    def _merge_regplace_description(
        self,
        description: str | None,
        source_url: str,
        title: str,
    ) -> str | None:
        extra: list[str] = []
        if self._is_mvm_event(source_url, title) and (
            not description or "серия мвм 2026" not in description.casefold()
        ):
            extra.append("Серия МВМ 2026")
        parts = [part for part in [description, " • ".join(extra) if extra else None] if part]
        return " • ".join(parts) if parts else None

    def _is_mvm_event(self, source_url: str, title: str) -> bool:
        haystack = f"{source_url} {title}".casefold()
        markers = (
            "mvm",
            "1perviy-etap-mvm",
            "gabo-velomarathon-2026",
            "stupinskiy-velomarathon-2026",
            "yakhromskiy-velomarathon-2026",
            "moscow-velomarathon-2026",
            "tomilinskiy-velomarathon-2026",
        )
        return any(marker in haystack for marker in markers)


class OrgeoParser(CssDirectoryParser):
    async def fetch_events(
        self, client: httpx.AsyncClient
    ) -> list[Event] | None:
        if not self.config.listing_urls:
            return []

        events: list[Event] = []
        page_queue = list(self.config.listing_urls)
        seen_pages: set[str] = set()

        while page_queue and len(seen_pages) < max(self.config.max_pages, 1):
            page_url = page_queue.pop(0)
            if page_url in seen_pages:
                continue

            try:
                response = await client.get(page_url)
                response.raise_for_status()
            except httpx.HTTPError:
                continue

            current_url = str(response.url)
            if current_url in seen_pages:
                continue

            seen_pages.add(current_url)
            events.extend(self.parse(response.text, current_url))

            for next_url in self.extract_pagination_urls(response.text, current_url):
                if next_url not in seen_pages and next_url not in page_queue:
                    page_queue.append(next_url)

        return events

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
        enriched = await asyncio.gather(*tasks, return_exceptions=True)
        result: list[Event] = []
        for original_event, enriched_event in zip(events, enriched):
            if isinstance(enriched_event, Exception):
                result.append(original_event)
                continue
            result.append(enriched_event)
        return result

    async def _enrich_orgeo_event(
        self,
        event: Event,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Event:
        if (
            event.starts_at
            and event.city
            and event.organizer_name
            and event.registration_status
            and event.price_from
        ):
            return event

        try:
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
            organizer_name = self._extract_orgeo_organizer(soup)
            registration_status, registration_deadline = self._extract_orgeo_registration_details(soup)
            price_from = self._extract_orgeo_price(soup)
            distance_summary = self._extract_distance_summary_from_text(soup.get_text(" ", strip=True))

            return event.model_copy(
                update={
                    "date_text": date_text or event.date_text,
                    "starts_at": starts_at or self._normalize_datetime(date_text),
                    "region": region or event.region,
                    "city": city or event.city,
                    "venue": venue or event.venue,
                    "organizer_name": organizer_name or event.organizer_name,
                    "registration_status": registration_status or event.registration_status,
                    "registration_deadline": registration_deadline or event.registration_deadline,
                    "price_from": price_from or event.price_from,
                    "distance_summary": distance_summary or event.distance_summary,
                }
            )
        except Exception:
            return event

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

    def _extract_orgeo_organizer(self, soup: BeautifulSoup) -> str | None:
        organizer = self._extract_optional_attr(soup, '[itemprop="organizer"] [itemprop="name"]', "content")
        if organizer:
            return organizer
        creator_heading = soup.find("h4", string=re.compile("Событие создал", re.IGNORECASE))
        if creator_heading:
            link = creator_heading.find_next("a")
            if link:
                text = link.get_text(" ", strip=True)
                if text:
                    return text
        return None

    def _extract_orgeo_registration_details(
        self,
        soup: BeautifulSoup,
    ) -> tuple[str | None, str | None]:
        text = soup.get_text(" ", strip=True)
        label_text = None
        label = soup.select_one(".label.label-default")
        if label is not None:
            label_text = label.get_text(" ", strip=True)

        haystack = " ".join(part for part in [label_text, text] if part).casefold()
        status = None
        if "регистрация закрыта" in haystack:
            status = "closed"
        elif "лист ожидания" in haystack:
            status = "limited"
        elif "регистрация" in haystack and "закрыта" not in haystack:
            status = "open"

        deadline = None
        deadline_match = re.search(
            r"(?:заявки принимаются до|регистрация закрыта)\s+(\d{1,2}\.\d{1,2}\.\d{4}(?:\s+\d{2}:\d{2})?)",
            text,
            flags=re.IGNORECASE,
        )
        if deadline_match:
            deadline = f"до {deadline_match.group(1)}"

        return status, deadline

    def _extract_orgeo_price(self, soup: BeautifulSoup) -> str | None:
        values: list[int] = []
        for cell in soup.select("table.table_dist_price td.text-center"):
            text = cell.get_text(" ", strip=True)
            match = re.search(r"(\d[\d\s]{2,6})\s*₽", text)
            if not match:
                continue
            try:
                values.append(int(re.sub(r"\s+", "", match.group(1))))
            except ValueError:
                continue
        if not values:
            return None
        return f"от {min(values)} ₽"


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
                    distance_summary=self._extract_distance_summary_from_text(title),
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
            distance_summary = self._extract_distance_summary_from_text(soup.get_text(" ", strip=True))

            enriched.append(
                self._apply_runc_title_hints(
                    event.model_copy(
                        update={
                            "date_text": date_text,
                            "starts_at": self._normalize_datetime(date_text),
                            "city": city,
                            "venue": venue,
                            "distance_summary": distance_summary or event.distance_summary,
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
                    distance_summary=self._extract_distance_summary_from_text(
                        " ".join(part for part in (title, description) if part)
                    ),
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
                        "distance_summary": self._extract_distance_summary_from_text(
                            soup.get_text(" ", strip=True)
                        )
                        or event.distance_summary,
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
                    distance_summary=self._extract_distance_summary_from_text(title),
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
            fetched_date, fetched_city, fetched_venue, fetched_distance_summary = (
                await self._fetch_russiarunning_details(
                    str(event.source_url),
                    client,
                )
            )

        date_text = inferred_date or fetched_date
        return event.model_copy(
            update={
                "date_text": date_text,
                "starts_at": self._normalize_datetime(date_text),
                "city": inferred_city or fetched_city,
                "venue": fetched_venue,
                "distance_summary": event.distance_summary or fetched_distance_summary,
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
    ) -> tuple[str | None, str | None, str | None, str | None]:
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
            distance_summary = self._extract_distance_summary_from_text(soup.get_text(" ", strip=True))
            date_text = self._extract_optional_text(soup, ".event-date")
            place_text = self._extract_optional_text(soup, ".place")
            if date_text or place_text:
                city, venue = self._extract_russiarunning_place(place_text)
                if date_text and self._looks_like_russiarunning_date(date_text):
                    return self._cleanup_russiarunning_date(date_text), city, venue, distance_summary
                if city or venue:
                    return None, city, venue, distance_summary

            for selector in (
                "p.text-medium-semibold.mb-0-75",
                ".text-medium-semibold.mb-0-75",
                ".event-date",
                "[data-testid='event-date']",
            ):
                value = self._extract_optional_text(soup, selector)
                if value and self._looks_like_russiarunning_date(value):
                    return self._cleanup_russiarunning_date(value), None, None, distance_summary

        return None, None, None, None

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
        organizer_name = item.get("organizerName")
        registration_status, registration_deadline = self._extract_russiarunning_registration_details(item)
        distance_summary = self._extract_russiarunning_distance_summary(item) or self._extract_distance_summary_from_text(
            " ".join(
                part
                for part in (
                    title,
                    item.get("sportSeriesTitle") if isinstance(item.get("sportSeriesTitle"), str) else None,
                    item.get("raceDescription") if isinstance(item.get("raceDescription"), str) else None,
                    json.dumps(item, ensure_ascii=False),
                )
                if part
            )
        )

        return Event(
            id=f"russiarunning-{code}",
            title=title.strip(),
            description=description,
            organizer_name=organizer_name.strip() if isinstance(organizer_name, str) and organizer_name.strip() else None,
            registration_status=registration_status,
            registration_deadline=registration_deadline,
            distance_summary=distance_summary,
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

    def _extract_russiarunning_registration_details(
        self,
        item: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        race_items = item.get("raceItems")
        if not isinstance(race_items, list) or not race_items:
            return None, None

        statuses: list[str] = []
        deadlines: list[str] = []

        for race_item in race_items:
            if not isinstance(race_item, dict):
                continue

            registration_state = race_item.get("registrationDateState")
            disable_registration = race_item.get("disableRegistration")
            available_count = race_item.get("availableRegistrationsCount")

            status = None
            if disable_registration is True:
                status = "closed"
            elif registration_state == 3:
                status = "open"
            elif registration_state in {1, 2}:
                status = "limited"

            if isinstance(available_count, int):
                if available_count <= 0:
                    status = "closed"
                elif available_count < 10 and status == "open":
                    status = "limited"

            if status:
                statuses.append(status)

            close_date = race_item.get("registrationCloseDate")
            if isinstance(close_date, str) and close_date.strip():
                formatted = self._format_russiarunning_date_text(close_date.strip())
                if formatted:
                    deadlines.append(f"до {formatted}")

        registration_status = None
        if "open" in statuses:
            registration_status = "open"
        elif "limited" in statuses:
            registration_status = "limited"
        elif "closed" in statuses:
            registration_status = "closed"

        registration_deadline = None
        if deadlines:
            registration_deadline = sorted(deadlines, key=len)[0]

        return registration_status, registration_deadline

    def _extract_russiarunning_distance_summary(self, item: dict[str, Any]) -> str | None:
        race_items = item.get("raceItems")
        if not isinstance(race_items, list):
            return None

        values: list[str] = []
        seen: set[str] = set()
        for race_item in race_items:
            if not isinstance(race_item, dict):
                continue
            distance = race_item.get("distance")
            if not isinstance(distance, (int, float)) or distance <= 0:
                continue
            formatted = self._format_russiarunning_distance_value(float(distance))
            if not formatted or formatted in seen:
                continue
            seen.add(formatted)
            values.append(formatted)

        if not values:
            return None
        return " • ".join(values)

    def _format_russiarunning_distance_value(self, value: float) -> str | None:
        if value <= 0:
            return None
        if value < 1:
            meters = int(round(value * 1000))
            if meters <= 0:
                return None
            return f"{meters} м"

        normalized = self._normalize_distance_value(str(value))
        if not normalized:
            return None
        return f"{normalized} км"


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
                    distance_summary=self._extract_distance_summary_from_text(
                        " ".join(part for part in (title, venue) if part)
                    ),
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

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        semaphore = asyncio.Semaphore(8)
        tasks = [
            asyncio.create_task(self._enrich_arta_event(event, client, semaphore))
            for event in events
        ]
        return await asyncio.gather(*tasks)

    async def _enrich_arta_event(
        self,
        event: Event,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Event:
        if event.distance_summary:
            return event
        async with semaphore:
            try:
                response = await client.get(str(event.source_url))
                response.raise_for_status()
            except httpx.HTTPError:
                return event

        soup = BeautifulSoup(response.text, "html.parser")
        distance_summary = self._extract_distance_summary_from_text(soup.get_text(" ", strip=True))
        return event.model_copy(update={"distance_summary": distance_summary or event.distance_summary})

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
        return TriNitiCupParser(self.config).parse(html, page_url)

    def _should_skip_marzocchi_event(self, title: str) -> bool:
        normalized = title.casefold().replace("ё", "е")
        if re.search(r"^\d+\s*[-йя]?\s*этап\s+tri\s*niti\s+cup", normalized):
            return True
        if "общая регистрация" in normalized and "веломарафон" in normalized:
            return True
        return False

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
        return events

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


class TriNitiCupParser(CssDirectoryParser):
    STAGE_PATTERN = re.compile(
        r"^(?P<stage>\d+)\s*этап(?:\s*[.\-–—]\s*|\.\s*)(?P<title>.+)$",
        flags=re.IGNORECASE,
    )

    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        content = soup.select_one(".text-item")
        if content is None:
            return []

        lines = [
            self._clean_tri_niti_line(node.get_text(" ", strip=True))
            for node in content.select("p")
        ]
        lines = [line for line in lines if line]
        events: list[Event] = []

        collecting = False
        pending_stage: tuple[int, str] | None = None
        for line in lines:
            lowered = line.lower()
            if "серия гонок" in lowered and "tri niti" in lowered:
                collecting = True
                continue
            if not collecting:
                continue
            if "все перечисленные соревнования" in lowered:
                break
            if "не входит в общий зачет" in lowered:
                continue

            stage_match = self.STAGE_PATTERN.match(line)
            if stage_match:
                stage_number = int(stage_match.group("stage"))
                stage_title = stage_match.group("title").strip(" .")
                pending_stage = (stage_number, stage_title)
                continue

            if pending_stage is None:
                continue

            if not re.search(r"\d{1,2}\s+[а-яА-Я]+", line):
                continue

            stage_number, stage_title = pending_stage
            pending_stage = None
            stage_title = self._normalize_tri_niti_title(stage_title)
            date_text, venue = self._split_tri_niti_date_and_venue(line)
            city = self._extract_tri_niti_city(venue)
            region = self._extract_tri_niti_region(venue)
            stable_hash = hashlib.sha1(f"{page_url}#{stage_number}".encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"tri-niti-cup-{stage_number}-{stable_hash}",
                    title=stage_title,
                    description=f"{stage_number} этап TRI NITI CUP 2026",
                    city=city,
                    region=region,
                    federal_district=None,
                    venue=venue,
                    category="Велоспорт",
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=f"{page_url}#stage-{stage_number}",
                    image_url=None,
                )
            )

        return events

    def _clean_tri_niti_line(self, value: str) -> str:
        cleaned = re.sub(r"\s+", " ", value).strip()
        return cleaned.replace("TRI NITI CUP 2025", "TRI NITI CUP 2026")

    def _normalize_tri_niti_title(self, value: str) -> str:
        cleaned = value.strip(" .")
        if re.search(r"\b20\d{2}\b", cleaned):
            return cleaned
        return f"{cleaned} 2026"

    def _split_tri_niti_date_and_venue(self, line: str) -> tuple[str | None, str | None]:
        match = re.match(
            r"(?P<date>\d{1,2}\s+[а-яА-Я]+(?:\s+\d{4})?)\.?\s*(?P<venue>.*)$",
            line.strip(),
        )
        if not match:
            return None, line.strip(" ,.")
        date_text = match.group("date").strip(" .")
        if not re.search(r"\d{4}", date_text):
            date_text = f"{date_text} 2026"
        venue = match.group("venue").strip(" ,.")
        return date_text, venue or None

    def _extract_tri_niti_city(self, venue: str | None) -> str | None:
        if not venue:
            return None
        patterns = [
            (r"\bКрасногорск\b", "Красногорск"),
            (r"\bИстра\b", "Истра"),
            (r"\bГоловино\b", "Головино"),
            (r"\bФилино\b", "Филино"),
            (r"\bПржевальское\b", "Пржевальское"),
        ]
        for pattern, city in patterns:
            if re.search(pattern, venue, flags=re.IGNORECASE):
                return city
        return venue.split(",")[0].strip() if "," in venue else venue.strip()

    def _extract_tri_niti_region(self, venue: str | None) -> str | None:
        if not venue:
            return None
        lowered = venue.lower()
        if "московская область" in lowered:
            return "Московская область"
        if "смоленская обл" in lowered or "смоленская область" in lowered:
            return "Смоленская область"
        return None


class VelomarathonParser(CssDirectoryParser):
    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        section = soup.select_one("#rec862409436")
        if section is None:
            return []

        events: list[Event] = []
        base_page_url = page_url.split("#", 1)[0]
        for index, card in enumerate(section.select(".t778__col.js-product")):
            href = self._extract_optional_attr(card, "a.js-product-link, a[href]", "href")

            title = self._extract_optional_text(card, ".t778__title")
            details_node = card.select_one(".t778__descr")
            image_url = self._extract_optional_attr(card, ".t778__bgimg", "data-original")
            if not title or details_node is None:
                continue

            details = details_node.get_text("\n", strip=True)
            lines = [line.strip() for line in details.split("\n") if line.strip()]
            if not lines:
                continue
            date_text = lines[0]
            venue = lines[1] if len(lines) > 1 else None
            if not re.search(r"2026", date_text):
                continue

            synthetic_url = f"{base_page_url}#event-{index + 1}"
            source_url = (
                urljoin(page_url, href)
                if isinstance(href, str) and href.strip()
                else synthetic_url
            )
            full_image = urljoin(page_url, image_url) if image_url else None
            stable_hash = hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"velomarathon-{index}-{stable_hash}",
                    title=self._normalize_velomarathon_title(title),
                    description=self._build_velomarathon_description(
                        title=title,
                        source_url=source_url,
                    ),
                    distance_summary=self._extract_distance_summary_from_text(
                        " ".join(part for part in (title, details, venue) if part)
                    ),
                    city=self._extract_velomarathon_city(venue),
                    region=self._extract_velomarathon_region(venue),
                    federal_district=None,
                    venue=venue,
                    category="Велоспорт",
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=source_url,
                    image_url=full_image,
                )
            )

        return events

    def _build_velomarathon_description(
        self,
        title: str,
        source_url: str,
    ) -> str | None:
        normalized_title = title.casefold()
        if "мвм" in normalized_title:
            return "Серия МВМ 2026"
        if "reg.place/events/" in source_url and any(
            marker in source_url
            for marker in (
                "1perviy-etap-mvm-2026",
                "gabo-velomarathon-2026",
                "stupinskiy-velomarathon-2026",
                "yakhromskiy-velomarathon-2026",
                "moscow-velomarathon-2026",
                "tomilinskiy-velomarathon-2026",
            )
        ):
            return "Серия МВМ 2026"
        return None

    def _normalize_velomarathon_title(self, title: str) -> str:
        normalized = re.sub(r"\s+", " ", title.replace("–", " — ")).strip()
        return normalized

    def _extract_velomarathon_city(self, venue: str | None) -> str | None:
        if not venue:
            return None
        patterns = [
            (r"\bДоброград\b", "Доброград"),
            (r"\bБелопесоцкий\b", "Белопесоцкий"),
            (r"\bИльинское\b", "Ильинское"),
            (r"\bГАБО\b", "Габо"),
        ]
        for pattern, city in patterns:
            if re.search(pattern, venue, flags=re.IGNORECASE):
                return city
        return venue.split(",")[0].strip()

    def _extract_velomarathon_region(self, venue: str | None) -> str | None:
        if not venue:
            return None
        lowered = venue.lower()
        if "доброград" in lowered:
            return "Владимирская область"
        if "белопесоцкий" in lowered or "ильинское" in lowered or "габо" in lowered:
            return "Московская область"
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
            if title and "granfondo" not in title.casefold():
                title = f"Granfondo {title}"

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
                    distance_summary=self._extract_distance_summary_from_text(
                        " ".join(part for part in (title, status) if part)
                    ),
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

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        semaphore = asyncio.Semaphore(8)
        tasks = [
            asyncio.create_task(self._enrich_granfondo_event(event, client, semaphore))
            for event in events
        ]
        return await asyncio.gather(*tasks)

    async def _enrich_granfondo_event(
        self,
        event: Event,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Event:
        if event.distance_summary:
            return event
        async with semaphore:
            try:
                response = await client.get(str(event.source_url))
                response.raise_for_status()
            except httpx.HTTPError:
                return event

        soup = BeautifulSoup(response.text, "html.parser")
        distance_summary = self._extract_distance_summary_from_text(soup.get_text(" ", strip=True))
        return event.model_copy(update={"distance_summary": distance_summary or event.distance_summary})


class SwimcupParser(CssDirectoryParser):
    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []
        current_month_year: str | None = None

        for node in soup.select("h3.center, ul.results > li.results__list"):
            if node.name == "h3":
                current_month_year = node.get_text(" ", strip=True)
                continue

            title = self._extract_optional_text(node, ".results__col--name")
            raw_date = self._extract_optional_text(node, ".results__col--cal")
            city = self._extract_optional_text(node, ".results__col--city")
            distances = self._extract_optional_text(node, ".results__col--clock")
            stage_type = self._extract_optional_text(node, ".results__col--type")
            detail_href = self._extract_optional_attr(node, "a.file--blue[href]", "href")
            register_href = self._extract_optional_attr(
                node,
                "a.file[href*='reg.place/events/']",
                "href",
            )

            if not title or not raw_date:
                continue

            date_text = self._normalize_swimcup_date(raw_date, current_month_year)
            source_href = detail_href or register_href
            if not source_href:
                continue

            full_link = urljoin(page_url, source_href)
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]
            description_parts = [part for part in (distances, stage_type) if part]

            events.append(
                Event(
                    id=f"swimcup-{len(events)}-{stable_hash}",
                    title=title,
                    description=" • ".join(description_parts) if description_parts else None,
                    distance_summary=self._extract_distance_summary_from_text(distances or title),
                    city=self._normalize_swimcup_city(city),
                    region=None,
                    federal_district=None,
                    venue=city,
                    category="Плавание",
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=None,
                )
            )

        return events

    def _normalize_swimcup_date(self, raw_date: str, month_year: str | None) -> str:
        cleaned = re.sub(r"\s+", " ", raw_date.replace("\xa0", " ")).strip()
        if re.search(r"\b20\d{2}\b", cleaned):
            return cleaned
        if month_year and re.search(r"\b20\d{2}\b", month_year):
            year_match = re.search(r"\b(20\d{2})\b", month_year)
            if year_match:
                return f"{cleaned} {year_match.group(1)}"
        return cleaned

    def _normalize_swimcup_city(self, city: str | None) -> str | None:
        if not city:
            return None
        cleaned = re.sub(r"\s+", " ", city.replace("\xa0", " ")).strip()
        replacements = {
            "Красногорск МО": "Красногорск",
            "Руза МО": "Руза",
            "Серпухов МО": "Серпухов",
        }
        return replacements.get(cleaned, cleaned)

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        semaphore = asyncio.Semaphore(8)
        tasks = [
            asyncio.create_task(self._enrich_swimcup_event(event, client, semaphore))
            for event in events
        ]
        return await asyncio.gather(*tasks)

    async def _enrich_swimcup_event(
        self,
        event: Event,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Event:
        if event.registration_status and event.registration_deadline and event.distance_summary:
            return event

        async with semaphore:
            try:
                response = await client.get(str(event.source_url))
                response.raise_for_status()
            except httpx.HTTPError:
                return event

        soup = BeautifulSoup(response.text, "html.parser")
        registration_status, registration_deadline = self._extract_swimcup_registration_details(soup)
        distance_summary = event.distance_summary or self._extract_distance_summary_from_text(
            soup.get_text(" ", strip=True)
        )
        return event.model_copy(
            update={
                "registration_status": registration_status or event.registration_status,
                "registration_deadline": registration_deadline or event.registration_deadline,
                "distance_summary": distance_summary or event.distance_summary,
            }
        )

    def _extract_swimcup_registration_details(
        self, soup: BeautifulSoup
    ) -> tuple[str | None, str | None]:
        text = soup.get_text(" ", strip=True)
        normalized = re.sub(r"\s+", " ", text.replace("\xa0", " ")).casefold()

        closed_markers = ("регистрация закрыта", "мест нет", "слоты законч", "sold out")
        waitlist_markers = ("лист ожидания", "waiting list", "предзапись")
        open_markers = ("зарегистрироваться", "регистрация на соревнования", "регистрация до")

        status = None
        if any(marker in normalized for marker in closed_markers):
            status = "closed"
        elif any(marker in normalized for marker in waitlist_markers):
            status = "limited"
        elif soup.select_one(".reg a.file[href]") and any(marker in normalized for marker in open_markers):
            status = "open"

        deadline = None
        deadline_node = soup.select_one(".reg__date")
        deadline_text = deadline_node.get_text(" ", strip=True) if deadline_node else None
        if deadline_text:
            cleaned = re.sub(r"\s+", " ", deadline_text.replace("\xa0", " ")).strip()
            numeric = re.search(r"(\d{1,2}[./]\d{1,2}[./]\d{2,4})", cleaned)
            month_name = re.search(
                r"(\d{1,2}\s+[А-Яа-яЁё]+(?:\s+\d{4})?)",
                cleaned,
            )
            if numeric:
                deadline = f"до {numeric.group(1)}"
            elif month_name:
                deadline = f"до {month_name.group(1)}"

        return status, deadline


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
                    distance_summary=self._extract_distance_summary_from_text(
                        " ".join(part for part in (title, location_text) if part)
                    ),
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

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        semaphore = asyncio.Semaphore(8)
        tasks = [
            asyncio.create_task(self._enrich_cyclingrace_event(event, client, semaphore))
            for event in events
        ]
        return await asyncio.gather(*tasks)

    async def _enrich_cyclingrace_event(
        self,
        event: Event,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Event:
        if event.distance_summary:
            return event
        async with semaphore:
            try:
                response = await client.get(str(event.source_url))
                response.raise_for_status()
            except httpx.HTTPError:
                return event

        soup = BeautifulSoup(response.text, "html.parser")
        distance_summary = self._extract_distance_summary_from_text(soup.get_text(" ", strip=True))
        return event.model_copy(update={"distance_summary": distance_summary or event.distance_summary})

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
        if event.city and event.distance_summary:
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
        distance_summary = self._extract_otime_distance_summary(soup) or self._extract_distance_summary_from_text(
            soup.get_text(" ", strip=True)
        )
        registration_status, registration_deadline = self._extract_otime_registration_details(soup)

        return event.model_copy(
            update={
                "city": city or event.city,
                "venue": venue,
                "registration_status": registration_status or event.registration_status,
                "registration_deadline": registration_deadline or event.registration_deadline,
                "distance_summary": distance_summary or event.distance_summary,
            }
        )

    def _extract_otime_distance_summary(self, soup: BeautifulSoup) -> str | None:
        values: list[str] = []
        seen: set[str] = set()

        for node in soup.select(".dist"):
            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip(" ,.")
            if not text:
                continue
            normalized = self._extract_distance_summary_from_text(text)
            candidate = normalized or self._normalize_source_specific_distance_label(text)
            if not candidate:
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            values.append(candidate)

        if not values:
            for cell in soup.select("tr td:first-child b"):
                text = re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip(" :,.")
                if not text:
                    continue
                normalized = self._extract_distance_summary_from_text(text)
                candidate = normalized or self._normalize_source_specific_distance_label(text)
                if not candidate:
                    continue
                if candidate in seen:
                    continue
                seen.add(candidate)
                values.append(candidate)

        if not values:
            return None
        return " • ".join(values)

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

    def _extract_otime_registration_details(
        self,
        soup: BeautifulSoup,
    ) -> tuple[str | None, str | None]:
        text = soup.get_text(" ", strip=True)
        normalized = text.casefold()

        status = None
        if "entry is open" in normalized or "регистрация открыта" in normalized:
            status = "open"
        elif "заявка откроется" in normalized or "opens" in normalized:
            status = "limited"
        elif "закрыта" in normalized or "entry is closed" in normalized:
            status = "closed"

        deadline = None
        match = re.search(
            r"(?:entry is open till|регистрация открыта до|прием заявок до)\s+(\d{1,2}\.\d{1,2}\.\d{4})",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            deadline = f"до {match.group(1)}"

        return status, deadline


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

        cards = soup.select("#section-races .col-lg-4, #content .col-lg-4")
        for index, card in enumerate(cards):
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
                    distance_summary=self._extract_distance_summary_from_text(title),
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

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        semaphore = asyncio.Semaphore(6)
        tasks = [
            asyncio.create_task(self._enrich_nezhesteam_event(event, client, semaphore))
            for event in events
        ]
        return await asyncio.gather(*tasks)

    async def _enrich_nezhesteam_event(
        self,
        event: Event,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Event:
        if event.distance_summary:
            return event
        async with semaphore:
            try:
                response = await client.get(str(event.source_url))
                response.raise_for_status()
            except httpx.HTTPError:
                return event

        soup = BeautifulSoup(response.text, "html.parser")
        distance_summary = self._extract_distance_summary_from_text(soup.get_text(" ", strip=True))
        return event.model_copy(update={"distance_summary": distance_summary or event.distance_summary})


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
        semaphore = asyncio.Semaphore(8)
        tasks = [
            asyncio.create_task(self._enrich_myrace_event(event, client, semaphore))
            for event in events
        ]
        return await asyncio.gather(*tasks)

    async def _enrich_myrace_event(
        self,
        event: Event,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Event:
        async with semaphore:
            try:
                response = await client.get(str(event.source_url))
                response.raise_for_status()
            except httpx.HTTPError:
                return event

        soup = BeautifulSoup(response.text, "html.parser")
        organizer_name = self._extract_myrace_organizer(soup)
        registration_status = self._extract_myrace_registration_status(soup)
        distance_summary = self._extract_myrace_distance_summary(soup)

        return event.model_copy(
            update={
                "organizer_name": organizer_name or event.organizer_name,
                "registration_status": registration_status or event.registration_status,
                "distance_summary": distance_summary or event.distance_summary,
            }
        )

    def _extract_myrace_distance_summary(self, soup: BeautifulSoup) -> str | None:
        values: list[str] = []
        seen: set[str] = set()

        def push(text: str | None) -> None:
            if not text:
                return
            cleaned = re.sub(r"\s+", " ", text).strip(" ,.")
            if not cleaned:
                return
            normalized = self._extract_distance_summary_from_text(cleaned)
            candidate = normalized or self._normalize_source_specific_distance_label(cleaned)
            if not candidate or candidate in seen:
                return
            seen.add(candidate)
            values.append(candidate)

        detail_text = soup.get_text(" ", strip=True)
        numeric = self._extract_distance_summary_from_text(detail_text)
        if numeric:
            return numeric

        for node in soup.select(
            ".event-description li, .event-description p, .event-details-amount div, .event-details .block-text"
        ):
            push(node.get_text(" ", strip=True))

        if values:
            return " • ".join(values)

        return self._extract_myrace_activity_summary(soup)

    def _normalize_source_specific_distance_label(self, value: str | None) -> str | None:
        if not value:
            return None
        cleaned = re.sub(r"\s+", " ", value).strip(" ,.")
        if not cleaned:
            return None
        lowered = cleaned.casefold()
        if len(cleaned) > 40:
            return None
        if any(token in lowered for token in ("стоимость", "участник", "возраст", "регистрац", "доступн", "слот", "старт ", "награждение")):
            return None
        if re.fullmatch(r"[тt]-?\d{1,2}", lowered):
            return cleaned.upper()
        if re.fullmatch(r"(онлайн|online|догтрейл|кросс|забег|мтб|гревел|фикс/сингл|велокросс)", lowered):
            return cleaned
        if re.fullmatch(r"[а-яёa-z0-9+./ -]{1,30}", lowered) and re.search(r"\d", cleaned):
            return cleaned
        return None

    def _extract_myrace_registration_status(self, soup: BeautifulSoup) -> str | None:
        text = self._extract_optional_text(soup, "a.push-right.right") or self._extract_optional_text(soup, ".registration-status")
        if not text:
            return None
        normalized = text.casefold()
        if "закрыт" in normalized:
            return "closed"
        if "открыт" in normalized:
            return "open"
        if "ожидания" in normalized:
            return "limited"
        return None

    def _extract_myrace_organizer(self, soup: BeautifulSoup) -> str | None:
        text = soup.get_text("\n", strip=True)
        match = re.search(
            r"Группа\s+Организаторов\s+([^\n<]+)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            organizer = match.group(1).strip(" :.-")
            return organizer or None
        return None

    def _extract_myrace_activity_summary(self, soup: BeautifulSoup) -> str | None:
        labels: list[str] = []
        blocks = list(soup.select(".event-details .block-text"))
        candidate_blocks: list[Any] = []
        for block in blocks:
            heading = block.find("label")
            title = heading.get_text(" ", strip=True).casefold() if heading else ""
            classes = " ".join(block.get("class", [])) if hasattr(block, "get") else ""
            text = block.get_text(" ", strip=True).casefold()
            if "contacts" in classes:
                continue
            if heading is not None and "дисциплины" in title:
                candidate_blocks.append(block)
                continue
            if heading is None and "дисциплины" in text:
                candidate_blocks.append(block)

        if not candidate_blocks and blocks:
            candidate_blocks.append(blocks[0])

        for block in candidate_blocks:
            for item in block.select(".event-details-amount"):
                first = item.select_one("div")
                if first is None:
                    continue
                text = re.sub(r"\s+", " ", first.get_text(" ", strip=True)).strip(" ,.")
                if not text:
                    continue
                if re.fullmatch(r"\d+(?:[.,]\d+)?\s*(?:км|м)", text, flags=re.IGNORECASE):
                    continue
                if text not in labels:
                    labels.append(text)
            if labels:
                break

        if not labels:
            return None
        return " • ".join(labels[:4])


class RaceTimeParser(CssDirectoryParser):
    SPORT_TYPE_MAP: dict[int, str] = {
        20: "Бег",
        40: "Бег",
        130: "Другие",
        220: "Бег",
    }

    async def fetch_events(
        self, client: httpx.AsyncClient
    ) -> list[Event] | None:
        if not self.config.listing_urls:
            return []

        events: list[Event] = []
        direct_urls = [
            url
            for url in self.config.listing_urls[1:]
            if "/RaceTime/" in url or "/scanEvent/" in url or url.count("/") > 3
        ]

        try:
            response = await client.get(self.config.listing_urls[0])
            response.raise_for_status()
            events.extend(self.parse(response.text, str(response.url)))
        except httpx.HTTPError:
            pass

        seen = {event.source_url for event in events}
        for url in direct_urls:
            if url in seen:
                continue
            try:
                detail_response = await client.get(url)
                detail_response.raise_for_status()
            except httpx.HTTPError:
                continue

            event = self._parse_racetime_detail(detail_response.text, str(detail_response.url))
            if event is None or event.source_url in seen:
                continue
            seen.add(event.source_url)
            events.append(event)

        return events

    def parse(self, html: str, page_url: str) -> list[Event]:
        races = self._extract_racetime_payload(html)
        if not races:
            return []

        events: list[Event] = []
        seen_urls: set[str] = set()

        for index, race in enumerate(races.values()):
            public_url = race.get("racePublicUrl")
            title = (race.get("displayName") or "").strip()
            if not isinstance(public_url, str) or not title:
                continue

            full_link = urljoin(page_url, public_url)
            if full_link in seen_urls:
                continue
            seen_urls.add(full_link)

            date_value = race.get("dateTime")
            city = race.get("city")
            secondary = (race.get("displayNameSecondary") or "").strip()
            organization = (race.get("organizationName") or "").strip()
            sport_type_id = race.get("sportTypeId")
            image_url = race.get("racePhotoUrl")

            description_parts = [secondary or None, organization or None]
            description = " • ".join(part for part in description_parts if part) or None
            category = self._racetime_category(secondary, title, sport_type_id)
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"racetime-{index}-{stable_hash}",
                    title=title,
                    description=description,
                    distance_summary=self._extract_distance_summary_from_text(
                        " ".join(part for part in (title, secondary) if part)
                    ),
                    city=city.strip() if isinstance(city, str) and city.strip() else None,
                    region=None,
                    federal_district=None,
                    venue=None,
                    category=category,
                    date_text=self._format_racetime_date(date_value),
                    starts_at=self._normalize_datetime(date_value),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=urljoin(page_url, image_url) if isinstance(image_url, str) and image_url else None,
                )
            )

        return events

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        semaphore = asyncio.Semaphore(8)
        tasks = [
            asyncio.create_task(self._enrich_racetime_event(event, client, semaphore))
            for event in events
        ]
        return await asyncio.gather(*tasks)

    def _parse_racetime_detail(self, html: str, page_url: str) -> Event | None:
        soup = BeautifulSoup(html, "html.parser")
        title_match = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
        title = None
        if title_match:
            title = BeautifulSoup(title_match.group(1), "html.parser").get_text(" ", strip=True)
        if not title:
            return None

        stage_match = re.search(r"var\\s+RACE_STAGE_INFO\\s*=\\s*(\\{.*?\\})\\s*;", html, re.S)
        date_value = None
        if stage_match:
            try:
                stage_info = json.loads(stage_match.group(1))
                date_value = stage_info.get("startDateTime")
            except json.JSONDecodeError:
                date_value = None

        image_match = re.search(r'<meta\\s+property=\"og:image\"\\s+content=\"([^\"]+)\"', html, re.I)
        image_url = image_match.group(1) if image_match else None
        stable_hash = hashlib.sha1(page_url.encode("utf-8")).hexdigest()[:12]

        return Event(
            id=f"racetime-direct-{stable_hash}",
            title=title,
            description=None,
            distance_summary=self._extract_distance_summary_from_text(soup.get_text(" ", strip=True)),
            city=None,
            region=None,
            federal_district=None,
            venue=None,
            category=self._racetime_category("", title, None),
            date_text=self._format_racetime_date(date_value),
            starts_at=self._normalize_datetime(date_value),
            source_name=self.config.name,
            source_url=page_url,
            image_url=urljoin(page_url, image_url) if isinstance(image_url, str) and image_url else None,
        )

    async def _enrich_racetime_event(
        self,
        event: Event,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Event:
        if event.distance_summary:
            return event
        async with semaphore:
            try:
                response = await client.get(str(event.source_url))
                response.raise_for_status()
            except httpx.HTTPError:
                return event
        distance_summary = self._extract_distance_summary_from_text(
            BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
        )
        return event.model_copy(update={"distance_summary": distance_summary or event.distance_summary})

    def _extract_racetime_payload(self, html: str) -> dict[str, dict[str, Any]]:
        marker = "var GLOBAL_races ="
        start = html.find(marker)
        if start == -1:
            return {}

        start = html.find("{", start)
        if start == -1:
            return {}

        depth = 0
        end = -1
        for index in range(start, len(html)):
            char = html[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break

        if end == -1:
            return {}

        try:
            data = json.loads(html[start:end])
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _racetime_category(
        self, secondary: str, title: str, sport_type_id: Any
    ) -> str | None:
        combined = f"{secondary} {title}".casefold()
        if "swim" in combined or "заплыв" in combined:
            return "Плавание"
        if "триат" in combined or "дуат" in combined:
            return "Триатлон"
        if "вело" in combined or "bike" in combined or "cycling" in combined:
            return "Велоспорт"
        if "лыж" in combined or "ski" in combined:
            return "Лыжи"
        if "трейл" in combined or "бег" in combined or "run" in combined or "марафон" in combined:
            return "Бег"
        if isinstance(sport_type_id, int):
            return self.SPORT_TYPE_MAP.get(sport_type_id)
        return None

    def _format_racetime_date(self, value: Any) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            dt = date_parser.isoparse(value)
        except (ValueError, TypeError):
            return value
        return dt.strftime("%d.%m.%Y")


class SportidentParser(CssDirectoryParser):
    CATEGORY_MAP = {
        "0": "Другие",
        "1": "Лыжи",
        "2": "Лыжи",
        "3": "Другие",
        "4": "Бег",
        "5": "Лыжи",
        "6": "Ориентирование и туризм",
        "7": "Другие",
        "8": "Плавание",
        "9": "Велоспорт",
        "10": "Бег",
        "11": "Ориентирование и туризм",
        "12": "Триатлон",
        "13": "Плавание",
        "14": "Лыжи",
        "15": "Бег",
    }

    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []
        seen_links: set[str] = set()
        month_year_by_row: dict[int, str] = {}
        current_month_year: str | None = None

        for tr in soup.find_all("tr"):
            month_cell = tr.find("td", class_="month_en")
            if month_cell is not None:
                heading = month_cell.get_text(" ", strip=True)
                if re.search(r"\b20\d{2}\b", heading):
                    current_month_year = heading
            month_year_by_row[id(tr)] = current_month_year

        for index, anchor in enumerate(soup.select("a.href_entry[href*='/entry/?id=']")):
            href = anchor.get("href")
            if not isinstance(href, str):
                continue

            full_link = urljoin(page_url, href)
            if full_link in seen_links:
                continue
            seen_links.add(full_link)

            title = anchor.get_text(" ", strip=True)
            row = anchor.find_parent("tr")
            if not title or row is None:
                continue

            date_cell = row.select_one("td.no_sp")
            icon_node = row.select_one(".ico_type[src]")
            location_font = row.select_one("font[color='black']")
            month_year = month_year_by_row.get(id(row))

            date_text = self._normalize_sportident_date_text(
                date_cell.get_text(" ", strip=True) if date_cell else None,
                month_year,
            )
            raw_location = (
                location_font.get_text(" ", strip=True)
                if location_font is not None
                else None
            )
            city, region, venue = self._extract_sportident_location(raw_location)
            category = self._extract_sportident_category(icon_node)
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"sportident-{index}-{stable_hash}",
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

        return events

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        semaphore = asyncio.Semaphore(8)
        tasks = [
            asyncio.create_task(self._enrich_sportident_event(event, client, semaphore))
            for event in events
        ]
        return await asyncio.gather(*tasks)

    async def _enrich_sportident_event(
        self,
        event: Event,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Event:
        if event.distance_summary and event.registration_status and event.registration_deadline:
            return event
        async with semaphore:
            try:
                response = await client.get(str(event.source_url))
                response.raise_for_status()
            except httpx.HTTPError:
                return event

        soup = BeautifulSoup(response.text, "html.parser")
        distance_summary = self._extract_distance_summary_from_text(soup.get_text(" ", strip=True))
        registration_status, registration_deadline = self._extract_sportident_registration_details(soup)
        return event.model_copy(
            update={
                "distance_summary": distance_summary or event.distance_summary,
                "registration_status": registration_status or event.registration_status,
                "registration_deadline": registration_deadline or event.registration_deadline,
            }
        )

    def _normalize_sportident_date_text(
        self, value: str | None, month_year: str | None
    ) -> str | None:
        if not value:
            return None
        cleaned = re.sub(r"\s+", " ", value).strip()
        year = self._extract_year_from_heading(month_year)
        if re.fullmatch(r"\d{2}\.\d{2}", cleaned):
            return f"{cleaned}.{year}" if year else cleaned
        if re.fullmatch(r"\d{2}\.\d{2}\s+\d{2}\.\d{2}", cleaned):
            start = cleaned.split()[0]
            return f"{start}.{year}" if year else start
        if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", cleaned):
            return cleaned
        return cleaned

    def _extract_year_from_heading(self, heading: str | None) -> str | None:
        if not heading:
            return None
        match = re.search(r"\b(20\d{2})\b", heading)
        if match:
            return match.group(1)
        return None

    def _extract_sportident_category(self, icon_node: Any) -> str | None:
        if icon_node is None:
            return None
        src = icon_node.get("src")
        if not isinstance(src, str):
            return None
        match = re.search(r"/(\d+)\.png$", src)
        if not match:
            return None
        return self.CATEGORY_MAP.get(match.group(1))

    def _extract_sportident_location(
        self, raw_location: str | None
    ) -> tuple[str | None, str | None, str | None]:
        if not raw_location:
            return None, None, None

        parts = [part.strip() for part in raw_location.split(">") if part.strip()]
        if not parts:
            return None, None, None

        venue = None
        city = None
        region = None

        if len(parts) >= 2:
            region = self._normalize_sportident_region(parts[1])
        if len(parts) >= 3:
            city = self._clean_sportident_place(parts[2])
        if len(parts) >= 4:
            venue = self._clean_sportident_place(parts[3])

        if city == region:
            city = None
        if region == "Москва" and city is None:
            city = "Москва"

        return city, region, venue

    def _normalize_sportident_region(self, value: str) -> str:
        cleaned = self._clean_sportident_place(value)
        replacements = {
            "Московская обл.": "Московская область",
            "Ленинградская обл.": "Ленинградская область",
            "Калининградская обл.": "Калининградская область",
            "Свердловская обл.": "Свердловская область",
            "Смоленская обл.": "Смоленская область",
            "Новосибирская обл.": "Новосибирская область",
            "Тверская обл.": "Тверская область",
            "Ярославская обл.": "Ярославская область",
            "Краснодарский край": "Краснодарский край",
            "г. Москва": "Москва",
            "г. Санкт-Петербург": "Санкт-Петербург",
            " г. Москва": "Москва",
        }
        return replacements.get(cleaned, cleaned)

    def _clean_sportident_place(self, value: str) -> str:
        cleaned = re.sub(r"\s+", " ", value).strip()
        cleaned = re.sub(r"^(г\.\s*)", "", cleaned, flags=re.IGNORECASE)
        return cleaned

    def _extract_sportident_registration_details(
        self, soup: BeautifulSoup
    ) -> tuple[str | None, str | None]:
        text = soup.get_text(" ", strip=True)
        normalized = re.sub(r"\s+", " ", text.replace("\xa0", " ")).casefold()

        closed_markers = (
            "регистрация закрыта",
            "заявка закрыта",
            "мест нет",
            "слоты законч",
        )
        if any(marker in normalized for marker in closed_markers):
            return "closed", None

        deadline = None
        range_match = re.search(
            r"регистрация участников с\s*(\d{1,2}\s+[а-яё]+(?:\s+\d{4})?|\d{1,2}[./]\d{1,2}[./]\d{2,4})\s*по\s*(\d{1,2}\s+[а-яё]+(?:\s+\d{4})?|\d{1,2}[./]\d{1,2}[./]\d{2,4})",
            normalized,
            flags=re.IGNORECASE,
        )
        if range_match:
            start_raw = range_match.group(1)
            end_raw = range_match.group(2)
            deadline = f"до {end_raw}"
            start_dt = self._normalize_datetime(start_raw)
            end_dt = self._normalize_datetime(end_raw)
            now = datetime.now()
            if start_dt and end_dt:
                try:
                    if datetime.fromisoformat(start_dt) <= now <= datetime.fromisoformat(end_dt):
                        return "open", deadline
                    if now > datetime.fromisoformat(end_dt):
                        return "closed", deadline
                    return None, deadline
                except ValueError:
                    pass

        open_at_match = re.search(
            r"заявка откроется\s*(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
            normalized,
            flags=re.IGNORECASE,
        )
        if open_at_match:
            open_at = open_at_match.group(1)
            try:
                open_dt = datetime.fromisoformat(self._normalize_datetime(open_at) or "")
                if datetime.now() >= open_dt:
                    return "open", deadline
            except ValueError:
                pass
            return None, deadline

        if "?id=" in str(soup) and "заявиться" in normalized:
            return "open", deadline

        return None, deadline


class LaStradaParser(CssDirectoryParser):
    API_URL = "https://heroleague.ru/api/event_city/type/lastrada"

    async def fetch_events(
        self, client: httpx.AsyncClient
    ) -> list[Event] | None:
        try:
            response = await client.get(self.API_URL)
            response.raise_for_status()
        except httpx.HTTPError:
            return []

        payload = response.json()
        values = payload.get("values")
        if not isinstance(values, list):
            return []

        events: list[Event] = []
        seen_urls: set[str] = set()

        for index, item in enumerate(values):
            if not isinstance(item, dict):
                continue

            event_info = item.get("event")
            if not isinstance(event_info, dict):
                continue

            title = self._extract_lastrada_title(event_info, item)
            starts_at = item.get("start_time")
            if not title or not isinstance(starts_at, str):
                continue

            source_url = self._extract_lastrada_url(event_info, item)
            if source_url in seen_urls:
                continue
            seen_urls.add(source_url)

            city_info = item.get("city") if isinstance(item.get("city"), dict) else {}
            city = city_info.get("name_ru") if isinstance(city_info.get("name_ru"), str) else None
            address = item.get("address") if isinstance(item.get("address"), str) else None
            image_path = item.get("info", {}).get("map_preview") if isinstance(item.get("info"), dict) else None
            image_url = (
                urljoin("https://heroleague.ru", image_path)
                if isinstance(image_path, str) and image_path
                else None
            )
            stable_hash = hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"lastrada-{index}-{stable_hash}",
                    title=title,
                    description=address,
                    distance_summary=self._extract_distance_summary_from_text(
                        json.dumps(item, ensure_ascii=False)
                    ),
                    city=city,
                    region=None,
                    federal_district=None,
                    venue=address,
                    category=self._extract_lastrada_category(event_info, item),
                    date_text=starts_at,
                    starts_at=starts_at,
                    source_name=self.config.name,
                    source_url=source_url,
                    image_url=image_url,
                )
            )

        return events

    def _extract_lastrada_title(self, event_info: dict[str, Any], item: dict[str, Any]) -> str | None:
        title_above = event_info.get("title_above")
        title = event_info.get("title")
        if isinstance(title_above, str) and title_above.strip():
            return f"La Strada — {title_above.strip()}"
        if isinstance(title, str) and title.strip():
            return title.strip()
        return None

    def _extract_lastrada_url(self, event_info: dict[str, Any], item: dict[str, Any]) -> str:
        external_url = event_info.get("external_url")
        public_id = item.get("public_id")
        if isinstance(external_url, str) and external_url.strip():
            anchor = public_id if isinstance(public_id, str) and public_id.strip() else None
            return f"{external_url.strip()}#{anchor}" if anchor else external_url.strip()
        return self.config.base_url

    def _extract_lastrada_category(
        self,
        event_info: dict[str, Any],
        item: dict[str, Any],
    ) -> str:
        text = " ".join(
            str(part or "")
            for part in (
                event_info.get("title"),
                event_info.get("title_above"),
                event_info.get("external_url"),
                item.get("event_public_id"),
            )
        ).lower()
        if "офф-роуд" in text or "offroad" in text or "бездорож" in text:
            return "Велоспорт"
        if "велогон" in text or "cycling" in text or "criterium" in text or "критериум" in text:
            return "Велоспорт"
        if "фестив" in text or "festival" in text:
            return "Велоспорт"
        return "Велоспорт"

class CityTrailParser(CssDirectoryParser):
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

        html = response.text
        page_url = str(response.url)
        soup = BeautifulSoup(html, "html.parser")
        myrace_links = self._extract_citytrail_myrace_links(html)
        city_pages = self._extract_citytrail_pages(soup, page_url)
        if not myrace_links:
            return []

        semaphore = asyncio.Semaphore(6)

        async def load_event(index: int, myrace_url: str) -> Event | None:
            async with semaphore:
                try:
                    detail_response = await client.get(myrace_url)
                    detail_response.raise_for_status()
                except httpx.HTTPError:
                    return None
            return self._parse_citytrail_detail(
                detail_response.text,
                myrace_url,
                city_pages.get(index),
                index,
            )

        tasks = [
            load_event(index, url)
            for index, url in sorted(myrace_links.items())
        ]
        loaded = await asyncio.gather(*tasks)
        return [event for event in loaded if event is not None]

    def _extract_citytrail_myrace_links(self, html: str) -> dict[int, str]:
        matches = re.findall(
            r'"js_city_(\d+)_click_reg"\s*:\s*"([^"]+myrace\.info/events/\d+)"',
            html,
        )
        result: dict[int, str] = {}
        for index_str, url in matches:
            result[int(index_str)] = url
        return result

    def _extract_citytrail_pages(self, soup: BeautifulSoup, page_url: str) -> dict[int, str]:
        pages: dict[int, str] = {}
        for anchor in soup.select('a[href^="/"] .tn-atom__button-text'):
            parent = anchor.parent
            if parent is None:
                continue
            href = parent.get("href")
            if not isinstance(href, str):
                continue
            match = re.fullmatch(r"/(\d+)", href.strip())
            if not match:
                continue
            pages[int(match.group(1))] = urljoin(page_url, href)
        return pages

    def _parse_citytrail_detail(
        self,
        html: str,
        myrace_url: str,
        source_url: str | None,
        index: int,
    ) -> Event | None:
        soup = BeautifulSoup(html, "html.parser")
        title = self._extract_optional_text(soup, ".heading-huge")
        date_text = self._extract_optional_text(soup, ".text-large.text-strong")
        if not title or not date_text:
            return None

        city = self._extract_optional_text(soup, ".mt-5.text-large .text-strong")
        venue = self._extract_optional_text(soup, ".mt-5.text-large .text-muted.text-regular")
        category = self._extract_optional_text(soup, ".event-details .type")
        description = self._extract_optional_text(soup, ".event-about p")
        image_url = self._extract_citytrail_image(soup, myrace_url)
        final_url = source_url or f"{self.config.base_url.rstrip('/')}/#{index}"
        stable_hash = hashlib.sha1(final_url.encode("utf-8")).hexdigest()[:12]

        return Event(
            id=f"city-trail-{index}-{stable_hash}",
            title=title,
            description=description,
            distance_summary=self._extract_distance_summary_from_text(soup.get_text(" ", strip=True)),
            city=None if city in {None, "-", "—"} else city,
            region=None,
            federal_district=None,
            venue=None if venue in {None, "-", "—"} else venue,
            category=category or "Бег",
            date_text=date_text,
            starts_at=self._normalize_datetime(date_text),
            source_name=self.config.name,
            source_url=final_url,
            image_url=image_url,
        )

    def _extract_citytrail_image(self, soup: BeautifulSoup, page_url: str) -> str | None:
        image_block = soup.select_one(".event-image")
        style = image_block.get("style") if image_block is not None else None
        if not isinstance(style, str):
            return None
        match = re.search(r"url\(['\"]?([^'\")]+)", style)
        if not match:
            return None
        return urljoin(page_url, match.group(1))


class BorisovoParser(CssDirectoryParser):
    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []

        for index, article in enumerate(soup.select("article.post")):
            title = self._extract_optional_text(article, ".entry-title")
            href = self._extract_optional_attr(article, ".entry-title a[href]", "href")
            if not title or not href:
                continue

            date_text = self._extract_borisovo_event_date(title)
            if not date_text or "2026" not in date_text:
                continue

            description = self._extract_optional_text(article, "p.has-black-color.has-text-color")
            image = self._extract_borisovo_image(article)
            full_link = urljoin(page_url, href)
            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]

            events.append(
                Event(
                    id=f"borisovo-{index}-{stable_hash}",
                    title=title.rstrip("!"),
                    description=description,
                    distance_summary=self._extract_distance_summary_from_text(
                        " ".join(part for part in (title, description) if part)
                    ),
                    city="Серпухов",
                    region="Московская область",
                    federal_district=None,
                    venue="Борисово",
                    category=self._extract_borisovo_category(title, description),
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=image,
                )
            )

        return events

    def _extract_borisovo_event_date(self, title: str) -> str | None:
        match = re.search(
            r"(\d{1,2}[./]\d{1,2}[./]20\d{2})",
            title,
        )
        if not match:
            return None
        return match.group(1).replace("/", ".")

    def _extract_borisovo_image(self, article: Any) -> str | None:
        image_node = article.select_one(".blog-post-blocks-inner-img")
        style = image_node.get("style") if image_node is not None else None
        if not isinstance(style, str):
            return None
        match = re.search(r"url\(([^)]+)\)", style)
        if not match:
            return None
        return match.group(1).strip("'\"")

    def _extract_borisovo_category(
        self,
        title: str,
        description: str | None,
    ) -> str:
        text = f"{title} {description or ''}".casefold()
        if "лыж" in text:
            return "Лыжи"
        if "trail" in text or "трейл" in text or "кросс" in text:
            return "Бег"
        if "вело" in text or "xcm" in text:
            return "Велоспорт"
        return "Другие"


class XWatersParser(CssDirectoryParser):
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

        events = self.parse(response.text, str(response.url))
        if not events:
            return []

        semaphore = asyncio.Semaphore(8)
        tasks = [self._enrich_xwaters_event(event, client, semaphore) for event in events]
        enriched = await asyncio.gather(*tasks, return_exceptions=True)
        result: list[Event] = []
        for original, item in zip(events, enriched):
            if isinstance(item, Event):
                result.append(item)
            else:
                result.append(original)
        return result

    def parse(self, html: str, page_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []
        seen_urls: set[str] = set()

        for index, card in enumerate(soup.select("a.project_itm.js-event-block")):
            href = card.get("href")
            if not isinstance(href, str):
                continue

            full_link = urljoin(page_url, href)
            if "/events/" not in full_link or full_link in seen_urls:
                continue
            seen_urls.add(full_link)

            title = self._extract_optional_text(card, ".project_itm__title")
            date_text = self._extract_optional_text(card, ".project_itm__date")
            description = self._extract_optional_text(card, ".project_itm__desc")
            image_url = None
            bg = card.select_one(".project_itm__bg")
            if bg is not None:
                image_url = bg.get("data-image")
            if not title or not date_text:
                continue

            stable_hash = hashlib.sha1(full_link.encode("utf-8")).hexdigest()[:12]
            events.append(
                Event(
                    id=f"xwaters-{index}-{stable_hash}",
                    title=title,
                    description=description,
                    distance_summary=self._extract_distance_summary_from_text(
                        " ".join(part for part in (title, description) if part)
                    ),
                    city=None,
                    region=None,
                    federal_district=None,
                    venue=None,
                    category="Плавание",
                    date_text=date_text,
                    starts_at=self._normalize_datetime(date_text),
                    source_name=self.config.name,
                    source_url=full_link,
                    image_url=urljoin(page_url, image_url) if isinstance(image_url, str) else None,
                )
            )

        return events

    async def _enrich_xwaters_event(
        self,
        event: Event,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Event:
        async with semaphore:
            try:
                response = await client.get(str(event.source_url))
                response.raise_for_status()
            except httpx.HTTPError:
                return event

        soup = BeautifulSoup(response.text, "html.parser")
        title = self._extract_optional_text(soup, "h1.title-event") or event.title
        subtitle = self._extract_optional_text(soup, "h2.slogan-event")
        description = event.description or subtitle

        date_text = event.date_text
        year = self._extract_optional_attr(soup, 'input[name="event_date_year"]', "value")
        month = self._extract_optional_attr(soup, 'input[name="event_date_month"]', "value")
        day = self._extract_optional_attr(soup, 'input[name="event_date_day"]', "value")
        if year and month and day:
            date_text = f"{day.zfill(2)}.{month.zfill(2)}.{year}"

        location_text = None
        for node in soup.select(".b_under-menu .b_under_itms .itm, .b_under-menu .b_under_itms h2.itm"):
            text = node.get_text(" ", strip=True)
            if not text:
                continue
            lowered = text.lower()
            if any(token in lowered for token in ("км", "миля", "эстафет", "дети")):
                continue
            if re.search(r"\d", lowered) and any(month_name in lowered for month_name in (
                "январ", "феврал", "март", "апрел", "мая", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр"
            )):
                continue
            if "," in text:
                location_text = text
                break

        city, region, venue = self._extract_xwaters_location(location_text or "")
        image_url = self._extract_optional_attr(soup, 'meta[property="og:image"]', "content") or event.image_url
        distance_summary = self._extract_distance_summary_from_text(soup.get_text(" ", strip=True))

        return event.model_copy(
            update={
                "title": title,
                "description": description,
                "date_text": date_text,
                "starts_at": self._normalize_datetime(date_text) or event.starts_at,
                "city": city or event.city,
                "region": region or event.region,
                "venue": venue or event.venue,
                "distance_summary": distance_summary or event.distance_summary,
                "image_url": image_url,
            }
        )

    def _extract_xwaters_location(
        self,
        location_text: str,
    ) -> tuple[str | None, str | None, str | None]:
        if not location_text:
            return None, None, None

        parts = [part.strip(" ,") for part in location_text.split(",") if part.strip(" ,")]
        if not parts:
            return None, None, None

        region = None
        city = None
        venue = None

        first = parts[0]
        if any(token in first.lower() for token in ("обл", "край", "республика", "турция", "сербия", "казахстан", "армения", "таиланд", "словения", "черногория", "киргиз", "кыргыз", "мурманская", "калининградская")):
            region = first
            if len(parts) > 1:
                city = parts[1]
            if len(parts) > 2:
                venue = ", ".join(parts[2:])
        else:
            city = first
            if len(parts) > 1:
                venue = ", ".join(parts[1:])

        if city:
            city = re.sub(r"^(г\.|город)\s*", "", city, flags=re.IGNORECASE).strip()
        if region:
            region = region.strip()
        if venue:
            venue = venue.strip()

        return city, region, venue


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
                    distance_summary=self._extract_ironstar_distance(title, href),
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

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        semaphore = asyncio.Semaphore(8)
        tasks = [
            asyncio.create_task(self._enrich_ironstar_event(event, client, semaphore))
            for event in events
        ]
        return await asyncio.gather(*tasks)

    async def _enrich_ironstar_event(
        self,
        event: Event,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Event:
        if event.distance_summary:
            return event

        async with semaphore:
            try:
                response = await client.get(str(event.source_url))
                response.raise_for_status()
            except httpx.HTTPError:
                return event

        soup = BeautifulSoup(response.text, "html.parser")
        meta_description = self._extract_optional_attr(soup, 'meta[name="description"]', "content")
        og_description = self._extract_optional_attr(soup, 'meta[property="og:description"]', "content")
        body_text = soup.get_text(" ", strip=True)
        distance_summary = self._extract_ironstar_distance(
            " ".join(
                part
                for part in (event.title, str(event.source_url), meta_description, og_description, body_text)
                if part
            ),
            str(event.source_url),
        )

        return event.model_copy(
            update={
                "distance_summary": distance_summary or event.distance_summary,
            }
        )

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

    def _extract_ironstar_distance(self, title: str, href: str) -> str | None:
        combined = f"{title} {href}"
        distance = self._extract_distance_summary_from_text(combined)
        if distance:
            return distance

        normalized = combined.casefold()
        aliases = [
            ("1k", "1 км"),
            ("1 к", "1 км"),
            ("2 мили", "2 мили"),
            ("double mile", "2 мили"),
            ("olympic", "51.5 км"),
            ("113", "113 км"),
            ("226", "226 км"),
            ("sprint", "Спринт"),
        ]
        for marker, value in aliases:
            if marker in normalized:
                return value
        return None


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
            distance_summary=self._extract_distance_summary_from_text(page_text),
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
                    distance_summary=self._extract_distance_summary_from_text(
                        " ".join(part for part in (title, meta_text) if part)
                    ),
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
                source_url = str(event.source_url)
                if source_url in seen_urls:
                    continue
                seen_urls.add(source_url)
                events.append(event)

        return events

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
                    distance_summary=self._extract_distance_summary_from_text(
                        " ".join(part for part in (title, description) if part)
                    ),
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
                "distance_summary": self._extract_distance_summary_from_text(combined)
                or event.distance_summary,
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
                    distance_summary=self._extract_distance_summary_from_text(
                        " ".join(part for part in (title, race_type) if part)
                    ),
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

    async def enrich_events(
        self, events: list[Event], client: httpx.AsyncClient
    ) -> list[Event]:
        semaphore = asyncio.Semaphore(8)
        tasks = [
            asyncio.create_task(self._enrich_xcnews_event(event, client, semaphore))
            for event in events
        ]
        return await asyncio.gather(*tasks)

    async def _enrich_xcnews_event(
        self,
        event: Event,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Event:
        if event.distance_summary:
            return event
        async with semaphore:
            try:
                response = await client.get(str(event.source_url))
                response.raise_for_status()
            except httpx.HTTPError:
                return event

        html = response.content.decode("cp1251", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        distance_summary = self._extract_distance_summary_from_text(soup.get_text(" ", strip=True))
        return event.model_copy(update={"distance_summary": distance_summary or event.distance_summary})

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
