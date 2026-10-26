# Architecture

How ExiledBroker is built: the data flow, the pages and the endpoints they read, the code layout and the full local setup. The product overview is the [README](../README.md); progress and next steps are in [roadmap.md](roadmap.md); the rules for working on the code are in [CLAUDE.md](../CLAUDE.md).

## How it works

```
poe.ninja dumps (daily) ─┐
GGG exchange (hourly) ───┼─► ingest/ ─► normalize/ ─► DuckDB (local, all history)
RePoE, loot filter ──────┘                  │
                                            └─► Postgres (hosted, running league only)
                                                        │
                                      services/ ─► api/ (FastAPI, cached) ─► web/ (React)
```

- **The pipeline writes, the site reads.** CLI jobs fetch and load; the API only reads, through `services/`. The hourly pipeline (`eb pipeline run`) is the only writer of the hosted database.
- **Everything is resumable and incremental.** Downloads resume, files are written atomically, and loads add new hours and remove only what left the window. Nothing finished is fetched or rewritten again.
- **Every price has a `day_offset`** from its league's launch, so leagues compare directly.
- **Store and send only what the site reads.** Summaries are computed in SQL, tables are cached per data version and served gzipped with an ETag. Cost is measured by budgets in the tests ([hosting.md](hosting.md)).

## The pages and their endpoints

