# Hosting and performance

How the site is hosted, what would make it expensive, and how cost is measured. The day-to-day rules for writing code that stays cheap are in [CLAUDE.md](../CLAUDE.md#hosting-plan-and-cost-rules).

## Shape

Everything on Railway (Hobby), three services in one project ([deploy/railway/](../deploy/railway/README.md)):

```
web (always on, no data of its own: uvicorn serving /api and the built frontend)
   │ reads (private network, free)
   ▼
Postgres (always on: only what the site reads: the live league, its window's
   ▲       raw pages, the Launch history and picks)
   │ loads the new hours once an hour, in one transaction
   │
pipeline (cron "6 * * * *": eb pipeline run, then exits; no volume, no disk)
```

| Piece | Local | Railway |
|---|---|---|
| Database | `db` service (Postgres 17) in `docker-compose.yml`, the same as CI | Railway's Postgres template (`EB_DATABASE_URL`, private URL) |
| Web | `api` service: uvicorn serving `/api` and the built frontend | web service, same image (`deploy/railway/web.json`) |
| Data | `eb live watch` (run by hand) or `eb pipeline run` | pipeline cron service, same image (`deploy/railway/pipeline.json`) |
| Frontend dev | `npm run dev` in `web/`, proxying `/api` to `:8000` | built into the image |
| All of it, metered | `deploy/railway-sim/` (below) | |

- **One image, two start commands** (`Dockerfile`): the frontend and API share one origin (no CORS, one service to pay for). The image bakes in DuckDB's postgres extension and runs as a non-root user.
- **DuckDB is the research database** (all history), local only. **Postgres is the site**: only what it reads. A new server is seeded from the local copy (`eb site seed --hosted`: the live league's rows and loaded pages, the Launch history and picks), so it never fetches from GGG what we already have.
- **One data service: `eb pipeline run`** (`ingest/pipeline.py`), one pass an hour, then exit (Railway bills a cron service only while it runs). It writes Postgres directly (`db.site_writer`: an in-memory DuckDB with Postgres attached, so the loader runs unchanged). It picks the league (the announced one once started, else poe.ninja's list through `reference.fetch_if_changed`, at most hourly), loads new hours (`sync_live`), keeps only the live window's raw pages in `exchange_page` (about 80 MB for a full window; a loader rebuild re-reads them), adds the live league to the Launch history once its fortnight is over and rebuilds the picks (`launch_picks.refresh`), and drops a replaced league's rows (`site.drop_leagues`). It refuses an unseeded database rather than backfill. Tested on the replay (`tests/test_pipeline.py`): one request per new hour, exactly the missed hours after downtime, a rebuild with no requests, and seeded-then-caught-up equal to the local copy on Postgres.
- **The Launch picks never read the hourly history.** Each finished league is reduced once to its window medians (`launch_history`, ~2.5k rows a league; 12,332 rows for the five reference leagues instead of 977k hourly rows), and the picks are ranked from that: on the real data, identical to ranking from the hourly rows.
- **`eb live watch` writes Postgres through DuckDB** (`EB_DATABASE_URL`, local use). `db.site_writer` attaches Postgres to an in-memory DuckDB, so the incremental loader runs unchanged and the transaction is Postgres's. On Mirage: 24 new hours in 1.0 s, identical rows, and a failed load rolls back. A worker container starting from an empty disk fetched only the 2 new hours (2 requests, 110 KB) and wrote them in 2 s.
- **Serving.** Each table is a `View` (`api/deps.py`), computed once per data version, gzipped once, and sent with an ETag (`304` for a client that has it). The data version is trusted for 15 s, so a cached request makes no database query. Default views are precomputed when an hour loads (`api/warm.py`). The cache is a bounded LRU. Cached calls take 2–8 ms on real Allflame data; the heaviest cold call (arbitrage, 566 loops) about 0.3 s.

Not deployed yet.

## Supabase for the database (tried 2026-10-23)

The idea: Postgres on Supabase's free tier (500 MB database, 5 GB egress a month, 500 MB RAM, paused after a week without activity), web and the pipeline on Railway. The bill stays $5 either way at our traffic (Hobby includes $5 of usage); it would free about half of that usage as headroom. Project in AWS us-east-1 (Railway should run in US East), Postgres 17.11, 60 connections, Data API turned off (it would expose `public` to anyone with the publishable key). Reached through the session pooler (port 5432, IPv4); the direct connection is IPv6 only.

Measured on the seeded project, from home (105 ms round trip), through a byte-counting relay:

| What | Read from Supabase (egress) |
|---|---|
| Seed (`eb site seed --hosted`, Allflame, 672 hours) | uploads only (2 min 18 s); the database is then 282 MB: `cross_market_hour` 114 MB, `price_observation` 96 MB, `exchange_page` 57 MB |
| Web: warm every default view for a new data version | 0.76 MB (6 views) |
| Web: every other endpoint once, cold | 1.24 MB |
| Web: a cached request | 0 |
| Web: one data-version read | 173 B (every 30 s ≈ 15 MB a month) |
| **Pipeline: one pass loading 2 hours** | **98 MB**, 121 s (2 requests to the GGG stand-in) |

- **The pipeline rules it out as it stands.** `db.site_writer` runs the loader on DuckDB with Postgres attached, and DuckDB's postgres scanner doesn't push down aggregates or deletes: it copies the columns it needs for the whole league (`pg_stat_statements`: ctid-range `COPY … TO STDOUT` of all 318k price rows and 439k loop rows, for `max(observed_at)`-style reads and for the DELETE of hours leaving the window). That is free and quick on Railway's private network (2–3 s a pass in the simulation) but ~70 GB a month across the internet, against 5 GB.
- **What would make it fit:** run the pipeline's whole-table statements on Postgres itself (`postgres_query` / `postgres_execute`, or plain psycopg) so a pass reads only the new hour. The site's reads (~1–2 MB an hour) plus that would be roughly 1.5–2 GB a month. It would also shorten passes on Railway.
- **Size:** the window is the most the site holds (launch fortnight + latest 14 days; a switch drops the old league), so 282 MB is about the peak, 56% of the free 500 MB. Re-seeding is a DELETE then COPY, which leaves the old rows as dead space until reused: two re-seeds took it to 488 MB (VACUUM marks the space reusable but doesn't shrink the files). Empty the tables (TRUNCATE) before re-seeding a near-full free project; Supabase makes it read-only above 500 MB.
- **Scheduled fetching on Supabase** (Edge Functions, TypeScript only, 2 s CPU and 256 MB per run, shared outbound IPs) doesn't fit the Python pipeline or the politeness rules; the pipeline stays a Railway cron.

## Hosting cost issues

Reviewed 2026-10-22; measured on real data where possible.

| # | Issue | Measured / estimated | Fix | Status |
|---|---|---|---|---|
| 1 | Live page pulled a league's whole cross-market history (135k rows, 15 MB) to show ~85 rows, every minute | ≈ 650 GB/month Supabase egress (Pro includes 250 GB) | Filter by time in SQL; re-query only when a new hour loads | ✅ 596 rows (0.07 MB) once per hour; the per-minute check takes ~10 ms via the index |
| 2 | Worker fetched any window page missing from disk: ~672 requests/hour on a throwaway disk | Risk of being blocked by GGG | Decide what to fetch from `exchange_hour_loaded` | ✅ a wiped disk fetches only the new hour |
| 3 | No indexes for league + source + time; primary keys start with item id | Full scans on Postgres | Add league/time indexes | ✅ in `schema.sql`; CI checks the live queries seek them (found P1) |
| 4 | Arbitrage pulled 439k rows (49 MB) per cache expiry | High if busy | Aggregate in SQL (exact for any fee buffer or direction) | ✅ 2,086 summary rows (0.23 MB) |
| 5 | Card turn-ins and analysis tools pulled 1.6–6 MB per load | Moderate | Aggregate in SQL (`percentile_cont` medians) | ✅ turn-ins 57 rows instead of 21,628; group timing 280 instead of ~81k |
| 6 | Worker re-downloaded RePoE (3 MB) and the loot filter every run | Small, impolite | Store in `reference_data`; conditional requests on a schedule | ✅ between checks no requests; an unchanged source answers 304 |
| 7 | Every exchange item stored every hour (~1,000 for Allflame) | ~30–50% more rows | Store hourly prices only for what the site reads | ✅ 820k rows instead of 1.44M (−43%; Allflame 260k vs 454k), same numbers on every page |
| 8 | Text primary keys (~2× row size) | Matters at larger scale | Measured | ⏸ integer keys would save ~46% a row, but only ~37 MB at hosted scale, against a refactor touching everything. Revisit at ~10× the rows |
| 9 | Per-visitor memory (Streamlit) and caches keyed on free-typed numbers | Launch-week traffic | Cap every cache; React frontend removes per-visitor state | ✅ all caches bounded at ~59 MB worst case |

## Performance tooling

So the effect of a change on cost is measured, not guessed. None of it is on the public site.

- **CI** (`.github/workflows/ci.yml`, free `ubuntu-latest` runners, superseded runs cancelled): lint, every test, the frontend checks, a **Postgres 17** job, and an image smoke test.
- **Query meter** (`storage/db.metered()`): off by default. When on, it records each read through `db.rows` / `db.scalar` / `db.frame`: rows, bytes, time, SQL and caller.
- **Budgets** (`tests/test_performance.py`, on the real-data replay): each endpoint's rows and bytes on a cold view; live endpoints must not read more as old leagues accumulate; each live update makes one request per new hour, writes only that hour's kept rows, and is recorded in `ingest_run`. A change that legitimately needs more raises the budget in the same change and says why.
- **Postgres checks** (`tests/test_postgres.py`, when `EB_TEST_POSTGRES_URL` is set; the database is wiped): `schema.sql` builds, every service and analysis query answers the same as on DuckDB, and the live queries seek an index.
- **`eb perf report`** (local): endpoint reads, rows stored overall and for the league that would be hosted, and the worker's last 7 days from `ingest_run`. Saved to `data/perf/` and compared with the previous report; growth over 25% or a failing read is flagged.

## Performance findings

Found by the tooling, then fixed. Each fix was checked against the previous version on the full local database (old leagues, the live league, several leagues, an unknown league): identical results.

| # | Finding | Fix | Result |
|---|---|---|---|
| P1 | Queries picked the league by joining `league` on its name, so Postgres had no `league_id` to seek the (league, time) indexes and read every league's recent rows (`cross_market.hourly(since=)`, `live_card_flips`, `hourly_turn_ins(since=)`, `live_loops`) | One league: `league_id = (SELECT id FROM league WHERE name = ?)`. Several: look up ids first (`services/leagues.ids`), then `IN (?, …)`. `IN (SELECT …)` becomes a hash semi-join that can't seek | ✅ all six live queries seek the index on Postgres 17 |
| P2 | Unique moves read raw daily rows and paired days in Python | Pair in SQL (self-join) | ✅ 21,056 rows (1.6 MB) → 7,488 (0.5 MB), 189 → 14 ms. Still the biggest read, but local-only |
| P3 | The whole card table was re-read inside services | Join it in SQL; read only the cards shown | ✅ turn-in summary 57 rows instead of ~418; Live 1,023 rows (165 KB) → 692 (102 KB) |
| P4 | Every `item` row (8,523) looked hosted | Nothing to fix: the exchange loader inserts only items its league refers to | ✅ hosted: 911 items |

Also fixed because Postgres rejected or reordered them: `cross_market.hourly` selected `item_id` twice (DuckDB renames the duplicate, Postgres can't build the frame), and `prices.item_names` sorted text in SQL (Postgres sorts by locale, DuckDB bytewise), so it now sorts in Python.
