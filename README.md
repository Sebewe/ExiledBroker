# ExiledBroker

A Path of Exile market speculation tool. It uses historical price data and the new patch notes to predict how prices move during a league start.

> **Data credit:** daily economy history comes from [poe.ninja](https://poe.ninja), whose economy dumps are published under [CC BY-SA](https://creativecommons.org/licenses/by-sa/3.0/). Thank you to poe.ninja for making this data available to the community. Hourly currency-exchange history comes from Grinding Gear Games' public API, and item names from [RePoE](https://github.com/repoe-fork/repoe). ExiledBroker is not affiliated with or endorsed by Grinding Gear Games or poe.ninja.

> **Living document.** This README tracks the project's design and progress. Update the [Status](#status) section and the relevant design sections as things are built or decisions change.

---

## Status

| Phase | Goal | Deliverable | State |
|---|---|---|---|
| 0 | Scaffolding | Package, CLI, DuckDB schema, config, service layer, Streamlit demo + API skeleton | ✅ Done |
| 1 | Historical ingest | Daily poe.ninja dumps + hourly GGG exchange → `item` / `price_observation`, league calendar, price mappings, core pool, divination cards | ✅ Done. All 32 challenge leagues daily; hourly for the four exchange-era leagues, plus the current league (Allflame) through the live feed |
| 2 | Exploration | Recurring launch-week patterns across recent leagues: `analysis/` module, the Analysis tab, and the Card turn-ins / Arbitrage trading pages | 🟨 Tools built; findings in §9 |
| 3 | Patch corpus | Scraper, extractor, review tool for past leagues | ⬜ Not started |
| 4 | Baseline + backtest | First honest accuracy numbers | ⬜ Not started |
| 5 | Signals | Ranked list: "farm X", "buy Y on day 2, sell day 6" | ⬜ Not started |
| 6 | Live mode | Hourly ingest of the running league; live view of what's best to arbitrage; later, alerts when prices drift from prediction | 🟨 Live feed (`eb live watch`) and the Live market page built; prediction alerts not started |
| 7 | UI | Streamlit demo (local) → hosted public frontend on the JSON API | 🟨 Streamlit demo: launch market, card turn-ins, data; handles leagues with no data yet |

Legend: ⬜ Not started · 🟨 In progress · ✅ Done

Phases 1–2 alone are useful: knowing which categories reliably spike in the first week is already an edge.

### Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev,demo]'
.venv/bin/eb init-db      # create data/exiledbroker.duckdb with the schema
.venv/bin/eb dumps list   # available poe.ninja league dumps and local state
.venv/bin/eb dumps sync   # download + extract all challenge leagues into data/ (resumable)
.venv/bin/eb dumps load   # process extracted leagues into item / price_observation
.venv/bin/eb exchange sync -l Mirage   # hourly exchange history, first 14 days (resumable)
.venv/bin/eb exchange status           # what's on disk and loaded
.venv/bin/eb exchange sync -l "<New League>" --start 2026-11-20   # register the upcoming league (see §2.8)
.venv/bin/eb live watch                # keep the current league's latest hours loaded (Live market page)
.venv/bin/streamlit run app/dashboard.py   # local demo (run from the repo root so the theme loads)
.venv/bin/eb serve        # API at http://127.0.0.1:8000/api/health (for hosting later)
.venv/bin/pytest          # tests
```

Settings come from `EB_*` environment variables or a `.env` file (see `src/exiledbroker/config.py`).

### Running the ingest unattended

`scripts/ingest.sh` runs the fetch-and-load steps without supervision:

```bash
scripts/ingest.sh                      # hourly exchange: first 14 days of every challenge league since Settlers
scripts/ingest.sh exchange -l Mirage   # one league (any `eb exchange sync` options work)
scripts/ingest.sh dumps                # daily poe.ninja dumps for every challenge league: download, extract, load
scripts/ingest.sh all                  # both
scripts/ingest.sh live                 # live feed for the current league: updates every hour, runs until stopped

# In the background, then check on it whenever:
nohup scripts/ingest.sh all >/dev/null 2>&1 &
tail -f data/logs/latest.log
```

- **Stop it any time** (Ctrl-C, closing the terminal, sleep, a crash) and run the same command again to continue. A run started in the background with `nohup … &` ignores Ctrl-C, so stop it with `pkill -f "eb "`. That's safe at any point. Hourly pages, zips and Parquet files are written to a temporary name and renamed when complete. Database loads are one transaction per league, and exchange loads are incremental: they add new hours and remove ones that left the window, nothing else. Nothing that's finished is fetched or rewritten again.
- On macOS it keeps the machine awake (`caffeinate`) while running. Each run logs to `data/logs/ingest-<time>.log`, and `latest.log` points at the newest.
- Rough cost: the hourly exchange for the four challenge leagues since Settlers is ~1.5k requests (~30 min, ~150 MB on disk). The daily dumps for all ~30 challenge leagues are about 1 GB of zips.
- While a run is loading, the demo may briefly fail to open the database (DuckDB allows one writer). Refresh the page.

### Live market (phase 6, started)

The site's default page. It shows what's best to arbitrage **right now** in the running league: Chaos↔Divine loops and card flips, ranked on the latest published hours.

- **Feed:** `scripts/ingest.sh live` (`eb live watch`) picks poe.ninja's current challenge league. If the launch hour isn't known, it finds it by binary search over GGG's exchange history (about a dozen requests). It then keeps two windows loaded: the league's **first 14 days**, for the launch tools, and its **last 14 days** (`--lookback-hours`), for the live view. Each new hour is fetched about 6 minutes after it ends; GGG published within about 3 minutes in practice. It refuses leagues that aren't trading in the latest hour, so an ended league's history can't be replaced by an empty window.
- **"Now"** is the latest published hour, about an hour behind real time. The page shows how old it is, warns if the feed looks stopped, and with **Live updates** on it re-reads the data every minute. The page never fetches; the feed does. On Railway this becomes a worker running `eb live watch` next to the web app.
- **Before the first trade:** a just-launched league shows "waiting for the first trades" rather than nothing. Mirage's launch hour was published with no trades in it.
- **Tested on real API output:** `tests/test_live_pipeline.py` replays Mirage's first 30 hours exactly as GGG published them (`tests/fixtures/mirage_launch.json.gz`, rebuilt by `tests/fixtures/make_fixtures.py`). After each new hour it runs the real live update and then every page and analysis tool. It also checks that an update interrupted mid-hour resumes cleanly. That's how the one-league slider bug (decision log) was found.

### Hosting cost issues (review of 2026-10-22)

Things that would raise the Railway/Supabase bill, measured on real data where possible. Fix before hosting; update the status as they're done.

| # | Issue | Measured / estimated | Fix | Status |
|---|---|---|---|---|
| 1 | Live page pulled a league's whole cross-market history (135k rows, 15 MB) to show ~85 rows, re-run every minute by auto-refresh | ≈ 650 GB/month Supabase egress (Pro includes 250 GB) | Filter by time in SQL; re-query only when a new hour is loaded | ✅ done: identical results, 596 rows (0.07 MB) instead of 135,532 (15.1 MB), once per new hour instead of every minute; the per-minute league check takes ~10 ms via the index |
| 2 | Live worker fetched any window page missing from disk: ~672 requests/hour on a server with a throwaway disk | Risk of being blocked by GGG; slow | Use `exchange_hour_loaded` (the database) to decide what to fetch | ✅ done: a worker with a wiped disk fetches only the new hour; a rebuild re-fetches the whole window, so data can't shrink (tested) |
| 3 | No indexes for the pages' access paths (league + source + time); primary keys start with item id | Full scans on Postgres → bigger paid database | Add league/time indexes | ✅ done (in `schema.sql`; tested on DuckDB only, no local Postgres) |
| 4 | Arbitrage trading pulls 439k rows (49 MB) per 10-minute cache expiry | High if busy | Aggregate in SQL instead (exact for any fee buffer / direction, which a fixed precomputed table couldn't be) | ✅ done: identical results, 2,086 summary rows (0.23 MB) instead of 438,729 raw rows (49 MB) |
| 5 | Card turn-ins and Analysis tools pull 1.6–6 MB per load | Moderate | Aggregate in SQL (medians via `percentile_cont`) | ✅ done: identical results. Card turn-ins 57 rows instead of 21,628; group timing 280 rows instead of ~81k. Unique moves still reads daily dump rows, but that's local-only historical data |
| 6 | Worker re-downloads RePoE (3 MB) and the loot filter every run on a wiped disk | Small, impolite | Store in the database (`reference_data`) and never re-download what we have: sources are checked for changes (RePoE weekly, core pool and filter tiers daily) with conditional requests (ETag / Last-Modified), so an unchanged source answers 304 with no body | ✅ done: RePoE stored trimmed (0.9 MB vs 3 MB); between checks there are no reference requests; a due check of an unchanged source downloads nothing (tested, and confirmed on the live endpoints) |
| 7 | Every exchange item stored every hour (~1,000 for Allflame); the site uses tracked items + cross-market legs | ~30–50% more rows (estimate) | Store only what the site uses | ⬜ |
| 8 | Text primary keys (~2× row size vs integer ids) | Matters only at larger scale | Defer | ⬜ |
| 9 | Streamlit memory grows per concurrent visitor; some caches keyed on free-typed numbers (unbounded) | Launch-week traffic | Cap caches; the planned frontend fixes the rest | ⬜ |

### Next steps

- **Phase 2:** use the Analysis tab across all four exchange-era leagues and write up the patterns that repeat (§9).
- **Before the next launch:** register the upcoming league once its name and date are announced (§2.8), and run the exchange sync on a schedule (hourly) through launch week. A small `eb exchange watch` loop or a launchd/cron entry is the obvious next step (phase 6).
- **Live recording at launch (phase 6):** uniques have no sub-daily history anywhere public, so the poe.ninja live poller must be running when the next league starts (§2.2).
- **Divination card expected value:** random rewards ("5x Currency") and unique rewards (§2.7).

### Open questions

- **Frontend framework** for the public UI. The API comes first, so this can wait. The first hosted demo can be the Streamlit app itself, on Railway.
- **What goes into Supabase.** All price history is ~100M+ rows, too much for a hosted Postgres plan. Likely: curated tables (e.g. the first 30 days, Medium/High confidence, plus aggregated curves) in Postgres, with the full Parquet history in Supabase Storage.

### Add-ons (after the first demo)

- **Arbitrage / flip tracker.** Once live-market polling exists, track exchange pairs with high volume and a decent spread, and surface what is worth flipping. GGG's hourly exchange digests (§2.2) already have volume and low/high ratios, so we can backtest flip margins on past launches before going live. This should be a tracker that advises the player; automating in-game trades is against GGG's terms of use.
- **Build popularity.** Scrape poe.ninja's builds pages for general signals: main skills, target uniques and common ascendancies. ⚠️ poe.ninja's API docs say the builds/profiles API is internal and not for third-party use, and their builds pages are rendered from that same API. So scraping them is effectively using it, and misbehaving clients get blocked. Before building this, ask poe.ninja for permission (they're on Discord) or look for another source. GGG's ladder API, for example, gives class/ascendancy but needs a registered OAuth app.

### Decision log

| Date | Decision |
|---|---|
| 2026-10-21 | DuckDB/Parquet storage. |
| 2026-10-21 | PoE1 only for now (a league launches in about a month). The `game` column stays on leagues and items so PoE2 can be added later. |
| 2026-10-21 | Built as a public site, demoed locally first. Batch pipeline and read-only serving are separate: CLI jobs write the DuckDB file and Parquet, the FastAPI app only reads precomputed predictions. This keeps hosting simple (static frontend + small API, no heavy compute on request). |
| 2026-10-21 | Streamlit is the first, local demo. The goal is a hosted public site, so all read logic lives in `services/`, which both the Streamlit app and the FastAPI app call. Moving to hosting means swapping the UI, not rewriting queries. |
| 2026-10-21 | Python >=3.11 with plain venv + pip (uv isn't installed on this machine); `pyproject.toml` is tool-agnostic, so uv can be adopted later. |
| 2026-10-21 | Ingest jobs run locally and are resumable: downloads continue with HTTP Range + If-Range, outputs are written to a temp path and renamed when done, and a finished file is its own completion marker (no separate state file to corrupt). Re-running never re-downloads or rewrites finished work. |
| 2026-10-21 | Dump price rows stay in Parquet and are exposed through DuckDB views (`dump_item_price`, `dump_currency_price`) rather than copied into the database. The views add `day_offset`. When we move to hosting, the same files can sit in object storage. |
| 2026-10-21 | By default we keep only each challenge league's softcore files. Standard, Hardcore and private leagues in the zips are skipped. Leagues are tagged `challenge`, `ruthless` or `event` (an event is a league nested inside another league's window, e.g. Phrecia). |
| 2026-10-21 | **Target hosting: Supabase (Postgres + Storage) for data, Railway for the app and scheduled workers.** Locally we keep DuckDB. The schema in `schema.sql` sticks to SQL that runs on both DuckDB and Postgres (`DOUBLE PRECISION`, `ON CONFLICT`, `ADD COLUMN IF NOT EXISTS`). Code that Supabase needs to read must use real tables (`item`, `price_observation`, ...), not the local Parquet views. On Railway: the FastAPI app, the Streamlit demo, and cron-style workers for live polling. |
| 2026-10-21 | League kinds: **challenge** = the main 3–4 month leagues (Settlers, Mirage, ...). **event** = short leagues of a few weeks (Ancestors, Phrecia) with far fewer players and a very different market. **ruthless** = Ruthless variants. |
| 2026-10-21 | **Event and Ruthless leagues are excluded** from data and analysis. Most players don't play them and their markets don't follow normal trends (§2.6), so including them would make predictions worse. Every command defaults to challenge leagues, the calendar lists only challenge leagues, and the Ancestors data was deleted. `--kind` / `-l` can still select one explicitly. |
| 2026-10-21 | **Scope: currency and uniques only.** The dump loader skips base items, gems, cluster jewels, maps and the other item types. Currency-like item types (scarabs, essences, fossils, oils, ...) are keyed by name (`currency:<slug>`), like the currency file and the exchange, so one item has one id whatever the source. Uniques keep `ninja:<Id>`. |
| 2026-10-21 | **For the first 14 days, hourly exchange prices replace daily ones** for everything traded on the exchange. The hourly price is volume-weighted across the item's Chaos and Divine markets, with Divine trades converted at that hour's Divine rate (§2.4). |
| 2026-10-21 | **Price mappings** (`tracked_item`) have four groups: **Currency** (mirrors included, not a separate group), **High-tier essences** (all Deafening, plus Hysteria/Insanity/Horror/Delirium), **Scarabs**, and **Divination cards**. The group rules are in `normalize/tracked.py`, so they apply to every source. |
| 2026-10-21 | **Only the core drop pool is shown** (`ingest/core_pool.py`). Currency, essences and scarabs are limited to what poe.ninja lists for the *current* league (exchange overview `type=Currency/Essence/Scarab`, minus Catalysts). Each list is a snapshot in the database (`reference_data`), checked for changes daily (or now with `eb exchange sync --refresh`) and replaced only if poe.ninja's list changed, so items whose league mechanic didn't go core drop out. (This replaces the earlier running-union currency list.) Divination cards are limited to what NeverSink's filter shows. Manual overrides go in the committed `config/core_pool.toml`: `exclude` hides a name everywhere, `[include]` forces a name into one group. Example: Deafening Essence of Doubt traded in Mirage but isn't in the current list, so it's hidden. |
| 2026-10-21 | **Malformed dump rows are dropped, not fatal.** poe.ninja doesn't quote CSV fields, so a name containing a line break (Necropolis coffins, a mechanic that never went core) spills one record over several lines. Extraction keeps only rows that start with the league name and have the right field count, and records the drop count next to the Parquet (`*.dropped.json`). Necropolis: 1,422 lines dropped. |
| 2026-10-21 | **Divination cards** (§2.7): follow only cards NeverSink's loot filter (what FilterBlade serves) shows at Semi-Strict (`EB_LOOT_FILTER_STRICTNESS`), i.e. tiers t1–t4. Each card's set size and reward come from RePoE, in the `divination_card` table. Cards trade on the exchange, so they get hourly prices, and a fixed currency or card reward gets an hourly **turn-in margin** (reward value − set size × card price). |
| 2026-10-21 | **Built for a new league's data arriving.** At launch every price is null, and GGG publishes each exchange hour only after it ends. A league can be registered before it has any data (`--start`), and every view handles none / one hour / a few days without errors. Day-based comparisons (e.g. "vs. day 1") only appear once there are two days. Keep this in mind for every new view (§2.8). |
| 2026-10-21 | The demo's KPI cards leave out Chaos (it's the unit everything is priced in), and every price column, axis and tooltip names its unit. |
| 2026-10-21 | Dump rows with no item name (15 Sanctum relics in the Ancestor dump) are skipped by the loader. |
| 2026-10-21 | **Phase 2 analyses favour recent leagues.** The economy changes a lot league by league, and the currency exchange (Settlers, 2024-07) was a structural break. So every tool reports per league, newest first, and summaries are recency-weighted: the newest league counts 1, and each *half-life* leagues back halves it (default 2, adjustable in the Analysis tab). Leagues before Settlers are context only. |
| 2026-10-21 | Launch curves are compared on a **relative** scale: price ÷ the item's day-1 price in the same league, where the day-1 price is the *median* of its first-24-hour hourly prices (thin early markets, like a few junk Mirror trades, would skew an average). Curves whose baseline rests on fewer than six traded hours are flagged. Turn-in figures are the **typical (median) hour**: set cost, reward value, margin and margin %. Thin card markets have junk hours (The Hoarder averaged 570c a set in Mirage, against a typical hour of about 1c), and averaging hourly percentages blows up for near-worthless sets. |
| 2026-10-22 | **Card flip score** (`services/divination.score_turn_ins`): margin %, investment (set cost), profitable hours and volume (full sets traded) are each ranked among the priced cards (best = 1), and the score is their weighted mean. Ranks rather than raw values, so chaos amounts, shares and counts combine fairly and one outlier can't dominate. Weights default to 4 / 2 / 3 / 3 and are tunable on the Card turn-ins page, as is whether a cheaper or a bigger set scores better. |
| 2026-10-22 | **Cross-market loops** (`services/cross_market.py`, the **Arbitrage trading** page). The exchange loader also writes `cross_market_hour`: every item-hour that traded against both Chaos and Divines, with the same hour's Divine rate (not carried forward, since a loop needs both trades in that hour). Both loops are priced at the worst prices of the hour on every leg. An hour pays only if the loop beats a fee buffer (default 2%), and a league where an item didn't trade in both markets counts as 0 for its worst-league share. Items under 1c are filtered by default: dust-priced bulk items (Rogue's Markers at ~0.001c) show huge gaps that say more about how they trade than about profit. |
| 2026-10-22 | **One scoring method** (`services/scoring.rank_score`) for card flips and cross-market loops: percentile rank per factor, weighted mean, weights tunable on the page. Cross-market factors: edge when paying, share of paying hours, worst league's share, and volume traded in both markets. |
| 2026-10-22 | **Trading pages put the money first.** On Card turn-ins and Arbitrage trading, the ranked table is full width at the top, its columns lead with score and chaos figures (score, set cost, reward, margin, margin %, sets traded, profitable hours; what the card gives comes last), and charts sit at the bottom. |
| 2026-10-22 | **Group timing defaults to Chaos.** Priced in Divines, almost every group sinks below its day-1 price, because the Divine itself inflates fastest at launch (86 → 266c in Mirage). That read as "currency loses value", which is wrong from a player's view. The Divine view is still available, with an explanation. |
| 2026-10-22 | **Incremental exchange loads; the database is never wiped to add data.** Loads used to delete a league's hourly rows and re-insert all of them (about 454k for Allflame) on every update. Now `exchange_hour_loaded` tracks loaded hours; a load inserts only new hours and deletes only hours leaving the window. The Divine rate is carried forward from rows already in the database (an ASOF join), and the curated tables (`tracked_item`, `divination_card`) are updated by difference. Verified: loading hour by hour gives exactly the same rows as one full load, and on Allflame a one-hour window slide removes and re-adds exactly 531 rows. The per-league processed Parquet files are no longer used. |
| 2026-10-22 | **Hosting will launch with live-league data only.** Past leagues' history is for building and testing (proof of concept, analysis) and stays local; anyone after old prices has poe.ninja. Hosted data is the running league's launch fortnight plus recent hours, a few hundred MB at most. |
| 2026-10-22 | **Live market is the landing page**, because it's what will be used most. The live feed is a separate process (`eb live watch`) and the page only reads, the same split as the rest of the app, so hosting means one web service plus one worker. |
| 2026-10-22 | **Launch views stay on the launch fortnight.** The Launch market only uses each league's first 14 days. A live league whose loaded hours are all later (e.g. Allflame, months in) shows a "past the launch window" note pointing to the Live page, instead of a misleading chart. |
| 2026-10-22 | **The running league keeps its launch fortnight.** A live window is the launch's first 14 days *plus* the latest 14 days, loaded together. Loading one window doesn't replace the other, so a league like Allflame (launched 2026-07-24 22:00 UTC) feeds both the Launch market / analysis tools and the Live view. While a new league is under two weeks old, the two windows are the same. A running league has no daily dump until it ends, so the Unique moves tool says so instead of leaving it out silently. |
| 2026-10-22 | Widgets whose range depends on the data (e.g. "seen in at least N leagues") are hidden when there's only one option. With one league loaded, as at a new league's launch, Streamlit rejects a slider with min = max. |
| 2026-10-22 | **Charts use linear axes by default**, because they're read by players. Log scale is an opt-in toggle only where values span orders of magnitude (the market chart comparing items, and the card opportunity map). Relative charts say what the numbers mean (1 = the day-1 price). |
| 2026-10-21 | Demo tables sort by each item's **average price over the window** (volume-weighted, in the selected unit), shown as the "Avg price" column. With nothing selected, the chart shows the five most-traded items. |
| 2026-10-21 | Exchange item names come from RePoE's base item table. RePoE gives some different items the same name, so an ambiguous name never merges items: each metadata id becomes its own item, labelled `Name (MetadataName)`. None of the tracked items are ambiguous. |
| 2026-10-21 | A league's `launched_at` is the first hour it trades on the exchange (Mirage: 2026-03-06 20:00 UTC). Hourly `day_offset` is fractional days from then. |
| 2026-10-21 | Item identity = poe.ninja's line `Id` (`item.id = 'ninja:<Id>'`), because it is stable across leagues. Currencies from the currency file get `currency:<slug>`. |
| 2026-10-21 | Currency price = midpoint of the two quoted sides: `chaos_ask` (chaos paid for one unit) and `chaos_bid` (chaos received for one unit). Both are kept, and the row's confidence is the weaker side's. Every row gets `divine_value` from that day's Divine midpoint. |
| 2026-10-21 | The dump loader runs locally on DuckDB (it reads Parquet). Read-side `services/` SQL must stay Postgres-compatible (no `GROUP BY ALL` or DuckDB-only functions), because Supabase will serve the same queries. |
| 2026-10-21 | All market data lives in the repo's gitignored `data/` folder (the default `EB_DATA_DIR`), with backup ignore rules for `*.duckdb`, `*.parquet` and partial downloads. |

---

## 1. What the tool does

Each new league starts with an empty economy, so you can't buy anything before launch. The edge is **predicting how prices move over the first ~14 days**, using what happened in past leagues plus what this patch changes. That breaks into three questions:

1. **Baseline:** how does this item's price usually move from day 0 to day 14 of a league?
2. **Patch effect:** how do this patch's buffs, nerfs, new mechanics and drop changes shift that path?
3. **Action:** what to farm, buy cheap on day 1–3 and sell on day 5–10, and how confident the tool is.

A fourth mode comes later: live tracking during launch week, flagging items that drift away from their predicted path.

## 2. Data sources

| Data | Source | Notes |
|---|---|---|
| Historical prices | poe.ninja data dumps (per-league CSVs) | The main dataset. Download once and store locally. |
| Live prices | poe.ninja currency/item overview endpoints | Poll politely (hourly at most) and cache. |
| Currency volume and history | GGG's public Currency Exchange API | **Hourly** digests with volume since Settlers (2024-07). No auth. See §2.2. |
| Patch notes | pathofexile.com patch-notes forum, poewiki | Scrape once per league and store the raw text. |
| Item metadata | RePoE / poedb exports | For matching patch-note names to items. |
| Build popularity | poe.ninja builds pages (add-on, needs permission) | A demand signal: main skills, target uniques, ascendancies. Not in the first demo. |

Follow GGG's terms and rate limits, and cache everything so the same data is never fetched twice.

**poe.ninja usage rules** (from [poe.ninja/docs/api](https://poe.ninja/docs/api)): only the economy endpoints may be used; the builds/profiles API is off-limits to third parties (see the build-popularity add-on for how we'd approach that). Send a descriptive User-Agent (ours names the repo), respect HTTP caching, and don't poll faster than the data refreshes (PoE1 is about every 15 minutes). Hosted apps should proxy through their own backend, not call poe.ninja from users' browsers. The dumps are licensed **CC BY-SA**, so the public site must credit poe.ninja.

### 2.1 What the dumps contain

- One zip per league from `GET /poe1/api/data/dumps` (listing) and `/poe1/api/data/dumps/dump?name=<league>`. Each zip holds that league, plus Standard, Hardcore and private leagues. It goes back to Essence (2016), and the format is unchanged since then.
- `<League>.items.csv`: `League;Date;Id;Type;Name;BaseType;Variant;Links;Value;Confidence`. **Daily** values in chaos. Confidence is Low/Medium/High. There are **no listing counts**, so confidence is our only liquidity signal for history.
- `<League>.currency.csv`: `League;Date;Get;Pay;Value;Confidence`. `Value` is how many `Pay` you give for one `Get`. Both directions are present (Get Divine / Pay Chaos ≈ 86; Get Chaos / Pay Divine ≈ 0.0117).
- Days 0–1 are thin and noisy (e.g. a Divine at 2 chaos on day 0). Down-weight them.
- Fields aren't quoted. An item name with a line break (Necropolis coffins) breaks its record over several lines; extraction drops such rows (decision log).
- Sizes vary a lot: Mirage is 55 MB zipped and 4.8M softcore item rows (11 MB Parquet); Settlers is 106 MB and 8.7M rows.
- The `Id` column is poe.ninja's item line id and is **stable across leagues** (Headhunter is 607 in Settlers, Mirage and Ancestors). One visible name/base/variant can map to several ids, because of attributes the dump omits (item level on bases and cluster jewels, etc.), so `Id` is the item identity.

### 2.2 Getting finer than daily (league-start volatility)

The first 48 hours are where prices move most and where the profit is, and daily rows flatten them. What exists:

| Source | Granularity | Covers | Since | Notes |
|---|---|---|---|---|
| poe.ninja dumps | daily | all priced items + currency | 2016 (Essence) | ✔ `eb dumps`. |
| **GGG Currency Exchange API** `GET https://web.poecdn.com/api/currency-exchange[/<unix-hour>]` | **hourly** | everything tradeable on the in-game exchange (currency, fragments, scarabs, essences, tattoos, omens, ...) | **Settlers launch, 2024-07-26 20:00 UTC** | ✔ `eb exchange`. Public, no auth. Each page is one hour across all leagues: per pair, `volume_traded`, low/high stock and low/high ratio. Pages are immutable (cached for a year), so each is fetched once. Items are named by metadata path (`Metadata/Items/Currency/CurrencyModValues` = Divine), so they need a name mapping. Roughly 770 KB per hour raw, ~45 KB gzipped. GGG says old history may be removed later, so it's worth archiving. |
| poe.ninja live overview API | ~15 min refresh | all poe.ninja categories, with listing counts | now only | No history. **For uniques, gems and bases, the only way to get sub-daily launch data is to record it ourselves**, so the live poller should be running at the upcoming launch. |
| GGG public stash river | real time | every public listing | now only | Needs a registered OAuth app and heavy processing. Not worth it for the demo. |

Example, Mirage: the league launched at 20:00 UTC on 2026-03-06. The first Divine trades came at 22:00, at **23 chaos** (range 15–28). By 03:00 the price was 59, and the first 24 hours averaged 86. The daily dump says 85.6 for day 1, with none of that path visible.

### 2.3 From dumps to the general tables (`eb dumps load`)

- **Scope:** currency, divination cards and uniques (`Unique*` item types, the currency file, and currency-like item types: `DivinationCard`, `Scarab`, `Essence`, `Fossil`, `Oil`, `Omen`, `Tattoo`, `Resonator`, `DeliriumOrb`). Base items, gems, cluster jewels and maps are skipped.
- **`item`**: uniques are one row per poe.ninja `Id` (`ninja:<Id>`) with name, category (`UniqueArmour`, ...), base, variant and links (`'1-4 links'` is stored as 4, meaning "four or fewer"). Currency-like items are `currency:<slug of name>` with category `currency`, `scarab`, `essence`, ... (The `gem_*` columns from earlier are unused now.)
- **`price_observation`**: one row per item per day. `chaos_value`, `divine_value`, `confidence`, `day_offset` and, for currency, `chaos_ask` / `chaos_bid`. `source = 'poe.ninja-dump'`, and `listing_count` is empty because the dumps don't have it. Zero-value rows are dropped.
- **`ingest_load`**: what was loaded per league, with an input fingerprint. Each league loads in a single transaction, so an interrupted load leaves it untouched, and re-running with the same inputs is a no-op. Use `--force` to rebuild.
- Sizes: Mirage is 2,900 items and 345k daily rows, loaded in about a second.

### 2.4 Hourly exchange pipeline (`eb exchange sync`)

1. **Find the launch.** Starting 12 hours before the league's first dump date, fetch hourly pages until the league first appears. That hour is `league.launched_at`.
2. **Fetch the window** (default 14 days after launch): one page per hour, gzipped to `data/raw/ggg/currency_exchange/<unix-hour>.json.gz`. Each page is checked against the hour requested, because a timestamp before the history starts silently returns the first page. If the league is still running, the fetch stops at the current hour.
3. **Load incrementally** into `price_observation` (`source = 'ggg-exchange-hourly'`) and `cross_market_hour`. `exchange_hour_loaded` records which hours each league has, including hours where nothing traded. A load reads only the pages of hours that aren't loaded yet (flattened to a temporary Parquet file), inserts them, and deletes only loaded hours that left the window, all in one transaction. A live update therefore touches one hour's rows (~500 for Allflame), not the league's ~450k. A full rebuild happens only when `LOADER_VERSION` changes or with `--force`. Pricing:
   - Divine rate per hour = Chaos traded ÷ Divines traded in the Chaos/Divine market, carried forward through hours with no Divine trades.
   - For each item and hour, every market against Chaos or Divine contributes. `volume` = units of the item traded. `chaos_volume` = Chaos traded, plus Divines traded × the Divine rate. `chaos_value` = chaos_volume ÷ volume. `chaos_low` / `chaos_high` = the lowest and highest traded ratio, in chaos. `divine_value` = chaos_value ÷ Divine rate.
   - Hours with no trades for an item have no row. Chaos is 1 by definition.
   - Names come from RePoE, stored trimmed in the database (`reference_data`), checked for changes weekly and only re-downloaded if RePoE changed.
5. **Checks on Mirage:** averaged by day, the hourly Divine rate matches the daily dump (86.5 vs 85.6 on day 1, 151 vs 145 on day 3), and all 269,018 hourly prices sit inside their hour's low/high range.

Mirage, first 14 days: 368 pages (39 MB raw), 1,027 items, 269k hourly rows.

### 2.5 Price mappings (`tracked_item`)

| Group | Items | In Mirage |
|---|---|---|
| Currency | poe.ninja's current-league Currency list minus Catalysts (88 names) | 87 shown (Dead Man's Sulphur is newer than Mirage) |
| High-tier essences | Deafening + Hysteria, Insanity, Horror, Delirium, if in the current Essence list | 23 (Deafening Essence of Doubt is no longer listed) |
| Scarabs | every "… Scarab …" in the current Scarab list | 111 |
| Divination cards | cards NeverSink's filter shows (361) | 358 with hourly prices |

