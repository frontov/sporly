from __future__ import annotations

from app.api_client import EventItem
from app.storage import Subscription


def matches(subscription: Subscription, event: EventItem) -> bool:
    if subscription.cities and event.city not in subscription.cities and event.region not in subscription.cities:
        return False
    if subscription.categories and event.category not in subscription.categories:
        return False
    return True
