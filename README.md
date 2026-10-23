# ExiledBroker

A Path of Exile market tool for league starts. It turns historical and live exchange data into launch-week price patterns and arbitrage opportunities: card turn-ins and Chaos↔Divine loops. Later it will predict how prices move using past leagues and the new patch notes.

> **Data credit:** daily economy history comes from [poe.ninja](https://poe.ninja), whose economy dumps are published under [CC BY-SA](https://creativecommons.org/licenses/by-sa/3.0/). Thank you to poe.ninja for making this data available to the community. Hourly currency-exchange history comes from Grinding Gear Games' public API, and item names from [RePoE](https://github.com/repoe-fork/repoe). ExiledBroker is not affiliated with or endorsed by Grinding Gear Games or poe.ninja.

> **Living document.** This README and [`docs/`](docs) track the project's design and progress. Update the Status table, [decision log](docs/decisions.md) and layout as work lands.

## Status

| Phase | Goal | State |
|---|---|---|
| 0 | Scaffolding: package, CLI, schema, config, service layer | ✅ Done |
| 1 | Historical ingest: daily poe.ninja dumps + hourly GGG exchange, league calendar, price mappings, core pool, divination cards | ✅ All 32 challenge leagues daily; hourly for the four exchange-era leagues and the current league (Allflame) |
| 2 | Exploration: recurring launch-week patterns (`analysis/`), Card turn-ins and Arbitrage pages | 🟨 Tools built; [findings](docs/findings.md) |
| 3 | Patch corpus: scraper, extractor, review tool | ⬜ |
| 4 | Baseline + backtest: first honest accuracy numbers | ⬜ |
| 5 | Signals: "farm X", "buy Y on day 2, sell day 6" | ⬜ |
| 6 | Live mode: hourly ingest of the running league, live arbitrage view, later drift alerts | 🟨 Live feed and Missed opportunities page built; poe.ninja poller and alerts not started |
| 7 | Hosted site: React on the JSON API, all on Railway (web, Postgres, hourly pipeline) | 🟨 Built and simulated locally with Railway's billing (about $4 a month of usage at 1000 daily visitors, inside the $5 Hobby fee); not deployed |

Legend: ⬜ not started · 🟨 in progress · ✅ done. Phases 1–2 alone are useful: knowing which categories reliably spike in the first week is already an edge.

## Next steps

The next league launches in about a month. Before then:

- **Go live on Railway**: the checklist is [go-live.md](docs/go-live.md) (Postgres-only server, catch-up test, usage limits with a fallback page, rehearsed league switch).
- **poe.ninja live poller** (phase 6). Uniques have no public sub-daily history, so it must be running at launch ([data.md](docs/data.md#sources)).
- **Register the new league** once its name and date are announced (`eb exchange sync -l "<Name>" --start <date>`), so the site shows "waiting for the first trades" from launch.

After that:
- **Phase 2:** run the analysis tools across all four exchange-era leagues and write up what repeats.
- **Divination card expected value** for random and unique rewards.
- **Site split** into live trading and historical sections (being designed).

## The site

| Page | What it shows | API |
|---|---|---|
| **Missed opportunities** (landing) | A recap of the last 1–3 published hours: key movers, volatile items, and the loops and card turn-ins that left the most on the table | `/api/status`, `/api/missed/{league}` |
| **Arbitrage** | Every Chaos↔Divine loop as a card, filtered by your capital, volume and margin | `/api/arbitrage` |
| **Card turn-ins** | Every profitable card set as a card, filtered by your capital, volume and margin | `/api/cards/{league}` |
| **Launch market** | What to buy on day 1, days 2–4 and days 5–10 with a couple of Divines, ranked from the last five leagues | `/api/launch/picks` |
| **About** | Sources and credits | |

"Now" is the latest published exchange hour, about an hour behind real time. Every page handles a league with no data yet, the first hours, and a stopped feed. Interactive API docs are at `/docs` when the API is running.

## Quick start

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

Settings come from `EB_*` environment variables or `.env` (`src/exiledbroker/config.py`, `.env.example`). Unattended ingest, logs and stopping a run: [data.md](docs/data.md#running-the-ingest). The full command list for development is in [CLAUDE.md](CLAUDE.md).

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
- **Store and send only what the site reads.** Summaries are computed in SQL, tables are cached per data version and served gzipped with an ETag. Cost is measured by budgets in the tests ([hosting.md](docs/hosting.md)).

## Docs

| Doc | Contents |
|---|---|
| [docs/data.md](docs/data.md) | Sources, how dumps and exchange hours become rows, the live feed, core pool, divination cards, new-league handling, data model, running the ingest |
| [docs/go-live.md](docs/go-live.md) | The checklist for going live on Railway, with decisions and open questions |
| [docs/hosting.md](docs/hosting.md) | Hosting shape, cost issues and their fixes, performance tooling and findings |
| [docs/findings.md](docs/findings.md) | Phase-2 findings from past launches |
| [docs/decisions.md](docs/decisions.md) | Decision log by topic, dated |
| [docs/roadmap.md](docs/roadmap.md) | The prediction design (patch notes, models, backtest), planned modules, add-ons, risks |
| [CLAUDE.md](CLAUDE.md) | Commands, architecture and coding rules for working on the code |

## Project layout

```
ExiledBroker/
├── src/exiledbroker/
│   ├── cli.py              # eb dumps | exchange | live | site seed | perf report | serve | init-db
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
├── docs/                   # design docs (see above)
├── config/core_pool.toml   # manual core-pool overrides
├── scripts/ingest.sh       # unattended, resumable ingest
├── Dockerfile, docker-compose.yml, .env.example
├── deploy/                 # railway/ (service configs), railway-sim/ (local Railway with billing)
├── .github/workflows/ci.yml
└── data/                   # gitignored: raw downloads, Parquet, logs, exiledbroker.duckdb
```

Planned modules are listed in [roadmap.md](docs/roadmap.md#planned-modules).

**Stack:** Python (`httpx`, `polars`, DuckDB, `pydantic`, `typer`, FastAPI), Postgres (Railway), React + Vite + TypeScript (TanStack Query/Table, ECharts, Tailwind); `scikit-learn`/LightGBM later.

## License

MIT. See [LICENSE](LICENSE).