The demo's "Launch market" page shows KPI cards for Divine, Alchemy, Mirror and Mirror Shard. Below them, each group gets a table sorted by average price, and selecting rows charts their hourly prices.

From day 1 to day 14 in Mirage: Divine 86 → 266 chaos (+208%), Mirror of Kalandra 84 → 678 divines (+710%), Mirror Shard 9.7 → 34 divines, Deafening Essence of Scorn 2.5 → 22.7 chaos.

### 2.6 Why event leagues are excluded

We looked at Ancestors (an event league, 21 days) before dropping event leagues. Its data has since been deleted:
- About 45–60% as many items were priced as in Mirage, and whole categories (scarabs, essences, divination cards, ...) were missing.
- Currency quotes were noisy: on day 1 the Divine buy and sell prices were 46% apart, while Mirage's stayed within 1–3% for the first week.
- Chase uniques moved the opposite way from a normal league: Mageblood fell 18.1k → 8.6k chaos over the first week, while in Mirage it rose 7.8k → 33k.

### 2.7 Divination cards

- **Which cards:** NeverSink's filter lists every card in a tier block (`$type->divination $tier->t1` ... `t5`). Tiers t1–t4 (incl. t4c, t5c) are shown, and t5 is hidden. At Semi-Strict that's 361 shown and 93 hidden (identical up to Strict). Stack-size rules aren't tiers. A card the filter doesn't know yet is shown by its catch-all rule, but we don't follow it until it's tiered. The tiers are checked with the core pool (daily) and stored in the database (`reference_data`); the filter file is only re-downloaded when it changes.
- **What a set gives** (RePoE `properties.description` / `stack_size`, parsed in `normalize/divination.py`): followed cards are 67 currency, 5 card, 180 unique, 41 normal, 26 gem, 20 magic and 18 rare rewards (plus 4 disabled). A currency or card reward is *fixed* if its name is exactly one item (`<currencyitem>{10x Exalted Orb}`), or *random* if it's generic (`5x Currency`, `3x Essence`, `Divination Card`). Fixed exchange-priced rewards get `reward_item_id`.
- **Turn-in margin** (`services/divination.py`): for each hour both the card and its reward traded, set cost = set size × card price, reward value = quantity × reward price, margin = reward value − set cost. This excludes gold fees and the time to buy a full set.
- **Mirage, first 14 days:** 57 fixed turn-ins priced, 28 profitable in 90%+ of hours. With the default weights and cheaper sets preferred, The Heroic Shot scores highest (a set costs about 0.7c and roughly doubles, profitable 95% of hours, about 44k sets traded). Preferring bigger sets puts steady large-capital flips on top, e.g. The Nurse (about 2,100c a set, +6.7%, profitable every hour) and The Sephirot.
- **Scoring and the opportunity map:** the Card turn-ins page ranks cards by a tunable score (decision log) and plots the top N as investment vs. margin, sized by sets traded.
- **Next: expected value.** Random rewards need an EV over what they can roll, and unique rewards need unique prices (daily dumps). Once the EV exists, a card trading below its reward's EV is an arbitrage target.

