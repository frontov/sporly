"""HTML widgets for the Telegram bot.

Bot API 10.4 introduced HTML widgets: small self-contained HTML documents that
live in a message.  The code is immutable after sending; the bot changes the
widget's ``chat_data`` / ``public_data`` and the open widget redraws.  A widget
can ask the bot with ``TelegramWidget.request()`` and the bot receives a
``widget_query`` update.

aiogram 3.13 does not know these methods and update types yet, so this module
uses small raw ``TelegramMethod`` classes and handles widget updates directly
on ``Dispatcher.update``.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import timedelta
from html import escape
import json
import logging
import zlib
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods.base import TelegramMethod
from aiogram.types import Message, Update

from app.api_client import Event, EventQuery, api_client, today_iso
from app.context import database
from app.formatting import clean_text
from app.links import event_click_url, share_url
from app.text import countdown, format_date, local_today


logger = logging.getLogger(__name__)

WIDGET_STATE_LIMIT = 1000  # Telegram allows 1024 bytes; keep a little headroom.
WIDGET_HTML_LIMIT = 32768
WIDGET_HTML_COMPRESSED_LIMIT = 4096
WIDGET_PAGE_SIZE = 4
_MAX_SESSIONS = 1000


# --------------------------------------------------------------------- methods


class SendWidget(TelegramMethod[Message]):
    __returning__ = Message
    __api_method__ = "sendWidget"

    chat_id: int | str
    html: str
    width: int | None = None
    height: int | None = None
    public_data: str | None = None
    chat_data: str | None = None
    caption: str | None = None
    parse_mode: str | None = None
    show_caption_above_media: bool | None = None
    allow_queries: bool | None = None
    is_shared: bool | None = None
    disable_notification: bool | None = None
    protect_content: bool | None = None


class EditMessageWidgetData(TelegramMethod[bool]):
    __returning__ = bool
    __api_method__ = "editMessageWidgetData"

    chat_id: int | str | None = None
    message_id: int | None = None
    inline_message_id: str | None = None
    public_data: str | None = None
    chat_data: str | None = None


class AnswerWidgetQuery(TelegramMethod[bool]):
    __returning__ = bool
    __api_method__ = "answerWidgetQuery"

    widget_query_id: str
    data: str | None = None


# --------------------------------------------------------------------- session


@dataclass(slots=True)
class WidgetSession:
    kind: str  # "list" or "card"
    chat_id: int
    message_id: int
    query: str | None = None
    cities: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    page: int = 1
    total_pages: int = 1
    total: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)
    bot_username: str = ""
    demo: bool = False
    state: dict[str, Any] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)
    fav_page: int = 1
    events: list[Any] = field(default_factory=list)
    event_total: int = 0
    cache_key: str = ""
    cache_offset: int = 0


_sessions: OrderedDict[str, WidgetSession] = OrderedDict()


def _session_key(chat_id: int, message_id: int) -> str:
    return f"{chat_id}:{message_id}"


def remember_session(session: WidgetSession) -> None:
    key = _session_key(session.chat_id, session.message_id)
    _sessions[key] = session
    _sessions.move_to_end(key)
    while len(_sessions) > _MAX_SESSIONS:
        _sessions.popitem(last=False)


def get_session(chat_id: int, message_id: int) -> WidgetSession | None:
    return _sessions.get(_session_key(chat_id, message_id))


def clear_sessions() -> None:
    _sessions.clear()


# ----------------------------------------------------------------------- html

_LIST_HTML = r"""<style>
.w{font:14px/1.35 system-ui,sans-serif;color:var(--tg-theme-text-color)}
.h{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin:0 0 6px}
.b{font-weight:700;font-size:15px}
.c{font-size:12px;color:var(--tg-theme-hint-color);white-space:nowrap}
.l{display:flex;flex-direction:column}
.r{display:flex;align-items:flex-start;gap:6px;padding:7px 0;border-top:1px solid var(--tg-theme-section-separator-color)}
.r:first-child{border-top:0}
.i{flex:1;min-width:0}
.t{display:block;font-weight:600;color:var(--tg-theme-link-color);text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.t:hover{text-decoration:underline}
.m{margin-top:2px;font-size:12px;color:var(--tg-theme-hint-color);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.k{display:inline-block;margin-right:4px;padding:0 5px;border-radius:6px;background:var(--tg-theme-secondary-bg-color);color:var(--tg-theme-subtitle-text-color);font-size:11px;line-height:16px}
.f{flex:0 0 30px;width:30px;height:30px;padding:0;border:0;border-radius:8px;background:transparent;color:var(--tg-theme-hint-color);font-size:18px;line-height:30px;text-align:center;cursor:pointer}
.f.on{color:var(--tg-theme-accent-text-color)}
.f:disabled{opacity:.5}
.a{display:flex;gap:8px;margin-top:8px}
.p{flex:1;min-height:34px;border:0;border-radius:9px;background:var(--tg-theme-button-color);color:var(--tg-theme-button-text-color);font:600 13px system-ui,sans-serif;cursor:pointer}
.p:disabled{opacity:.5}
.g{min-height:34px;padding:0 12px;border:1px solid var(--tg-theme-section-separator-color);border-radius:9px;background:transparent;color:var(--tg-theme-text-color);font:13px system-ui,sans-serif;cursor:pointer}
.g:disabled{opacity:.5}
.s{min-height:16px;margin-top:6px;font-size:12px;color:var(--tg-theme-hint-color)}
.e{padding:10px 0;color:var(--tg-theme-hint-color)}
</style>
<div class="w">
<div class="h"><span class="b">Ближайшие старты</span><span id="c" class="c"></span></div>
<div id="l" class="l"></div>
<div class="a"><button id="m" class="p">Показать ещё</button><button id="r" class="g">Обновить</button></div>
<div id="s" class="s"></div>
</div>
<script>
(function(){
var W=window.TelegramWidget;if(!W)return;
var L=document.getElementById('l'),M=document.getElementById('m'),R=document.getElementById('r'),S=document.getElementById('s'),C=document.getElementById('c'),B=false;
function D(){try{return JSON.parse(W.chatData||'{}')}catch(e){return{}}}
function T(x){S.textContent=x||''}
function A(a){B=false;var d={};try{d=JSON.parse(a.result||'{}')}catch(e){}T(d.e||'');Render()}
function E(x){B=false;T(x&&x.code==='RATE_LIMITED'?'Слишком часто. Попробуйте через пару секунд.':'Не получилось. Попробуйте ещё раз.');Render()}
function Q(u,t){B=true;T(t);var p=W.request(u);Render();p.then(A,E)}
function Render(){
var d=D(),e=d.e||[],n=d.n||e.length,p=d.p||1,g=d.g||1;
M.hidden=g<=p;M.disabled=B;R.disabled=B;
L.innerHTML='';
C.textContent=e.length?((p-1)*4+1)+'\u2013'+((p-1)*4+e.length)+' из '+n:'';
if(!e.length){var z=document.createElement('div');z.className='e';z.textContent='Стартов пока нет';L.appendChild(z);return}
e.forEach(function(it){
var r=document.createElement('div');r.className='r';
var i=document.createElement('div');i.className='i';
var t=document.createElement(it.u?'a':'div');t.className='t';t.textContent=it.t;if(it.u)t.href=it.u;i.appendChild(t);
var m=document.createElement('div');m.className='m';
if(it.c){var k=document.createElement('span');k.className='k';k.textContent=it.c;m.appendChild(k)}
m.appendChild(document.createTextNode([it.w,it.l].filter(Boolean).join(' \u00b7 ')));i.appendChild(m);
r.appendChild(i);
var f=document.createElement('button');f.className='f'+(it.f?' on':'');f.textContent=it.f?'\u2605':'\u2606';f.disabled=B;f.setAttribute('aria-label',it.f?'Убрать из избранного':'В избранное');
f.addEventListener('click',function(){if(B)return;Q('f:'+it.k,'Сохраняю\u2026')});
r.appendChild(f);L.appendChild(r)
})
}
M.addEventListener('click',function(){if(B)return;Q('more','Загружаю\u2026')});
R.addEventListener('click',function(){if(B)return;Q('refresh','Обновляю\u2026')});
W.onEvent('chatDataChanged',function(){B=false;Render()});
Render();W.ready();
})();
</script>"""

_CARD_HTML = r"""<style>
.c{font:14px/1.4 system-ui,sans-serif;color:var(--tg-theme-text-color)}
.h{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px}
.b{font-weight:700;font-size:13px;letter-spacing:.04em;text-transform:uppercase;color:var(--tg-theme-hint-color)}
.g{padding:1px 7px;border-radius:8px;background:var(--tg-theme-secondary-bg-color);color:var(--tg-theme-subtitle-text-color);font-size:11px;white-space:nowrap}
.t{font-size:19px;line-height:1.2;font-weight:700;margin:2px 0 8px}
.m{font-size:13px;color:var(--tg-theme-hint-color);margin:2px 0;overflow-wrap:anywhere}
.d{margin:8px 0 0;font-size:13px;color:var(--tg-theme-hint-color)}
.a{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.f{flex:1;min-width:150px;min-height:36px;border:0;border-radius:9px;background:var(--tg-theme-button-color);color:var(--tg-theme-button-text-color);font:600 13px system-ui,sans-serif;cursor:pointer}
.f.on{background:var(--tg-theme-secondary-bg-color);color:var(--tg-theme-text-color)}
.f:disabled{opacity:.5}
.o{display:inline-flex;align-items:center;justify-content:center;min-height:36px;padding:0 12px;border:1px solid var(--tg-theme-section-separator-color);border-radius:9px;color:var(--tg-theme-text-color);text-decoration:none;font-size:13px}
.s{min-height:16px;margin-top:8px;font-size:12px;color:var(--tg-theme-hint-color)}
</style>
<div class="c">
<div class="h"><span class="b">Sporly</span><span class="g">__BADGE__</span></div>
<div class="t">__TITLE__</div>
<div class="m">__WHEN__</div>
<div class="m">__PLACE__</div>
<div class="m">__META__</div>
__DESC__
<div class="a">__ACTIONS__</div>
<div id="s" class="s"></div>
</div>
<script>
(function(){
var W=window.TelegramWidget;if(!W)return;
var F=document.getElementById('f'),S=document.getElementById('s'),B=false;
function D(){try{return JSON.parse(W.chatData||'{}')}catch(e){return{}}}
function R(){var d=D(),on=!!d.f;F.textContent=on?'\u2605 В избранном':'\u2606 В избранное';F.className=on?'f on':'f';F.disabled=B}
F.addEventListener('click',function(){
if(B)return;B=true;S.textContent='Сохраняю\u2026';
var p=W.request(__TOKEN_JSON__);R();
p.then(function(a){B=false;var d={};try{d=JSON.parse(a.result||'{}')}catch(e){}S.textContent=d.e||'';R()},function(e){B=false;S.textContent=e&&e.code==='RATE_LIMITED'?'Слишком часто. Попробуйте ещё раз.':'Не получилось. Попробуйте ещё раз.';R()})
});
W.onEvent('chatDataChanged',function(){B=false;R()});
R();W.ready();
})();
</script>"""


def render_list_widget_html() -> str:
    return _LIST_HTML


def _action_link(url: str | None, label: str) -> str:
    if not url:
        return ""
    return f'<a class="o" href="{escape(url, quote=True)}">{escape(label)}</a>'


def render_card_widget_html(
    event: Event,
    *,
    token: str,
    is_favorite: bool,
    open_url: str | None,
    share_url_value: str | None,
) -> str:
    badge = "✨ Рекомендуем" if event.is_featured else "Старт"
    when = format_date(event.starts_at, event.date_text)
    relative = countdown(event.starts_at)
    if relative:
        when = f"{when} · {relative}"
    place = event.location or clean_text(event.venue, 120) or "место уточняется"

    meta: list[str] = []
    if event.category:
        meta.append(clean_text(event.category, 40))
    if event.distance_summary:
        meta.append(clean_text(event.distance_summary, 50))
    if event.price_from:
        meta.append(clean_text(event.price_from, 40))
    if event.registration_deadline:
        meta.append("регистрация " + clean_text(event.registration_deadline, 50))
    elif event.registration_status == "open":
        meta.append("регистрация открыта")
    elif event.registration_status == "closed":
        meta.append("регистрация закрыта")
    meta_text = " · ".join(meta) or "Подробности на сайте"

    description = clean_text(event.description, 180)
    desc_html = f'<div class="d">{escape(description)}</div>' if description else ""

    favorite_class = "f on" if is_favorite else "f"
    favorite_text = "★ В избранном" if is_favorite else "☆ В избранное"
    actions = (
        f'<button id="f" class="{favorite_class}">{favorite_text}</button>'
        + _action_link(open_url, "Открыть сайт")
        + _action_link(share_url_value, "Поделиться")
    )

    return (
        _CARD_HTML.replace("__TOKEN_JSON__", json.dumps("f:" + token))
        .replace("__BADGE__", escape(badge))
        .replace("__WHEN__", "📅 " + escape(when))
        .replace("__PLACE__", "📍 " + escape(place))
        .replace("__META__", "🏁 " + escape(meta_text))
        .replace("__DESC__", desc_html)
        .replace("__ACTIONS__", actions)
        # Title is inserted last so its text cannot match another placeholder.
        .replace("__TITLE__", escape(clean_text(event.title, 160)))
    )


def widget_html_sizes(html: str) -> tuple[int, int]:
    raw = len(html.encode("utf-8"))
    compressed = len(zlib.compress(html.encode("utf-8"), 9))
    return raw, compressed


# ---------------------------------------------------------------------- state


def _dump_state(state: dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"))


def fit_state(state: dict[str, Any], limit: int = WIDGET_STATE_LIMIT) -> str:
    """Return a state JSON that fits Telegram's 1024-byte limit."""

    raw = _dump_state(state)
    if len(raw.encode("utf-8")) <= limit:
        return raw

    for item in state.get("e", []):
        for key, length in (("t", 40), ("l", 18), ("c", 12), ("w", 12)):
            value = item.get(key)
            if isinstance(value, str):
                item[key] = value[:length]
    raw = _dump_state(state)
    if len(raw.encode("utf-8")) <= limit:
        return raw

    while len(state.get("e", [])) > 1 and len(raw.encode("utf-8")) > limit:
        state["e"].pop()
        raw = _dump_state(state)

    if len(raw.encode("utf-8")) > limit:
        for item in state.get("e", []):
            item["u"] = ""
        raw = _dump_state(state)
    return raw


def build_list_items(
    events: list[Event],
    *,
    chat_id: int,
    favorite_ids: set[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for event in events:
        items.append(
            {
                "k": database.event_token(event.id),
                "t": clean_text(event.title, 64),
                "w": format_date(event.starts_at, event.date_text, short=True),
                "c": clean_text(event.category, 18),
                "l": clean_text(event.location or event.venue, 30),
                "u": event_click_url(chat_id, event.id, event.source_url) or "",
                "f": 1 if event.id in favorite_ids else 0,
            }
        )
    return items


def session_state_json(session: WidgetSession) -> str:
    if session.kind == "card":
        favorite = 1 if session.items and session.items[0].get("f") else 0
        return _dump_state({"f": favorite})
    state = {
        "p": session.page,
        "g": session.total_pages,
        "n": session.total,
        "e": session.items,
    }
    return fit_state(state)


# -------------------------------------------------------------------- sending


async def _favorite_ids(chat_id: int) -> set[str]:
    return {favorite.event_id for favorite in await database.favorites(chat_id)}


async def send_widget(
    bot: Bot,
    chat_id: int,
    *,
    html: str,
    chat_data: str | None,
    caption: str | None = None,
    height: int | None = None,
    disable_notification: bool = False,
) -> Message | None:
    try:
        return await bot(
            SendWidget(
                chat_id=chat_id,
                html=html,
                chat_data=chat_data,
                caption=caption,
                parse_mode="HTML",
                height=height,
                allow_queries=True,
                disable_notification=disable_notification,
            )
        )
    except TelegramBadRequest:
        logger.exception("sendWidget failed")
        return None


async def send_events_list_widget(
    bot: Bot,
    chat_id: int,
    events: list[Event],
    *,
    page: int = 1,
    total_pages: int = 1,
    total: int = 0,
    query: str | None = None,
    cities: list[str] | None = None,
    categories: list[str] | None = None,
    bot_username: str = "",
    disable_notification: bool = False,
    demo: bool = False,
) -> Message | None:
    await database.remember_events([event.ref_payload() for event in events])
    items = build_list_items(
        events,
        chat_id=chat_id,
        favorite_ids=await _favorite_ids(chat_id),
    )
    session = WidgetSession(
        kind="list",
        chat_id=chat_id,
        message_id=0,
        query=query,
        cities=list(cities or []),
        categories=list(categories or []),
        page=page,
        total_pages=max(total_pages, 1),
        total=total or len(events),
        items=items,
        bot_username=bot_username,
        demo=demo,
    )
    sent = await send_widget(
        bot,
        chat_id,
        html=render_list_widget_html(),
        chat_data=session_state_json(session),
        caption="Ближайшие старты · Sporly\n💡 ☆ — сохранить в избранное",
        disable_notification=disable_notification,
    )
    if sent is not None:
        session.message_id = sent.message_id
        remember_session(session)
    return sent


async def send_list_widget(
    bot: Bot,
    chat_id: int,
    *,
    query: str | None = None,
    cities: list[str] | None = None,
    categories: list[str] | None = None,
    page: int = 1,
    bot_username: str = "",
    disable_notification: bool = False,
) -> Message | None:
    try:
        result = await api_client.get_events(
            EventQuery(
                query=query,
                cities=cities or [],
                categories=categories or [],
                date_from=today_iso(),
                page=max(page, 1),
                page_size=WIDGET_PAGE_SIZE,
                sort_by="date_asc",
            )
        )
    except Exception:
        logger.exception("Cannot load events for widget")
        return None

    if not result.items:
        return await bot.send_message(
            chat_id, "Стартов пока нет. Попробуйте изменить фильтры."
        )

    return await send_events_list_widget(
        bot,
        chat_id,
        result.items,
        page=result.page,
        total_pages=result.total_pages,
        total=result.total,
        query=query,
        cities=cities,
        categories=categories,
        bot_username=bot_username,
        disable_notification=disable_notification,
    )


async def send_card_widget(
    bot: Bot,
    chat_id: int,
    event: Event,
    *,
    bot_username: str = "",
    disable_notification: bool = False,
) -> Message | None:
    token = database.event_token(event.id)
    await database.remember_events([event.ref_payload()])
    is_favorite = await database.is_favorite(chat_id, event.id)
    sent = await send_widget(
        bot,
        chat_id,
        html=render_card_widget_html(
            event,
            token=token,
            is_favorite=is_favorite,
            open_url=event_click_url(chat_id, event.id, event.source_url),
            share_url_value=share_url(bot_username, token, event.title),
        ),
        chat_data=_dump_state({"f": 1 if is_favorite else 0}),
        caption=escape(clean_text(event.title, 120)) + " · Sporly",
        disable_notification=disable_notification,
    )
    if sent is not None:
        remember_session(
            WidgetSession(
                kind="card",
                chat_id=chat_id,
                message_id=sent.message_id,
                total=1,
                total_pages=1,
                items=[{"k": token, "f": 1 if is_favorite else 0}],
                bot_username=bot_username,
            )
        )
    return sent


async def load_widget_page(session: WidgetSession, page: int):
    try:
        return await asyncio.wait_for(
            api_client.get_events(
                EventQuery(
                    query=session.query,
                    cities=session.cities,
                    categories=session.categories,
                    date_from=today_iso(),
                    page=max(page, 1),
                    page_size=WIDGET_PAGE_SIZE,
                    sort_by="date_asc",
                )
            ),
            timeout=10,
        )
    except asyncio.TimeoutError:
        logger.warning("Widget page %s timed out", page)
        return None
    except Exception:
        logger.exception("Cannot load widget page %s", page)
        return None


# --------------------------------------------------------------------- queries


async def answer_widget_query(bot: Bot, query_id: str, payload: dict[str, Any]) -> None:
    try:
        await bot(
            AnswerWidgetQuery(
                widget_query_id=query_id,
                data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            )
        )
    except Exception:
        logger.exception("answerWidgetQuery failed")


async def edit_widget_data(
    bot: Bot, chat_id: int, message_id: int, chat_data: str
) -> bool:
    try:
        await bot(
            EditMessageWidgetData(
                chat_id=chat_id,
                message_id=message_id,
                chat_data=chat_data,
            )
        )
        return True
    except TelegramBadRequest as error:
        if "not modified" in str(error).lower():
            return True
        logger.warning("editMessageWidgetData failed: %s", error)
        return False


async def _handle_widget_query(bot: Bot, payload: dict[str, Any]) -> None:
    query_id = str(payload.get("id") or "")
    if not query_id:
        return

    data = str(payload.get("data") or "")
    chat = payload.get("chat") or {}
    chat_id = chat.get("id")
    message_id = payload.get("message_id")
    user = payload.get("from") or {}
    user_id = user.get("id")

    if not isinstance(chat_id, int) or not isinstance(message_id, int) or not isinstance(user_id, int):
        await answer_widget_query(bot, query_id, {"e": "Некорректный запрос"})
        return

    session = get_session(chat_id, message_id)
    if session is None:
        await answer_widget_query(bot, query_id, {"e": "Виджет устарел. Откройте заново."})
        return

    if session.kind == "app":
        from app.widget_app import handle_app_query

        await handle_app_query(bot, session, query_id, user_id, data)
        return

    if data.startswith("f:"):
        token = data[2:]
        item = next((item for item in session.items if item.get("k") == token), None)
        if item is None:
            await answer_widget_query(bot, query_id, {"e": "Старт не найден"})
            return

        from app.flows import toggle_favorite_by_token

        target = not bool(item.get("f"))
        ok, _ = await toggle_favorite_by_token(user_id, token, add=target)
        if not ok:
            await answer_widget_query(bot, query_id, {"e": "Старт устарел. Откройте заново."})
            return

        item["f"] = 1 if target else 0
        await edit_widget_data(bot, chat_id, message_id, session_state_json(session))
        await answer_widget_query(
            bot,
            query_id,
            {
                "f": item["f"],
                "e": "Добавлено в избранное" if target else "Убрано из избранного",
            },
        )
        return

    if session.kind != "list":
        await answer_widget_query(bot, query_id, {"e": "Не понял действие"})
        return

    if data == "more":
        if session.demo:
            await answer_widget_query(bot, query_id, {"e": "В демо это последняя страница"})
            return
        target_page = session.page + 1
        if target_page > session.total_pages:
            await answer_widget_query(bot, query_id, {"e": "Это последняя страница"})
            return
        result = await load_widget_page(session, target_page)
        if result is None or not result.items:
            await answer_widget_query(bot, query_id, {"e": "Не удалось загрузить ещё"})
            return
        await database.remember_events([event.ref_payload() for event in result.items])
        session.page = result.page
        session.total_pages = max(result.total_pages, 1)
        session.total = result.total
        session.items = build_list_items(
            result.items,
            chat_id=chat_id,
            favorite_ids=await _favorite_ids(chat_id),
        )
        await edit_widget_data(bot, chat_id, message_id, session_state_json(session))
        await answer_widget_query(bot, query_id, {"e": ""})
        return

    if data == "refresh":
        if session.demo:
            await answer_widget_query(bot, query_id, {"e": "Обновлено (демо)"})
            return
        result = await load_widget_page(session, session.page)
        if result is None:
            await answer_widget_query(bot, query_id, {"e": "Не удалось обновить"})
            return
        await database.remember_events([event.ref_payload() for event in result.items])
        session.page = result.page
        session.total_pages = max(result.total_pages, 1)
        session.total = result.total
        session.items = build_list_items(
            result.items,
            chat_id=chat_id,
            favorite_ids=await _favorite_ids(chat_id),
        )
        await edit_widget_data(bot, chat_id, message_id, session_state_json(session))
        await answer_widget_query(bot, query_id, {"e": "Обновлено"})
        return

    await answer_widget_query(bot, query_id, {"e": "Не понял действие"})


def is_widget_update(update: Update) -> bool:
    extra = update.model_extra or {}
    return "widget_query" in extra or "shared_widget_query" in extra


async def handle_widget_update(update: Update, bot: Bot) -> None:
    extra = update.model_extra or {}
    shared = extra.get("shared_widget_query")
    if shared:
        query_id = str(shared.get("id") or "")
        if query_id:
            await answer_widget_query(
                bot,
                query_id,
                {"e": "Откройте виджет в личном чате с ботом"},
            )
        return

    payload = extra.get("widget_query")
    if not isinstance(payload, dict):
        return

    try:
        await _handle_widget_query(bot, payload)
    except Exception:
        logger.exception("Widget query failed")
        query_id = str(payload.get("id") or "")
        if query_id:
            await answer_widget_query(bot, query_id, {"e": "Ошибка. Попробуйте ещё раз."})


def setup_widget_updates(dp: Dispatcher) -> None:
    dp.update.register(handle_widget_update, is_widget_update)


# ----------------------------------------------------------------------- demo


def demo_events() -> list[Event]:
    base = Event(
        id="widget-demo",
        title="Московский полумарафон",
        description=(
            "21,1 км по набережной и центру города. Старт и финиш — Парк Горького."
        ),
        category="Бег",
        distance_summary="21,1 км",
        city="Москва",
        venue="Парк Горького",
        starts_at=(local_today() + timedelta(days=12)).isoformat(),
        price_from="2 500 ₽",
        registration_status="open",
        source_url="https://sporly.ru",
        source_name="sporly.ru",
        is_featured=True,
        featured_label="Рекомендуем Sporly",
    )
    rows = [
        ("Гонка героев: осенний забег", "Санкт-Петербург", "Бег", "10 км"),
        ("Велогонка «Тур Крыма»", "Ялта", "Велоспорт", "80 км"),
        ("Триатлон Solstice", "Сочи", "Триатлон", "олимпийская"),
    ]
    events = [base]
    for index, (title, city, category, distance) in enumerate(rows, start=1):
        events.append(
            base.model_copy(
                update={
                    "id": f"widget-demo-{index}",
                    "title": title,
                    "city": city,
                    "category": category,
                    "distance_summary": distance,
                    "starts_at": (local_today() + timedelta(days=5 + index * 7)).isoformat(),
                    "is_featured": False,
                }
            )
        )
    return events


def demo_event() -> Event:
    return demo_events()[0]


async def send_demo_list_widget(
    bot: Bot,
    chat_id: int,
    *,
    bot_username: str = "",
    disable_notification: bool = False,
) -> Message | None:
    return await send_events_list_widget(
        bot,
        chat_id,
        demo_events(),
        page=1,
        total_pages=2,
        total=8,
        bot_username=bot_username,
        disable_notification=disable_notification,
        demo=True,
    )
