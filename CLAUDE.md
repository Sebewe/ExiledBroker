# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

ExiledBroker is a Path of Exile 1 market tool: historical and live exchange data → league-start price patterns, arbitrage (card turn-ins, Chaos↔Divine loops) and, later, predictions. `README.md` is the project's **living design document**: the Status table, decision log (with dates), project layout and findings (§9) are updated as work lands. Read it before larger changes and update it with them.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev,demo]'   # Python >=3.11, plain venv (no uv)

.venv/bin/pytest                                   # all tests
.venv/bin/pytest tests/test_live_pipeline.py       # one file
.venv/bin/pytest tests/test_live.py::test_find_launch   # one test
.venv/bin/ruff format . && .venv/bin/ruff check .  # format + lint (line length 100)

.venv/bin/streamlit run app/dashboard.py   # demo; run from the repo root so .streamlit/config.toml (theme) loads
.venv/bin/eb serve                         # FastAPI (hosted-API skeleton)

# Data (all resumable; Ctrl-C and re-run continues)
.venv/bin/eb dumps sync && .venv/bin/eb dumps load   # daily poe.ninja dumps → tables
.venv/bin/eb exchange sync [-l Mirage]               # hourly GGG exchange, first 14 days per league
.venv/bin/eb live sync|watch [-l Allflame]           # running league: launch fortnight + latest 14 days
scripts/ingest.sh [exchange|dumps|all|live]          # unattended runner, logs to data/logs/latest.log
```

A background run (`nohup … &`) ignores Ctrl-C. Stop it with `pkill -f "eb "`, which is safe at any point. The user runs the live feed (`eb live watch`) externally. Don't leave long-running ingest processes running.

## Architecture

**Pipeline writes, UI reads.** CLI jobs (`cli.py` → `ingest/` → `normalize/`) fetch data and write a local DuckDB file (`data/exiledbroker.duckdb`) plus Parquet. The Streamlit demo (`app/`) and the FastAPI app (`api/`) only read, and only through `services/`. This split is what lets the site move to **Supabase (Postgres) + Railway** later without rewriting the read side.

- **`services/` SQL must stay Postgres-compatible.** No `GROUP BY ALL`, no DuckDB-only functions. The loaders in `normalize/` run locally on DuckDB (they `read_parquet` etc.), so they're exempt. `storage/schema.sql` must run on both engines (`DOUBLE PRECISION`, `ON CONFLICT`, `ADD COLUMN IF NOT EXISTS`). New columns are appended as `ALTER TABLE … ADD COLUMN IF NOT EXISTS` *after* the table's `CREATE`.
- **DuckDB 2.0:** an `execute()` result stays open until fully fetched. Use the helpers `db.rows` / `db.scalar` / `db.frame` (`storage/db.py`), never `fetchone()` on a connection. Polars is 2.0 too (e.g. CSVs are read positionally with an explicit header check).
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
- **Pages must read small results.** Do aggregation in SQL or in precomputed summary tables written by the worker, not by pulling raw hourly rows into Python. Database egress and compute are what cost money on Supabase. Summaries are computed in SQL (`cross_market.summarize`, `divination.turn_in_summary`, `launch_patterns._curves_sql` / `group_curves`) with Postgres-compatible medians (`percentile_cont(0.5) WITHIN GROUP (ORDER BY …)`, `FILTER (WHERE …)`). The Live page filters by time in SQL (`since=`) and caches on the latest loaded hour, not a timer. Don't divide by a column without `nullif(…, 0)` (Postgres raises on division by zero).
- **Index for the access paths.** `schema.sql` indexes league + source + time, because the primary keys start with item id.
- **The worker must not depend on a persistent disk.** What to fetch is decided by the database (`exchange_loader.needs_rebuild` / `loaded_hours`), not by which pages are on disk. Reference data (RePoE names, core-pool snapshots, loot-filter tiers) lives in `reference_data` (`ingest/reference.py`). **Never download data we already have:** market hours are immutable and fetched once; reference sources go through `reference.fetch_if_changed`, which checks at most every `max_age` (RePoE weekly, pool and tiers daily; `eb exchange sync --refresh` checks now) using conditional requests (stored ETag / Last-Modified), so an unchanged source answers 304 and nothing is downloaded.
- **The full list** of known cost issues and their status is in the README ("Hosting cost issues").
- **Planned (user is designing it; don't build yet):** the site will split into a clear **live trading** section and a **historical** section with preloaded data and graphs.

## Scope rules (decided by the user)

- **Challenge leagues only.** Event and Ruthless leagues are excluded from data and analysis; every command defaults to `kind = challenge`.
- **Only show items in the current core drop pool.** Remove an item via `config/core_pool.toml`, not code.
- **Design for a new league's data arriving.** At launch everything is null and fills in hour by hour, with gaps (no Divine rate in the first hours, untraded items, a single league loaded). Every page must handle no data, one hour, partial days and one-league states. Widgets with data-dependent ranges must not break when there's only one option.
- Recent leagues are the best reference; the currency exchange (Settlers, 2024-07) is a structural break.
- Charts default to linear axes (log scale is only an opt-in toggle). Trading tables put the money columns first. Credit poe.ninja (CC BY-SA) on the public site.

## Testing patterns

- Exchange behaviour is tested with `FakeExchange` / `market()` / `client_for()` in `tests/test_currency_exchange.py` (other test modules import them). `FakeExchange.now` marks the hour still being traded (end of stream).
- Pages are tested headlessly with `streamlit.testing.v1.AppTest`, using an **absolute** path to `app/dashboard.py` and `EB_DATA_DIR` pointed at a temp dir. Call `st.cache_data.clear()` between states. The default page is the Live market.
- `tests/test_live_pipeline.py` replays real GGG pages (Mirage's first 30 hours, `tests/fixtures/mirage_launch.json.gz`) through `ingest.live.sync_live`, hour by hour, and runs every page and analysis tool after each hour. Regenerate the fixture with `python tests/fixtures/make_fixtures.py` (needs Mirage data in `data/`).

## Data and repo hygiene

- All data lives in the gitignored `data/` folder (the default `EB_DATA_DIR`, anchored to the repo root). Never commit it.
- Settings come from `EB_*` environment variables or `.env` (`config.py`).
- `.claude/` and `.agents/` (the Streamlit skill; `.claude/skills/...` is a symlink into `.venv`) are intentionally left untracked.