### 2.8 Designing for a new league

The upcoming league is what the tool is for, and its data starts empty:
- **Before launch** it isn't in poe.ninja's dumps. Register it with `eb exchange sync -l "<Name>" --start <launch date>`. The league row is created right away (`exchange_tracked`), the demo shows "waiting for the first hour of trades", and later runs remember the start date.
- **First hours:** GGG publishes each exchange hour only after it ends, so the first prices appear about an hour after launch. Many items have no trades for hours, and the Divine rate is unknown until the first Chaos/Divine trade. Prices in divines are then null, and averages leave those hours out of both the sum and the weight.
- **Each re-run** of the sync adds the newly published hours (finished hours are never re-fetched or rewritten) and drops hours that slid out of the window, in one transaction.
- **Every view** must handle: no data, one hour, items that haven't traded, days with gaps. The demo's tests (`tests/test_dashboard.py`) run the app headlessly in each of those states.


## 3. Architecture

```
patch notes ──► parse ──► LLM extraction ──► reviewed changes ─┐
                                                               ├─► features ─► models ─► signals ─► CLI / dashboard
price dumps ──► ingest ──► normalize (day offset, renames) ───┘                  ▲
live prices ──────────────────────────────────────────────────────────────────┘ (live comparison)
```

## 4. Project layout

