# Flight Notifier

A private Telegram Mini App that watches Iranian domestic flights on Alibaba, Flightio,
Trip, and Respina24. It performs an immediate search, keeps polling active alerts, and sends
one paginated Telegram message whenever matching inventory changes.

## What is included

- Persian RTL Telegram Mini App with Jalali/Gregorian calendars, explicit date ranges,
  separate outbound/return time windows, passenger counts, cabin class, and alert management.
- Phone allowlist authentication. The bot accepts only the contact attached to the sender's
  Telegram account and binds it to a pre-provisioned database record.
- FastAPI and aiogram webhook service, PostgreSQL persistence, Redis query cache, Celery
  scheduling, Playwright scraper workers, Alembic migrations, Caddy TLS, and Docker Compose.
- Four isolated site adapters, complete-round-trip enforcement, official-host link validation,
  price-unit normalization, cross-site itinerary grouping, and change-only notifications.
- Fixture-based tests. Live scraping is deliberately disabled by default.

The service finds and links flights; it does not purchase tickets, log into seller accounts,
solve CAPTCHAs, rotate identities, or bypass access controls.

## Production setup

1. Create a bot with BotFather and configure its Main Mini App/menu URL as
   `https://YOUR_DOMAIN/app/`.
2. Point the domain at an outside-Iran server with Docker and Docker Compose installed.
3. Copy `.env.example` to `.env` and set at minimum:
   - `DOMAIN` and `BASE_URL`
   - `POSTGRES_PASSWORD` and the matching `DATABASE_URL`
   - `TELEGRAM_BOT_TOKEN`
   - long random `TELEGRAM_WEBHOOK_SECRET` and `SESSION_SECRET`
   - `ALLOWED_ORIGINS=https://YOUR_DOMAIN`
4. Build and start the stack:

   ```sh
   docker compose build
   docker compose up -d
   ```

5. Provision each allowed phone number in canonical or familiar Iranian format:

   ```sh
   docker compose exec api flight-notifier users grant 09396451429
   docker compose exec api flight-notifier users list
   ```

6. From the deployment IP, manually exercise a current domestic route on all four sellers and
   verify the generated result links. Review each site's current terms and crawler directives.
   Only then set `SCRAPING_ENABLED=true` and restart `worker` and `scheduler`.

If a phone is moved to another Telegram account, explicitly clear its old binding:

```sh
docker compose exec api flight-notifier users unbind 09396451429
```

## Local development

Python 3.12 is the target runtime.

```sh
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/playwright install chromium
.venv/Scripts/pytest
.venv/Scripts/uvicorn app.main:app --reload
```

In another terminal:

```sh
cd frontend
npm install
npm run dev
```

Telegram authentication is intentionally not bypassed in development. Use Telegram's test
environment or test the API with a correctly signed `X-Telegram-Init-Data` header.

## Scraper maintenance

Each adapter opens a first-party search URL, captures JSON responses, and falls back to
conservative rendered-card extraction. A parser emits nothing unless it can prove the route,
departure, airline, and official seller link. Round trips additionally require both source-backed
legs. This fail-closed behavior prevents schema drift from creating false flight alerts.

When a site changes:

1. Capture a sanitized Playwright HAR/HTML/JSON fixture from its public search flow.
2. Add that fixture under `tests/fixtures/` and update only the affected adapter/parser.
3. Run the full suite, then a live smoke test from the production egress IP.
4. Never include cookies, account credentials, passenger data, or payment data in fixtures.

## Operations

- Normal polling: 15 minutes. Final 24 hours: 5 minutes. Both include jitter and per-site delay.
- A missing offer is removed only after two successful source checks; a source outage never
  becomes a false availability notification.
- Default quota: five active alerts and 30 alert submissions per authorized user per day.
- `/health` is the container readiness endpoint. Scrape-run status and errors are persisted in
  `scrape_runs`; application logs redact phone numbers.
- Back up the PostgreSQL volume and keep `.env`, database backups, and bot tokens out of source
  control.

