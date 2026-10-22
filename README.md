# ExiledBroker

A Path of Exile market speculation tool. It uses historical price data and the new patch notes to predict how prices move during a league start.

> **Data credit:** daily economy history comes from [poe.ninja](https://poe.ninja), whose economy dumps are published under [CC BY-SA](https://creativecommons.org/licenses/by-sa/3.0/). Thank you to poe.ninja for making this data available to the community. Hourly currency-exchange history comes from Grinding Gear Games' public API, and item names from [RePoE](https://github.com/repoe-fork/repoe). ExiledBroker is not affiliated with or endorsed by Grinding Gear Games or poe.ninja.

> **Living document.** This README tracks the project's design and progress. Update the [Status](#status) section and the relevant design sections as things are built or decisions change.

---

## Status

| Phase | Goal | Deliverable | State |
|---|---|---|---|
| 0 | Scaffolding | Package, CLI, DuckDB schema, config, service layer, Streamlit demo + API skeleton | ✅ Done |
| 1 | Historical ingest | Daily poe.ninja dumps + hourly GGG exchange → `item` / `price_observation`, league calendar, price mappings | 🟨 Both pipelines done. Mirage loaded (daily, plus hourly for the first 14 days). Other challenge leagues: run `scripts/ingest.sh` |
| 2 | Exploration | Notebooks: recurring launch-week patterns by category | ⬜ Not started |
| 3 | Patch corpus | Scraper, extractor, review tool for past leagues | ⬜ Not started |
| 4 | Baseline + backtest | First honest accuracy numbers | ⬜ Not started |
| 5 | Signals | Ranked list: "farm X", "buy Y on day 2, sell day 6" | ⬜ Not started |
| 6 | Live mode | Hourly ingest at launch, alerts when prices drift from prediction | ⬜ Not started |
| 7 | UI | Streamlit demo (local) → hosted public frontend on the JSON API | 🟨 Streamlit demo: Mirage launch market for the tracked groups |

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

# In the background, then check on it whenever:
nohup scripts/ingest.sh all >/dev/null 2>&1 &
tail -f data/logs/latest.log
```

- **Stop it any time** (Ctrl-C, closing the terminal, sleep, a crash) and run the same command again to continue. Hourly pages, zips and Parquet files are written to a temporary name and renamed when complete. Database loads are one transaction per league. Nothing that's finished is fetched or rewritten again.
- On macOS it keeps the machine awake (`caffeinate`) while running. Each run logs to `data/logs/ingest-<time>.log`, and `latest.log` points at the newest.
- Rough cost: the hourly exchange for the four challenge leagues since Settlers is ~1.5k requests (~30 min, ~150 MB on disk). The daily dumps for all ~30 challenge leagues are about 1 GB of zips.
- While a run is loading, the demo may briefly fail to open the database (DuckDB allows one writer). Refresh the page.

### Phase 1 next steps

- Run `scripts/ingest.sh all` to fill in the other challenge leagues.
- Add the upcoming league to the calendar once its name and start time are announced. It won't be in the dumps.
- Live recording at launch (phase 6): uniques have no sub-daily history anywhere public, so the poe.ninja live poller must be running when the next league starts (§2.2).

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
| 2026-10-21 | **Price mappings** (`tracked_item`): Chaos, Divine, Orb of Alchemy, Mirror of Kalandra + Mirror Shard, high-tier essences (all Deafening, plus Hysteria/Insanity/Horror/Delirium), and scarabs. Groups are name rules in `normalize/tracked.py`, so they apply to every source. |
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

- **Scope:** currency and uniques only (`Unique*` item types, the currency file, and currency-like item types such as `Scarab`, `Essence`, `Fossil`, `Oil`, `Omen`, `Tattoo`, `Resonator`, `DeliriumOrb`). Base items, gems, cluster jewels and maps are skipped.
- **`item`**: uniques are one row per poe.ninja `Id` (`ninja:<Id>`) with name, category (`UniqueArmour`, ...), base, variant and links (`'1-4 links'` is stored as 4, meaning "four or fewer"). Currency-like items are `currency:<slug of name>` with category `currency`, `scarab`, `essence`, ... (The `gem_*` columns from earlier are unused now.)
- **`price_observation`**: one row per item per day. `chaos_value`, `divine_value`, `confidence`, `day_offset` and, for currency, `chaos_ask` / `chaos_bid`. `source = 'poe.ninja-dump'`, and `listing_count` is empty because the dumps don't have it. Zero-value rows are dropped.
- **`ingest_load`**: what was loaded per league, with an input fingerprint. Each league loads in a single transaction, so an interrupted load leaves it untouched, and re-running with the same inputs is a no-op. Use `--force` to rebuild.
- Sizes: Mirage is 2,900 items and 345k daily rows, loaded in about a second.

### 2.4 Hourly exchange pipeline (`eb exchange sync`)

1. **Find the launch.** Starting 12 hours before the league's first dump date, fetch hourly pages until the league first appears. That hour is `league.launched_at`.
2. **Fetch the window** (default 14 days after launch): one page per hour, gzipped to `data/raw/ggg/currency_exchange/<unix-hour>.json.gz`. Each page is checked against the hour requested, because a timestamp before the history starts silently returns the first page. If the league is still running, the fetch stops at the current hour.
3. **Extract:** flatten that league's markets to `data/processed/ggg/currency_exchange/<league>.parquet`, one row per market per hour with volume, stock and ratio for both sides. It's rebuilt only when the set of hours changes. This file keeps every pair, for the arbitrage add-on later.
4. **Load** into `price_observation` with `source = 'ggg-exchange-hourly'`, in one transaction per league:
   - Divine rate per hour = Chaos traded ÷ Divines traded in the Chaos/Divine market, carried forward through hours with no Divine trades.
   - For each item and hour, every market against Chaos or Divine contributes. `volume` = units of the item traded. `chaos_volume` = Chaos traded, plus Divines traded × the Divine rate. `chaos_value` = chaos_volume ÷ volume. `chaos_low` / `chaos_high` = the lowest and highest traded ratio, in chaos. `divine_value` = chaos_value ÷ Divine rate.
   - Hours with no trades for an item have no row. Chaos is 1 by definition.
   - Names come from RePoE (`data/raw/repoe/base_items.min.json`, fetched once).
5. **Checks on Mirage:** averaged by day, the hourly Divine rate matches the daily dump (86.5 vs 85.6 on day 1, 151 vs 145 on day 3), and all 269,018 hourly prices sit inside their hour's low/high range.

Mirage, first 14 days: 368 pages (39 MB raw), 1,027 items, 269k hourly rows.

### 2.5 Price mappings (`tracked_item`)

| Group | Items | Mirage hourly rows |
|---|---|---|
| Chaos Orb | 1 | 334 |
| Divine Orb | 1 | 334 |
| Orb of Alchemy | 1 | 335 |
| Mirrors | Mirror of Kalandra, Mirror Shard | 630 |
| High-tier essences | 20 Deafening + Hysteria, Insanity, Horror, Delirium | 7,900 |
| Scarabs | every item named "… Scarab …" (111 traded in Mirage) | 35,987 |

From day 1 to day 14 in Mirage: Divine 86 → 266 chaos (+208%), Mirror of Kalandra 84 → 678 divines (+710%), Mirror Shard 9.7 → 34 divines, Deafening Essence of Scorn 2.5 → 22.7 chaos.

### 2.6 Why event leagues are excluded

We looked at Ancestors (an event league, 21 days) before dropping event leagues. Its data has since been deleted:
- About 45–60% as many items were priced as in Mirage, and whole categories (scarabs, essences, divination cards, ...) were missing.
- Currency quotes were noisy: on day 1 the Divine buy and sell prices were 46% apart, while Mirage's stayed within 1–3% for the first week.
- Chase uniques moved the opposite way from a normal league: Mageblood fell 18.1k → 8.6k chaos over the first week, while in Mirage it rose 7.8k → 33k.


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
│   │   ├── currency_exchange.py # ✔ GGG hourly exchange: find launch, fetch window, → Parquet
│   │   ├── item_names.py       # ✔ RePoE metadata id → name
│   │   ├── poe_ninja_live.py   # live economy overview (phase 6)
│   │   └── patch_notes.py      # scrape raw text → store
│   ├── storage/
│   │   ├── db.py               # ✔ DuckDB connection (read-only for the API), query helpers
│   │   ├── dumps.py            # ✔ league upsert + Parquet views
│   │   └── schema.sql          # ✔
│   ├── normalize/
│   │   ├── dump_loader.py      # ✔ dump Parquet → item / price_observation (currency + uniques)
│   │   ├── exchange_loader.py  # ✔ exchange Parquet → hourly prices (one transaction per league)
│   │   ├── tracked.py          # ✔ price mapping groups (name rules)
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
│   ├── services/               # ✔ read-side queries shared by the demo and the API (overview, prices, market)
│   ├── api/app.py              # ✔ FastAPI, read-only (/api/leagues, /api/market/<league>/groups/<group>, /api/market/<league>/hourly, ...)
│   └── cli.py                  # ✔ `eb dumps list|sync|load`, `eb exchange sync|status`, `eb serve`, `eb init-db`
├── app/
│   ├── dashboard.py            # ✔ Streamlit entry point (navigation, credit)
│   ├── common.py               # ✔ cached loaders + formatting
│   └── app_pages/              # ✔ market.py (launch market for the price mappings), data.py (loads, calendar, refresh)
├── .streamlit/config.toml      # ✔ demo theme
├── scripts/ingest.sh           # ✔ unattended, resumable ingest runner
├── web/                        # hosted public frontend (later; framework TBD)
├── data/                       # ✔ gitignored: raw/{poe_ninja/dumps, ggg/currency_exchange, repoe}, processed/{poe_ninja/dumps, ggg/currency_exchange}, logs/, exiledbroker.duckdb
├── notebooks/                  # exploration
└── tests/                      # ✔
```

**Stack:** `httpx`, `polars`, DuckDB with Parquet, `pydantic`, `typer`, Streamlit (demo), FastAPI + uvicorn (hosted API), and `scikit-learn`/LightGBM later. DuckDB suits this well: a single file, fast queries over time series, and no server to run.

## 5. Core data model

```
League(id, game, name, version, start_at, end_at, mechanic, kind, dump_name, launched_at)
Item(id, canonical_name, category, base_type, variant, links, ninja_id, metadata_id)
TrackedItem(item_id, group_id, group_label, sort_order)   -- price mappings
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

---

## License

MIT. See [LICENSE](LICENSE).