*Built so far is marked ✔; the rest is planned. Update as modules are created.*

```
ExiledBroker/
├── pyproject.toml              # ✔ Python >=3.11
├── src/exiledbroker/
│   ├── config.py               # ✔ settings (pydantic-settings), paths, API keys
│   ├── ingest/
│   │   ├── http.py             # ✔ polite client (UA, spacing, retries) + resumable download
│   │   ├── files.py            # ✔ atomic writes
│   │   ├── poe_ninja_dumps.py  # ✔ dump listing, download, zip → Parquet
│   │   ├── currency_exchange.py # ✔ GGG hourly exchange: find launch (binary search), fetch launch or recent window, → Parquet
│   │   ├── live.py             # ✔ one live update for a running league (used by `eb live sync|watch`)
│   │   ├── item_names.py       # ✔ RePoE metadata id → name
│   │   ├── core_pool.py        # ✔ core drop pool: current-league lists + config/core_pool.toml
│   │   ├── loot_filter.py      # ✔ NeverSink filter divination tiers
│   │   ├── poe_ninja_live.py   # live economy overview (phase 6)
│   │   └── patch_notes.py      # scrape raw text → store
│   ├── storage/
│   │   ├── db.py               # ✔ DuckDB connection (read-only for the API), query helpers
│   │   ├── dumps.py            # ✔ league upsert + Parquet views
│   │   └── schema.sql          # ✔
│   ├── normalize/
│   │   ├── dump_loader.py      # ✔ dump Parquet → item / price_observation (currency + uniques)
│   │   ├── exchange_loader.py  # ✔ incremental hourly loads: add new hours, drop ones leaving the window
│   │   ├── tracked.py          # ✔ price mapping groups: currency, essences, scarabs, divination cards
│   │   ├── divination.py       # ✔ card set size + reward parsing
│   │   ├── mappings.py         # ✔ rebuild tracked_item + divination_card after each load
│   │   ├── leagues.py          # ✔ day_offset, league ids, challenge/ruthless/event tagging
│   │   ├── entities.py         # name resolution, renames, variants
│   │   └── currency.py         # chaos/divine normalization
│   ├── patchnotes/
│   │   ├── taxonomy.py         # change types (pydantic models)
│   │   ├── extractor.py        # LLM → structured PatchChange
│   │   └── review.py           # human approve/edit loop
│   ├── features/               # curve shape, change impact, demand proxies
│   ├── models/
│   │   ├── baseline.py         # historical curve per item/category
│   │   ├── impact.py           # patch-adjusted curve
│   │   └── backtest.py         # leave-one-league-out evaluation
│   ├── signals/                # ranking, buy/sell windows, risk
│   ├── analysis/
│   │   └── launch_patterns.py  # ✔ phase 2: unique moves by tier, launch curves, group timing, card turn-ins across leagues, recency weights
│   ├── services/               # ✔ read-side queries shared by the demo and the API (overview, prices, market, divination, cross_market, scoring, live)
│   ├── api/app.py              # ✔ FastAPI, read-only (/api/leagues, /api/market/<league>/groups/<group>, /api/market/<league>/hourly, ...)
│   └── cli.py                  # ✔ `eb dumps list|sync|load`, `eb exchange sync|status`, `eb live sync|watch`, `eb serve`, `eb init-db`
├── app/
│   ├── dashboard.py            # ✔ Streamlit entry point (navigation, credit)
│   ├── common.py               # ✔ cached loaders + formatting
│   ├── static/                 # ✔ sidebar wordmark + icon
│   └── app_pages/              # ✔ live.py (default), market.py, cards.py, arbitrage.py, analysis.py, data.py
├── .streamlit/config.toml      # ✔ demo theme
├── scripts/ingest.sh           # ✔ unattended, resumable ingest runner
├── config/core_pool.toml       # ✔ manual core-pool overrides (exclude / include by name)
├── web/                        # hosted public frontend (later; framework TBD)
├── data/                       # ✔ gitignored: raw/{poe_ninja/{dumps,categories}, ggg/currency_exchange, repoe}, processed/{poe_ninja/dumps, ggg/currency_exchange}, logs/, exiledbroker.duckdb
└── tests/                      # ✔ incl. fixtures/ (real exchange pages for the live replay)
```

