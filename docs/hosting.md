# Hosting and performance

How the site is hosted, what would make it expensive, and how cost is measured. The day-to-day rules for writing code that stays cheap are in [CLAUDE.md](../CLAUDE.md#hosting-plan-and-cost-rules).

## Shape

Everything on Railway (Hobby), three services in one project ([deploy/railway/](../deploy/railway/README.md)), plus an off-site backup on Supabase's free tier ([supabase.md](supabase.md)):

```
web (always on, no data of its own: uvicorn serving /api and the built frontend)
   │ reads (private network, free)
   ▼
Postgres (always on: only what the site reads: the live league, its window's
   ▲       raw pages, the Launch history and picks, the Farming history and report)
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
- **One data service: `eb pipeline run`** (`ingest/pipeline.py`), one pass an hour, then exit (Railway bills a cron service only while it runs). It writes Postgres directly (`db.site_writer`: an in-memory DuckDB with Postgres attached, so the loader runs unchanged). It picks the league (the announced one once started, else poe.ninja's list through `reference.fetch_if_changed`, at most hourly), loads new hours (`sync_live`), keeps only the live window's raw pages in `exchange_page` (about 80 MB for a full window; a loader rebuild re-reads them), adds the live league to the Launch history once its fortnight is over and rebuilds the picks (`launch_picks.refresh`), captures it into the Farming history the same way (`item_history.refresh`, one transaction per league; 2 queries reading no rows on a pass with nothing to capture), and drops a replaced league's rows (`site.drop_leagues`). It refuses an unseeded database rather than backfill. Tested on the replay (`tests/test_pipeline.py`): one request per new hour, exactly the missed hours after downtime, a rebuild with no requests, and seeded-then-caught-up equal to the local copy on Postgres.
- **The Launch picks never read the hourly history.** Each finished league is reduced once to its window medians (`launch_history`, ~2.5k rows a league; 12,332 rows for the five reference leagues instead of 977k hourly rows), and the picks are ranked from that: on the real data, identical to ranking from the hourly rows.
- **`eb live watch` writes Postgres through DuckDB** (`EB_DATABASE_URL`, local use). `db.site_writer` attaches Postgres to an in-memory DuckDB, so the incremental loader runs unchanged and the transaction is Postgres's. On Mirage: 24 new hours in 1.0 s, identical rows, and a failed load rolls back. A worker container starting from an empty disk fetched only the 2 new hours (2 requests, 110 KB) and wrote them in 2 s.
- **Serving.** Each table is a `View` (`api/deps.py`), computed once per data version, gzipped once, and sent with an ETag (`304` for a client that has it). The data version is trusted for 15 s, so a cached request makes no database query. Default views are precomputed when an hour loads (`api/warm.py`). The cache is a bounded LRU, and a new data version drops the old one's results (they're never asked for again; with the Farming page's 206 kB responses, keeping them grew the web service from ~190 MB to ~340 MB, now ~190–220 MB). Cached calls take 2–8 ms on real Allflame data; the heaviest cold call (arbitrage, 566 loops) about 0.3 s.

- **The off-site backup.** After each pass, with `EB_BACKUP_URL` set, the pipeline syncs the site's database to Supabase (`storage/backup.py`): the hours the backup lacks, reference data only when its MD5 differs, the rebuilt Launch, backtest and Farming tables (each group with its own stamp; `item_day_history` league by league, so a new league's capture sends ~1.2 MB, not the whole history), the window's pages; it drops what the site dropped. It reads back only which hours and pages the backup has and a few checksums (~25 kB, ~18 MB a month), and a failed backup never fails the pass. `eb site restore` is the one bulk read, behind `--yes`. Details and measurements: [supabase.md](supabase.md).

Not deployed yet.

## The Railway bill

Simulated with `deploy/railway-sim/` (Railway's per-minute rates, read 2026-10-23: memory $10/GB-month, CPU $20/vCPU-month, volumes $0.15/GB-month, egress $0.05/GB; Hobby is $5 a month including $5 of usage). Visitors follow the real browser model (`web/src/lib/schedule.ts`, the 6 h saved cache, assets cached for a year after the first visit); a day is compressed to an hour of real time, with a pipeline pass each simulated hour against the GGG stand-in. Projected to a month, current layout (web + Railway's Postgres + the pipeline cron, no volume), measured 2026-10-23, before the Farming page. **To rerun:** the page added a fifth precomputed response (206 kB, warmed for every listed league) and the web service now holds ~190–220 MB with the cache fix, against the 0.16–0.17 GB below, so memory, the biggest cost, should be up about $0.4 a month (~40 MB more at $10/GB-month), still well inside the $5:

| Daily visitors | Memory | CPU | Volume | Egress | **Usage** | Bill | Requests / visitor / day |
|---|---|---|---|---|---|---|---|
| 10 | $2.31 | $0.31 | $0.02 | $0.00 | **$2.64** | $5 | 18 |
| 100 | $2.46 | $0.32 | $0.02 | $0.04 | **$2.83** | $5 | 21 |
| 1000 | ~$2.5 | ~$0.3 | $0.02 | ~$0.4 | **~$3.2** (estimate) | $5 | — |

- **Memory is most of it:** the web service ~0.16–0.17 GB and Postgres ~0.07 GB, always on. Visitors barely move it: every response is cached and precomputed each hour.
- **The pipeline costs almost nothing:** ~2.5 s and ~0.2 GB a pass, billed only while it runs: about $0.03 a month, nearly all CPU. Its backup sync adds ~0.3 s a pass.
- **CPU is reported at Railway's rates for the measured use;** Apple Silicon is faster than Railway's vCPUs, so the "slow CPU" band doubles it: still $2.96 / $3.14 at 10 / 100 visitors.
- **1000 visitors** wasn't rerun on this layout (the run was interrupted). The estimate scales the 100-visitor egress tenfold (assets are cached after a first visit) on the same always-on memory; the earlier layout measured $4.12 at 1000, almost all the difference being asset egress before assets were cached.
- **What would push it over $5:** much more always-on memory (a second web replica, a larger cache), a Railway volume holding history again, or an endpoint that recomputes per visitor (the API serves only the five precomputed responses, `docs/decisions.md`). The Supabase backup isn't on this bill.
- **p95 latency** 33–75 ms at 10 and 100 visitors, no errors.

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
