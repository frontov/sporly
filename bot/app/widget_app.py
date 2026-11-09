"""Widget-only Sporly interface.

One HTML widget is the whole screen: navigation, lists, cards, filters and
settings.  The bot only changes the widget state; there are no inline
keyboards or text screens in this flow.

The HTML is intentionally compact: Telegram allows 4 KB after zlib level 9
compression.  Every view renders from ``chat_data`` and talks to the bot with
``TelegramWidget.request()``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiogram import Bot

from app.api_client import Event, EventQuery, api_client, today_iso
from app.context import database
from app.formatting import clean_text
from app.links import event_click_url
from app.text import countdown, format_date, pluralize
from app.widgets import (
    WidgetSession,
    answer_widget_query,
    edit_widget_data,
    remember_session,
    send_widget,
)


logger = logging.getLogger(__name__)

APP_PAGE_SIZE = 6
CACHE_PAGE_SIZE = 60
APP_STATE_LIMIT = 1000
POPULAR_CATEGORIES = [
    "Бег",
    "Велоспорт",
    "Триатлон",
    "Плавание",
    "Лыжи",
    "Трейл",
    "Силовые виды",
    "Единоборства",
]
POPULAR_CITIES = [
    "Москва",
    "Санкт-Петербург",
    "Казань",
    "Екатеринбург",
    "Новосибирск",
    "Сочи",
    "Краснодар",
    "Нижний Новгород",
]


_APP_HTML = r"""<style>
.w{font:14px/1.35 system-ui,sans-serif;color:var(--tg-theme-text-color)}
.h{display:flex;align-items:center;gap:6px;margin-bottom:8px}
.hb{flex:0 0 30px;width:30px;height:30px;border:0;border-radius:8px;background:transparent;color:var(--tg-theme-link-color);font-size:20px;line-height:30px}
.hb[hidden]{display:none}
.ht{flex:1;min-width:0}
.b{font-weight:700;font-size:15px;line-height:1.2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.s{font-size:12px;color:var(--tg-theme-hint-color);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nav{display:flex;gap:4px;margin-top:10px;padding-top:8px;border-top:1px solid var(--tg-theme-section-separator-color)}
.nav button{flex:1;min-width:0;border:0;border-radius:8px;background:transparent;color:var(--tg-theme-hint-color);font:11px system-ui,sans-serif;padding:4px 2px}
.nav button.on{background:var(--tg-theme-secondary-bg-color);color:var(--tg-theme-text-color);font-weight:600}
.row{display:flex;align-items:flex-start;gap:4px;padding:7px 0;border-top:1px solid var(--tg-theme-section-separator-color)}
.row:first-child{border-top:0}
.rb{flex:1;min-width:0;border:0;background:transparent;text-align:left;padding:0;color:inherit}
.tt{font-weight:600;color:var(--tg-theme-link-color);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mt{margin-top:2px;font-size:12px;color:var(--tg-theme-hint-color);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pl{display:inline-block;margin-right:4px;padding:0 5px;border-radius:6px;background:var(--tg-theme-secondary-bg-color);color:var(--tg-theme-subtitle-text-color);font-size:11px;line-height:16px}
.st{flex:0 0 30px;width:30px;height:30px;padding:0;border:0;border-radius:8px;background:transparent;color:var(--tg-theme-hint-color);font-size:18px;line-height:30px}
.st.on{color:var(--tg-theme-accent-text-color)}
.st:disabled,.btn:disabled,.chip:disabled,.pg button:disabled{opacity:.5}
.pg{display:flex;align-items:center;gap:6px;margin-top:6px}
.pg button{flex:1;min-height:32px;border:1px solid var(--tg-theme-section-separator-color);border-radius:8px;background:transparent;color:var(--tg-theme-text-color);font:12px system-ui}
.btn{width:100%;min-height:34px;border:0;border-radius:9px;background:var(--tg-theme-button-color);color:var(--tg-theme-button-text-color);font:600 13px system-ui}
.bt2{display:flex;align-items:center;justify-content:center;width:100%;min-height:34px;margin-top:6px;border:1px solid var(--tg-theme-section-separator-color);border-radius:9px;background:transparent;color:var(--tg-theme-text-color);font:13px system-ui;text-decoration:none}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
.chip{border:1px solid var(--tg-theme-section-separator-color);border-radius:999px;background:transparent;color:var(--tg-theme-text-color);padding:5px 9px;font:12px system-ui}
.chip.on{background:var(--tg-theme-button-color);border-color:var(--tg-theme-button-color);color:var(--tg-theme-button-text-color)}
.card .tt{display:block;font-size:19px;line-height:1.2;white-space:normal;margin:2px 0 8px;text-decoration:none}
.card .mt{white-space:normal;overflow-wrap:anywhere}
.card .body{font-size:13px;color:var(--tg-theme-hint-color);margin:8px 0}
.act{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.act .btn{flex:1;min-width:140px}
.act a.btn{display:flex;align-items:center;justify-content:center;text-decoration:none}

.empty{padding:12px 0;color:var(--tg-theme-hint-color);text-align:center}
.status{min-height:16px;margin-top:6px;font-size:12px;color:var(--tg-theme-hint-color)}
.sec{margin:8px 0 2px;font-size:12px;font-weight:600;color:var(--tg-theme-hint-color)}.secb{float:right;border:0;background:transparent;color:var(--tg-theme-link-color);font:11px system-ui;padding:0}
.tg{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 0;border-top:1px solid var(--tg-theme-section-separator-color)}
.tg:first-child{border-top:0}
.tg button{min-width:48px;min-height:28px;border-radius:999px;border:1px solid var(--tg-theme-section-separator-color);background:transparent;color:var(--tg-theme-hint-color);font:11px system-ui}
.tg button.on{background:var(--tg-theme-button-color);border-color:var(--tg-theme-button-color);color:var(--tg-theme-button-text-color)}
</style>
<div class="w">
<div class="h"><button id="b" class="hb" hidden>‹</button><div class="ht"><div id="t" class="b"></div><div id="s" class="s"></div></div></div>
<div id="v"></div>
<div id="st" class="status"></div>
<div class="nav" id="n"><button data-nav="list">🔥 Старты</button><button data-nav="fav">⭐ Избранное</button><button data-nav="filters">🎯 Интересы</button><button data-nav="more">⚙️ Ещё</button></div>
</div>
<script>
(function(){
var W=window.TelegramWidget;if(!W)return;
var BOT=__BOT_JSON__;
var V=document.getElementById('v'),T=document.getElementById('t'),S=document.getElementById('s'),ST=document.getElementById('st'),N=document.getElementById('n'),B=document.getElementById('b'),BUSY=false;
var FSEL=null,FSTATE=null,FCP=0;
function E(x){return String(x==null?'':x).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function D(){try{return JSON.parse(W.chatData||'{}')}catch(e){return{}}}
function M(x){ST.textContent=x||''}
function A(a){BUSY=false;var d={};try{d=JSON.parse(a.result||'{}')}catch(e){}M(d.e||'');R()}
function F(e){BUSY=false;M(e&&e.code==='RATE_LIMITED'?'Слишком часто. Попробуйте через пару секунд.':'Не получилось. Попробуйте ещё раз.');R()}
function Q(a,x){if(BUSY)return;BUSY=true;M(x||'Загружаю…');var p=W.request(a);R();p.then(A,F)}
function up(el,a){while(el&&el!==V){if(el.hasAttribute&&el.hasAttribute(a))return el;el=el.parentElement}return null}
function rows(e,empty){if(!e||!e.length)return '<div class="empty">'+E(empty||'Стартов пока нет')+'</div>';return e.map(function(it){return '<div class="row"><button class="rb" data-card="'+E(it.k)+'"><div class="tt">'+E(it.t)+'</div><div class="mt">'+(it.g?'<span class="pl">'+E(it.g)+'</span>':'')+E([it.w,it.c].filter(Boolean).join(' · '))+'</div></button><button class="st'+(it.f?' on':'')+'" data-fav="'+E(it.k)+'">'+(it.f?'★':'☆')+'</button></div>'}).join('')}
function pager(d){if(!d.g||d.g<=1)return '';return '<div class="pg"><button data-page="'+(d.p-1)+'"'+(d.p<=1?' disabled':'')+'>‹</button><button disabled>'+d.p+' / '+d.g+'</button><button data-page="'+(d.p+1)+'"'+(d.p>=d.g?' disabled':'')+'>›</button></div>'}
function list(d,fav){T.textContent=fav?'Избранное':(d.t||'Старты');var p=[];if(d.l)p.push(d.l);if(d.q)p.push('«'+d.q+'»');if(d.f&&d.f.c&&d.f.c.length)p.push(d.f.c.join(', '));if(d.f&&d.f.g&&d.f.g.length)p.push(d.f.g.join(', '));S.textContent=p.join(' · ');var h=rows(d.e,fav?'Пока пусто. Добавляйте старты звездой.':'Стартов пока нет')+pager(d);if(!fav)h+='<button class="btn" data-nav="filters" style="margin-top:8px">🎯 Фильтры</button>';V.innerHTML=h}
function share(k){return 'https://t.me/share/url?url='+encodeURIComponent('https://t.me/'+BOT+'?start=wapp_'+k)+'&text='+encodeURIComponent('Старт в Sporly')}
function card(d){var c=d.c||{};T.textContent='Старт';S.textContent=c.g||'';V.innerHTML='<div class="card">'+(c.u?'<a class="tt" href="'+E(c.u)+'">'+E(c.t)+'</a>':'<div class="tt">'+E(c.t)+'</div>')+'<div class="mt">📅 '+E(c.w)+'</div><div class="mt">📍 '+E(c.l||'место уточняется')+'</div>'+(c.m?'<div class="mt">🏁 '+E(c.m)+'</div>':'')+(c.d?'<div class="body">'+E(c.d)+'</div>':'')+(c.u?'<div class="mt">🔗 <a href="'+E(c.u)+'">Сайт</a></div>':'')+'<div class="act"><button class="btn'+(c.f?' on':'')+'" data-fav="'+E(c.k)+'">'+(c.f?'★ В избранном':'☆ В избранное')+'</button>'+(BOT?'<a class="btn" href="'+E(share(c.k))+'">Поделиться</a>':'')+'</div></div>'}
function filters(d){FSTATE=d;FSEL={g:((d.s||{}).g||[]).slice(),c:((d.s||{}).c||[]).slice()};FCP=0;renderFilters()}
function fpages(){return Math.max(Math.ceil(((FSTATE.o||{}).c||[]).length/8),1)}
function fchips(kind){var arr=(FSTATE.o||{})[kind]||[],start=kind==='c'?FCP*8:0;return '<div class="chips">'+arr.slice(start,start+8).map(function(x,j){var on=FSEL[kind].indexOf(x)>=0;return '<button class="chip'+(on?' on':'')+'" data-tg="'+kind+':'+(start+j)+'">'+E(x)+'</button>'}).join('')+'</div>'}
function fsec(){var pages=fpages();return '<div class="sec">Регионы'+(pages>1?'<button class="secb" data-fpage="c">'+(FCP+1)+'/'+pages+' ›</button>':'')+'</div>'}
function renderFilters(){T.textContent='Мои интересы';S.textContent='Выберите интересы';V.innerHTML='<div class="sec">Виды спорта</div>'+fchips('g')+fsec()+fchips('c')+'<button class="btn" data-apply="1">Показать старты</button><button class="bt2" data-freset="1">Сбросить</button>'}
function toggleFilter(raw){var p=raw.split(':'),kind=p[0],idx=+p[1],val=((FSTATE.o||{})[kind]||[])[idx],arr=FSEL[kind],at=arr.indexOf(val);if(at>=0)arr.splice(at,1);else arr.push(val);renderFilters()}
function pageFilter(){FCP=(FCP+1)%fpages();renderFilters()}
function filterMask(kind){var arr=(FSTATE.o||{})[kind]||[],m=0;for(var i=0;i<arr.length;i++)if(FSEL[kind].indexOf(arr[i])>=0)m|=1<<i;return m}
function applyFilters(){Q('apply:'+filterMask('g')+':'+filterMask('c'),'Загружаю…')}

function more(){T.textContent='Ещё';S.textContent=(W.viewer&&W.viewer.first_name?'Привет, '+W.viewer.first_name:'Sporly');var h='<button class="btn" data-nav="settings">🔔 Уведомления</button>';if(BOT)h+='<a class="bt2" href="https://t.me/'+E(BOT)+'?start=ref_'+(W.viewer?W.viewer.id:'')+'">🎁 Пригласить друга</a>';h+='<div class="mt">Классика — /classic</div>';V.innerHTML=h}
function settings(d){T.textContent='Уведомления';S.textContent='Можно включить любую комбинацию';var n=d.n||{n:1,d:0,r:1};V.innerHTML='<div class="tg"><span>Новые старты по фильтрам</span><button class="'+(n.n?'on':'')+'" data-set="notify">'+(n.n?'вкл':'выкл')+'</button></div><div class="tg"><span>Ежедневный дайджест</span><button class="'+(n.d?'on':'')+'" data-set="digest">'+(n.d?'вкл':'выкл')+'</button></div><div class="tg"><span>Напоминания об избранном</span><button class="'+(n.r?'on':'')+'" data-set="rem">'+(n.r?'вкл':'выкл')+'</button></div>'}
function R(){var d=D();B.hidden=!(['card','settings'].indexOf(d.v)>=0);switch(d.v){case 'list':list(d,false);break;case 'fav':list(d,true);break;case 'card':card(d);break;case 'filters':filters(d);break;case 'more':more();break;case 'settings':settings(d);break;default:list(d,false)}var bs=N.children;for(var i=0;i<bs.length;i++){bs[i].className=bs[i].getAttribute('data-nav')===d.v?'on':''}if(BUSY){var x=V.getElementsByTagName('button');for(var j=0;j<x.length;j++)x[j].disabled=true}}
V.addEventListener('click',function(e){var t=e.target;var n=up(t,'data-nav');if(n){Q('n:'+n.getAttribute('data-nav'));return}var c=up(t,'data-card');if(c){if(BUSY)return;T.textContent='Старт';V.innerHTML='<div class="empty">Загружаю…</div>';BUSY=true;var p=W.request('c:'+c.getAttribute('data-card'));p.then(A,F);return}var f=up(t,'data-fav');if(f){Q('f:'+f.getAttribute('data-fav'),'Сохраняю…');return}var p=up(t,'data-page');if(p){Q('pg:'+p.getAttribute('data-page'));return}var g=up(t,'data-tg');if(g){toggleFilter(g.getAttribute('data-tg'));return}var fp=up(t,'data-fpage');if(fp){pageFilter();return}var a=up(t,'data-apply');if(a){applyFilters();return}var fr=up(t,'data-freset');if(fr){FSEL={g:[],c:[]};FCP=0;renderFilters();return}var s=up(t,'data-set');if(s){Q('set:'+s.getAttribute('data-set'));return}});
N.addEventListener('click',function(e){var n=up(e.target,'data-nav');if(n)Q('n:'+n.getAttribute('data-nav'))});
B.addEventListener('click',function(){Q('b')});
W.onEvent('chatDataChanged',function(){BUSY=false;R()});R();W.ready();
})();
</script>"""


def render_app_html(bot_username: str) -> str:
    return (
        _APP_HTML.replace("__BOT_JSON__", json.dumps(bot_username))
    )


def app_html_sizes() -> tuple[int, int]:
    import zlib

    html = render_app_html("sporly_bot")
    return len(html.encode("utf-8")), len(zlib.compress(html.encode("utf-8"), 9))


# --------------------------------------------------------------------- state


def _dump(state: dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"))


def fit_app_state(state: dict[str, Any], limit: int = APP_STATE_LIMIT) -> str:
    raw = _dump(state)
    if len(raw.encode("utf-8")) <= limit:
        return raw

    items = state.get("e") or []
    for title_limit, place_limit, category_limit in (
        (36, 24, 16),
        (30, 20, 12),
        (26, 16, 10),
    ):
        for item in items:
            for key, length in (
                ("t", title_limit),
                ("c", place_limit),
                ("g", category_limit),
            ):
                value = item.get(key)
                if isinstance(value, str):
                    item[key] = _shorten(value, length)
        raw = _dump(state)
        if len(raw.encode("utf-8")) <= limit:
            return raw

    while len(items) > 1 and len(raw.encode("utf-8")) > limit:
        items.pop()
        raw = _dump(state)

    card = state.get("c")
    if card:
        for key, length in (("t", 80), ("d", 80), ("m", 60), ("l", 60)):
            value = card.get(key)
            if isinstance(value, str):
                card[key] = _shorten(value, length)
        raw = _dump(state)
        if len(raw.encode("utf-8")) > limit:
            card["d"] = ""
            card["u"] = ""
            raw = _dump(state)

    options = state.get("o")
    if options:
        for key in ("g", "c"):
            values = options.get(key) or []
            while len(values) > 3 and len(raw.encode("utf-8")) > limit:
                values.pop()
                raw = _dump(state)

    return raw


def _shorten(value: str | None, limit: int) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    cut = cut.rstrip(" ,.-—–")
    return (cut or text[:limit]).rstrip() + "…"


def _place_from_parts(
    city: str | None, region: str | None, venue: str | None = None
) -> str:
    raw = (city or "").strip() or (region or "").strip() or (venue or "").strip()
    for separator in (" и ", " / "):
        if separator in raw:
            first = raw.split(separator, 1)[0].strip()
            if first:
                return first
    if "," not in raw:
        return raw
    first, rest = raw.split(",", 1)
    first = first.strip()
    rest = rest.strip()
    if first and not any(character.isdigit() for character in first):
        return first
    return rest or first


def _event_item(event: Event, favorite_ids: set[str]) -> dict[str, Any]:
    return {
        "k": database.event_token(event.id),
        "t": _shorten(clean_text(event.title), 40),
        "w": format_date(event.starts_at, event.date_text, short=True),
        "c": _shorten(
            _place_from_parts(event.city, event.region, event.venue), 28
        ),
        "g": _shorten(clean_text(event.category), 20),
        "f": 1 if event.id in favorite_ids else 0,
    }


def _event_cache_key(
    query: str | None, cities: list[str], categories: list[str]
) -> str:
    return "|".join(
        (
            query or "",
            ",".join(cities),
            ",".join(categories),
        )
    )


async def _load_event_cache(
    session: WidgetSession, key: str, api_page: int = 1
) -> None:
    result = await api_client.get_events(
        EventQuery(
            query=session.query,
            cities=session.cities,
            categories=session.categories,
            date_from=today_iso(),
            page=max(api_page, 1),
            page_size=CACHE_PAGE_SIZE,
            sort_by="date_asc",
        )
    )
    session.events = list(result.items)
    session.event_total = result.total
    session.cache_key = key
    session.cache_offset = (max(api_page, 1) - 1) * CACHE_PAGE_SIZE
    await database.remember_events(
        [event.ref_payload() for event in session.events]
    )


async def _favorite_ids(chat_id: int) -> set[str]:
    return {favorite.event_id for favorite in await database.favorites(chat_id)}


def _title_for(query: str | None, cities: list[str], categories: list[str]) -> str:
    if query:
        return "Поиск"
    if cities or categories:
        return "Подборка"
    return "Ближайшие старты"


async def list_state(
    chat_id: int,
    *,
    page: int,
    query: str | None,
    cities: list[str],
    categories: list[str],
    session: WidgetSession | None = None,
    force: bool = False,
) -> dict[str, Any]:
    key = _event_cache_key(query, cities, categories)
    favorites = await _favorite_ids(chat_id)

    if session is None:
        result = await api_client.get_events(
            EventQuery(
                query=query,
                cities=cities,
                categories=categories,
                date_from=today_iso(),
                page=max(page, 1),
                page_size=APP_PAGE_SIZE,
                sort_by="date_asc",
            )
        )
        await database.remember_events(
            [event.ref_payload() for event in result.items]
        )
        total = result.total
        pages = max((total + APP_PAGE_SIZE - 1) // APP_PAGE_SIZE, 1)
        current = min(max(result.page, 1), pages)
        events = list(result.items)
    else:
        if force or session.cache_key != key or not session.events:
            await _load_event_cache(session, key, 1)

        total = session.event_total
        pages = max((total + APP_PAGE_SIZE - 1) // APP_PAGE_SIZE, 1)
        current = min(max(page, 1), pages)
        start = (current - 1) * APP_PAGE_SIZE
        if session.events and (
            start < session.cache_offset
            or start >= session.cache_offset + len(session.events)
        ):
            await _load_event_cache(
                session, key, start // CACHE_PAGE_SIZE + 1
            )
        local_start = start - session.cache_offset
        events = session.events[local_start : local_start + APP_PAGE_SIZE]

    filters: dict[str, Any] = {}
    if cities:
        filters["c"] = cities
    if categories:
        filters["g"] = categories
    return {
        "v": "list",
        "t": _title_for(query, cities, categories),
        "p": current,
        "g": pages,
        "n": total,
        "l": f"{total} {pluralize(total, 'старт', 'старта', 'стартов')}",
        "q": query or "",
        "f": filters,
        "e": [_event_item(event, favorites) for event in events],
    }


async def favorites_state(chat_id: int, *, page: int) -> dict[str, Any]:
    favorites = await database.favorites(chat_id)
    total = len(favorites)
    total_pages = max((total + APP_PAGE_SIZE - 1) // APP_PAGE_SIZE, 1)
    current = min(max(page, 1), total_pages)
    start = (current - 1) * APP_PAGE_SIZE
    visible = favorites[start : start + APP_PAGE_SIZE]
    items = [
        {
            "k": database.event_token(favorite.event_id),
            "t": _shorten(clean_text(favorite.title), 40),
            "w": format_date(favorite.starts_at, favorite.date_text, short=True),
            "c": _shorten(
                _place_from_parts(favorite.city, favorite.region), 28
            ),
            "g": _shorten(clean_text(favorite.category), 20),
            "f": 1,
        }
        for favorite in visible
    ]
    return {
        "v": "fav",
        "t": "Избранное",
        "p": current,
        "g": total_pages,
        "n": total,
        "l": f"{total} {pluralize(total, 'старт', 'старта', 'стартов')}",
        "e": items,
    }


async def card_state(
    chat_id: int, token: str
) -> dict[str, Any] | None:
    payload = await database.get_event_by_token(token)
    if payload is not None:
        event = Event.model_validate(payload)
        when = format_date(event.starts_at, event.date_text)
        relative = countdown(event.starts_at)
        if relative:
            when = f"{when} · {relative}"
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
        return {
            "v": "card",
            "c": {
                "k": token,
                "t": clean_text(event.title, 160),
                "w": when,
                "l": event.location or clean_text(event.venue, 120),
                "g": clean_text(event.category, 40),
                "m": " · ".join(meta),
                "d": clean_text(event.description, 180),
                "u": event_click_url(chat_id, event.id, event.source_url) or "",
                "f": 1 if await database.is_favorite(chat_id, event.id) else 0,
            },
        }

    favorites = await database.favorites(chat_id)
    favorite = next(
        (
            item
            for item in favorites
            if database.event_token(item.event_id) == token
        ),
        None,
    )
    if favorite is None:
        return None
    return {
        "v": "card",
        "c": {
            "k": token,
            "t": clean_text(favorite.title, 160),
            "w": format_date(favorite.starts_at, favorite.date_text),
            "l": favorite.location,
            "g": clean_text(favorite.category, 40),
            "m": "",
            "d": "",
            "u": event_click_url(
                chat_id, favorite.event_id, favorite.source_url
            )
            or "",
            "f": 1,
        },
    }


def _pick_options(
    all_values: list[str],
    popular: list[str],
    selected: list[str],
    *,
    fill: bool = False,
    limit: int = 8,
) -> list[str]:
    result: list[str] = []
    for value in popular:
        if value and value in all_values and value not in result:
            result.append(value)
    for value in selected:
        if value and value not in result:
            result.append(value)
    if fill:
        for value in all_values:
            if len(result) >= limit:
                break
            if value not in result:
                result.append(value)
    return result[:limit]


def _clean_places(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        place = _place_from_parts(value, None)
        if place and place not in result:
            result.append(place)
    return result


async def filters_state(
    cities: list[str], categories: list[str]
) -> dict[str, Any]:
    try:
        all_cities, all_categories = await api_client.get_filter_options()
    except Exception:
        all_cities, all_categories = [], []
    city_values = _clean_places(all_cities)
    city_selected = [
        place
        for place in (_place_from_parts(city, None) for city in cities)
        if place
    ]
    return {
        "v": "filters",
        "o": {
            "g": _pick_options(
                all_categories,
                POPULAR_CATEGORIES,
                categories,
                fill=True,
                limit=8,
            ),
            "c": _pick_options(
                city_values,
                POPULAR_CITIES,
                city_selected,
                fill=True,
                limit=20,
            ),
        },
        "s": {"g": categories, "c": city_selected},
    }


async def settings_state(chat_id: int) -> dict[str, Any]:
    subscription = await database.get_subscription(chat_id)
    reminders = await database.reminders_enabled(chat_id)
    return {
        "v": "settings",
        "n": {
            "n": 1 if subscription is None or subscription.notify_enabled else 0,
            "d": 1 if subscription and subscription.digest_enabled else 0,
            "r": 1 if reminders else 0,
        },
    }


def simple_state(view: str) -> dict[str, Any]:
    return {"v": view}


# -------------------------------------------------------------------- sending


async def send_app_widget(
    bot: Bot,
    chat_id: int,
    *,
    bot_username: str = "",
    disable_notification: bool = False,
    start_token: str | None = None,
    initial_view: str = "list",
) -> Any:
    subscription = await database.get_subscription(chat_id)
    cities = list(subscription.cities) if subscription else []
    categories = list(subscription.categories) if subscription else []
    session = WidgetSession(
        kind="app",
        chat_id=chat_id,
        message_id=0,
        cities=cities,
        categories=categories,
        bot_username=bot_username,
    )
    try:
        if initial_view == "filters":
            state = await filters_state(cities, categories)
        else:
            state = await list_state(
                chat_id,
                page=1,
                query=None,
                cities=cities,
                categories=categories,
                session=session,
            )
    except Exception:
        logger.exception("Cannot load app widget state")
        return None

    sent = await send_widget(
        bot,
        chat_id,
        html=render_app_html(bot_username),
        chat_data=fit_app_state(state),
        disable_notification=disable_notification,
    )
    if sent is None:
        return None

    session.message_id = sent.message_id
    session.page = state.get("p", 1)
    session.total_pages = state.get("g", 1)
    session.total = state.get("n", 0)
    session.state = state
    remember_session(session)

    if start_token:
        card = await card_state(chat_id, start_token)
        if card is not None:
            session.state = card
            session.history = ["list"]
            await edit_widget_data(
                bot,
                chat_id,
                sent.message_id,
                fit_app_state(card),
            )
    return sent


# --------------------------------------------------------------------- actions


async def _edit(session: WidgetSession, bot: Bot) -> None:
    chat_data = fit_app_state(session.state)
    await edit_widget_data(bot, session.chat_id, session.message_id, chat_data)


async def _answer(
    bot: Bot, query_id: str, status: str = "", error: str = ""
) -> None:
    payload: dict[str, Any] = {}
    if status:
        payload["e"] = status
    if error:
        payload["e"] = error
    await answer_widget_query(bot, query_id, payload)


async def _commit(
    bot: Bot,
    session: WidgetSession,
    query_id: str,
    *,
    status: str = "",
) -> None:
    """Push the new state and answer the query in parallel."""
    await asyncio.gather(
        _edit(session, bot),
        _answer(bot, query_id, status=status),
        return_exceptions=True,
    )


async def _save_filters(
    chat_id: int, cities: list[str], categories: list[str]
) -> None:
    subscription = await database.get_subscription(chat_id)
    await database.save_subscription(
        chat_id,
        cities=cities,
        categories=categories,
        notify_enabled=subscription.notify_enabled if subscription else True,
        digest_enabled=subscription.digest_enabled if subscription else False,
    )
    await database.mark_survey_completed(chat_id)


async def _go_list(
    bot: Bot,
    session: WidgetSession,
    query_id: str,
    *,
    page: int = 1,
    status: str = "",
    force: bool = False,
) -> None:
    try:
        session.state = await list_state(
            session.chat_id,
            page=page,
            query=session.query,
            cities=session.cities,
            categories=session.categories,
            session=session,
            force=force,
        )
    except Exception:
        logger.exception("Cannot load app list")
        await _answer(bot, query_id, error="Каталог временно недоступен")
        return
    session.page = session.state.get("p", 1)
    session.total_pages = session.state.get("g", 1)
    session.total = session.state.get("n", 0)
    session.history.clear()
    await _commit(bot, session, query_id, status=status)


async def _go_favorites(
    bot: Bot, session: WidgetSession, query_id: str, *, page: int = 1
) -> None:
    session.fav_page = max(page, 1)
    session.state = await favorites_state(session.chat_id, page=session.fav_page)
    session.history.clear()
    await _commit(bot, session, query_id)


async def _go_view(
    bot: Bot, session: WidgetSession, query_id: str, view: str
) -> None:
    if view == "list":
        await _go_list(bot, session, query_id, page=1)
    elif view == "fav":
        await _go_favorites(bot, session, query_id, page=1)
    elif view == "filters":
        session.state = await filters_state(session.cities, session.categories)
        await _commit(bot, session, query_id)
    elif view == "settings":
        session.state = await settings_state(session.chat_id)
        await _commit(bot, session, query_id)
    elif view in {"search", "more", "help", "partners"}:
        session.state = simple_state(view)
        await _commit(bot, session, query_id)
    else:
        await _answer(bot, query_id, error="Не понял действие")


async def _toggle_favorite(
    bot: Bot, session: WidgetSession, query_id: str, user_id: int, token: str
) -> None:
    from app.flows import toggle_favorite_by_token

    state = session.state
    current = 0
    if state.get("v") == "card":
        current = int(state.get("c", {}).get("f") or 0)
    else:
        item = next(
            (item for item in state.get("e", []) if item.get("k") == token),
            None,
        )
        current = int(item.get("f") or 0) if item else 0

    target = not bool(current)
    ok, _ = await toggle_favorite_by_token(user_id, token, add=target)
    if not ok:
        await _answer(bot, query_id, error="Старт устарел. Откройте заново.")
        return

    if state.get("v") == "card":
        state["c"]["f"] = 1 if target else 0
    else:
        items = state.get("e", [])
        for item in items:
            if item.get("k") == token:
                item["f"] = 1 if target else 0
        if state.get("v") == "fav" and not target:
            state["e"] = [item for item in items if item.get("k") != token]
            state["n"] = max(int(state.get("n") or 0) - 1, 0)
            state["g"] = max(
                (state["n"] + APP_PAGE_SIZE - 1) // APP_PAGE_SIZE,
                1,
            )
            if not state["e"] and session.fav_page > 1:
                session.fav_page -= 1
                state.update(
                    await favorites_state(
                        session.chat_id, page=session.fav_page
                    )
                )
    await _commit(
        bot,
        session,
        query_id,
        status="Добавлено в избранное" if target else "Убрано из избранного",
    )


async def _toggle_filter(
    bot: Bot, session: WidgetSession, query_id: str, raw: str
) -> None:
    try:
        kind, index_raw = raw.split(":", 1)
        index = int(index_raw)
    except (ValueError, AttributeError):
        await _answer(bot, query_id, error="Не понял фильтр")
        return
    if kind not in {"g", "c"}:
        await _answer(bot, query_id, error="Не понял фильтр")
        return

    state = session.state
    options = (state.get("o") or {}).get(kind) or []
    if index < 0 or index >= len(options):
        await _answer(bot, query_id, error="Фильтр устарел")
        return
    value = options[index]
    selected = (state.get("s") or {}).get(kind) or []
    if value in selected:
        selected = [item for item in selected if item != value]
    else:
        selected = [*selected, value]
    state.setdefault("s", {})[kind] = selected
    if kind == "g":
        session.categories = selected
    else:
        session.cities = selected
    await _commit(bot, session, query_id)


async def _toggle_setting(
    bot: Bot, session: WidgetSession, query_id: str, field: str
) -> None:
    chat_id = session.chat_id
    if field in {"notify", "digest"}:
        subscription = await database.get_subscription(chat_id)
        if subscription is None:
            subscription = await database.save_subscription(
                chat_id,
                cities=session.cities,
                categories=session.categories,
                notify_enabled=True,
                digest_enabled=False,
            )
        column = "notify_enabled" if field == "notify" else "digest_enabled"
        subscription = await database.toggle_subscription(chat_id, column)
        if subscription is None:
            await _answer(bot, query_id, error="Не удалось изменить настройку")
            return
    elif field == "rem":
        enabled = await database.toggle_reminders(chat_id)
        if enabled is None:
            await database.ensure_user(chat_id, None, None)
            await database.toggle_reminders(chat_id)
    else:
        await _answer(bot, query_id, error="Не понял настройку")
        return

    session.state = await settings_state(chat_id)
    await _commit(bot, session, query_id)


async def handle_app_query(
    bot: Bot,
    session: WidgetSession,
    query_id: str,
    user_id: int,
    data: str,
) -> None:
    state = session.state
    try:
        if data == "b":
            view = "list"
            if state.get("v") == "card":
                view = session.history.pop() if session.history else "list"
            elif state.get("v") in {"settings", "help", "partners"}:
                view = "more"
            elif state.get("v") == "search":
                view = "filters"
            await _go_view(bot, session, query_id, view)
            return

        if data == "rf":
            if state.get("v") == "fav":
                await _go_favorites(
                    bot, session, query_id, page=session.fav_page
                )
            else:
                await _go_list(bot, session, query_id, page=session.page, force=True)
            return

        if data.startswith("n:"):
            view = data[2:]
            if view == "card":
                await _answer(bot, query_id, error="Не понял действие")
                return
            if view in {"settings", "help", "partners", "search"}:
                session.history.append(state.get("v", "list"))
            await _go_view(bot, session, query_id, view)
            return

        if data.startswith("c:"):
            token = data[2:]
            next_state = await card_state(session.chat_id, token)
            if next_state is None:
                await _answer(bot, query_id, error="Старт устарел")
                return
            session.history = [state.get("v", "list")]
            session.state = next_state
            # Edit first: the widget shows the card as soon as Telegram applies
            # the state, then the request promise is resolved.
            await _edit(session, bot)
            await _answer(bot, query_id)
            return

        if data.startswith("f:"):
            await _toggle_favorite(bot, session, query_id, user_id, data[2:])
            return

        if data.startswith("pg:"):
            try:
                page = int(data[3:])
            except ValueError:
                await _answer(bot, query_id, error="Не понял страницу")
                return
            if state.get("v") == "fav":
                await _go_favorites(bot, session, query_id, page=page)
            else:
                await _go_list(bot, session, query_id, page=page)
            return

        if data.startswith("t:"):
            await _toggle_filter(bot, session, query_id, data[2:])
            return

        if data.startswith("apply:"):
            parts = data.split(":")
            if len(parts) != 3:
                await _answer(bot, query_id, error="Не понял фильтры")
                return
            try:
                category_mask = int(parts[1])
                city_mask = int(parts[2])
            except ValueError:
                await _answer(bot, query_id, error="Не понял фильтры")
                return
            state = session.state
            options = state.get("o") or {}
            session.categories = [
                value
                for index, value in enumerate(options.get("g", []))
                if category_mask & (1 << index)
            ]
            session.cities = [
                value
                for index, value in enumerate(options.get("c", []))
                if city_mask & (1 << index)
            ]
            await _save_filters(
                session.chat_id, session.cities, session.categories
            )
            await _go_list(bot, session, query_id, page=1, status="Обновлено")
            return

        if data == "apply":
            state = session.state
            session.cities = list((state.get("s") or {}).get("c") or [])
            session.categories = list((state.get("s") or {}).get("g") or [])
            await _save_filters(
                session.chat_id, session.cities, session.categories
            )
            await _go_list(bot, session, query_id, page=1, status="Обновлено")
            return

        if data == "reset":
            session.cities = []
            session.categories = []
            session.query = None
            await _save_filters(session.chat_id, [], [])
            session.state = await filters_state([], [])
            await _commit(bot, session, query_id)
            return

        if data.startswith("q:"):
            query = data[2:].strip() or None
            session.query = query
            await _go_list(bot, session, query_id, page=1, status="Обновлено")
            return

        if data == "mode:classic":
            await database.set_ui_mode(session.chat_id, "classic")
            await _answer(bot, query_id, status="Классический режим")
            from app.handlers.common import send_home

            sent = await send_home(bot, session.chat_id)
            if sent is not None:
                try:
                    await bot.delete_message(
                        session.chat_id, session.message_id
                    )
                except Exception:
                    pass
            return

        if data.startswith("set:"):
            await _toggle_setting(bot, session, query_id, data[4:])
            return

        await _answer(bot, query_id, error="Не понял действие")
    except Exception:
        logger.exception("Widget app action failed: %s", data)
        await _answer(bot, query_id, error="Ошибка. Попробуйте ещё раз.")