**Stack:** `httpx`, `polars`, DuckDB with Parquet, `pydantic`, `typer`, Streamlit (demo), FastAPI + uvicorn (hosted API), and `scikit-learn`/LightGBM later. DuckDB suits this well: a single file, fast queries over time series, and no server to run.

## 5. Core data model

```
League(id, game, name, version, start_at, end_at, mechanic, kind, dump_name, launched_at, exchange_tracked)
Item(id, canonical_name, category, base_type, variant, links, ninja_id, metadata_id)
TrackedItem(item_id, group_id, group_label, sort_order)   -- price mappings: currency | essence | scarab | divination
DivinationCard(item_id, name, stack_size, reward_kind, reward_name, reward_quantity,
               reward_item_id, reward_fixed, reward_text, filter_tier, followed)
CrossMarketHour(league_id, item_id, observed_at, day_offset,
                chaos_price, chaos_volume, chaos_low, chaos_high,       -- X/Chaos market
                divine_price, divine_volume, divine_low, divine_high,   -- X/Divine market
                divine_rate, divine_rate_low, divine_rate_high)         -- same hour
ItemAlias(alias, item_id, valid_from_league)     -- handles renames/reworks
PriceObservation(item_id, league_id, observed_at, day_offset,
                 chaos_value, divine_value, listing_count, source,
                 confidence, chaos_ask, chaos_bid,               -- daily dumps
                 volume, chaos_volume, chaos_low, chaos_high)    -- hourly exchange
PatchNote(id, league_id, version, published_at, url, raw_text)
PatchChange(id, patch_note_id, section, raw_line,
            entity_type,   -- skill_gem | unique | mechanic | currency | drop_rate | crafting ...
            entity_ref, change_type, direction (+/-), magnitude (0-3),
            confidence, extracted_by, reviewed)
PatchChangeItem(patch_change_id, item_id, relation)  -- direct | ingredient | build_dependency
Prediction(run_id, league_id, item_id, horizon_day, p10, p50, p90, rationale)
```

