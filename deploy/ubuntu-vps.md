# Sporly on Ubuntu VPS

Ниже минимальный production-сценарий для Ubuntu VPS с `docker compose`, `systemd` и автостартом после перезагрузки.

## 1. Установка Docker

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable docker
sudo systemctl start docker
```

## 2. Копирование проекта

```bash
sudo mkdir -p /opt/sporly
sudo chown $USER:$USER /opt/sporly
cd /opt/sporly
git clone <YOUR_REPO_URL> .
```

Если репозиторий не используется, можно просто скопировать файлы проекта в `/opt/sporly`.

## 3. Production env

```bash
cp .env.prod.example .env.prod
```

Заполните:

```bash
DOMAIN=sporly.example.com
```

И проверьте:

- `backend/app/config/sources.json` существует и заполнен
- DNS домена уже указывает на IP сервера
- порты `80` и `443` открыты в firewall/security group

## 4. Первый запуск

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up --build -d
```

Проверка:

```bash
docker compose -f docker-compose.prod.yml ps
curl -I https://your-domain.com
```

## 5. Автостарт через systemd

Скопируйте unit:

```bash
sudo cp deploy/systemd/sporly.service /etc/systemd/system/sporly.service
sudo systemctl daemon-reload
sudo systemctl enable sporly
sudo systemctl start sporly
```

Проверка статуса:

```bash
sudo systemctl status sporly
```

## 6. Обновление приложения

```bash
cd /opt/sporly
git pull
docker compose --env-file .env.prod -f docker-compose.prod.yml up --build -d
```

Если используется `systemd`, отдельный restart тоже возможен:

```bash
sudo systemctl restart sporly
```

## 7. Полезные команды

Логи:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f
```

Перезапуск:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml restart
```

Остановка:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml down
```
