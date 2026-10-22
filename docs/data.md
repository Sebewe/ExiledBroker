# Data

Where ExiledBroker's data comes from, how it becomes rows, and the rules that decide what's kept. Decisions behind these rules are in [decisions.md](decisions.md).

- [Sources](#sources)
- [poe.ninja daily dumps](#poeninja-daily-dumps)
- [GGG hourly exchange](#ggg-hourly-exchange)
- [Live feed](#live-feed)
- [Price mappings and the core pool](#price-mappings-and-the-core-pool)
- [Divination cards](#divination-cards)
- [A new league's data](#a-new-leagues-data)
- [Scope: what's left out](#scope-whats-left-out)
- [Data model](#data-model)
- [Running the ingest](#running-the-ingest)

## Sources

| Data | Source | Granularity | Since | Status |
|---|---|---|---|---|
| Historical prices | poe.ninja dumps (`/poe1/api/data/dumps`) | daily, all priced items | 2016 (Essence) | ✔ `eb dumps` |
| Currency prices and volume | GGG currency exchange, `GET https://web.poecdn.com/api/currency-exchange[/<unix-hour>]` | **hourly**, everything on the in-game exchange | Settlers launch, 2024-07-26 20:00 UTC | ✔ `eb exchange`, `eb live` |
| Item names | [RePoE](https://github.com/repoe-fork/repoe) | — | — | ✔ |
| Card tiers | NeverSink's loot filter (what FilterBlade serves) | — | — | ✔ |
| Live prices with listing counts | poe.ninja overview endpoints (~15 min refresh) | now only | — | ⬜ planned (phase 6) |
| Patch notes | pathofexile.com forum, poewiki | per league | — | ⬜ planned (phase 3) |
| Every public listing | GGG public stash river | real time | — | not planned: needs an OAuth app and heavy processing |

**Uniques have no public sub-daily history.** The exchange doesn't carry them, so the only way to get their launch-hour prices is to record poe.ninja's live overview ourselves while the league starts. The live poller has to be running at the next launch.

**Rules of use.** Follow GGG's terms and rate limits, and never fetch the same data twice. From [poe.ninja/docs/api](https://poe.ninja/docs/api): only the economy endpoints may be used, and the builds/profiles API is off-limits to third parties. Send a descriptive User-Agent (ours names the repo), respect HTTP caching, and don't poll faster than the data refreshes (PoE1 is about every 15 minutes). A hosted app proxies through its own backend rather than calling poe.ninja from browsers. The dumps are **CC BY-SA**, so the public site credits poe.ninja.

## poe.ninja daily dumps

`ingest/poe_ninja_dumps.py` → `normalize/dump_loader.py`, `source = 'poe.ninja-dump'`.

**What a dump contains.** One zip per league, holding that league plus Standard, Hardcore and private leagues. The format is unchanged since 2016.
- `<League>.items.csv`: `League;Date;Id;Type;Name;BaseType;Variant;Links;Value;Confidence`. Daily chaos values. Confidence is Low/Medium/High, and there are **no listing counts**, so confidence is history's only liquidity signal.
- `<League>.currency.csv`: `League;Date;Get;Pay;Value;Confidence`. `Value` is how many `Pay` you give for one `Get`, quoted in both directions (Get Divine / Pay Chaos ≈ 86; the reverse ≈ 0.0117).
- `Id` is poe.ninja's item line id, **stable across leagues** (Headhunter is 607 in Settlers, Mirage and Ancestors). One visible name can map to several ids because of attributes the dump omits, so `Id` is the identity.
- Days 0–1 are thin and noisy (a Divine at 2 chaos on day 0). Down-weight them.
- Sizes vary: Mirage is 55 MB zipped and 4.8M softcore item rows (11 MB Parquet); Settlers is 106 MB and 8.7M rows. All ~30 challenge leagues are about 1 GB of zips.

**Extraction** keeps only each challenge league's softcore files. Fields aren't quoted, so a name with a line break (Necropolis coffins) spills over several lines. Rows that don't start with the league name or have the wrong field count are dropped and counted in `*.dropped.json` (Necropolis: 1,422 lines). Rows with no name (15 Sanctum relics in Ancestor) are skipped.

**Loading** (`eb dumps load`):
- **Scope:** uniques (`Unique*` types), the currency file, and currency-like types (`DivinationCard`, `Scarab`, `Essence`, `Fossil`, `Oil`, `Omen`, `Tattoo`, `Resonator`, `DeliriumOrb`). Base items, gems, cluster jewels and maps are skipped.
- **`item`:** uniques are `ninja:<Id>`, with name, category, base, variant and links (`'1-4 links'` is stored as 4, "four or fewer"). Currency-like items are `currency:<slug of name>`, the same id every source uses.
- **`price_observation`:** one row per item per day: `chaos_value`, `divine_value` (from that day's Divine midpoint), `confidence`, `day_offset`. Currency also gets `chaos_ask` / `chaos_bid`: the price is their midpoint, and the confidence is the weaker side's. Zero-value rows are dropped.
- **`ingest_load`** records each league's input fingerprint, so re-running with unchanged inputs is a no-op (`--force` rebuilds). Each league loads in one transaction. Mirage: 2,900 items and 345k daily rows in about a second.
- Raw dump rows also stay in Parquet behind the views `dump_item_price` / `dump_currency_price`, for local exploration only. The site reads real tables.

## GGG hourly exchange

`ingest/currency_exchange.py` → `normalize/exchange_loader.py`, `source = 'ggg-exchange-hourly'`.

**The API.** Each page is one hour across all leagues, with per-pair `volume_traded`, low/high stock and low/high ratio. Pages are immutable (cached for a year), roughly 770 KB raw or 45 KB gzipped. An hour is published a few minutes after it ends. Page `T` must return `next_change_id == T+3600`: a timestamp before the history starts silently returns the first page, so every page is validated. Items are named by metadata path (`Metadata/Items/Currency/CurrencyModValues` is the Divine), mapped through RePoE. GGG says old history may be removed, so pages are worth archiving.

**`eb exchange sync`** (first 14 days of a league):
1. **Find the launch.** From 12 hours before the first dump date, fetch hours until the league appears. That hour is `league.launched_at` (Mirage: 2026-03-06 20:00 UTC), and hourly `day_offset` is fractional days from it.
2. **Fetch the window**, one gzipped page per hour into `data/raw/ggg/currency_exchange/`. A running league stops at the current hour.
3. **Load incrementally.** `exchange_hour_loaded` records which hours each league has, including empty ones. A load reads only new hours, inserts them, and deletes only hours that left the window, in one transaction. A live update touches one hour (~500 rows for Allflame), not the league's ~450k. A full rebuild happens only when `LOADER_VERSION` changes or with `--force`.

**Pricing:**
- The Divine rate per hour is Chaos traded ÷ Divines traded in the Chaos/Divine market, carried forward through hours with no Divine trades (an ASOF join, which also reads rows already in the database).
- Every market an item has against Chaos or Divine contributes. `volume` is units traded; `chaos_volume` is Chaos traded plus Divines × the rate; `chaos_value = chaos_volume / volume`; `chaos_low` / `chaos_high` are the extreme traded ratios in chaos; `divine_value = chaos_value / rate`. Chaos is 1 by definition. Hours with no trades have no row.
- Before the first Chaos/Divine trade the rate is unknown, so prices in divines are null, and averages leave those hours out of the sum and the weight.

**Cross-market rows** (`cross_market_hour`): every item-hour that traded against Chaos, with the Divine leg and that same hour's Divine rate when it also traded against Divines (not carried forward, since a loop needs both trades in one hour). Loops and the Arbitrage summary use only the hours with both legs (`cross_market.BOTH_LEGS`); the Chaos-only hours keep the charts' Chaos price line unbroken (most items trade against Divines in only a minority of hours). This is the arbitrage universe, so it's stored complete.

**What's kept.** Hourly price rows are stored only for what the site reads: price-mapping items, followed cards' rewards, and Chaos and Divine (`exchange_loader._keep_used_items`). An item that joins the pool later has no earlier hours until a `--force` rebuild.

**Item names.** RePoE gives some different items the same name. An ambiguous name never merges items: each metadata id becomes `Name (MetadataName)`. Two kinds of twin don't count (`exchange_loader.ambiguous_ids`): a legacy id with no stack size (the classic fragments and breachstones each have one, e.g. `ShaperFragment1` next to the exchange's `CurrencyShaperFragment1`), and a Tencent-realm copy, which never trades on the global exchange. That frees 26 names, so the exchange's Fragment of the Phoenix is the same item as the dump's. Real ambiguities stay apart: some names are simply wrong in RePoE (a Harbinger Delirium Orb named "Fine Delirium Orb"), and the stackable and socketable Chaotic Resonators share names.

**Checks on Mirage:** 368 pages (39 MB raw), 1,027 items, 269k hourly rows. Averaged by day, the Divine rate matches the dump (86.5 vs 85.6 on day 1, 151 vs 145 on day 3), and all 269,018 hourly prices sit inside their hour's low/high range.

What hourly data shows that daily data hides: Mirage launched at 20:00 UTC. The first Divine trades came at 22:00 at **23 chaos** (range 15–28), by 03:00 it was 59, and the first 24 hours averaged 86. The daily dump says 85.6 for day 1.

**Volume scale.** GGG's `volume_traded` figures are very large (~5 billion chaos traded against Divines in Mirage's first 14 days). The prices they produce match poe.ninja, so they're fine for relative comparisons, but don't read the absolute volume as exact.

## Live feed

`eb live sync|watch` (`ingest/live.py`) keeps the running league loaded. It's what the Live market page reads, and on Railway it's the worker.

- It picks poe.ninja's current challenge league. If the launch hour isn't known it finds it by binary search over the exchange history (`find_launch`, about a dozen requests).
- It keeps two windows: the league's **first 14 days** (for the launch views) and its **last 14 days** (`--lookback-hours`, for the live view), loaded together (`Window.keep_launch_days`). For a league under two weeks old they're the same window.
- Each hour is fetched about 6 minutes after it ends (GGG publishes within about 3 in practice).
- What to fetch is decided by the database (`exchange_loader.needs_rebuild` / `loaded_hours`), not by which pages are on disk, so a worker with a wiped disk fetches only the new hour. A rebuild re-fetches the whole window, so data can't shrink.
- `eb live sync --force` rebuilds the league's rows, e.g. after the core pool gains items (new items otherwise have no hours from before they joined). It reuses pages on disk and fetches only missing ones, so don't run it on a wiped disk.
- It refuses a league that isn't trading in the latest hour, so an ended league's history can't be replaced by an empty window.
- Each update is recorded in `ingest_run` (requests, bytes, 304s, hours and rows added or removed, seconds, state or error), kept 90 days.
- **Reference data** (RePoE names, core-pool snapshots, filter tiers) lives in `reference_data` (`ingest/reference.py`). Sources are checked at most every `max_age` (RePoE weekly, pool and tiers daily; `eb exchange sync --refresh` checks now) with conditional requests, so an unchanged source answers 304 and nothing is downloaded. RePoE is stored trimmed (0.9 MB vs 3 MB).

**Tested on real API output.** `tests/test_live_pipeline.py` replays Mirage's first 30 hours exactly as GGG published them (`tests/fixtures/mirage_launch.json.gz`, rebuilt by `tests/fixtures/make_fixtures.py`). After each hour it runs the real live update and calls every endpoint, and it checks that an update interrupted mid-hour resumes cleanly. Mirage's launch hour was published with no trades in it, which the pages show as "waiting for the first trades".

## Price mappings and the core pool

`tracked_item` groups items for the Launch market page. Rules are in `normalize/tracked.py` and apply to every source. They're rebuilt after every load by `normalize/mappings.refresh_mappings`.

| Group | Items | In Mirage |
|---|---|---|
| Currency (mirrors, catalysts, fragments and oils included) | poe.ninja's current-league Currency list (99 names, Catalysts included), plus its Fragment (68) and Oil (16) lists: 183 names, all traded on the exchange | 177 |
| High-tier essences | all Deafening, plus Hysteria, Insanity, Horror, Delirium, if in the current Essence list | 23 |
| Scarabs | every "… Scarab …" in the current Scarab list | 111 |
| Divination cards | cards NeverSink's filter shows (361) | 358 with hourly prices |

**The core drop pool** (`ingest/core_pool.py`): only items still in the current drop pool are shown. The pool is poe.ninja's *current-league* exchange lists (`type=Currency/Fragment/Oil/Essence/Scarab`, mapped to groups by `core_pool.SOURCES`), one snapshot per list in `reference_data` (`core_pool/type/<Type>`), **replaced, never merged**. A group is decided by the pool only once all its lists are stored, so items whose league mechanic didn't go core drop out. Overrides go in the committed `config/core_pool.toml`: `exclude` hides a name everywhere, `[include]` forces a name into one group. Example: Deafening Essence of Doubt traded in Mirage but isn't in the current list, so it's hidden.

Launch market numbers, Mirage day 1 → day 14: Divine 86 → 266 chaos (+208%), Mirror of Kalandra 84 → 678 divines (+710%), Mirror Shard 9.7 → 34 divines, Deafening Essence of Scorn 2.5 → 22.7 chaos.

## Divination cards

The `divination_card` table (`ingest/loot_filter.py`, `normalize/divination.py`).

- **Which cards.** NeverSink's filter lists every card in a tier block (`$type->divination $tier->t1` … `t5`). At Semi-Strict (`EB_LOOT_FILTER_STRICTNESS`), tiers t1–t4 (incl. t4c, t5c) are shown and t5 hidden: 361 shown, 93 hidden, identical up to Strict. A card the filter doesn't tier yet isn't followed.
- **What a set gives**, from RePoE's `properties.description` / `stack_size`. Followed cards: 67 currency, 5 card, 180 unique, 41 normal, 26 gem, 20 magic and 18 rare rewards, plus 4 disabled. A reward is *fixed* if it names exactly one item (`<currencyitem>{10x Exalted Orb}`) and *random* if it's generic (`5x Currency`, `Divination Card`). Only fixed currency/card rewards get a `reward_item_id`.
- **Turn-in margin** (`services/divination.py`), for each hour both the card and its reward traded: set cost = set size × card price, reward value = quantity × reward price, margin = reward − cost. Gold fees and the time to collect a set aren't included. Summaries use the **median hour**, because thin card markets have junk hours (The Hoarder averaged 570c a set in Mirage against a typical hour of about 1c).
- **Mirage, first 14 days:** 57 fixed turn-ins priced, 28 profitable in 90%+ of hours. Preferring cheap sets, The Heroic Shot scores highest (a set costs ~0.7c and roughly doubles, profitable 95% of hours, ~44k sets traded). Preferring big sets puts steady large-capital flips on top, e.g. The Nurse (~2,100c a set, +6.7%, profitable every hour) and The Sephirot.
- **Next: expected value.** Random rewards need an EV over what they can roll; unique rewards need unique prices. A card trading below its reward's EV is then an arbitrage target.

## A new league's data

The upcoming league is what the tool is for, and its data starts empty.

- **Before launch** it isn't in poe.ninja's dumps. Register it with `eb exchange sync -l "<Name>" --start <launch date>`: the league row is created right away (`exchange_tracked`), and later runs remember the date. The site shows "waiting for the first hour of trades".
- **First hours:** each exchange hour is published only after it ends, so prices appear about an hour in. Many items don't trade for hours, and there's no Divine rate until the first Chaos/Divine trade.
- **Each update** adds newly published hours and drops hours that left the window, in one transaction.
- **Every page and endpoint** must handle no data (the API answers 503), one hour, untraded items, gappy days, a stale feed and a single loaded league. Day comparisons ("vs. day 1") appear only once there are two days. Controls whose range depends on the data are hidden when there's only one option. These states are covered by `tests/test_api.py`, the replay in `tests/test_live_pipeline.py` and the frontend's Vitest tests.

## Scope: what's left out

- **Event and Ruthless leagues** are excluded from data and analysis; every command defaults to `kind = challenge` (`--kind` / `-l` can still pick one). Leagues are tagged `challenge` (the 3–4 month leagues), `event` (a few weeks, nested inside another league's window, e.g. Phrecia) or `ruthless`. Why, from Ancestors (an event league, since deleted): about half as many items were priced as in Mirage, whole categories were missing, day-1 Divine buy and sell quotes were 46% apart (Mirage: 1–3%), and Mageblood fell 18.1k → 8.6k chaos over the first week while in Mirage it rose 7.8k → 33k.
- **Base items, gems, cluster jewels and maps** aren't loaded.
- **Past leagues aren't hosted.** The site launches with the running league only; history stays local for research.

## Data model

```
League(id, game, name, version, start_at, end_at, mechanic, kind, dump_name, launched_at, exchange_tracked)
Item(id, canonical_name, category, base_type, variant, links, ninja_id, metadata_id)
PriceObservation(item_id, league_id, observed_at, day_offset,
                 chaos_value, divine_value, listing_count, source,
                 confidence, chaos_ask, chaos_bid,               -- daily dumps
                 volume, chaos_volume, chaos_low, chaos_high)    -- hourly exchange
CrossMarketHour(league_id, item_id, observed_at, day_offset,
                chaos_price, chaos_volume, chaos_low, chaos_high,       -- X/Chaos market
                divine_price, divine_volume, divine_low, divine_high,   -- X/Divine market
                divine_rate, divine_rate_low, divine_rate_high)         -- same hour
TrackedItem(item_id, group_id, group_label, sort_order)   -- currency | essence | scarab | divination
DivinationCard(item_id, name, stack_size, reward_kind, reward_name, reward_quantity,
               reward_item_id, reward_fixed, reward_text, filter_tier, followed)
ExchangeHourLoaded, IngestLoad, IngestRun, ReferenceData       -- load bookkeeping
```

The key design choice is **`day_offset`**: every price is stored relative to its league's start, so Settlers' day 3 and Mirage's day 3 compare directly. The `game` column on leagues and items leaves room for PoE2. Planned tables (patch notes, aliases, predictions) are in [roadmap.md](roadmap.md#planned-data-model).

`storage/schema.sql` runs on both DuckDB and Postgres. `price_observation` costs about 150 bytes a row in DuckDB, mostly the text primary key (Mirage: 614k rows, 96 MB).

## Running the ingest

Every step is resumable: Ctrl-C and re-run continues. Downloads resume with HTTP Range + If-Range, outputs are written to a temp name and renamed when complete (a finished file is its own completion marker), and loads are one transaction per league.

```bash
.venv/bin/eb dumps list                 # available dumps and local state
.venv/bin/eb dumps sync && .venv/bin/eb dumps load
.venv/bin/eb exchange sync [-l Mirage]  # hourly exchange, first 14 days per league
.venv/bin/eb exchange status
.venv/bin/eb live sync|watch            # running league
```

`scripts/ingest.sh` runs them unattended:

```bash
scripts/ingest.sh                      # hourly exchange for every challenge league since Settlers
scripts/ingest.sh exchange -l Mirage   # any `eb exchange sync` options work
scripts/ingest.sh dumps                # daily dumps: download, extract, load
scripts/ingest.sh all                  # both
scripts/ingest.sh live                 # live feed, runs until stopped

nohup scripts/ingest.sh all >/dev/null 2>&1 &    # in the background
tail -f data/logs/latest.log
```

- A background run ignores Ctrl-C; stop it with `pkill -f "eb "`, which is safe at any point.
- On macOS it keeps the machine awake (`caffeinate`). Each run logs to `data/logs/ingest-<time>.log`.
- Cost: the hourly exchange for the four exchange-era leagues is ~1.5k requests (~30 min, ~150 MB on disk).
- DuckDB allows one writer, so a load can briefly lock out a local `eb serve` reading the same file. Retry; nothing is lost.