The services, demo and API read `item` / `price_observation`, the tables that will move to Supabase. The `dump_item_price` / `dump_currency_price` views over raw Parquet remain for local exploration only. `ingest_load(league_id, source, fingerprint, item_count, row_count, loaded_at)` tracks loads.

The key design choice is **`day_offset`**: every price is stored relative to its league's start. That way the Settlers day-3 price and the Mercenaries day-3 price can be compared directly.

## 6. Patch-note pipeline

1. Split the notes into sections and individual lines.
2. An LLM (e.g. Claude) turns each line into a `PatchChange` using a fixed set of change types, enforced with a pydantic schema.
3. Match the changed thing to items directly ("Mageblood now…") and indirectly: a buffed skill raises demand for the uniques and bases its builds use, which is learned from past build-popularity data.
4. **Review the extractions by hand.** There are only a few patches a year, so checking ~300 lines per league is realistic, and it gives us labeled data.

## 7. Modeling

There are only about 15–25 leagues with usable data, so we start simple:

1. **Baseline curves:** the median day 0–14 price path per item and category, scaled to day-1 price.
2. **Analog matching:** find past items that got a similar change (e.g. "unique buffed, magnitude 2, build-enabling") and apply their observed price lift.
3. **Learned model (later):** gradient boosting on curve, change and demand features, only once the backtest shows it beats step 2.
4. **Backtest everything:** hold out each league, give the model only that league's patch notes, and score its day-1/3/7/14 predictions. This harness gets built early, because it's what tells us whether anything works.

