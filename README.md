# Sporly

Поиск спортивных мероприятий из разных источников в одном каталоге.

## Стек

- `backend/` - FastAPI + парсеры сайтов + JSON-кэш каталога.
- `frontend/` - React + TypeScript + Vite.
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
