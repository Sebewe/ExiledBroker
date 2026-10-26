# Hosting and performance

How the site is hosted, what would make it expensive, and how cost is measured. The day-to-day rules for writing code that stays cheap are in [CLAUDE.md](../CLAUDE.md#hosting-plan-and-cost-rules).

## Shape

Everything on Railway (Hobby), three services in one project ([deploy/railway/](../deploy/railway/README.md)), plus an off-site backup on Supabase's free tier ([supabase.md](supabase.md)):

```
web (always on, no data of its own: uvicorn serving /api and the built frontend)
   │ reads (private network, free)
   ▼
Postgres (always on: only what the site reads: the live league, its window's
   ▲       raw pages, the Launch history and picks, the backtest and farming reports)
   │ loads the new hours once an hour, in one transaction
   │
pipeline (cron "6 * * * *": eb pipeline run, then exits; no volume, no disk)
   │ then syncs the changes (storage/backup.py: uploads; reads back ~25 kB)
   ▼
Supabase (another provider, free tier): the off-site backup, read only to restore
```

| Piece | Local | Railway |
|---|---|---|
| Database | `db` service (Postgres 17) in `docker-compose.yml`, the same as CI | Railway's Postgres template (`EB_DATABASE_URL`, private URL) |
| Web | `api` service: uvicorn serving `/api` and the built frontend | web service, same image (`deploy/railway/web.json`) |
| Data | `eb live watch` (run by hand) or `eb pipeline run` | pipeline cron service, same image (`deploy/railway/pipeline.json`) |
| Backup | the simulation's `backup` container | Supabase's free tier (`EB_BACKUP_URL`, on the pipeline only) |
| Frontend dev | `npm run dev` in `web/`, proxying `/api` to `:8000` | built into the image |
| All of it, metered | `deploy/railway-sim/` (below) | |

- **One image, two start commands** (`Dockerfile`): the frontend and API share one origin (no CORS, one service to pay for). The image bakes in DuckDB's postgres extension and runs as a non-root user.
- **DuckDB is the research database** (all history), local only. **Postgres is the site**: only what it reads. A new server is seeded from the local copy (`eb site seed --hosted`: the live league's rows and loaded pages, the Launch history and picks), so it never fetches from GGG what we already have.
- **One data service: `eb pipeline run`** (`ingest/pipeline.py`), one pass an hour, then exit (Railway bills a cron service only while it runs). It writes Postgres directly (`db.site_writer`: an in-memory DuckDB with Postgres attached, so the loader runs unchanged). It picks the league (the announced one once started, else poe.ninja's list through `reference.fetch_if_changed`, at most hourly), loads new hours (`sync_live`), keeps only the live window's raw pages in `exchange_page` (about 80 MB for a full window; a loader rebuild re-reads them), adds the live league to the Launch history once its fortnight is over and rebuilds the picks (`launch_picks.refresh`), adds its paths to Price check's the same way (`price_paths.refresh`: one primary-key lookup on a pass with nothing to capture), and drops a replaced league's rows (`site.drop_leagues`). It refuses an unseeded database rather than backfill. Tested on the replay (`tests/test_pipeline.py`): one request per new hour, exactly the missed hours after downtime, a rebuild with no requests, and seeded-then-caught-up equal to the local copy on Postgres.
- **The Launch picks never read the hourly history.** Each finished league is reduced once to its window medians (`launch_history`, ~2.5k rows a league; 12,332 rows for the five reference leagues instead of 977k hourly rows), and the picks are ranked from that: on the real data, identical to ranking from the hourly rows.
- **`eb live watch` writes Postgres through DuckDB** (`EB_DATABASE_URL`, local use). `db.site_writer` attaches Postgres to an in-memory DuckDB, so the incremental loader runs unchanged and the transaction is Postgres's. On Mirage: 24 new hours in 1.0 s, identical rows, and a failed load rolls back. A worker container starting from an empty disk fetched only the 2 new hours (2 requests, 110 KB) and wrote them in 2 s.
- **Serving.** Each table is a `View` (`api/deps.py`), computed once per data version, gzipped once, and sent with an ETag (`304` for a client that has it). The data version is trusted for 15 s, so a cached request makes no database query. Default views are precomputed when an hour loads (`api/warm.py`). The cache is a bounded LRU, and a new data version drops the old one's results (they're never asked for again; with the Farming page's 206 kB responses, keeping them grew the web service from ~190 MB to ~340 MB, now ~190–220 MB). Cached calls take 2–8 ms on real Allflame data; the heaviest cold call (arbitrage, 566 loops) about 0.3 s.

- **Failure alert.** With `EB_HEALTHCHECK_URL` set, each pass pings a healthchecks.io check: `/start` (one extra request, so the check shows how long a pass runs and a pass that starts and never reports fails after the grace), then success or `/fail` (the pass raised, the backup failed, or the feed looks stopped: the latest hour ended more than 3 h ago with no next league announced). One or two small POSTs to the user's own monitor an hour (never GGG or poe.ninja), 5 s timeout, one retry, never fatal. Set-up: [go-live.md](go-live.md) item 5.
- **The off-site backup.** After each pass, with `EB_BACKUP_URL` set, the pipeline syncs the site's database to Supabase (`storage/backup.py`): the hours the backup lacks, reference data only when its MD5 differs, the rebuilt Launch tables and the backtest and farming reports (each group with its own stamp), the window's pages; it drops what the site dropped. It reads back only which hours and pages the backup has and a few checksums (~25 kB, ~18 MB a month), and a failed backup never fails the pass (it is reported to the failure alert above). `eb site restore` is the one bulk read, behind `--yes`. Details and measurements: [supabase.md](supabase.md).

Not deployed yet.

**In front of it (planned):** Cloudflare's free plan with a small Worker ([deploy/cloudflare/](../deploy/cloudflare/README.md), built, not deployed) that shows a static "Something went wrong, we're investigating" page when Railway can't answer (a hard usage limit, a deploy, a crash). It tells the app's own errors from Railway's by the `X-EB-Origin: app` header the web service stamps on every response. Visitors make ~30 requests a day, so the Worker's free 100,000 requests a day covers ~3,000 visitors; it doesn't change Railway's bill.

## The Railway bill

Simulated with `deploy/railway-sim/` (Railway's per-minute rates, read 2026-10-23: memory $10/GB-month, CPU $20/vCPU-month, volumes $0.15/GB-month, egress $0.05/GB; Hobby is $5 a month including $5 of usage). Visitors follow the real browser model (`web/src/lib/schedule.ts`, the 6 h saved cache, assets cached for a year after the first visit); a day is compressed to an hour of real time, with a pipeline pass each simulated hour against the GGG stand-in. Projected to a month, current layout (web + Railway's Postgres + the pipeline cron, no volume), with the Farming page in the visitors' browsing, measured 2026-10-25:

| Daily visitors | Memory | CPU | Volume | Egress | **Usage** | Bill | Requests / visitor / day |
|---|---|---|---|---|---|---|---|
| 10 | $2.44 | $0.26 | $0.02 | $0.01 | **$2.72** | $5 | 28 |
| 100 | $3.34 | $0.25 | $0.02 | $0.12 | **$3.73** | $5 | 35 |
| 1000 | ~$3.4 | ~$0.3 | $0.02 | ~$1.2 | **~$4.9** (estimate) | $5 | — |

Before the Farming page (2026-10-23) it was $2.64 and $2.83 at 10 and 100 visitors, and ~$3.2 estimated at 1000.

**Price check's data and responses (2026-10-25, [price-check.md](price-check.md) B and C), measured on a copy of the local database and a throwaway Postgres 17:**
- **Tables** (`eb price-check build`, seeded whole, a league switch keeps them): `price_path` 19,360 rows, 3.05 MB (what the pages read); `price_path_league` 3,874 rows (five leagues' own paths as JSON lists), 2.63 MB; `price_path_constant` 12 rows. **5.75 MB in all**, on Postgres and in the backup, uploaded once and again only when a league is captured (the backup reads back a few counts a pass, ~100 B more). It grows by ~0.5 MB a league, never per hour.
- **The pipeline** captures the live league once its fortnight is over: one read of its fortnight's traded hours on the site's database (~250k rows, once a league), then the medians rebuilt. Every other pass makes one primary-key lookup. The constants (the weight and band per phase) aren't refitted there (numpy): they stay as fitted until the next local `eb price-check build` and `eb site seed`. Tested on DuckDB and Postgres (`tests/test_pipeline.py`), where the fortnight is read on Postgres itself, never copied out through DuckDB's scanner.
- **The backup** reads **68 bytes** a pass for these tables (five leagues' stamp: league names and counts, the paths' row count, the constants' count and build time), and uploads ~6 MB (the three tables, replaced whole) only when a league is captured or the constants are refitted. `tests/test_backup.py` budgets the stamp under 150 bytes and a whole pass under 2 kB.
- **Responses** (cached `View`s, as the others): the list is ~148 kB, **24–27 kB gzipped** (Allflame day 90 / Mirage day 4, ~870 items); an item ~18–32 kB, **5–9 kB gzipped** (its series over the hosted window, up to ~670 hours). Computing the list takes ~0.1 s on DuckDB, an item ~20 ms. `eb perf report` (2026-10-25, Allflame day 91, cold cache, local DuckDB opened read-only): the list is 25 queries, 1,965 rows, 140 kB read, 85 ms, 145 kB sent; an item beyond the list is ~677 rows, 51 kB, ~35 ms, 30 kB sent. The report now measures both endpoints (`perf.ENDPOINTS`) and flags growth against the last one. The list and the movers' items (≤ 20) are warmed each hour; other items are built on first request and cached per data version (the bounded LRU, 256 entries).

**The Farming page is retired (2026-10-25, [price-check.md](price-check.md) E):** its warmed view per listed league (206 kB, ~21 kB gzipped each), `item_day_history` (~10 MB on Postgres and in the backup; the schema drops it on the next pass and sync) and its capture are gone, so the figures above, measured with it, are an upper bound until the bill is simulated again. The simulation's visitors no longer ask for `/api/farming`; they price-check about three items a visit (`deploy/railway-sim`). The bill hasn't been re-run with Price check (only on request).

- **Memory is most of it**, and the Farming page added to it. The web service averaged 0.14 GB at 10 visitors and 0.21 GB at 100 (peak 0.34 GB), against ~0.16–0.17 GB before; Postgres 0.11–0.12 GB. The cache fix keeps it from growing without end (old data versions are dropped), but each Farming response is large (206 kB, ~21 kB gzipped), and more visitors warm more of them.
- **The pipeline costs almost nothing:** ~2.4 s and ~0.12–0.16 GB a pass, billed only while it runs: about $0.03 a month, nearly all CPU. Its backup sync adds ~0.3 s a pass.
- **CPU is reported at Railway's rates for the measured use;** Apple Silicon is faster than Railway's vCPUs, so the "slow CPU" band doubles it: still $2.98 / $3.98 at 10 / 100 visitors.
- **1000 visitors** wasn't run (it would take hours). The estimate scales the 100-visitor egress tenfold on the same always-on memory, which puts it close to the $5 included in Hobby. Worth measuring before a launch week, and the Farming response is the first thing to shrink if it's over.
- **What would push it over $5:** much more always-on memory (a second web replica, a larger cache), a Railway volume holding history again, or an endpoint that recomputes per visitor (the API serves only the four precomputed responses since the Farming page was retired, `docs/decisions.md`). The Supabase backup isn't on this bill.
- **p95 latency** 20–34 ms at 10 and 100 visitors, no errors. The league-switch replay (`run.py switch`) passed with the Farming view warmed.

## Supabase: tried as the database, now the off-site backup

Tried on 2026-10-23 as the site's database (free tier: 500 MB, 5 GB egress a month, AWS us-east-1), with web and the pipeline on Railway. It fitted only after the pipeline fix below, at ~1.4 GB of egress a month, and needed rules around every read of it (reads cross from Railway's network, on Google Cloud, to AWS: billed egress), so it became the off-site backup instead (`docs/decisions.md`, [supabase.md](supabase.md)): written to every hour, read only to restore.

Measured on the seeded project, from home (105 ms round trip), through a byte-counting relay, when it was the database:

| What | Read from Supabase (egress) |
|---|---|
| Seed (`eb site seed --hosted`, Allflame, 672 hours) | uploads only (2 min 18 s); 282 MB: `cross_market_hour` 114 MB, `price_observation` 96 MB, `exchange_page` 57 MB |
| Web: warm the default views for a new data version | 0.76 MB (6 views), 0.46 MB (4 views) |
| Web: one data-version read | 173 B |
| Pipeline: one pass loading 2 hours, before the fix | 98 MB, 121 s |
| Pipeline: the same pass, after the fix | 1.8 MB |

- **What the pipeline read, and the fix (kept: it makes Railway's passes shorter too).** `db.site_writer` runs the loader on DuckDB with Postgres attached, and DuckDB's postgres scanner doesn't push down deletes, aggregates or correlated subqueries: it copies the columns it needs for the whole league (`pg_stat_statements`: ctid-range `COPY … TO STDOUT` of all 318k price rows and 439k loop rows). Fixed (profiled on a local Postgres, then confirmed on Supabase):
  - `db.pushdown(con)` runs a statement on Postgres itself, inside the same transaction (`postgres_query` / `postgres_execute`), so a failed pass still rolls back. Used for the loader's deletes (hours listed, not a DuckDB temp table) and its item count, `live_leagues` in `pick_league`, the picks' per-pass checks (`launch_picks.refresh`), the league drop and the seeded check.
  - The attach sees only `public` (`SCHEMA 'public'`): its catalog read was ~0.5 MB per connection, ×8 a pass.
  - Reference documents are read only when used (`Fetch.value` is lazy) and kept in memory by content MD5 (`reference.get`): RePoE's ~1 MB was read 5 times a pass, now once.
  - Pages a pass writes or reads are kept in memory by MD5 (`cx.read_page` asks the database for the stored page's MD5 first), so the loader doesn't read back what was just fetched.
  - `tests/test_pipeline.py::test_a_pass_never_copies_a_whole_table_out_of_postgres` logs every query DuckDB sends (`db.SHOW_PG_QUERIES`) and fails if one copies a big table without an hour or item filter.
- **Re-seeding a free project:** a seed is a DELETE then COPY, which leaves the old rows as dead space (two re-seeds took it to 488 MB of 500; plain VACUUM doesn't shrink the files). Empty the tables first (TRUNCATE, in the dashboard's SQL editor). The backup's own rebuild path uses `VACUUM FULL` for the same reason.
- **Scheduled fetching on Supabase** (Edge Functions, TypeScript only, 2 s CPU and 256 MB per run, shared outbound IPs) doesn't fit the Python pipeline or the politeness rules.
- **A local publisher** (this computer loading the hours and uploading them, with a heartbeat the Railway pipeline deferred to) was built on the `local-publisher` branch to save the pipeline's egress while Supabase was the database. With the database on Railway it isn't needed; the incremental upload it introduced is what `storage/backup.py` does.

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

## A traffic spike (a streamer or a video)

Checked 2026-10-25: what tens of thousands of visitors at once would do to the hosted setup, and what was changed. Visitors can't cause requests to GGG or poe.ninja or reads from Supabase (the pipeline is separate; the API serves precomputed views), so a spike only loads our own stack.

| Risk | Fix | Status |
|---|---|---|
| The fallback Worker sees every request, and its free plan allows 100,000 a day. A first visit is ~15 requests (page, ~10 assets, 3–5 API), so 20k visitors pass the limit within the hour, after which the route fails closed (a Cloudflare error for everyone until 00:00 UTC) | Assets bypass the Worker (a `exiledbroker.trade/assets/*` route with no Worker; the CDN serves them, hashed and immutable for a year); the route fails open; Workers Paid ($5, 10M requests) is the switch if a spike looks big | Go-live checklist section 7 (dashboard steps) |
| Cloudflare cached nothing: JSON isn't cached by default, and a Worker's own requests to Railway aren't either. Every API call reached the one web process | The Worker fetches reads with `cacheEverything`, so the edge keeps what the origin's Cache-Control allows: tables 30 s, the status 60 s, assets a year, index.html and errors never. Each Cloudflare location then asks Railway for a URL about twice a minute however many visitors it serves | ✅ `deploy/cloudflare/handler.mjs`, tested |
| Edge or browser caching could hand a page that has just seen a new hour the previous hour's table, which the page then keeps for the hour (the browser's own 30 s cache already had a small window) | The pages send the data version as `?v=` on every table request: each hour has its own URL. The server ignores it (same server cache entry, same ETag) | ✅ `deps.Version`, `queries.ts`, tested both sides |
| A response without Cache-Control would get Cloudflare's default edge TTL (2 h for a 200, minutes for a 404) | `/api` responses without their own header say `no-store` (errors, the 503 "no data yet", `/api/health`) | ✅ `ApiNoStoreByDefault`, tested |
| Concurrent requests for one uncached view each computed it (dozens of identical queries on a pool of 5) | One computation per key; the others wait for it | ✅ `ResultCache`, tested with 20 threads |
| Price check's items (876 for Allflame) didn't fit the 256-entry cache, and each held ~155 kB (validated rows beside the bytes): caching them all would add ~130 MB | Items go in their own cache (1,024 entries) as gzipped bytes only (~26 kB each, ~25 MB for a whole list); a rare client without gzip gets them decompressed | ✅ `View.slim`, tested |
| A cached request spent most of its time rebuilding the settings (reading the environment and `.env`, ~0.5 ms, several times a request) | The API keeps them for the data version's 15 s window (`deps.settings()`) | ✅ one uvicorn on local Postgres, `ab` at 50 concurrent: cached tables 595 → 4,020 req/s, the status 418 → 3,791 req/s (`/api/health`: ~4,200) |

Cold items stay bounded by the work: ~50 ms an item over 5 connections, about 100 new items a second (300 different items opened by 300 clients at once: all served, the slowest in 5.5 s). With edge caching and one computation per key that path is rare. Memory stayed at ~200 MB through the tests. Only on the live site can Cloudflare's side be checked (`cf-cache-status: HIT`, the fail-open setting): go-live section 7.