## 8. Risks to plan for

- **Thin or manipulated listings:** drop or down-weight items with low listing counts. The historical dumps have only Low/Medium/High confidence, so use that until live data gives real counts.
- **Structural changes:** things like the in-game currency exchange and new crafting systems break past patterns. Tag leagues with these changes so the models can account for them.
- **Renames and reworks:** handled by the `ItemAlias` table.
- **Survivorship bias:** poe.ninja only tracks items that are actually listed.
- **Table size at full scale:** `price_observation` costs about 150 bytes/row in DuckDB (Mirage: 614k daily + hourly rows → 96 MB), mostly the text primary key. Dropping base items and gems cut the daily rows by ~90%, so all challenge leagues should be roughly 10M rows. For Supabase, still consider integer surrogate keys and loading only the window we model.
- **Exchange volume scale:** GGG's `volume_traded` figures are very large (e.g. ~5 billion chaos traded against Divines in Mirage's first 14 days). The prices they produce match poe.ninja, so they're reliable for relative comparisons, but don't read the absolute volume as exact until it's understood better.
- **RePoE names:** some metadata ids share or carry a wrong name (e.g. a Harbinger Delirium Orb named "Fine Delirium Orb"). Ambiguous names are kept apart (see the decision log), but an exchange item's name is only as good as RePoE's.
- **DuckDB single writer:** loads need the write lock. If one collides with a dashboard refresh, re-run it; nothing is lost.