| Page | What it shows | API |
|---|---|---|
| **Market recap** (landing) | What traded in the last 1–3 published hours: the latest hour's volatile flips, then every loop and card turn-in that paid (liquid markets only; a random card reward at its worst roll), likeliest to go through first with how often its orders went through in the last 3 days, and behind Show rates the orders the backtest's best option would place this hour and its 24-hour price range, what moved, and options to look into | `/api/status`, `/api/missed/{league}` |
| **Price check** (replaces Farming; `/farming` redirects to it) | One item at a time: its price this league in Chaos and Divines, sell now / hold / no clear signal for 24 hours and 3 days in the launch fortnight (from past leagues' paths, `eb price-check build`), the biggest moves after it, the stack seller (a stack as hours of the market's trading) and the best hour to sell ([price-check.md](price-check.md)) | `/api/price-check/{league}`, `/api/price-check/{league}/{item_id}` |
| **Research** (`/research`) | The journal: [findings](findings.md) rendered as notes, newest first (`npm run gen:notes` after editing them; no server cost), and How the tools work, the method the trading pages link to | |
| **Backtest** (Research) | Would following the site have paid? The site's tools replayed an hour late at fair and harsh prices (`eb backtest run`) | `/api/backtest` |
| **Launch market** | What to buy on day 1, days 2–4 and days 5–10 with a couple of Divines, ranked from the last five leagues | `/api/launch/picks` |
| **Multi-layered conversions**, **About** (Research) | Side markets measured; sources, credits and privacy | |
| **Admin** (`/admin`, not linked; the owner's) | The site's usage counts and the pipeline's health per league ([admin.md](admin.md)) | `/api/stats`, `/api/admin/overview`, behind `EB_ADMIN_TOKEN` |

"Now" is the latest published exchange hour, about an hour behind real time. Every page handles a league with no data yet, the first hours, and a stopped feed. Interactive API docs are at `/docs` when the API is running.

## Project layout

```
ExiledBroker/
├── src/exiledbroker/
│   ├── cli.py              # eb dumps | exchange | live | site seed/smoke | perf report | serve | init-db
│   ├── config.py           # settings (EB_* env vars / .env)
│   ├── ingest/             # fetching: http client, atomic files, poe.ninja dumps, GGG exchange,
│   │                       #   live updates, RePoE names, core pool, loot filter, reference data
│   ├── normalize/          # loading: dump loader, incremental exchange loader, leagues,
│   │                       #   price-mapping groups, divination cards, mapping refresh
│   ├── storage/            # schema.sql (DuckDB + Postgres), db helpers + query meter, site seed
│   ├── services/           # read-side queries shared by the API: market, live, cross_market,
│   │                       #   divination, scoring, prices, leagues, overview
│   ├── analysis/           # phase-2 research tools (local only)
│   ├── api/                # FastAPI app, routes (live, trading, market), models, cached views, warm-up
│   └── perf.py             # eb perf report
├── web/                    # React + Vite + TS frontend (pages, components, generated API types)
├── tests/                  # incl. real-data replay fixture, performance budgets, Postgres checks
├── docs/                   # design docs (listed below)
├── config/core_pool.toml   # manual core-pool overrides
├── scripts/ingest.sh       # unattended, resumable ingest
├── Dockerfile, docker-compose.yml
├── deploy/                 # railway/ (service configs), railway-sim/ (local Railway with billing)
├── .github/workflows/ci.yml
└── data/                   # gitignored: raw downloads, Parquet, logs, exiledbroker.duckdb
```

Planned modules are listed in [roadmap.md](roadmap.md#planned-modules).

**Stack:** Python (`httpx`, `polars`, DuckDB, `pydantic`, `typer`, FastAPI), Postgres (Railway; off-site backup on Supabase), React + Vite + TypeScript (TanStack Query/Table, ECharts, Tailwind); `scikit-learn`/LightGBM later.

## Running it locally

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev,pg]'
.venv/bin/eb init-db                    # create data/exiledbroker.duckdb
.venv/bin/eb dumps sync && .venv/bin/eb dumps load   # daily history, all challenge leagues (resumable)
.venv/bin/eb exchange sync -l Mirage    # hourly exchange, first 14 days (resumable)
.venv/bin/eb live watch                 # keep the current league loaded
.venv/bin/eb serve                      # API at http://127.0.0.1:8000/api
cd web && npm install && npm run dev    # frontend at http://localhost:5173 (Node 24)
.venv/bin/pytest                        # tests
```

The hosted setup, locally (Postgres in Docker stands in for Railway's):

```bash
docker compose up -d db
EB_DATABASE_URL=postgresql://eb:eb@localhost:55432/exiledbroker .venv/bin/eb site seed
EB_DATABASE_URL=postgresql://eb:eb@localhost:55432/exiledbroker .venv/bin/eb serve
docker compose up -d --build api        # or the whole site as Railway runs it, on :8000
```

Settings come from `EB_*` environment variables or `.env` (`src/exiledbroker/config.py`). Unattended ingest, logs and stopping a run: [data.md](data.md#running-the-ingest). The full command list for development is in [CLAUDE.md](../CLAUDE.md).

## The docs

| Doc | Contents |
|---|---|
| [data.md](data.md) | Sources, how dumps and exchange hours become rows, the live feed, core pool, divination cards, new-league handling, data model, running the ingest |
| [go-live.md](go-live.md) | The checklist for going live on Railway, with decisions and open questions |
| [hosting.md](hosting.md) | Hosting shape, cost issues and their fixes, performance tooling and findings |
| [supabase.md](supabase.md) | The off-site backup on Supabase: what a sync does and costs, restoring, setting it up |
| [security.md](security.md) | Security and abuse: the layers in front of the API, what was checked, remaining risks ranked |
| [findings.md](findings.md) | Phase-2 findings from past launches |
| [farming.md](farming.md) | The retired Farming page: how it was built (superseded by price-check.md) |
| [price-check.md](price-check.md) | The Price check page (replacing Farming): its plan, response contract and status |
| [demand.md](demand.md) | The Demand feature: planned, researched (finding 11) and shelved |
| [admin.md](admin.md) | The admin page: what it shows, the token, setting it up once deployed |
| [roadmap.md](roadmap.md) | Status by phase, next steps, the prediction design, planned modules, add-ons, risks |
| [decisions.md](decisions.md) | Decision log by topic, dated |
| [usage.md](usage.md) | Cookie-free usage counts: what's counted, how, and why there's no consent banner |
| [architecture.md](architecture.md) | This page |
| [CLAUDE.md](../CLAUDE.md) | Commands, architecture and coding rules for working on the code |
