from __future__ import annotations

from datetime import date
import json
import logging

from aiohttp import web

from app.config import settings
from app.context import database, partner_registry


logger = logging.getLogger(__name__)


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def event_go(request: web.Request) -> web.StreamResponse:
    token = request.match_info.get("token", "")
    payload = await database.get_event_by_token(token)
    if not payload:
        raise web.HTTPNotFound(text="Unknown event link")

    source_url = str(payload.get("source_url") or "")
    if not source_url.startswith(("http://", "https://")):
        raise web.HTTPNotFound(text="Event has no source link")

    uid = request.query.get("uid")
    chat_id = int(uid) if uid and uid.isdigit() else None
    if chat_id is not None:
        event_id = str(payload.get("id") or payload.get("event_id") or "")
        title = str(payload.get("title") or "")
        try:
            await database.log_event(
                chat_id,
                "event_click",
                json.dumps(
                    {"id": event_id, "title": title, "url": source_url},
                    ensure_ascii=False,
                ),
            )
        except Exception:
            logger.exception("Cannot record event click %s", event_id)

    raise web.HTTPFound(source_url)


async def go(request: web.Request) -> web.StreamResponse:
    partner_id = request.match_info.get("partner_id", "")
    partner = partner_registry.get(partner_id)
    if (
        partner is None
        or not partner.url.startswith(("http://", "https://"))
        or not partner.is_live(date.today())
    ):
        raise web.HTTPNotFound(text="Unknown partner link")

    uid = request.query.get("uid")
    chat_id: int | None = None
    if uid and uid.isdigit():
        chat_id = int(uid)

    try:
        await database.record_partner_click(partner.id, chat_id)
    except Exception:
        logger.exception("Cannot record partner click %s", partner.id)

    url = (
        partner.decorate_url(partner.url, chat_id)
        if chat_id is not None
        else partner.url.replace("{uid}", "")
    )
    raise web.HTTPFound(url)


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/go/event/{token}", event_go)
    app.router.add_get("/go/{partner_id}", go)
    return app


async def start_redirect_server() -> web.AppRunner:
    runner = web.AppRunner(create_app(), access_log=None)
    await runner.setup()
    site = web.TCPSite(
        runner,
        settings.redirect_host,
        settings.redirect_port,
    )
    await site.start()
    logger.info(
        "Partner redirect server on http://%s:%s",
        settings.redirect_host,
        settings.redirect_port,
    )
    return runner
