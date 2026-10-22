# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

ExiledBroker is a Path of Exile 1 market tool: historical and live exchange data → league-start price patterns, arbitrage (card turn-ins, Chaos↔Divine loops) and, later, predictions. `README.md` is the project's **living design document**: the Status table, decision log (with dates), project layout and findings (§9) are updated as work lands. Read it before larger changes and update it with them.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev,pg]'   # Python >=3.11, plain venv (no uv)

.venv/bin/pytest                                   # all tests
.venv/bin/pytest tests/test_live_pipeline.py       # one file
.venv/bin/pytest tests/test_live.py::test_find_launch   # one test
.venv/bin/ruff format . && .venv/bin/ruff check .  # format + lint (line length 100)
# Postgres checks (skipped unless the URL is set; the database is wiped):
docker run -d --name eb-pg -e POSTGRES_PASSWORD=eb -p 55432:5432 postgres:17
EB_TEST_POSTGRES_URL=postgresql://postgres:eb@localhost:55432/postgres .venv/bin/pytest tests/test_postgres.py   # needs .[pg]
.venv/bin/eb perf report   # page reads, storage, worker cost; saved to data/perf/, flags growth vs the last report

.venv/bin/eb serve                         # the site's API at http://127.0.0.1:8000/api (docs at /docs)

# Local copy of hosting: Postgres in Docker stands in for Supabase (see .env.example)
docker compose up -d db
EB_DATABASE_URL=postgresql://eb:eb@localhost:55432/exiledbroker .venv/bin/eb site seed   # copy the live league in
EB_DATABASE_URL=postgresql://eb:eb@localhost:55432/exiledbroker .venv/bin/eb serve       # API from Postgres

# Frontend (web/). Node 24 is unpacked at ~/.local/node (not Homebrew): export PATH=~/.local/node/bin:$PATH
cd web && npm install
npm run dev          # http://localhost:5173, proxies /api to `eb serve` on :8000
npm run gen:api      # after changing API models: regenerate openapi.json + src/api/schema.d.ts
npm run typecheck && npm run lint && npm test && npm run build

# The image Railway runs (web: API + built frontend; worker: eb live watch)
docker compose up -d --build api             # the site as hosted, on http://localhost:8000
docker compose --profile worker up -d        # also the live worker (makes requests to GGG)

