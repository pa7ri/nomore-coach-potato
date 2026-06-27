# nomore-coach-potato

A small Telegram bot for planning things with my partner. Add plans (date, duration, price, location, link), query them by week or day, ask for a random one, and keep a shared movie watchlist with a random pick.

## Stack

- Python 3.11
- [`python-telegram-bot`](https://docs.python-telegram-bot.org/) v21 (async)
- Supabase Postgres via `asyncpg`
- Deployed on Render (free web service) with a Telegram webhook

## Commands

Plans:
- `/addplan` — guided add (title, when, duration, price, location, description, link)
- `/week` — plans in the next 7 days, grouped by day
- `/day <date>` — plans for a specific day (`today`, `tomorrow`, `friday`, or `YYYY-MM-DD`)
- `/randomplan` — a random upcoming plan
- `/listplans` — paginated full list (10/page)
- `/delplan <id>`

Movies:
- `/addmovie Title | optional note | optional link`
- `/movies` — unwatched, paginated
- `/randommovie`
- `/watched <id>` — marks watched (kept for history)
- `/delmovie <id>`

## Running locally

```bash
cp .env.example .env
# fill in BOT_TOKEN, DATABASE_URL, ALLOWED_CHAT_IDS
pip install -e .
MODE=poll python -m app.main
```

`MODE=poll` uses long-polling so you don't need a public URL. `MODE=webhook` is what Render runs.

## Deploy (Render + GitHub)

1. Push to GitHub.
2. In Render, "New → Blueprint" pointing at this repo — `render.yaml` is picked up automatically.
3. Fill the env vars in the dashboard (everything except `TIMEZONE` is `sync: false`).
4. After the first deploy, set `PUBLIC_URL` to the assigned `https://<service>.onrender.com` URL and redeploy.
5. Send `/start` from each partner's Telegram account, read the user IDs from the logs, set `ALLOWED_CHAT_IDS`, restart.

The free tier sleeps after 15 min of inactivity and wakes on the first request (~30s cold start).
