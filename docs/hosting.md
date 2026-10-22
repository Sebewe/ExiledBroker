# Hosting and performance

How the site is hosted, what would make it expensive, and how cost is measured. The day-to-day rules for writing code that stays cheap are in [CLAUDE.md](../CLAUDE.md#hosting-plan-and-cost-rules).

## Shape

| Piece | Local | Railway / Supabase |
|---|---|---|
| Database | `db` service (Postgres 17) in `docker-compose.yml`, the same as CI | Supabase Postgres (`EB_DATABASE_URL`) |
| Web | `api` service: uvicorn serving `/api` and the built frontend | web service, same image |
| Worker | `worker` profile: `eb live watch` writing Postgres | worker service, same image |
| Frontend dev | `npm run dev` in `web/`, proxying `/api` to `:8000` | built into the image |

- **One image, two start commands** (`Dockerfile`, `railway.json`): the frontend and API share one origin (no CORS, one service to pay for). The image bakes in DuckDB's postgres extension and runs as a non-root user.
- **DuckDB is the research database** (all history, local). **Postgres is the site**: only the running league, a few hundred MB at most. `eb site seed` copies leagues from DuckDB into Postgres for development; production data comes from the worker.
- **The worker writes Postgres through DuckDB.** `db.site_writer` attaches Postgres to an in-memory DuckDB, so the incremental loader runs unchanged and the transaction is Postgres's. On Mirage: 24 new hours in 1.0 s, identical rows, and a failed load rolls back. A worker container starting from an empty disk fetched only the 2 new hours (2 requests, 110 KB) and wrote them in 2 s.
- **Serving.** Each table is a `View` (`api/deps.py`), computed once per data version, gzipped once, and sent with an ETag (`304` for a client that has it). The data version is trusted for 15 s, so a cached request makes no database query. Default views are precomputed when an hour loads (`api/warm.py`). The cache is a bounded LRU. Cached calls take 2–8 ms on real Allflame data; the heaviest cold call (arbitrage, 566 loops) about 0.3 s.

Not deployed yet.

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
