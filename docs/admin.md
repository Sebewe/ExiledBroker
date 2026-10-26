# The admin page

`/admin` is the site owner's page: the pipeline's health now, the site's usage counts once the cookie-free metrics land. It isn't linked anywhere and shows nothing without the token. Built 2026-10-26.

## What it shows

- **Pipeline**, per league, from `ingest_run` (one row per live update, failed or not, kept 90 days; `services/pipeline_health.summary`): when it last ran and last succeeded, the latest hour loaded, the latest run's state and error, and over the past 24 hours the runs and failures, median run time, requests, bytes downloaded and hours added. It warns when the latest update failed or nothing has succeeded for 2 hours.
- **Usage** (visitors per day, uniques, returning, per-page and per-feature counts): comes from the cookie-free metrics work and is added to the same response when it lands.

## Access

No user system: one token.

- **Server:** `EB_ADMIN_TOKEN`, at least 32 characters (shorter refuses to start). Generate one with `python -c 'import secrets; print(secrets.token_urlsafe(32))'`. Unset or empty, every `/api/admin/*` route answers 404, as if it didn't exist.
- **Requests:** `Authorization: Bearer <token>`, compared in constant time. A wrong or missing token gets 401 before the database is touched, so guessing costs nothing but the request (and at 32 random bytes it can't succeed). The Worker's per-IP rate limit on `/api/*` covers it too.
- **Browser:** the page asks for the token and keeps it in `sessionStorage` (this tab only, gone when it closes; "Sign out" clears it). The overview is never written to the site's saved query cache (`lib/persist.ts` keeps only the status and the current version's tables) and is dropped from memory when the page is left. The page adds `noindex`.
- **Caching:** responses are `Cache-Control: no-store, private`, so neither browsers nor Cloudflare's edge keep them.

## Cost

The page's code is its own lazy chunk (~2 kB gzipped); nobody else downloads it. The overview is read from the database on each request (a couple of aggregates over a few thousand `ingest_run` rows), only for the admin, and the page refreshes it every 5 minutes while open. It isn't precomputed or cached, unlike the public endpoints, because only one person can ask for it.

## Once deployed

- Set `EB_ADMIN_TOKEN` on the Railway **web** service (sealed). The pipeline doesn't need it.
- Optional second lock: **Cloudflare Access** (Zero Trust, free for up to 50 users) on `exiledbroker.trade/admin*` and `exiledbroker.trade/api/admin*`, with a one-time-PIN email policy for the owner's address. Then Cloudflare asks for a login before the request reaches Railway, and the token still applies behind it. Not needed for safety; it hides the page's existence.
- Locally: `EB_ADMIN_TOKEN=… .venv/bin/eb serve` plus `npm run dev`, then open http://localhost:5173/admin.
