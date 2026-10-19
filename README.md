# Sporly

Поиск спортивных мероприятий из разных источников в одном каталоге.

## Стек

- `backend/` - FastAPI + парсеры сайтов + JSON-кэш каталога.
- `frontend/` - React + TypeScript + Vite.
- `bot/` - Telegram-бот: поиск, подписки, уведомления, напоминания и партнёрские размещения.
- `docker-compose.yml` - production-ready локальный деплой через Docker Compose.

## Что умеет приложение

- собирает события с нескольких спортивных сайтов без публичного API;
- нормализует даты, регионы и категории;
- кеширует результат в `backend/app/data/events_cache.json`;
- отдает единый API `/api/events`;
- показывает каталог с фильтрами, пагинацией и мобильной панелью фильтров.

## Локальная разработка

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Backend будет доступен на `http://localhost:8000`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend будет доступен на `http://localhost:5173`.

### Telegram bot

Подробная инструкция: `bot/README.md`.

```bash
cd bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# укажите BOT_TOKEN
python -m app.main
```

При первом запуске бот спрашивает интересные виды спорта и регионы.
«Ближайшие» показывает только эту подборку, изменить её можно в «Мои интересы».
Бот также присылает новые события по подписке и напоминает об избранных.
Монетизация — партнёрские слоты в поиске и дайджесте
(`bot/app/config/partners.json`).

## Деплой через Docker Compose

Самый простой production-сценарий:

```bash
docker compose up --build -d
```

После запуска:

- frontend: `http://localhost:8080`
- backend внутри compose-сети: `http://backend:8000`
- bot: работает внутри compose-сети и слушает `8080` для партнёрских редиректов

### Что входит в production-конфиг

- backend запускается в отдельном контейнере через `uvicorn`;
- frontend собирается в static bundle и отдается через `nginx`;
- `nginx` проксирует `/api` в backend;
- кэш каталога сохраняется в `backend/app/data`;
- `sources.json` монтируется в контейнер backend как read-only.

## Деплой на реальный домен с HTTPS

Для домена и автоматического TLS подготовлен отдельный сценарий через `Caddy`.

Используются файлы:

- `docker-compose.prod.yml`
- `Caddyfile`
- `.env.prod.example`

### Подготовка

1. Создайте production env:

```bash
cp .env.prod.example .env.prod
```

2. Укажите ваш домен в `.env.prod`:

```bash
DOMAIN=sporly.example.com
```

3. Проверьте, что:

- домен уже указывает на ваш сервер;
- порты `80` и `443` доступны снаружи;
- `backend/app/config/sources.json` заполнен актуальными источниками.

### Запуск

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up --build -d
```

После запуска:

- приложение будет доступно по `https://ваш-домен`;
- `Caddy` автоматически выпустит и обновит TLS-сертификаты;
- `www`-домен редиректится на основной.

### Схема

- `Caddy` принимает внешний HTTPS-трафик;
- `frontend` обслуживает SPA и проксирует `/api` в backend;
- `backend` работает только внутри docker-сети и наружу не публикуется;
- `bot` ходит в backend по внутренней сети, а `/go/` проксируется через nginx для учёта партнёрских переходов.

## Ubuntu VPS + auto-start

Для Ubuntu VPS подготовлен отдельный сценарий с `systemd` и автостартом после перезагрузки:

- инструкция: `deploy/ubuntu-vps.md`
- unit-файл: `deploy/systemd/sporly.service`

Типовой запуск на сервере:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up --build -d
sudo cp deploy/systemd/sporly.service /etc/systemd/system/sporly.service
sudo systemctl daemon-reload
sudo systemctl enable sporly
sudo systemctl start sporly
```

## Переменные окружения backend

Основные настройки лежат в `backend/.env.example`:

- `APP_ENV`
- `API_HOST`
- `API_PORT`
- `CORS_ORIGINS`
- `CACHE_TTL_SECONDS`
- `REQUEST_TIMEOUT_SECONDS`
- `SOURCE_TIMEOUT_SECONDS`
- `ENRICH_TIMEOUT_SECONDS`
- `REFRESH_SCHEDULER_ENABLED`
- `REFRESH_INTERVAL_SECONDS`
- `EVENT_MISS_THRESHOLD`
- `ADMIN_TOKEN`

Для локальной разработки:

```bash
cp backend/.env.example backend/.env
```

## Источники

Текущий список источников задается в:

- `backend/app/config/sources.json`

Шаблон:

- `backend/app/config/sources.example.json`

Чтобы добавить новый сайт:

1. Добавьте источник в `sources.json`.
2. Если DOM нестандартный, добавьте отдельный парсер в `backend/app/parsers/base.py`.
3. Подключите его в `backend/app/services/catalog.py`.

## Рекомендованные и партнёрские старты

Админ может отметить старт как рекомендованный. Такие события получают бейдж
`Рекомендовано Sporly`, поднимаются в начало выдачи (приоритет выше даты) и
доступны через отдельный публичный эндпоинт.

Защита админ-эндпоинтов — заголовок `X-Admin-Token`, значение задаётся в
`ADMIN_TOKEN`. Если токен не задан, админ-эндпоинты отвечают `403`.

Основные методы:

```http
GET  /api/admin/events?q=марафон&date_from=2026-10-19&limit=50
GET  /api/admin/featured
POST /api/admin/featured
DELETE /api/admin/featured/{entry_id}
GET  /api/events/featured
```

Пример отметки события:

```bash
curl -X POST https://sporly.ru/api/admin/featured \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "getrun-1-db58875133a2",
    "label": "Рекомендовано Sporly",
    "priority": 100
  }'
```

Можно передать `source_url` вместо `event_id`. Поле `until` задаёт дату, после
которой отметка перестаёт действовать. Отметки хранятся в
`backend/app/data/featured_events.json` и переживают обновления кэша.

Публичный эндпоинт `GET /api/events/featured` отдаёт только рекомендованные
предстоящие события в формате обычного списка `/api/events`. На сайте они
отмечены звёздочкой и доступны отдельным списком по пункту меню
«Рекомендуем» (`/featured`).

## Кэширование

- кэш хранится в `backend/app/data/events_cache.json`;
- backend поднимает кэш с диска после рестарта;
- если TTL не истек, сайты заново не парсятся;
- новые события добавляются в кэш всегда, даже если источник резко просел;
- старые события не удаляются: после `EVENT_MISS_THRESHOLD` подтверждённых пропусков они помечаются `inactive` и пропадают из выдачи, но остаются в кэше;
- если источник не отдал ни одного события, пропуски не засчитываются — события остаются активными;
- выборка больше не отклоняется из-за общего падения: refresh выполняет event-level merge, а о сильном падении пишет warning;
- фоновый планировщик обновляет кэш каждые `REFRESH_INTERVAL_SECONDS` (по умолчанию 1800 секунд), даже если запросов к API нет;
- планировщик можно отключить через `REFRESH_SCHEDULER_ENABLED=false` — тогда останется только ленивый refresh по TTL.

## Полезные команды

Проверка backend:

```bash
python3 -m compileall backend/app
```

Проверка frontend:

```bash
cd frontend
npx tsc --noEmit
```
