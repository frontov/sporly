from __future__ import annotations

import hashlib
from urllib.parse import quote

from app.config import settings


def event_token(event_id: str) -> str:
    return hashlib.sha1(event_id.encode("utf-8")).hexdigest()[:12]


def event_click_url(
    chat_id: int,
    event_id: str,
    source_url: str | None,
) -> str | None:
    """Track outbound event clicks through the bot's /go/event endpoint."""

    if not source_url:
        return None
    if not settings.public_base_url:
        return source_url
    base = settings.public_base_url.rstrip("/")
    return f"{base}/go/event/{event_token(event_id)}?uid={chat_id}"


def share_url(
    bot_username: str,
    token: str,
    title: str | None = None,
) -> str | None:
    if not bot_username:
        return None
    target = f"https://t.me/{bot_username}?start=ev_{token}"
    text = "Старт в Sporly"
    return (
        "https://t.me/share/url"
        f"?url={quote(target, safe='')}&text={quote(text, safe='')}"
    )


def favorite_click_url(
    chat_id: int,
    event_id: str,
    source_url: str | None,
) -> str | None:
    return event_click_url(chat_id, event_id, source_url)
