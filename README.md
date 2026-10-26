# ExiledBroker

A Path of Exile market tool for league starts. It turns historical and live exchange data into launch-week price patterns and arbitrage opportunities: card turn-ins and Chaos↔Divine loops. Later it will predict how prices move using past leagues and the new patch notes.

> **Data credit:** daily economy history comes from [poe.ninja](https://poe.ninja), whose economy dumps are published under [CC BY-SA](https://creativecommons.org/licenses/by-sa/3.0/). Thank you to poe.ninja for making this data available to the community. Hourly currency-exchange history comes from Grinding Gear Games' public API, and item names from [RePoE](https://github.com/repoe-fork/repoe). ExiledBroker is not affiliated with or endorsed by Grinding Gear Games or poe.ninja.

> **Living document.** This README and [`docs/`](docs) track the project's design and progress. Update the Status table, [decision log](docs/decisions.md) and layout as work lands.

## Status

| Phase | Goal | State |
|---|---|---|
| 0 | Scaffolding: package, CLI, schema, config, service layer | ✅ Done |
| 1 | Historical ingest: daily poe.ninja dumps + hourly GGG exchange, league calendar, price mappings, core pool, divination cards | ✅ All 32 challenge leagues daily; hourly for the four exchange-era leagues and the current league (Allflame) |
| 2 | Exploration: recurring launch-week patterns (`analysis/`), loops and card turn-ins (now on the Market recap) | ✅ Run across all five exchange-era leagues: what repeats is [finding 10](docs/findings.md#10-what-repeats-across-the-five-exchange-era-leagues) |
| 3 | Patch corpus: scraper, extractor, review tool | ⬜ |
| 4 | Baseline + backtest: first honest accuracy numbers | 🟨 The site's tools backtested at fair and harsh prices: Launch picks pay, hourly tools at best break even ([finding 4](docs/findings.md#4-backtest-the-launch-picks-pay-the-hourly-tools-at-best-break-even), the Backtest page) |
| 5 | Signals: "farm X", "buy Y on day 2, sell day 6" | 🟨 The Farming page's mechanic ranking is retired (2026-10-25); the Price check page replaces it: one item's price in Chaos and Divines, a sell-or-hold verdict if one beats "no change", the stack seller and the best hour to sell ([findings 6–8](docs/findings.md), [price-check.md](docs/price-check.md)). Built end to end (data, API, page, seed, backup, the pipeline adds each finished league's paths); the 375 px check is left |
| 6 | Live mode: hourly ingest of the running league, live arbitrage view, later drift alerts | 🟨 Live feed and Market recap page built; alerts not started (the poe.ninja poller is dropped with uniques, 2026-10-25) |
| 7 | Hosted site: React on the JSON API, all on Railway (web, Postgres, hourly pipeline), with an off-site backup on Supabase | 🟨 Built and simulated locally with Railway's billing ($2.7–3.7 a month of usage at 10–100 daily visitors, ~$4.9 estimated at 1000, inside the $5 Hobby fee); the backup is seeded; the Cloudflare fallback Worker (`deploy/cloudflare/`) and the pipeline's failure alert (`EB_HEALTHCHECK_URL`) are built; not deployed |

Legend: ⬜ not started · 🟨 in progress · ✅ done. Phases 1–2 alone are useful: knowing which categories reliably spike in the first week is already an edge.

## Next steps

The next league launches in about a month. Before then:

- **Go live on Railway** (waiting on Railway reopening signups): the checklist is [go-live.md](docs/go-live.md). The code side is done (Postgres-only server, rehearsed league switch, fallback Worker, failure alert); what's left is account setup: the Railway project, the healthchecks.io check, an uptime monitor, Cloudflare in front, then the seed and catch-up test.
- **Register the new league** once its name and date are announced (`eb exchange sync -l "<Name>" --start <date>`), so the site shows "waiting for the first trades" from launch.

After that:
- **Phase 2 again on the next league** once its fortnight is complete (~2026-11-27): the first out-of-sample check of [finding 10](docs/findings.md).
- **Cards with random rewards on the Market recap?** Researched ([finding 12](docs/findings.md#12-cards-with-random-rewards-two-delirium-orb-cards-beat-their-floor-at-typical-prices-nothing-survives-harsh-prices-in-the-launch-fortnight)): two cards beat their worst roll at typical prices; the user decides whether to show them.
- **Site split** into live trading and historical sections (being designed).

## The site

| Page | What it shows | API |
|---|---|---|
| **Market recap** (landing) | What traded in the last 1–3 published hours: the latest hour's volatile flips, then every loop and card turn-in that paid (liquid markets only), likeliest to go through first with how often its orders went through in the last 3 days, and behind Show rates the orders the backtest's best option would place this hour and its 24-hour price range, what moved, and options to look into | `/api/status`, `/api/missed/{league}` |
| **Price check** (replaces Farming; `/farming` redirects to it) | One item at a time: its price this league in Chaos and Divines, sell now / hold / no clear signal for 24 hours and 3 days in the launch fortnight (from past leagues' paths, `eb price-check build`), the biggest moves after it, the stack seller (a stack as hours of the market's trading) and the best hour to sell ([price-check.md](docs/price-check.md)) | `/api/price-check/{league}`, `/api/price-check/{league}/{item_id}` |
| **Backtest** | Would following the site have paid? The site's tools replayed an hour late at fair and harsh prices (`eb backtest run`) | `/api/backtest` |
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

Settings come from `EB_*` environment variables or `.env` (`src/exiledbroker/config.py`). Unattended ingest, logs and stopping a run: [data.md](docs/data.md#running-the-ingest). The full command list for development is in [CLAUDE.md](CLAUDE.md).

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
| [docs/supabase.md](docs/supabase.md) | The off-site backup on Supabase: what a sync does and costs, restoring, setting it up |
| [docs/findings.md](docs/findings.md) | Phase-2 findings from past launches |
| [docs/farming.md](docs/farming.md) | The retired Farming page: how it was built (superseded by price-check.md) |
| [docs/price-check.md](docs/price-check.md) | The Price check page (replacing Farming): its plan, response contract and status |
| [docs/demand.md](docs/demand.md) | The Demand feature: planned, researched (finding 11) and shelved |
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
├── Dockerfile, docker-compose.yml
├── deploy/                 # railway/ (service configs), railway-sim/ (local Railway with billing)
├── .github/workflows/ci.yml
└── data/                   # gitignored: raw downloads, Parquet, logs, exiledbroker.duckdb
```

Planned modules are listed in [roadmap.md](docs/roadmap.md#planned-modules).

**Stack:** Python (`httpx`, `polars`, DuckDB, `pydantic`, `typer`, FastAPI), Postgres (Railway; off-site backup on Supabase), React + Vite + TypeScript (TanStack Query/Table, ECharts, Tailwind); `scikit-learn`/LightGBM later.

## License

MIT. See [LICENSE](LICENSE).
