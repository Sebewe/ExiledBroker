# ExiledBroker

A Path of Exile market speculation tool. It uses historical price data and the new patch notes to predict how prices move during a league start.

> **Data credit:** historical and live economy data comes from [poe.ninja](https://poe.ninja), whose economy dumps are published under [CC BY-SA](https://creativecommons.org/licenses/by-sa/3.0/). Thank you to poe.ninja for making this data available to the community. Hourly currency-exchange history comes from Grinding Gear Games' public API. ExiledBroker is not affiliated with or endorsed by Grinding Gear Games or poe.ninja.

> **Living document.** This README tracks the project's design and progress. Update the [Status](#status) section and the relevant design sections as things are built or decisions change.

---

## Status

| Phase | Goal | Deliverable | State |
|---|---|---|---|
| 0 | Scaffolding | Package, CLI, DuckDB schema, config, service layer, Streamlit demo + API skeleton | ✅ Done |
| 1 | Historical ingest | poe.ninja dumps → Parquet, league calendar | 🟨 Code done and tested on Mirage + Settlers; full local sync pending |
| 2 | Exploration | Notebooks: recurring launch-week patterns by category | ⬜ Not started |
| 3 | Patch corpus | Scraper, extractor, review tool for past leagues | ⬜ Not started |
| 4 | Baseline + backtest | First honest accuracy numbers | ⬜ Not started |
| 5 | Signals | Ranked list: "farm X", "buy Y on day 2, sell day 6" | ⬜ Not started |
| 6 | Live mode | Hourly ingest at launch, alerts when prices drift from prediction | ⬜ Not started |
| 7 | UI | Streamlit demo (local) → hosted public frontend on the JSON API | ⬜ Not started |

Legend: ⬜ Not started · 🟨 In progress · ✅ Done

Phases 1–2 alone are useful: knowing which categories reliably spike in the first week is already an edge.

### Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev,demo]'
.venv/bin/eb init-db      # create data/exiledbroker.duckdb with the schema
.venv/bin/eb dumps list   # available poe.ninja league dumps and local state
.venv/bin/eb dumps sync   # download + extract + load all challenge leagues (resumable)
.venv/bin/streamlit run app/dashboard.py   # local demo
.venv/bin/eb serve        # API at http://127.0.0.1:8000/api/health (for hosting later)
.venv/bin/pytest          # tests
```

Settings come from `EB_*` environment variables or a `.env` file (see `src/exiledbroker/config.py`).

### Phase 1 next steps

- Run `eb dumps sync` locally to fetch every challenge league. Add `--hardcore` to also keep the hardcore twins, `--since 2020` to limit by year, `-l Mirage` for one league, or `--kind all` to include Ruthless and event leagues.
- Add the upcoming league to the calendar once its name and start time are announced. It won't be in the dumps.
- Map dump rows onto `item` / `price_observation`. This needs item identity across leagues (`ItemAlias`) and a decision on how to read currency `Get`/`Pay` pairs (see §2.1).

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
| 2026-10-21 | League kinds: **challenge** = the main 3–4 month leagues (Settlers, Mirage, ...). **event** = short leagues of a few weeks (Ancestors, Phrecia) with far fewer players and a very different market. **ruthless** = Ruthless variants. Models must never mix event curves into challenge-league baselines without an explicit flag. |
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
| poe.ninja dumps | daily | all priced items + currency | 2016 (Essence) | What we have now. |
| **GGG Currency Exchange API** `GET https://web.poecdn.com/api/currency-exchange[/<unix-hour>]` | **hourly** | everything tradeable on the in-game exchange (currency, fragments, scarabs, essences, tattoos, omens, ...) | **Settlers launch, 2024-07-26 21:00 UTC** | Public, no auth. Each page is one hour across all leagues: per pair, `volume_traded`, low/high stock and low/high ratio. Pages are immutable (cached for a year), so each is fetched once. Items are named by metadata path (`Metadata/Items/Currency/CurrencyModValues` = Divine), so they need a name mapping. Roughly 770 KB per hour raw, ~45 KB gzipped. GGG says old history may be removed later, so it's worth archiving. |
| poe.ninja live overview API | ~15 min refresh | all poe.ninja categories, with listing counts | now only | No history. **For uniques, gems and bases, the only way to get sub-daily launch data is to record it ourselves**, so the live poller should be running at the upcoming launch. |
| GGG public stash river | real time | every public listing | now only | Needs a registered OAuth app and heavy processing. Not worth it for the demo. |

Example: in Ancestors' first full hour (2026-06-26 02:00 UTC) the exchange shows Divines trading between **26 and 38 chaos**, with 859 chaos ↔ 27 Divines changing hands (≈31.8 chaos/div volume-weighted). The daily dump only says ~75 chaos for day 1.

**Plan:** add an hourly exchange ingest (resumable, one gzipped JSON per hour) targeted at the first ~14 days of each league since Settlers. That's ~7 leagues × 336 hours ≈ 2.4k requests, about 45 minutes at one request per second. Then start the live poller before the next launch to capture items.

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
│   │   ├── currency_exchange.py # GGG hourly exchange digests (next)
│   │   ├── poe_ninja_live.py   # live economy overview (phase 6)
│   │   ├── patch_notes.py      # scrape raw text → store
│   │   └── item_meta.py        # RePoE
│   ├── storage/
│   │   ├── db.py               # ✔ DuckDB connection (read-only for the API), query helpers
│   │   ├── dumps.py            # ✔ league upsert + Parquet views
│   │   └── schema.sql          # ✔
│   ├── normalize/
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
│   ├── services/               # ✔ read-side queries shared by the demo and the API (overview, prices)
│   ├── api/app.py              # ✔ FastAPI, read-only (/api/health, /api/overview, /api/leagues, item curve)
│   └── cli.py                  # ✔ `eb init-db`, `eb serve`, `eb dumps list|sync` (extract/predict to come)
├── app/dashboard.py            # ✔ Streamlit demo: league calendar + league-start price curves
├── web/                        # hosted public frontend (later; framework TBD)
├── data/                       # ✔ gitignored; raw/poe_ninja/dumps (zips), processed/poe_ninja/dumps/{items,currency}/*.parquet
├── notebooks/                  # exploration
└── tests/                      # ✔
```

**Stack:** `httpx`, `polars`, DuckDB with Parquet, `pydantic`, `typer`, Streamlit (demo), FastAPI + uvicorn (hosted API), and `scikit-learn`/LightGBM later. DuckDB suits this well: a single file, fast queries over time series, and no server to run.

## 5. Core data model

```
League(id, game, name, version, start_at, end_at, mechanic, kind, dump_name)
Item(id, canonical_name, category, base_type, variant, links, gem_level, corrupted, ...)
ItemAlias(alias, item_id, valid_from_league)     -- handles renames/reworks
PriceObservation(item_id, league_id, observed_at, day_offset,
                 chaos_value, divine_value, listing_count, source)
PatchNote(id, league_id, version, published_at, url, raw_text)
PatchChange(id, patch_note_id, section, raw_line,
            entity_type,   -- skill_gem | unique | mechanic | currency | drop_rate | crafting ...
            entity_ref, change_type, direction (+/-), magnitude (0-3),
            confidence, extracted_by, reviewed)
PatchChangeItem(patch_change_id, item_id, relation)  -- direct | ingredient | build_dependency
Prediction(run_id, league_id, item_id, horizon_day, p10, p50, p90, rationale)
```

Until `price_observation` is populated, history is read through the `dump_item_price` / `dump_currency_price` views. These are the raw dump columns plus `league_id`, `hardcore` and `day_offset`.

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
- **DuckDB single writer:** `eb dumps sync` needs a write lock for a moment at the end. If it collides with a dashboard refresh, re-run it; nothing is lost.

---

## License

MIT. See [LICENSE](LICENSE).
