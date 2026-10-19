# Bot-only deployment

Production layout: the catalog backend and frontend stay on the main server,
while the Telegram bot runs on a separate VPS.

```
Telegram  ->  bot VPS  ->  https://sporly.ru/api
                  |
                  +-- https://go.sporly.ru/go/...  (partner/event redirects)
```

## Server layout

```
/opt/sporly-bot/
  .env
  docker-compose.yml
  data/                     # SQLite + bot data
  bot/                      # this directory from the repository
```

The bot container joins the existing `blog_default` Docker network so the
already running Caddy container can reach it as `sporly-bot:8081`.

## DNS

```
go.sporly.ru  A  146.103.124.234
```

## Compose

```bash
cd /opt/sporly-bot
docker compose up -d --build
docker compose logs -f --tail 100
```

`API_BASE_URL` must point to the public backend:

```env
API_BASE_URL=https://sporly.ru
PUBLIC_BASE_URL=https://go.sporly.ru
```

## Caddy

Add the site block from `Caddyfile.snippet` to the existing Caddyfile and
reload:

```bash
docker exec blog-caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker exec blog-caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

Check:

```bash
curl https://go.sporly.ru/health
# {"status":"ok"}
```

## Notes

- Only one bot instance may poll Telegram. Stop any local/dev instance before
  starting the production container.
- The bot connects outbound to Telegram and to `https://sporly.ru`; it does not
  need an inbound port except through Caddy.
- Partner and event click tracking work only when `PUBLIC_BASE_URL` is set.
