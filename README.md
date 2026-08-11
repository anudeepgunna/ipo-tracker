# IPO Tracker

A dashboard for Indian IPOs — live subscription figures, grey market premium, listing
estimates, and the thing no IPO website does well: **an alert before the application
window closes.**

> **Informational only. Not investment advice.** Grey market premium is unofficial,
> unregulated, thinly traded and easily manipulated. The listing outlook score is a
> transparent heuristic over public data, not a prediction.

---

## What it does

- **Live IPO list** from NSE — mainboard and SME, with price band, lot size, dates and
  the minimum investment per lot.
- **Category-wise subscription** (QIB / NII / Retail / Employee / Total) captured as a
  time series, so you can see whether a book is building or stalling rather than just
  its current multiple.
- **GMP and listing estimate** — `estimated listing price = issue price + GMP`, plus the
  implied gain percentage.
- **Listing outlook score (0–100)** that shows every component and weight that produced
  it, and returns *no score at all* when the inputs are too thin to justify one.
- **Alerts on four channels** — email, Telegram, browser push and in-app — with
  last-day reminders that fire at 10:00 and 15:00 IST and never after the ~17:00
  application cutoff.

## Where the data comes from

| Data | Source | Key needed |
|---|---|---|
| IPO list, dates, price band, issue size | NSE `/api/all-upcoming-issues` | No |
| Category-wise subscription | NSE `/api/ipo-active-category` | No |
| Lot size, face value, registrar | NSE `/api/ipo-detail` | No |
| Grey market premium | Pluggable provider (IPO Guru) | Yes — free |

NSE has no documented public API, but the JSON endpoints its own site calls are open.
They do reject requests that don't look like a browser session, so
[`app/clients/nse.py`](backend/app/clients/nse.py) primes a cookie jar by fetching the
HTML page first and reuses it — the usual reason NSE scrapers break.

**GMP is the one field with a hard third-party dependency**, because no exchange
publishes grey market data. It sits behind a `GmpProvider` protocol with a null
implementation, so the app runs fully without it; the UI just shows "no GMP data".

## Quick start

```bash
# 1. Database (or point DATABASE_URL at any Postgres)
docker compose up -d db

# 2. Backend
cd backend
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env          # works as-is for local development
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli poll     # pull live data from NSE
.venv/bin/uvicorn app.main:app --reload

# 3. Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

Open http://localhost:5173. The API is at http://localhost:8000, docs at `/docs`.

No Docker? Set `DATABASE_URL=sqlite+aiosqlite:///./ipo_dev.db` in `backend/.env`.
SQLite is fine for development; Postgres is the deployment target.

### Signing in

Auth is a passwordless magic link. Without `RESEND_API_KEY` set, the server returns the
link in the response (and logs it) instead of emailing it, so local development is never
locked out.

## Setting up alerts

Every channel is independently optional — the UI only offers ones the server has
credentials for.

| Channel | What you need |
|---|---|
| **In-app** | Nothing |
| **Email** | A [Resend](https://resend.com) API key (free: 3k/month) in `RESEND_API_KEY` |
| **Telegram** | Create a bot with [@BotFather](https://t.me/botfather), set `TELEGRAM_BOT_TOKEN`, then use "Link Telegram" in the UI |
| **Browser push** | `python -m app.cli vapid-keys`, paste both keys into `.env` |

Then create a rule on the **Alerts** page, or seed the defaults:

```bash
python -m app.cli seed-alerts you@example.com   # last-day alerts, 10:00 & 15:00 IST
python -m app.cli test-notify you@example.com   # verify each channel actually delivers
```

### How firing works

A date rule declares the IST hours it fires at. A slot fires when the current time falls
inside `[hour, hour + 3h)`. That window does two jobs: with a 15-minute poll every slot
is reliably caught, and a rule created late in the day fires only the slot it is
currently inside rather than dumping every earlier slot at once.

Each queued alert carries a unique `dedupe_key` of
`{rule}:{ipo}:{event}:{date}:{hour}:{channel}`. **Without it a single last-day rule
would emit ~28 duplicate alerts per day**, so it is enforced by a database constraint,
not by application logic alone.

Rule evaluation and delivery are separate passes. Evaluation only inserts rows;
a delivery failure leaves the row pending and the next cycle retries it, so a Telegram
outage can't lose an alert.

## Deployment (Render)

`render.yaml` provisions a Postgres database, the API, and the static dashboard.

1. Push this repo to GitHub, then **New → Blueprint** in Render and point it here.
2. Set the optional secrets (`RESEND_API_KEY`, `TELEGRAM_BOT_TOKEN`, VAPID keys,
   `IPOGURU_API_KEY`) in the dashboard.
3. Add two repository secrets in GitHub so the scheduler can run:
   - `API_URL` — your Render API URL
   - `INTERNAL_TASK_TOKEN` — copy the generated value from Render's env vars

The poller runs from [`.github/workflows/poll.yml`](.github/workflows/poll.yml), which
POSTs to `/internal/tasks/poll` every 15 minutes during IST market hours. Render's
native cron jobs need a paid instance, and free web services sleep when idle — an
Actions cron is free and wakes the service as a side effect. `render.yaml` includes a
commented-out native cron block for when you upgrade.

> Render's free Postgres expires after 30 days. Upgrade the database or re-provision
> before then if you want history to persist.

## Testing

```bash
cd backend && .venv/bin/python -m pytest      # 62 tests
```

Parser tests run against **real NSE payloads** captured in `tests/fixtures/`, so they
encode the shapes that actually break naive parsing: header echo rows, compound `srNo`
breakdown rows that would double-count against the total, empty-string numerics, and
scientific notation (`8.1798244E7`) on the Total row.

The alert tests simulate a poller running every 15 minutes and assert exactly one alert
per slot — the regression that would make the feature unusable.

## Layout

```
backend/
  app/
    clients/nse.py            cookie-primed NSE client + pure parsers
    services/
      ingest.py               NSE + GMP -> database
      alerts.py               rule evaluation, dedupe, message building
      scoring.py              transparent 0-100 outlook heuristic
      views.py                dashboard payload assembly
      gmp/                    pluggable GMP providers
      notifications/          4 channels + dispatcher
    routers/                  ipos, auth, me, telegram, internal
    tasks/poll.py             ingest -> evaluate -> dispatch
frontend/
  src/pages/                  Dashboard, IpoDetail, Alerts, Inbox, Login
  src/components/             IpoCard, ScoreMeter, SubscriptionChart
```

## Notes and limitations

- **Subscription data is not real-time.** NSE republishes periodically and stamps each
  update; snapshots are keyed on that stamp, so polling more often doesn't produce finer
  data — it just avoids missing a refresh.
- **Allotment and listing dates** are not in NSE's IPO feed. They're backfilled
  opportunistically from the GMP provider, so those alert types need one configured.
- **SME coverage** is NSE-listed SME issues only (series `SME`). BSE-only SME IPOs would
  need a second client.
