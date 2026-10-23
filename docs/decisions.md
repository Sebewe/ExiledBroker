# Decision log

Why things are the way they are, grouped by topic and dated. Add new decisions under the right topic, newest last. When a decision is replaced, keep it, mark it ~~superseded~~ and link the replacement, so the history stays readable.

- [Scope](#scope)
- [Data and ingest](#data-and-ingest)
- [Analysis and scoring](#analysis-and-scoring)
- [Site and UI](#site-and-ui)
- [Hosting and performance](#hosting-and-performance)
- [Tooling](#tooling)

## Scope

| Date | Decision |
|---|---|
| 2026-10-21 | **PoE1 only for now** (a league launches in about a month). The `game` column stays on leagues and items so PoE2 can be added later. |
| 2026-10-21 | **League kinds:** *challenge* = the main 3–4 month leagues (Settlers, Mirage, …); *event* = short leagues of a few weeks (Ancestors, Phrecia), nested in another league's window, with far fewer players; *ruthless* = Ruthless variants. Only each challenge league's softcore files are kept; Standard, Hardcore and private leagues in the zips are skipped. |
| 2026-10-21 | **Event and Ruthless leagues are excluded** from data and analysis. Most players don't play them and their markets don't follow normal trends ([data.md](data.md#scope-whats-left-out)), so including them would make predictions worse. Every command defaults to challenge leagues, and the Ancestors data was deleted. `--kind` / `-l` can still select one. |
| 2026-10-21 | **Currency and uniques only** (plus divination cards). Base items, gems, cluster jewels, maps and other types are skipped. Currency-like types (scarabs, essences, fossils, oils, …) are keyed by name (`currency:<slug>`) like the currency file and the exchange, so one item has one id in every source. Uniques keep `ninja:<Id>`. |
| 2026-10-21 | **Only the core drop pool is shown** (`ingest/core_pool.py`). Currency, essences and scarabs are limited to poe.ninja's *current-league* lists (minus Catalysts), snapshotted in `reference_data`, checked daily and replaced only if the list changed, so items whose mechanic didn't go core drop out. This replaced an earlier running union. Cards are limited to what NeverSink's filter shows. Overrides go in `config/core_pool.toml` (`exclude` everywhere, `[include]` per group). Catalysts were left out at first; see 2026-10-22. |
| 2026-10-21 | **Built for a new league's data arriving.** At launch every price is null, and GGG publishes each hour only after it ends. A league can be registered before it has data (`--start`), and every view handles none / one hour / a few days. Day comparisons appear only once there are two days. Applies to every new view ([data.md](data.md#a-new-leagues-data)). |
| 2026-10-22 | **Catalysts, fragments and oils are currency.** They trade on the exchange like any currency, so the Currency group now takes poe.ninja's Currency list with Catalysts, plus its Fragment and Oil lists (183 names for Allflame instead of 88). Each list is its own snapshot (`core_pool/type/<Type>`); the old per-group snapshots are deleted on refresh. Hosted hourly rows grow ~22% (Allflame 260k → 319k); the daily pool check makes 5 list requests instead of 3. Daily dumps already had them (fragments and catalysts are in the currency file, oils in the items file). |
| 2026-10-22 | **Hosting launches with live-league data only.** Past leagues are for building and testing and stay local; anyone after old prices has poe.ninja. Hosted data is the running league's launch fortnight plus recent hours, a few hundred MB at most. |

## Data and ingest

| Date | Decision |
|---|---|
| 2026-10-21 | **DuckDB + Parquet storage.** |
| 2026-10-21 | **Ingest is local and resumable.** Downloads continue with HTTP Range + If-Range; outputs are written to a temp path and renamed, so a finished file is its own completion marker (no state file to corrupt). Re-running never re-downloads or rewrites finished work. |
| 2026-10-21 | **Dump rows stay in Parquet** behind DuckDB views (`dump_item_price`, `dump_currency_price`, which add `day_offset`) rather than being copied in. Code the site reads must use real tables, not these views. |
| 2026-10-21 | **Item identity** = poe.ninja's line `Id` (`ninja:<Id>`), stable across leagues. Currencies get `currency:<slug>`. |
| 2026-10-21 | **Currency price** = midpoint of `chaos_ask` and `chaos_bid`, both kept; confidence is the weaker side's. Every row gets `divine_value` from that day's Divine midpoint. |
| 2026-10-21 | **Malformed dump rows are dropped, not fatal.** Unquoted names with line breaks (Necropolis coffins) spill over several lines; only rows that start with the league name and have the right field count are kept, and the drop count is recorded (`*.dropped.json`). Rows with no name (15 Sanctum relics in Ancestor) are skipped too. |
| 2026-10-21 | **For the first 14 days, hourly exchange prices replace daily ones** for everything on the exchange. The hourly price volume-weights the Chaos and Divine markets, with Divine trades converted at that hour's rate. |
| 2026-10-21 | **A league's `launched_at`** is the first hour it trades on the exchange (Mirage: 2026-03-06 20:00 UTC); hourly `day_offset` is fractional days from it. |
| 2026-10-21 | **Exchange names come from RePoE.** An ambiguous name never merges items: each metadata id becomes `Name (MetadataName)`. |
| 2026-10-22 | **Legacy and Tencent twins don't make a name ambiguous.** Classic fragments and breachstones share their name with a legacy RePoE id that has no stack size and never trades, so the exchange's ids were all labelled `Name (CurrencyShaperFragment1)` and so on, and matched neither the pool nor the dumps. The one stackable global id now keeps the plain name (26 names); Tencent-realm copies don't count either. `LOADER_VERSION` 6 rebuilds each league from pages on disk. |
| 2026-10-21 | **Price mappings** (`tracked_item`) have four groups: Currency (mirrors included), High-tier essences (all Deafening, plus Hysteria/Insanity/Horror/Delirium), Scarabs and Divination cards. Rules in `normalize/tracked.py` apply to every source. |
| 2026-10-21 | **Divination cards:** follow only cards NeverSink's filter shows at Semi-Strict (`EB_LOOT_FILTER_STRICTNESS`), tiers t1–t4. Set size and reward come from RePoE (`divination_card`). A fixed currency/card reward gets an hourly turn-in margin. |
| 2026-10-21 | All market data lives in the gitignored `data/` folder (the default `EB_DATA_DIR`), with backup ignore rules for `*.duckdb`, `*.parquet` and partial downloads. |
| 2026-10-22 | **Incremental exchange loads; the database is never wiped to add data.** `exchange_hour_loaded` tracks loaded hours; a load inserts only new hours and deletes only hours leaving the window. The Divine rate is carried forward from rows already stored (ASOF join), and curated tables are updated by difference. Hour-by-hour loading gives exactly the same rows as one full load; on Allflame a one-hour slide removes and re-adds exactly 531 rows. |
| 2026-10-22 | **The running league keeps its launch fortnight.** A live window is the first 14 days *plus* the latest 14 days, loaded together, so a league like Allflame (launched 2026-07-24 22:00 UTC) feeds both the launch views and the Live page. A running league has no daily dump until it ends. |
| 2026-10-22 | **Launch views stay on the launch fortnight** (`day_offset < 14`). A live league whose loaded hours are all later shows a "past the launch window" note instead of a misleading chart. |

## Analysis and scoring

| Date | Decision |
|---|---|
| 2026-10-21 | **Analyses favour recent leagues.** The economy changes every league and the exchange (Settlers, 2024-07) was a structural break, so every tool reports per league, newest first, and summaries are recency-weighted: the newest league counts 1 and each *half-life* leagues back halves it (default 2). Leagues before Settlers are context only. |
| 2026-10-21 | **Launch curves are relative:** price ÷ the item's day-1 price in that league, where day 1 is the *median* of its first 24 hourly prices (a few junk early trades would skew a mean). Baselines on fewer than six traded hours are flagged. |
| 2026-10-21 | **Turn-in figures use the median hour** (set cost, reward value, margin, margin %). Thin card markets have junk hours (The Hoarder averaged 570c a set in Mirage against a typical ~1c), and averaging hourly percentages blows up for near-worthless sets. |
| 2026-10-22 | **Card flip score** (`services/divination.score_turn_ins`): margin %, investment (set cost), profitable hours and volume (full sets traded) are ranked among priced cards and combined as a weighted mean (default weights 4 / 2 / 3 / 3, tunable, as is whether cheap or big sets score better). Ranks, so different units combine fairly and one outlier can't dominate. |
| 2026-10-22 | **Cross-market loops** (`services/cross_market.py`). `cross_market_hour` holds every item-hour traded against both Chaos and Divines, with that hour's rate (not carried forward). Loops are priced at the hour's worst price on every leg; an hour pays only if it beats a fee buffer (default 2%); a league where an item didn't trade in both markets counts 0 for its worst-league share. Items under 1c are filtered by default: dust-priced bulk (Rogue's Markers at ~0.001c) shows gaps that reflect how they trade, not profit. |
| 2026-10-22 | **One scoring method** (`services/scoring.rank_score`) for card flips, loops and the Live page: percentile rank per factor, weighted mean, weights tunable on the page. Loop factors: edge when paying, share of paying hours, worst league's share, volume traded in both markets. |
| 2026-10-22 | **Group timing defaults to Chaos.** In Divines almost every group sinks below its day-1 price because the Divine inflates fastest (86 → 266c in Mirage), which reads as "currency loses value". The Divine view stays available, with an explanation. |
| 2026-10-22 | **Launch picks** (`services/launch_picks.py`, `eb launch picks`): what to buy on day 1, days 2–4 and days 5–10, ranked from the newest five leagues with a complete launch fortnight (recency half-life 2 leagues). Growth is median price on days 12–14 over median price in the window, **in Divines**, because Chaos loses about half its value against Divines over the fortnight. Candidates must cost at most 2 div each, trade at least 20 div a day in both the window and the sale, and have traded in at least 3 of the leagues, which drops each league's own currency (Dead Man's Sulphur, the Mirage coins). Score (`rank_score`): typical growth 0.35, worst league 0.25, consistency (weighted share of all leagues it beat Divines; a missing league counts against it) 0.25, liquidity 0.15. Built on the research database and copied to the site by `eb site seed` (three small tables, replaced whole), since the site holds only the live league. |

## Site and UI

| Date | Decision |
|---|---|
| 2026-10-21 | **Built as a public site, demoed locally first.** The batch pipeline and read-only serving are separate: CLI jobs write the database, the site only reads, so hosting needs no heavy compute on request. All read logic lives in `services/`, so changing the UI never means rewriting queries. |
| 2026-10-21 | ~~Streamlit is the first, local demo.~~ Superseded 2026-10-22 by the React site. |
| 2026-10-21 | **Units are named everywhere.** KPI cards leave out Chaos (everything is priced in it), and every price column, axis and tooltip names its unit. |
| 2026-10-21 | **Market tables sort by average price over the window** (volume-weighted, in the selected unit). With nothing selected, the chart shows the five most-traded items. |
| 2026-10-22 | **Trading pages put the money first.** The ranked table is full width at the top, columns lead with score and chaos figures (what a card gives comes last), and charts sit at the bottom. |
| 2026-10-22 | ~~**Live market is the landing page**~~ (superseded 2026-10-23 by Missed opportunities), because it's what will be used most. The feed is a separate process (`eb live watch`) and the page only reads. |
| 2026-10-22 | **Widgets whose range depends on the data are hidden when there's only one option** (e.g. "seen in at least N leagues" with one league loaded, as at a launch). Found in Streamlit, which rejects a slider with min = max; the rule stays for the React site. |
| 2026-10-22 | **Charts use linear axes by default**, because players read them. Log scale is an opt-in toggle only where values span orders of magnitude. Relative charts say what the numbers mean (1 = the day-1 price). |
| 2026-10-22 | **The site won't be hosted on Streamlit.** React + Vite + TypeScript on the FastAPI API, Supabase Postgres, a live worker, all on Railway. Unique moves and the other analysis tools aren't in the launch: the focus is investment and trading. |
| 2026-10-22 | **Frontend stack:** React + Vite + TypeScript, TanStack Query and Table (v8), ECharts (lazy-loaded; first load 119 KB gzipped), Tailwind with a small token set, Fira Sans self-hosted. Types are generated from the OpenAPI schema. Dark only; green/red only for profit/loss, gold as the brand. Lines break where hours are missing (a live league's two windows are weeks apart) and isolated hours get a dot. |
| 2026-10-22 | **Streamlit retired.** The React site covers Live market, Arbitrage, Card turn-ins and Launch market. Page tests became API tests (every endpoint after every replayed hour), page budgets became endpoint budgets. The analysis tools stay in `analysis/` for local research. |
| 2026-10-22 | **Live and trading charts show the last 3 days** (`hours`, default 72, up to 28 days for a later "expand"), not the whole window, which left a weeks-long gap in the zoom bar and sent data nobody looked at. The loop chart shows the Chaos price and the price via Divines (at that hour's rate) as lines, so the gap is the margin, with Chaos volume in both markets as bars. |
| 2026-10-22 | **Live market tables:** one "Prices in" switch for both tables, converted in the browser at the league's latest Divine price (from `/api/status`). The loop chart stays in Chaos: converting history at today's rate would misstate it. The look-back control and "Last seen" are gone (scoring keeps 6 hours). Loops show **volume per hour** (Chaos value in both markets in the latest hour) and **items per hour** (units traded in both markets). GGG publishes units, not trade counts. Number boxes can be emptied while typing; empty counts as 0. |
| 2026-10-22 | **Price columns say what kind of price they are**, because the data is hourly, not live. Live loops show **Price (low)** and **Price (high)**, the range traded in the Chaos market in the latest published hour (`price_low`/`price_high`; `price`, the hour's average, still drives the min-price filter). Other columns name their aggregate: *hour avg* (live card turn-ins), *median* (Arbitrage, Card turn-ins: medians of hourly averages), *Day N avg* and *Peak day avg* (Launch: daily volume-weighted averages). |
| 2026-10-22 | **Loop charts keep the Chaos price line through hours without a Divine trade.** The gaps were real: over Allflame's last 3 days the median item traded in both markets in 11 of 72 hours. `cross_market_hour` now also stores Chaos-only hours with the Divine side null (LOADER_VERSION 7; hosted rows 135k → 439k, no perf flags); loops and summaries filter to `BOTH_LEGS`. The via-Divines line and the volume bars are drawn from the both-market hours only, as before. |
| 2026-10-22 | **Launch market page is the launch picks**, replacing the per-item table and multi-line chart: three window tabs (following the live league's current window), a three-bar "your 2 Divines by day 14" comparison (kept as Chaos, a typical item, the #1 pick), cards for the top 3 and a short list for 4–10, each with one dot per reference league. During a window, picks show the live league's latest price against their usual one. The `/api/market/*` endpoints stay for the planned historical section. |
| 2026-10-23 | **Missed opportunities replaces Live market as the landing page** (`services/missed.py`, `/api/missed/{league}`). Without live tracking, the honest pitch is a recap: what the latest published hours offered, framed as what you missed. One response holds the 1, 2 and 3 hour look-backs (≈2.4 KB gzipped, computed once per loaded hour and warmed), so the slider switches locally. Sections: **key movement** (top 3 risers and fallers since the look-back began, with how many hours running they've moved, and the 3 widest high–low ranges; liquid items only, ≥5c and ≥2,000c traded an hour), then the top 3 **loops** and **card turn-ins** by Chaos left on the table (edge × volume in both markets, or margin × sets traded, over paying hours, both loop directions). The headline is the total over every paying loop and turn-in: an upper bound, and labelled as one. No tables: the full lists stay on Arbitrage and Card turn-ins. Prices under a Divine show in Chaos. |

## Hosting and performance

| Date | Decision |
|---|---|
| 2026-10-21 | **Target hosting: Supabase Postgres for data, Railway for the app and workers.** DuckDB stays local. `schema.sql` sticks to SQL both engines run (`DOUBLE PRECISION`, `ON CONFLICT`, `ADD COLUMN IF NOT EXISTS`), and `services/` SQL stays Postgres-compatible (no `GROUP BY ALL` or DuckDB-only functions). The dump loader is exempt: it runs locally on Parquet. |
| 2026-10-22 | **The worker writes Postgres through DuckDB.** `db.site_writer` attaches Postgres to an in-memory DuckDB and the incremental loader runs unchanged; rows and the transaction are Postgres's. Spike on Mirage: 24 new hours in 1.0 s, identical rows, a failed load rolls back. The replay test checks the worker's Postgres tables equal the DuckDB pipeline's. |
| 2026-10-22 | **API results are cached per data version**, not on a timer: computed once per hourly update for all visitors (bounded LRU). On Allflame from Postgres, cached calls take 2–8 ms and the heaviest cold call ~0.3 s. |
| 2026-10-22 | **One image, two Railway services.** Web: uvicorn serving `/api` and the built frontend from one origin (no CORS, one service). Worker: `eb live watch`. Locally, a worker container on an empty disk fetched only the 2 new hours (2 requests, 110 KB) and wrote them to Postgres in 2 s. |
| 2026-10-22 | **Tables are served from a cache, never computed per request.** Each is computed once per data version, gzipped once, and sent with an ETag (`304` for a returning client). The data version is trusted for 15 s, so a cached request makes no query. Default tables are precomputed as soon as an hour loads. |
| 2026-10-22 | **Text primary keys stay** (cost issue 8): integer keys would save ~37 MB at hosted scale, not worth a refactor touching everything. Revisit at ~10× the rows. |
| 2026-10-22 | **Performance measurements stay off the site.** The query meter, budgets and `eb perf report` are local and CI tools; live numbers would go in a server-side dev panel later. |
| 2026-10-22 | **ETags include the code version** (a hash of the package's code and SQL, `deps.CODE_VERSION`), not just the data version. Otherwise a deploy that adds a field is answered with 304 and browsers keep the old body until the next hour loads (found when the new loop low/high columns showed blank). Each deploy costs every visitor one full download per view. |

## Tooling

| Date | Decision |
|---|---|
| 2026-10-21 | **Python ≥ 3.11 with plain venv + pip** (uv isn't installed here); `pyproject.toml` is tool-agnostic, so uv can be adopted later. |
| 2026-10-22 | **CI on GitHub Actions** (lint, tests, a Postgres 17 job), only on the free `ubuntu-latest` runner; superseded runs are cancelled. |
| 2026-10-22 | **Tests never touch `data/`.** `tests/conftest.py` points the default data directory at a temp dir before any fixture runs. Added after a fixture without `EB_DATA_DIR` reached the real database through `sync_live` and shrank Mirage's loaded hours to 30 (reloaded from the pages on disk, totals identical). |
