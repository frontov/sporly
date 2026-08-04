from __future__ import annotations

FAVORITE_PREFIX = "fav_"
UNFAVORITE_PREFIX = "unfav_"

_bot_username: str | None = None


def set_bot_username(username: str | None) -> None:
    global _bot_username
    _bot_username = username


def start_link(payload: str) -> str | None:
    """Builds a t.me deep link that makes Telegram send `/start <payload>`.

    Returns None until the bot username is known, so callers can silently fall
    back to rendering no link instead of a broken one.
    """
    if not _bot_username:
        return None
    return f"https://t.me/{_bot_username}?start={payload}"