# Data (all resumable; Ctrl-C and re-run continues)
.venv/bin/eb dumps sync && .venv/bin/eb dumps load   # daily poe.ninja dumps → tables
.venv/bin/eb exchange sync [-l Mirage]               # hourly GGG exchange, first 14 days per league
.venv/bin/eb live sync|watch [-l Allflame]           # running league: launch fortnight + latest 14 days
scripts/ingest.sh [exchange|dumps|all|live]          # unattended runner, logs to data/logs/latest.log
```

A background run (`nohup … &`) ignores Ctrl-C. Stop it with `pkill -f "eb "`, which is safe at any point. The user runs the live feed (`eb live watch`) externally. Don't leave long-running ingest processes running.

## Architecture

**Pipeline writes, UI reads.** CLI jobs (`cli.py` → `ingest/` → `normalize/`) fetch data and write a local DuckDB file (`data/exiledbroker.duckdb`) plus Parquet. The site (FastAPI in `api/`, React in `web/`) only reads, and only through `services/`. (The Streamlit demo was retired on 2026-10-22; it's in git history.)

**The site's database** is Postgres when `EB_DATABASE_URL` is set (Supabase hosted, the compose `db` service locally), else the local DuckDB file. DuckDB stays the research database (all history); Postgres holds only what the site reads (the live league).
- `db.site_session()`: the API's reads (pooled psycopg). `db.site_writer()`: the live worker's writes, an in-memory DuckDB with Postgres attached (`USE site`), so the incremental loader runs unchanged and its transaction is Postgres's. Code that takes `settings` uses these or `settings.db_path`, never a default path.
- `eb site seed` copies leagues' site rows from DuckDB into Postgres (development bootstrap only; production data comes from the worker).
- **API** (`api/routes/*`): thin wrappers over services with pydantic response models (the frontend's TS types come from the OpenAPI schema). Results are cached in a bounded LRU (`api/cache.py`) keyed on the data version (`max(ingest_load.loaded_at)`), so they're recomputed once per load. Timestamps go out as UTC; NaN/inf as null. Unknown league 404, bad args 422, no data yet 503.
- **Frontend** (`web/`): React + Vite + TypeScript. Types come from the API (`web/openapi.json` → `src/api/schema.d.ts`; `tests/test_api.py` fails if they drift). Data hooks (`src/api/queries.ts`) key every query on `/api/status`'s `data_version`, which is polled each minute: data refetches when a new hour loads, never on a timer. Controls live in the URL (`useParam`). Pins: TypeScript 5.9 (openapi-typescript needs 5) and TanStack Table v8.
- **Design rules** (`web/src/index.css` tokens): dark only; green and red mean profit and loss and nothing else; gold (`accent`) is the brand. Money columns first, numbers right-aligned in tabular figures, long names truncated with a tooltip. Charts: ECharts, lazy-loaded, UTC axis, lines break at missing hours (`lib/chartOptions.line`), linear with log as an opt-in. Every page handles no data (503), waiting for first trades and a stale feed. Check phone width (375px) with real device emulation, since headless Chrome won't size a window that narrow.
- **Deploy:** one `Dockerfile`, two Railway services (web: uvicorn serving `/api` + `web/dist`; worker: `eb live watch`), `railway.json`. The image bakes in DuckDB's postgres extension and runs as a non-root user.
- **Same answers on both engines:** text sorts happen in polars, not SQL `ORDER BY` (Postgres sorts by locale); rankings break ties by `item_id`. `tests/test_postgres.py` compares every service and endpoint.

- **`services/` SQL must stay Postgres-compatible.** No `GROUP BY ALL`, no DuckDB-only functions. The loaders in `normalize/` run locally on DuckDB (they `read_parquet` etc.), so they're exempt. `storage/schema.sql` must run on both engines (`DOUBLE PRECISION`, `ON CONFLICT`, `ADD COLUMN IF NOT EXISTS`). New columns are appended as `ALTER TABLE … ADD COLUMN IF NOT EXISTS` *after* the table's `CREATE`.
- **DuckDB 2.0:** an `execute()` result stays open until fully fetched. Use the helpers `db.rows` / `db.scalar` / `db.frame` (`storage/db.py`), never `fetchone()` on a connection. The same helpers take a psycopg (Postgres) connection, translating `?` placeholders, and they feed the opt-in query meter (`db.metered()`). Reads that bypass them are invisible to the performance tests. Polars is 2.0 too (e.g. CSVs are read positionally with an explicit header check).
- **Resumability is by construction:** every output is written to a temp path and renamed (`ingest/files.py`, `.part` + HTTP Range/If-Range for downloads), so a finished file is its own completion marker. Each league loads in one DB transaction. Exchange loads are **incremental** (`exchange_hour_loaded` tracks loaded hours; a load adds new hours and deletes only hours that left the window), so the database is never wiped to add data. The dump loader skips unchanged inputs via the `ingest_load` fingerprint. Bump a loader's `*_VERSION` constant when its output changes; that triggers one full rebuild.

**Data sources and how they become rows.** The source is in `price_observation.source`.
- `poe.ninja-dump`: daily, every challenge league since 2016 (`ingest/poe_ninja_dumps.py` → `normalize/dump_loader.py`). Only currency, divination cards and uniques are loaded; no base items or gems.
- `ggg-exchange-hourly`: GGG's public currency-exchange history, one immutable page per hour across all leagues, since Settlers (`ingest/currency_exchange.py` → `normalize/exchange_loader.py`). An hour is published a few minutes after it ends. Page `T` must return `next_change_id == T+3600`; earlier timestamps silently return the first page, so every page is validated. The loader prices items by volume-weighting their Chaos and Divine legs (Divine rate carried forward) and also writes `cross_market_hour` (same-hour legs, used by the arbitrage tool).
- **Item identity:** uniques are `ninja:<poe.ninja Id>` (stable across leagues). Everything currency-like, cards included, is `currency:<slug of name>` in every source. Exchange items are named from RePoE by GGG metadata id. An ambiguous RePoE name never merges items: it becomes `Name (MetadataName)`.
- **Hosting scope:** launch with live-league data only. Past leagues are local, for testing and proof of concept.
- **Windows:** `exchange sync` loads a league's first 14 days. `live` loads the launch fortnight **plus** the latest 14 days (`Window.keep_launch_days`), and finds an unknown launch hour by binary search (`find_launch`). Launch-oriented views limit themselves to `day_offset < 14`.

**Curated mappings** (rebuilt after every load by `normalize/mappings.refresh_mappings`):
- `tracked_item` groups (currency / essence / scarab / divination) are name rules in `normalize/tracked.py`, limited to the **core drop pool** (`ingest/core_pool.py`). The pool is poe.ninja's *current-league* lists, snapshotted and replaced (never merged), plus overrides in the committed `config/core_pool.toml` (`exclude` global, `[include]` per group).
- `divination_card`: cards are followed only if NeverSink's loot filter shows them (`ingest/loot_filter.py`, tiers t1–t4). Set size and reward come from RePoE (`normalize/divination.py`). `reward_item_id` is set only for fixed currency/card rewards. Random and unique rewards wait for expected-value work.

**Analysis and scoring.** `analysis/launch_patterns.py` holds the phase-2 tools: unique moves by tier, relative launch curves using a median day-1 baseline, group timing, and card turn-ins across leagues. They report per league, newest first, with recency weights (half-life in leagues). `services/scoring.rank_score` is the one opportunity score: percentile rank per factor, then a weighted mean. Card flips, cross-market loops and the live view all use it. Turn-in figures use the median hour, because thin markets have junk hours.

## Hosting plan and cost rules

Target: the web app **and** the live worker (`eb live watch`, or `eb live sync` on an hourly cron) run on Railway, with data in Supabase Postgres. Only live-league data is hosted (a few hundred MB). The goal is Railway Hobby plus Supabase Free/Pro, so watch for anything that scales cost with time or traffic:
- **Never rewrite data to add data.** Loads stay incremental: insert new hours, delete only what leaves the window.
- **Pages must read small results.** Do aggregation in SQL or in precomputed summary tables written by the worker, not by pulling raw hourly rows into Python. Database egress and compute are what cost money on Supabase. Summaries are computed in SQL (`cross_market.summarize`, `divination.turn_in_summary`, `launch_patterns._curves_sql` / `group_curves`) with Postgres-compatible medians (`percentile_cont(0.5) WITHIN GROUP (ORDER BY …)`, `FILTER (WHERE …)`). The Live page filters by time in SQL (`since=`) and caches on the latest loaded hour, not a timer. Don't divide by a column without `nullif(…, 0)` (Postgres raises on division by zero). Filter the big tables by `league_id`, never by a joined `league.name`: use `= (SELECT id FROM league WHERE name = ?)` for one league, or `services/leagues.ids()` plus `IN (?, …)` for several. Otherwise Postgres can't seek the (league, time) indexes (`IN (SELECT …)` becomes a hash semi-join).
- **Store only what the site reads.** This is a standing practice, not a one-off fix. Before adding a table, column or data source, or loading more of an existing one, check which page or feature reads it, and keep only that. Measure it: rows stored vs rows actually read. Keep whole datasets only where the feature needs the whole universe.
  - Today: hourly price rows are kept only for price-mapping items, followed cards' rewards, and Chaos and Divine (`exchange_loader._keep_used_items`). `cross_market_hour` stays complete because it *is* the arbitrage universe.
  - When a feature needs more, widen the keep rule deliberately and rebuild with `--force`, rather than storing everything "just in case".
  - The same goes for reads: return summaries from SQL, not raw rows.
- **Serve tables from the cache, never per request.** An endpoint builds a `View` (`api/deps.py`): computed once per data version, stored as JSON bytes gzipped once, sent to every visitor with an ETag (`304` for a client that has it). The data version is read at most every 15 s, so a cached request makes no database query. The pages' default views are precomputed when new data loads (`api/warm.py`; `default_views` must match what the frontend sends, which `tests/test_api.py` checks). The cache is a bounded LRU (keys include free-typed numbers).
- **Charts load a window, not the whole history:** hourly chart endpoints take `hours` (default 72, max 28 days).
- **Index for the access paths.** `schema.sql` indexes league + source + time, because the primary keys start with item id.
- **The worker must not depend on a persistent disk.** What to fetch is decided by the database (`exchange_loader.needs_rebuild` / `loaded_hours`), not by which pages are on disk. Reference data (RePoE names, core-pool snapshots, loot-filter tiers) lives in `reference_data` (`ingest/reference.py`). **Never download data we already have:** market hours are immutable and fetched once; reference sources go through `reference.fetch_if_changed`, which checks at most every `max_age` (RePoE weekly, pool and tiers daily; `eb exchange sync --refresh` checks now) using conditional requests (stored ETag / Last-Modified), so an unchanged source answers 304 and nothing is downloaded.
- **The full list** of known cost issues and their status is in the README ("Hosting cost issues", and "Performance findings to fix" from the tooling).
- **Performance is measured, not guessed.** CI (`.github/workflows/ci.yml`) runs lint, all tests and a Postgres 17 job. `tests/test_performance.py` budgets each page's reads, checks that live pages don't read more as history accumulates, and checks each live update's requests and writes (via `ingest_run`). When a change legitimately needs more, raise the budget in the same change and say why. Perf tooling stays local or in CI; nothing goes on the public site (a server-side dev panel later, if needed).
- **Planned (user is designing it; don't build yet):** the site will split into a clear **live trading** section and a **historical** section with preloaded data and graphs.

## Scope rules (decided by the user)

- **Challenge leagues only.** Event and Ruthless leagues are excluded from data and analysis; every command defaults to `kind = challenge`.
- **Only show items in the current core drop pool.** Remove an item via `config/core_pool.toml`, not code.
- **Design for a new league's data arriving.** At launch everything is null and fills in hour by hour, with gaps (no Divine rate in the first hours, untraded items, a single league loaded). Every page must handle no data, one hour, partial days and one-league states. Widgets with data-dependent ranges must not break when there's only one option.
- Recent leagues are the best reference; the currency exchange (Settlers, 2024-07) is a structural break.
- Charts default to linear axes (log scale is only an opt-in toggle). Trading tables put the money columns first. Credit poe.ninja (CC BY-SA) on the public site.

## Testing patterns

- **Tests never touch `data/`.** `tests/conftest.py` points `EB_DATA_DIR` at a temp dir at import. Code that takes `settings` must still use `settings.db_path` for every session, never the default path.
- **A new service or analysis query goes into `_cases` in `tests/test_postgres.py`**, so it's compared between DuckDB and Postgres. Queries behind the live pages also go into `LIVE_QUERIES`, which checks their index use. Text ordering differs between the engines (Postgres sorts by locale), so sort name lists in Python, and don't select a column twice.

- Exchange behaviour is tested with `FakeExchange` / `market()` / `client_for()` in `tests/test_currency_exchange.py` (other test modules import them). `FakeExchange.now` marks the hour still being traded (end of stream).
- The API is tested with FastAPI's `TestClient` on the replay fixture (`tests/test_api.py`: every endpoint after every update). `conftest.py` resets the API caches and sets the version TTL to 0 for each test. The frontend has Vitest + Testing Library tests against a stubbed `fetch` (`web/src/**/*.test.ts(x)`), covering each page's no-data / waiting / stale states.
- `tests/test_live_pipeline.py` replays real GGG pages (Mirage's first 30 hours, `tests/fixtures/mirage_launch.json.gz`) through `ingest.live.sync_live`, hour by hour, and checks what the API reports after each hour. Regenerate the fixture with `python tests/fixtures/make_fixtures.py` (needs Mirage data in `data/`).

## Data and repo hygiene

- All data lives in the gitignored `data/` folder (the default `EB_DATA_DIR`, anchored to the repo root). Never commit it.
- Settings come from `EB_*` environment variables or `.env` (`config.py`).
- `.claude/` and `.agents/` are intentionally left untracked.
- The root `.gitignore` is Python's template, which ignores every `lib/`; `!web/src/lib/` re-includes the frontend's. Check `git add -n` for new folders.
