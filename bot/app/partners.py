from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import json
import logging
from pathlib import Path
import random
import time
from typing import Any

from app.config import settings
from app.storage import Database


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Partner:
    id: str
    title: str
    text: str
    button_text: str
    url: str
    placements: tuple[str, ...] = ("search",)
    cities: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    weight: float = 1.0
    label: str = "Партнёр"
    enabled: bool = True
    starts_at: str | None = None
    ends_at: str | None = None

    def is_live(self, today: date) -> bool:
        if not self.enabled or not self.url.startswith(("http://", "https://")):
            return False
        if self.starts_at:
            try:
                if today < date.fromisoformat(self.starts_at):
                    return False
            except ValueError:
                pass
        if self.ends_at:
            try:
                if today > date.fromisoformat(self.ends_at):
                    return False
            except ValueError:
                pass
        return True

    def matches(
        self,
        *,
        placement: str,
        cities: list[str] | None = None,
        categories: list[str] | None = None,
        query: str | None = None,
    ) -> bool:
        if placement not in self.placements:
            return False

        if self.categories:
            selected = {value.casefold() for value in (categories or [])}
            targets = {value.casefold() for value in self.categories}
            if not selected or not selected & targets:
                return False

        if self.cities:
            selected = {value.casefold() for value in (cities or [])}
            targets = {value.casefold() for value in self.cities}
            if not selected or not selected & targets:
                return False

        if self.keywords:
            haystack = (query or "").casefold()
            if not haystack:
                return False
            if not any(keyword.casefold() in haystack for keyword in self.keywords):
                return False

        return True

    def decorate_url(self, url: str, chat_id: int) -> str:
        if "{uid}" in url:
            return url.replace("{uid}", str(chat_id))
        return url


class PartnerRegistry:
    def __init__(self, path: Path, database: Database) -> None:
        self.path = path
        self.database = database
        self._partners: list[Partner] = []
        self._mtime: float | None = None
        self._last_check = 0.0
        self._reload()

    def _reload(self) -> None:
        if not self.path.exists():
            self._partners = []
            return
        try:
            payload = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError) as error:
            logger.warning("Cannot read partner config %s: %s", self.path, error)
            return
        raw_partners = payload.get("partners") if isinstance(payload, dict) else None
        if not isinstance(raw_partners, list):
            self._partners = []
            return

        partners: list[Partner] = []
        for raw in raw_partners:
            if not isinstance(raw, dict) or not raw.get("id") or not raw.get("url"):
                continue
            try:
                weight = max(float(raw.get("weight", 1)), 0.0)
            except (TypeError, ValueError):
                weight = 1.0
            partners.append(
                Partner(
                    id=str(raw["id"]),
                    title=str(raw.get("title") or ""),
                    text=str(raw.get("text") or ""),
                    button_text=str(raw.get("button_text") or "Перейти"),
                    url=str(raw["url"]),
                    placements=tuple(str(item) for item in raw.get("placements") or ["search"]),
                    cities=tuple(str(item) for item in raw.get("cities") or []),
                    categories=tuple(str(item) for item in raw.get("categories") or []),
                    keywords=tuple(str(item) for item in raw.get("keywords") or []),
                    weight=weight,
                    label=str(raw.get("label") or "Партнёр"),
                    enabled=bool(raw.get("enabled", True)),
                    starts_at=raw.get("starts_at"),
                    ends_at=raw.get("ends_at"),
                )
            )
        self._partners = partners
        logger.info("Loaded %s partner placements", len(partners))

    def maybe_reload(self) -> None:
        now = time.monotonic()
        if now - self._last_check < 30:
            return
        self._last_check = now
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self._partners = []
            self._mtime = None
            return
        if self._mtime != mtime:
            self._mtime = mtime
            self._reload()

    def all(self) -> list[Partner]:
        self.maybe_reload()
        return list(self._partners)

    def get(self, partner_id: str) -> Partner | None:
        self.maybe_reload()
        for partner in self._partners:
            if partner.id == partner_id:
                return partner
        return None

    async def choose(
        self,
        chat_id: int,
        *,
        placement: str,
        cities: list[str] | None = None,
        categories: list[str] | None = None,
        query: str | None = None,
    ) -> Partner | None:
        self.maybe_reload()
        today = date.today()
        candidates = [
            partner
            for partner in self._partners
            if partner.is_live(today)
            and partner.matches(
                placement=placement,
                cities=cities,
                categories=categories,
                query=query,
            )
        ]
        if not candidates:
            return None

        cap = settings.partner_impression_per_user_day
        if cap > 0:
            shown_today = await self.database.partner_impressions_by_user_today(
                chat_id
            )
            if shown_today >= cap:
                return None

        pool = [partner for partner in candidates if partner.weight > 0]
        while pool:
            partner = random.choices(
                pool, weights=[item.weight for item in pool], k=1
            )[0]
            shown_for_partner = await self.database.partner_impressions_today(
                partner.id, chat_id
            )
            if cap > 0 and shown_for_partner >= cap:
                pool.remove(partner)
                continue
            await self.database.record_partner_impression(partner.id, chat_id)
            await self.database.log_event(chat_id, "partner_impression", partner.id)
            return partner
        return None

    def tracked_url(self, partner: Partner, chat_id: int) -> str:
        if settings.public_base_url:
            base = settings.public_base_url.rstrip("/")
            return f"{base}/go/{partner.id}?uid={chat_id}"
        return partner.decorate_url(partner.url, chat_id)

    def admin_rows(self, stats: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_id = {partner.id: partner for partner in self.all()}
        rows: list[dict[str, Any]] = []
        for item in stats:
            partner = by_id.get(item["partner_id"])
            rows.append(
                {
                    **item,
                    "title": partner.title if partner else item["partner_id"],
                    "enabled": partner.enabled if partner else False,
                }
            )
        for partner in by_id.values():
            if partner.id not in {item["partner_id"] for item in stats}:
                rows.append(
                    {
                        "partner_id": partner.id,
                        "title": partner.title,
                        "impressions": 0,
                        "clicks": 0,
                        "ctr": 0.0,
                        "enabled": partner.enabled,
                    }
                )
        return rows
