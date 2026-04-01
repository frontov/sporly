# DEPLOY: sporly.ru

Готовая инструкция для деплоя `Sporly` на VPS:

- IP: `213.171.28.240`
- домен: `sporly.ru`
- целевая ОС: `Ubuntu`
- путь проекта на сервере: `/opt/sporly`

## 1. DNS

Проверьте, что домен уже указывает на сервер:

- `A` запись `sporly.ru` -> `213.171.28.240`
- желательно `A` запись `www.sporly.ru` -> `213.171.28.240`

## 2. Подготовка сервера

Подключение:

```bash
ssh fronteno@213.171.28.240
sudo su
```

Обновление пакетов:

```bash
apt update && apt upgrade -y
apt install -y ca-certificates curl gnupg git
```

## 3. Установка Docker

```bash
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable docker
systemctl start docker
```

Проверка:

```bash
docker --version
docker compose version
```

## 4. Копирование проекта

Если используете git:

```bash
mkdir -p /opt/sporly
cd /opt/sporly
git clone <YOUR_REPO_URL> .
```

Если git-репозитория нет, скопируйте проект в `/opt/sporly` любым удобным способом.

## 5. Production env

Создайте env-файл:

```bash
cd /opt/sporly
cp .env.prod.example .env.prod
```

Содержимое `.env.prod` для вашего домена:

```env
DOMAIN=sporly.ru

CACHE_TTL_SECONDS=300
REQUEST_TIMEOUT_SECONDS=15
SOURCE_TIMEOUT_SECONDS=45
ENRICH_TIMEOUT_SECONDS=12
MAX_CONCURRENT_SOURCES=2
MAX_ENRICH_EVENTS_PER_SOURCE=120
MINIMUM_REFRESH_RATIO=0.7
```

## 6. Источники и данные

Проверьте, что файл источников существует:

```bash
ls -la /opt/sporly/backend/app/config/sources.json
```

Если нужно, отредактируйте его:

```bash
nano /opt/sporly/backend/app/config/sources.json
```

Каталог кэша создастся автоматически, но можно создать заранее:

```bash
mkdir -p /opt/sporly/backend/app/data
```

## 7. Запуск production-стека

```bash
cd /opt/sporly
docker compose --env-file .env.prod -f docker-compose.prod.yml up --build -d
```

Проверка контейнеров:

```bash
docker compose -f docker-compose.prod.yml ps
```

Проверка HTTP:

```bash
curl -I http://sporly.ru
```

Проверка HTTPS:

```bash
curl -I https://sporly.ru
```

Примечание:

- `Caddy` сам выпустит сертификат Let's Encrypt
- для этого домен должен уже смотреть на сервер, а порты `80` и `443` должны быть открыты

## 8. Открытие портов

Если включен `ufw`:

```bash
ufw allow 22
ufw allow 80
ufw allow 443
ufw enable
ufw status
```

## 9. Автостарт после перезагрузки

Скопируйте systemd unit:

```bash
cp /opt/sporly/deploy/systemd/sporly.service /etc/systemd/system/sporly.service
systemctl daemon-reload
systemctl enable sporly
systemctl start sporly
```

Проверка:

```bash
systemctl status sporly
```

## 10. Полезные команды

Логи:

```bash
cd /opt/sporly
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f
```

Перезапуск:

```bash
cd /opt/sporly
docker compose --env-file .env.prod -f docker-compose.prod.yml up --build -d
```

Остановка:

```bash
cd /opt/sporly
docker compose --env-file .env.prod -f docker-compose.prod.yml down
```

Рестарт через systemd:

```bash
systemctl restart sporly
```

## 11. Обновление приложения

```bash
cd /opt/sporly
git pull
docker compose --env-file .env.prod -f docker-compose.prod.yml up --build -d
```

## 12. Что должно получиться

После успешного деплоя:

- `https://sporly.ru` открывает frontend
- `Caddy` обслуживает HTTPS
- frontend проксирует `/api` в backend
- backend работает внутри docker-сети
- стек автоматически стартует после reboot
