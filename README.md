# Sporly

Поиск спортивных мероприятий из разных источников в одном каталоге.

## Стек

- `backend/` - FastAPI + парсеры сайтов + JSON-кэш каталога.
- `frontend/` - React + TypeScript + Vite.
- `bot/` - Telegram-бот (aiogram) поверх API backend.
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

### Telegram-бот

```bash
cd bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Заполните в `bot/.env`:

- `BOT_TOKEN` - токен, выданный [@BotFather](https://t.me/BotFather);
- `API_BASE_URL` - адрес backend, локально `http://localhost:8000`;
- `ADMIN_TOKEN` - тот же секрет, что и `ADMIN_TOKEN` у backend (см. `backend/.env.example`), включает админ-команды бота;
- `ADMIN_TELEGRAM_IDS` - ваш Telegram numeric ID (можно узнать у [@userinfobot](https://t.me/userinfobot)), через запятую для нескольких админов.

Запуск:

```bash
python -m app.main
```

Бот работает через long polling, публичный HTTPS-эндпоинт не нужен.

При первом `/start` бот предлагает кнопками выбрать любимые виды спорта и регионы (как фильтры на сайте). Внизу чата всегда висит меню (оно прикрепляется к каждому сообщению без своей инлайн-клавиатуры, поэтому не пропадает и не устаревает):

- 🔍 Найти события - события по сохранённым фильтрам;
- 🎯 Другие фильтры - разовый поиск с другими настройками, сохранённые не меняет;
- ⭐ Избранное - сохранённые старты, отсортированные по близости даты, с обратным отсчётом и ссылкой «Убрать» у каждого;
- ⚙️ Настройки - включить/выключить уведомления о новых стартах по фильтру, включить/выключить ежедневный дайджест, изменить фильтры, сбросить.

Под каждым найденным событием с известной датой есть ссылка «⭐ Сохранить» - добавляет именно это событие в избранное. Бот пришлёт отдельное напоминание за 7, 3 и 1 день до его старта, независимо от фильтров и подписки на новые старты. Добавление и удаление подтверждаются сообщением со ссылкой отмены («✕ Убрать» / «↩ Вернуть в избранное»).

Все действия с избранным - Telegram deep links вида `t.me/<bot>?start=fav_<токен>`, поэтому они остаются рабочими и в старых сообщениях, и после перезапуска бота (соответствие токен - событие хранится в `bot/app/data/event_tokens.json`).

Также доступны команды (для обратной совместимости и текстового поиска): `/find <запрос>` - поиск по названию, `/browse`, `/subscribe`, `/my`. Админские `/status`, `/refresh` - только для `ADMIN_TELEGRAM_IDS`: статус кэша backend и принудительное обновление.

## Деплой через Docker Compose

Самый простой production-сценарий:

```bash
docker compose up --build -d
```

После запуска:

- frontend: `http://localhost:8080`
- backend внутри compose-сети: `http://backend:8000`

### Что входит в production-конфиг

- backend запускается в отдельном контейнере через `uvicorn`;
- frontend собирается в static bundle и отдается через `nginx`;
- `nginx` проксирует `/api` в backend;
- кэш каталога сохраняется в `backend/app/data`;
- `sources.json` монтируется в контейнер backend как read-only;
- `bot` - опциональный сервис (нужен `BOT_TOKEN`), ходит в backend по внутренней сети (`http://backend:8000`), подписки хранит в `bot/app/data`.

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
- `backend` работает только внутри docker-сети и наружу не публикуется.

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
- `ADMIN_TOKEN` - секрет для `/api/admin/*`, используется ботом

Для локальной разработки:

```bash
cp backend/.env.example backend/.env
```

## Переменные окружения бота

Основные настройки лежат в `bot/.env.example`:

- `BOT_TOKEN`
- `API_BASE_URL`
- `ADMIN_TOKEN`
- `ADMIN_TELEGRAM_IDS`
- `POLL_INTERVAL_SECONDS`
- `DIGEST_HOUR_UTC`

## Источники

Текущий список источников задается в:

- `backend/app/config/sources.json`

Шаблон:

- `backend/app/config/sources.example.json`

Чтобы добавить новый сайт:

1. Добавьте источник в `sources.json`.
2. Если DOM нестандартный, добавьте отдельный парсер в `backend/app/parsers/base.py`.
3. Подключите его в `backend/app/services/catalog.py`.

## Кэширование

- кэш хранится в `backend/app/data/events_cache.json`;
- backend поднимает кэш с диска после рестарта;
- если TTL не истек, сайты заново не парсятся;
- при refresh backend защищен от перезаписи кэша слишком маленькой выборкой.

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