## 9. Findings (phase 2)

Each finding is reproducible from the Analysis tab, with the leagues it rests on.

### 9.1 Mid- and low-value uniques lose most of their value over launch week

*Tool: Analysis → Unique moves. Divine prices, day 2 → day 14, High-confidence prices on both days, the six most recent challenge leagues (Affliction → Mirage).*

| Day-2 price | Median day-14 ÷ day-2 | Share that rose | Leagues where it held |
|---|---|---|---|
| chase (≥ 50 div) | ≈ 1.3–1.4× | ≈ 67% | small sample (6–16 item-leagues) |
| mid (5–50 div) | ≈ 0.27× | ≈ 26% | 6 of 6 |
| low (0.5–5 div) | ≈ 0.21× | ≈ 15% | 6 of 6 |
| cheap (< 0.5 div) | ≈ 0.69× | ≈ 26% | 6 of 6 |

- In every league, mid- and low-value uniques lost about **65–80%** of their divine price between day 2 and day 14. Starting from day 3, they still lost about 60–70%.
- It's **stronger in the exchange era:** the median was 0.18–0.22× in Settlers, Mercenaries, Keepers and Mirage, against 0.27–0.33× in Necropolis and Affliction.
- **Implication:** sell non-chase uniques as early as possible. Holding a 5–50 div unique through week one has been a reliable loss in every recent league. Chase uniques are the exception, but there are too few of them to call it yet.
- **Caveats:** daily data only (uniques aren't on the exchange); survivorship (an item needs a price on both days); and High-confidence filtering leaves out the thinnest markets.

### 9.2 Items sold for Divines fetch more than the same items sold for Chaos (preliminary)

*Tool: the Arbitrage trading page (table `cross_market_hour`). All four exchange-era leagues.*

- **How common:** in each league, 63k–86k item-hours traded in both the Chaos and the Divine market.
- **The gap:** the median price via Divines (X/Divine price × the hour's Divine rate) was **13–19% above** the direct Chaos price.
- **It survives worst-case prices.** Run the loop Chaos → item → Divines → Chaos, buying at the hour's highest Chaos price, selling at its lowest Divine price and converting at its lowest Divine rate. It still came out positive in **15–26% of item-hours** (over +2% in 14–25%). The reverse loop was positive in only about 1%, so the premium runs one way.
- **Items where it recurred in all four leagues** (share of hours positive in the worst league): Rogue's Marker (66%), Essence Scarab of Stability (47%), Tainted Jeweller's Orb (46%), Timeless Eternal and Karui Emblems (about 36%), Enkindling Orb (26%).
- **In the tool,** with a 2% buffer and a 1c price floor: the Chaos-first loop paid in 17.2% of all 297,778 cross-market item-hours, and the Divines-first loop in 0.9%. 21 items paid in at least 25% of hours in every league. Even a 50% buffer leaves 6.2% of hours paying, which is the first thing to verify in-game: an edge that size is either a real, persistent mispricing or a quirk of how GGG reports ratios.
- **Caveats before trusting it:**
  - These are hourly summaries, not an order book, so a gap within an hour doesn't prove one player could have caught both sides.
  - We haven't confirmed whether GGG's lowest/highest ratios are executed trades or listings.
  - Exchange gold fees and integer trade ratios aren't modelled, and the overlap volume on many items is small.

### 9.3 In chaos, currency and cards inflate over launch fortnight; farmed consumables deflate

*Tool: Analysis → Group timing, in Chaos. Median of each item's price ÷ its day-1 price, day 13, per league (Settlers / Mercenaries / Keepers / Mirage).*

| Group | Day 13 ÷ day 1 |
|---|---|
| Currency | 0.85 / 1.13 / 1.28 / 1.84 |
| Divination cards | 0.83 / 1.73 / 1.09 / 2.29 |
| High-tier essences | 0.79 / 0.55 / 0.49 / 1.38 |
| Scarabs | 1.37 / 0.41 / 0.65 / 0.56 |

- **Currency** inflates in chaos in three of four leagues, most in the newest (Mirage). Settlers, the exchange's first league, is the exception.
- **Divination cards** inflate in three of four leagues.
- **Essences and scarabs** mostly lose value, as expected for consumables whose supply keeps growing from farming. Mirage essences and Settlers scarabs are the exceptions.
- **In Divines,** almost everything sinks, because the Divine inflates fastest (this is why the chart briefly looked wrong, see the decision log).

---

## License

MIT. See [LICENSE](LICENSE).
