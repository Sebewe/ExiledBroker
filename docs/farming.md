# Farming page: the work plan

This plan comes from an interview with the user on 2026-10-24. It is split into workstreams so that several agents can work at once. Each workstream lists what it owns, what it waits for and when it's done. Tick items off here as they land, and record the reasoning in [decisions.md](decisions.md).

Deadline: the next league launches in about a month, in parallel with [go-live](go-live.md). If time runs short, ship in priority order: **P1** Launch outlook and Best hour to sell, **P2** mechanic trend and Easy to sell, **P3** stack impact.

## Status (2026-10-24)

**On `main`:** A (baskets, reviewed), B, C and D (findings 6–8 and their analysis modules), E (`item_day_history`, captured locally) and H (the Farming page, on a hand-written copy of the contract). The research is done and the contract below holds every finding. Nothing serves the page yet: it needs F, G and I. `main` isn't pushed past `01b826a`.

**What the research found** ([findings.md](findings.md), sections 6–8):
- **Hour of day ([finding 6](findings.md#6-hour-of-day-sell-in-the-evening-utc-in-the-first-week-buy-divines-around-noon-after-that-it-barely-matters)): real but small.** Items are dearest in the UTC evening, by about 5% on days 0–2, 2% on days 2–7 and under 1% after. Volume doubles in the evening. The one lasting effect is the Divine's own cycle: cheapest in Chaos around 12:00 UTC, 4–8% below its evening price in the launch fortnight. A few baskets (Essence, Eldritch altars, Legion) have stronger patterns of their own. B recommends a sentence on the page, not a chart.
- **Stack impact ([finding 7](findings.md#7-stack-impact-cant-be-measured-from-hourly-data-show-a-stack-as-hours-of-the-markets-trading-and-dont-load-the-stock-fields)): no percentage can be measured.** Hourly prices bounce more than a stack moves them, and volumes are unsigned. So the page shows a stack as hours of the market's trading, banded at ¼ h and 1 h, Chaos market first. The order-book stock fields add nothing and aren't loaded.
- **Mechanics ([finding 8](findings.md#8-mechanics-each-has-its-own-launch-path-but-leagues-shift-it-the-launch-outlook-carries-over-easy-to-sell-is-stable)):**
  - Each mechanic has its own launch path: it beats a pooled path and "no change", walk-forward. But leagues shift it by about ±60%, so `usual` comes with past leagues' range and stops at day 13.
  - Being above usual lasts (0.9 three days on) without predicting the next move: it means farm it now, not hold.
  - The launch premium carries over: ranking correlation 0.80 / 0.72 / 0.58 for day 1 / days 2–4 / days 5–10. Expedition, Essence, Beyond and Legion drops are worth 2–5× their settled price on day 1; Delirium, Heist and Betrayal drops are cheapest at launch.
  - Easy to sell is stable from league to league (0.86).
- **Data (E):** the page reads `cross_market_hour`, which holds every traded item, so the keep rule and loader don't change and no rebuild is needed. Past leagues come from `item_day_history`: 46,679 rows, about 10 MB on Postgres. It was captured on the 23-mechanic baskets: the dropped mechanics' rows are never read, and `eb farming history` trims them.

**What still needs doing, in order:**
1. **F, services** (`services/farming.py`), the critical path. Build every contract field from the definitions already in code, not new ones:
   - `item_history.history` for past leagues and `item_history.league_days` for the live league.
   - `analysis/mechanics`: `index`, `usual`, `premiums` / `outlook`, `liquidity` / `easy_to_sell`, `score`, `window_at`.
   - `hours.report` and C's `impact` constant, shipped as a locally built report with a `stamp`, like `backtest_report`.
   - Then Postgres parity, `LIVE_QUERIES` and read budgets.
2. **G, API:** `/api/farming/{league}`, warmed for each trading league; regenerate `openapi.json` and `schema.d.ts`.
3. **H, follow-ups: done (2026-10-24, `farm-h3`).** The sell helper shows hours of trading in `impact.bands`, best hours are a sentence plus the Divine tip, and the page uses the generated types. Checked end to end against `eb serve` on a copy of the research database (Allflame on day 90, Mirage on day 14).
4. **I, pipeline, seed and backup:**
   - The pass calls `item_history.refresh` beside `launch_picks.refresh`.
   - `eb site seed` and the backup copy `item_day_history`: about 10 MB once, then ~2 MB a league.
   - A league switch keeps it.
   - Rerun both replays and update the simulation's bill.
5. **J, docs:** README, decisions, data.md (`item_day_history`), hosting.md.

**Open questions for the user:**
- `main` is ahead of `origin/main`: push when ready.

## What we're building, and why

The site so far serves traders. This page serves **farmers**, players who mostly play and want to turn their drops into currency well. It answers three questions:

1. **What to farm.** About 15–20 mechanics (Delirium, Essence, Expedition, Legion…), each a curated basket of what it drops, ranked on three signals:
   - **Trend vs usual path:** is the basket's price index above or below where that mechanic usually sits at this point in a league?
   - **Launch outlook** (pre-league and launch week): which mechanics' outputs paid most in week 1 of past leagues, and on which days (day 1, days 2–4, days 5–10, as the Launch picks).
   - **Easy to sell:** baskets whose outputs trade thinly are ranked down, since a farmer can't turn them into currency.
2. **When to sell:** price and volume by hour of day (UTC, shown in the visitor's local time).
3. **Dumping a stack:** the expected price drop from selling *Q* units now, in the Chaos market and in the Divine market, and which of the two takes it better.

Settled in the interview:
- **Uniques are out.** They aren't target-farmed, and an existing tool already covers boss profit.
- **Mechanics, not atlas strategies.** Strategies are defined at the mechanic level only.
- **Baskets are curated by hand** in a committed config: an agent drafts it, the user reviews it.
- **The bar is "informative".** Descriptive numbers ship even if they don't produce trades. When an effect is too small to matter, the page says so ("time of day barely matters for this").
- **It's a new Farming page.** Its place in the planned live/historical split is undecided.

Out of scope here: drop rates and yields per map (we have prices, not drop rates), sell-or-hold forecasts per item, alerts and portfolio tools.

## Rules for every agent

These restate [CLAUDE.md](../CLAUDE.md); read it first.

- **No new requests to GGG.** Everything from GGG comes from data we already have: pages on disk, the DuckDB file and reference data. If a workstream seems to need a GGG fetch, stop and ask the user. **poe.ninja is fine to fetch** (the user, 2026-10-24). Still go through `PoliteClient`, conditionally where possible, and say how many requests were made.
- **No Supabase.** Use only local databases, plus a throwaway Postgres container for `EB_TEST_POSTGRES_URL`.
- **Work in your own worktree and branch:** `git worktree add ../eb-farm-<letter> -b farm-<letter>`. Commit only the files your workstream owns (the ownership table is below). Merging back into `main` is done by the user or the coordinating session.
- **Research reads a copy of the data.** The user runs `eb live watch` against the main checkout's `data/exiledbroker.duckdb`, and DuckDB allows only one writer. Copy the file into your scratchpad and open the copy (`EB_DATA_DIR` pointing at a scratch folder, or `duckdb.connect(path, read_only=True)` on the copy). Raw pages under the main checkout's `data/raw/ggg/currency_exchange/` may be read in place, never written. Worktrees have no `data/` of their own.
- **Leave rebuilds of the real database to workstream E,** which runs one rebuild at the end, with the user.
- **The site's rules:**
  - SQL in `services/` must run on Postgres too.
  - Aggregate in SQL, never in Python over raw hourly rows.
  - The page reads only precomputed views.
  - Every colour comes from a token.
  - Every page handles no data, one hour, partial days and a single league.

## Data we have, and the gaps

| Need | Where it is | Gap |
|---|---|---|
| Hourly price, volume and low/high per market | `cross_market_hour` (Chaos leg + Divine leg, every item that traded against Chaos); `price_observation` (`source = 'ggg-exchange-hourly'`, kept items only) | `cross_market_hour` is complete. `price_observation` keeps only price-mapping items, card rewards, Chaos and Divine (`exchange_loader._keep_used_items`). Fossils, resonators, Delirium orbs etc. may be missing. Workstream E measures this. |
| Order-book depth | Raw pages: `low_stock` / `high_stock` per pair | **Not loaded.** C decides whether it's worth loading. |
| Past leagues' launch paths | Local DuckDB: Settlers, Mercenaries, Keepers, Mirage and Allflame (first 14 days each) | Hosted, only `launch_history` survives: window medians per item in Divines, not daily paths. Mechanic curves need a new reduced table (E). |
| Item names, the core pool | `item`, `tracked_item`, `reference_data`, `config/core_pool.toml` | — |

Scale note: GGG's `volume_traded` is right in relative terms but not exact in absolute terms ([data.md](data.md#ggg-hourly-exchange)). Impact estimates must be calibrated on relative quantities (C).

## The response contract (fixed first, so F, G and H work in parallel)

There's one new endpoint, **`GET /api/farming/{league}`**, precomputed each hour for every trading league, like `/api/missed/{league}`. It takes no other arguments. Prices are in Chaos only, and the browser converts them with `divine_chaos` from `/api/status`. A field is null whenever its data isn't there yet.

```jsonc
{
  "league": "Allflame",
  "latest_hour": "2026-10-24T09:00:00Z",   // null before the first trades
  "day_offset": 91.4,                       // null before launch
  "phase": "pre_launch",                    // pre_launch | launch (day_offset < 14) | later
  "mechanics": [{                           // empty in pre_launch; finding 8 fixes every field
    "id": "essence", "name": "Essence", "items": 64, "priced_items": 60,
    "index": 0.31,                 // in Divines: geometric mean over the basket's items (≥ 3, each with
                                   // ≥ 6 hours on day 0) of their median price over the last 24 h ÷ their
                                   // day-0 median; null with fewer than 3 items
    "usual": 0.28,                 // past leagues' index on day floor(day_offset): recency-weighted
                                   // geometric mean (half-life 2), ≥ 2 past leagues; null after day 13
    "usual_low": 0.24, "usual_high": 0.32,   // past leagues' min and max ("their range", not a forecast)
    "change_24h": 0.04, "change_7d": -0.08,  // fractional change of the index (0.04 = +4%)
    "chaos_volume_h": 18500.0,     // Chaos traded an hour across the basket, last 3 days (shown, not scored)
    "liquidity": 0.71,             // Easy to sell: rank_score among mechanics of the median item's Amihud
                                   // (0.5, lower is better), Chaos traded per item (0.25) and the mean share
                                   // of hours traded (0.25), last 3 days (past leagues' days 1–3 before then)
    "score": 0.66                  // rank_score: index ÷ usual 0.4, this window's outlook premium 0.3,
                                   // liquidity 0.3 (analysis/mechanics.SCORE_*); a factor null for every
                                   // mechanic drops out
  }],
  "outlook": [{                    // always present once any league is captured
    "id": "essence", "name": "Essence", "leagues": 5,
    // premium: the window's median Divine price over days 12–14's (settled), geometric mean over the
    // basket's items, recency-weighted over leagues; worst: the lowest league's. Above 1 = worth more then.
    "windows": { "day1": {"premium": 3.41, "worst": 3.06}, "days2_4": {…}, "days5_10": {…} }
  }],
  "items": [{                      // basket items with a recent price; sell helper inputs
    "item_id": "currency:screaming-essence-of-greed", "name": "Screaming Essence of Greed", "mechanics": ["essence"],
    "chaos": {"price": 1.4, "volume_h": 3200.0, "sigma_h": 0.031, "hours_traded": 0.92},
    "divine": {"price": 0.007, "volume_h": 40.0, "sigma_h": 0.05, "hours_traded": 0.21} // or null
  }],
  "hours": {                       // finding 6: from past leagues, for the league's phase (a constant, not live)
    "phase": "d2_7",               // d0_2 | d2_7 | d7_14 | later, from day_offset; pre_launch shows d0_2
    "leagues": 5, "days": 30,      // what the profile rests on
    // 24 values each, by UTC hour (the page shows local time): the price's fraction over
    // its centred 24-hour average, median over liquid items. null for an hour with no data.
    "price": [/* Chaos market, e.g. +0.021 at 23:00, -0.017 at 06:00 */],
    "price_divine_market": [/* the Divine market's own prices (not Chaos ÷ rate) */],
    "divine": [/* the Divine's Chaos price: dear at 23:00, cheap at 12:00 → when to convert */],
    "volume": [/* share of the day's Chaos traded; sums to 1 */] /* null on days 0–2 */,
    // effect of each profile: best hour over the average (gain) and over the worst (gap),
    // fractions; null95 = the noise floor; verdict small | worth_it (SMALL 1%, beats the
    // floor, ≥ 2 leagues). "small" → the page says time of day barely matters.
    "effect": {"gain": 0.021, "gap": 0.038, "best": 23, "worst": 6, "null95": 0.012, "verdict": "worth_it"},
    "effect_divine_market": {…}, "divine_effect": {…},
    "mechanics": {                 // only baskets whose own profile holds across leagues
      "essence": {"price": [/* 24 */], "gain": 0.092, "gap": 0.178, "best": 23, "worst": 6,
                  "null95": 0.045, "verdict": "worth_it", "stability": 0.90, "items": 42}
    }                              // a mechanic not listed uses `price`
  },
  "impact": {                      // finding 7: no calibrated percentage; a constant
    "y": null,                     // the square-root law can't be fitted on hourly data
    "bands": [0.25, 1.0],          // Q / volume_h, in hours of the market's trading: low < 0.25 ≤ medium < 1 ≤ high
    "note": "Hourly prices swing more than a stack moves them, so this shows how much of the market's trading your stack is, not a price drop."
  }
}
```

Stack impact is computed **in the browser**, per market: `hours = Q / volume_h`, banded by `impact.bands` (under a quarter of an hour sells into the market as it is; over an hour, split it and list over several hours), Chaos market first. Finding 7 replaced the earlier `impact ≈ y · sigma_h · sqrt(Q / volume_h)`: y can't be calibrated, so no percentage is shown, and `sigma_h` is only an informative typical hourly swing. The typed quantity never reaches the server, which keeps the "no free-form arguments" rule. B, C and D may change field meanings, but any change goes into this section first, in the same commit as the change.

## Workstreams

Dependencies: **A, B, C, D** start now. **E** waits for A's draft and C's verdict on stock. **F** waits for A, E and the findings, but can scaffold earlier. **G** waits for F's model; **H** waits only for the contract above. **I** comes after E and F; **J** comes last.

```
A baskets ─┬─► E data ─► F services ─► G API ─┐
B hours ───┤              ▲                   ├─► I pipeline/seed/backup ─► J docs, sim
C impact ──┤──────────────┘   H frontend ─────┘
D curves ──┘ (D can start on a provisional basket)
```

### A. Mechanic baskets (P1)
- **Owns:** `config/mechanics.toml`, `src/exiledbroker/normalize/mechanics.py`, `tests/test_mechanics.py`.
- **Do:**
  - Draft about 15–20 mechanics, each listing its outputs by exact item name. Start from the core pool (`tracked_item`, poe.ninja's lists in `reference_data`) and RePoE names, and use game knowledge.
  - Mark items that belong to several mechanics.
  - Leave out uniques and anything outside the core drop pool, unless the user includes it.
  - Write a loader that validates every name against `item` and reports unknown names; tests cover it.
- **Then:** a short list of open questions for the user ("is X Breach or Legion?"). **The user reviews the draft before E and F treat it as final.**
- **Done when:** the TOML loads, every name resolves on the five exchange-era leagues and Allflame, and the user has signed off.

**Done (2026-10-24, branch `farm-a`), reviewed by the user the same day.** `config/mechanics.toml` has 20 mechanics and 431 names, and all of them resolve (23 and 474 at review; three were dropped afterwards, see 10 below). Every output is in the core pool. The loader is `normalize/mechanics.py`, with tests in `tests/test_mechanics.py`. `eb mechanics check` reads only the local database and prints, per mechanic, how many outputs traded in each league, plus anything the core pool doesn't show.
- **Each mechanic has four lists:**
  - `outputs`: the basket.
  - `groups`: whole price-mapping groups; the divination cards are one.
  - `legacy`: outputs that left the game. They're used only for past leagues' curves, never shown.
  - `inputs`: scarabs and astrolabes, as the cost of running the mechanic. They're context, not part of the basket.
- **The mechanics:** Abyss, Betrayal, Blight, Delirium, Delve, Divination cards, Eldritch altars, Essence, Expedition, Harvest, Heist, Legion, Atlas memories, Necropolis (Allflame Embers), Ritual (vessels, splinters, omens), Runegrafts (Kalguur), Ultimatum (catalysts), Tattoos, Boss rush and Beyond (Tainted currency).
- **Built from the data, not memory.** Each item's "traded in" leagues come from `cross_market_hour`, and the mechanic often from the GGG metadata id (`HarvestBossKey`, `RitualBossFragment`, `CurrencyMavenKeyFragment`…). The user settled the rest in review.
- **Mechanics changed between leagues:**
  - **Breach:** splinters, blessings and breachstones last traded in Keepers. Mirage and Allflame have Flesh of Xesht and Hivebrain Gland instead.
  - **Gone from Allflame:** Harbinger's shards (after Keepers) and Unrelenting emblems (after Mirage).
  - **New in Allflame:** Legion's Enshrouding Crystals and Abyss's Zorath's Eyes.
  - **No Settlers history:** Atlas memories, Allflame Embers and runegrafts all started in Mercenaries. Sanctum's Volatile Vaal Orb started in Mirage.
  - **For D:** Abyss has no usual path yet. Breach's compares only loosely, via `legacy`.
- **For D:** `cross_market_hour` already holds every traded item, so D's research needs no rebuild.
- **The core pool now covers the baskets.**
  - `core_pool.SOURCES` has a `mechanics` entry: poe.ninja's AllflameEmber, Artifact, Astrolabe, DeliriumOrb, EnshroudingCrystal, Fossil, Omen, Resonator, Runegraft and Tattoo lists. That's 10 more conditional requests at each daily pool check, locally and hosted.
  - No price-mapping group reads the entry, so the other pages don't change.
  - `mechanics.in_pool` reads a stored `Name (MetadataName)` as `Name`, since poe.ninja lists items by their in-game name.
  - Fetched into a copy of the database on 2026-10-24 (17 requests to poe.ninja, none to GGG). That brought the gap from 174 outputs to 35.
  - The 35 left traded on the exchange in Allflame but are too thin for poe.ninja's lists: Screaming and some Shrieking essences, Timeless splinters, Ritual Splinter, a few runegrafts, tattoos and an ember. They're listed under `[include] mechanics` in `config/core_pool.toml`.
  - The real database picks up the new lists at its next daily pool check (`eb exchange sync`) once this branch is merged.
- **For E:** the keep rule should keep every basket output (`mechanics.output_ids`). With the pool covering them, `in_pool` says which ones the page shows.

**Decided in review (2026-10-24):**
1. **Core pool:** fetch poe.ninja's lists. poe.ninja tolerates more than GGG, so its lists are fine to fetch (still through `PoliteClient`, conditionally).
2. **Breach:** Flesh of Xesht and Hivebrain Gland.
3. **Tattoos** are their own basket, not Ritual's.
4. **Runegrafts** come from Kalguur (Kingsmarch); the Kalguuran scarabs are their inputs.
5. **Ultimatum** is the catalysts.
6. **Necropolis** and **Atlas memories** keep their names and contents.
7. **Essence** is Screaming and up, plus the four special essences.
8. **Deepwater is dropped:** a league's own mechanic joins only once it goes core.
9. **Left-out items:**
   - **Boss rush** is a new basket: pinnacle fragments (Shaper, Elder, Uber Elder, Sirus, Maven, Atziri, the Uber keys) plus the influenced exalts, Awakener's Orb and Orb of Dominance. They drop from influenced maps' bosses, or from the pinnacle bosses fought with the fragments. Inputs: the Influencing scarabs.
   - **Beyond** is new, for the Tainted currency.
   - **Sanctum** is new, for the Volatile Vaal Orb.
   - Valdo's Puzzle Box, Voidborn Reliquary Key, Reflecting Mist, Enkindling and Instilling Orbs and the Labyrinth offerings stay out: they can't be target-farmed.
   - Tainted Oil stays in Blight and Tainted Catalyst in Ultimatum, by their metadata. Move them to Beyond if they drop there.
10. **Dropped after review (2026-10-24):** these were also the three mechanics with fewer than the 3 current outputs an index needs (finding 8). The reasons are noted in `config/mechanics.toml`'s header.
    - **Harbinger:** no longer in the game. Fracturing Orbs are core drops that can't be target-farmed.
    - **Breach:** its currency comes from glands that aren't listed on trade, and their rewards vary widely.
    - **Sanctum:** a separate strategy that mostly yields raw currency. The Volatile Vaal Orb is a rare extra, and there's no data on the rest.

### B. Finding 6: hour of day (P1, research)
- **Owns:** `src/exiledbroker/analysis/hours.py`, `tests/test_hours.py`, section 6 of `findings.md`.
- **Do:**
  - For each league, take each item-hour's log price minus the mean log price of its UTC day. Group by UTC hour, by mechanic basket (provisional from A) and pooled. Do the same for volume share.
  - Bootstrap across days for intervals.
  - Check whether the pattern holds across leagues and in launch week versus later.
  - Look at the day of week only as a side note.
- **Decide:**
  - Per item, per mechanic or pooled: what's stable enough to show?
  - Where the "small" line falls. The site says "small" rather than hiding it.
  - Whether the profile comes from past leagues (a constant shipped in a report) or from the live league's recent days.
- **Done when:** the finding is written with numbers and a recommendation, and the `hours` section of the contract is updated if needed.
- **Conclusion (2026-10-24, [finding 6](findings.md#6-hour-of-day-sell-in-the-evening-utc-in-the-first-week-buy-divines-around-noon-after-that-it-barely-matters)): time of day barely matters.** Volume doubles in the UTC evening, but prices hardly move with it: about 2% between the best and worst hour in days 2–7, under 1% after day 7, and nothing that holds in the later league. The one effect worth a line is the Divine's own cycle (cheapest around 12:00 UTC, a 4–8% gap in the launch fortnight). So "Best hour to sell" should drop from P1 to a small note on the page (the busiest hours, and when to buy Divines), not a chart. F can ship `hours` as is; H can render it as one sentence.

### C. Finding 7: stack impact and market depth (P3, research)
- **Owns:** `src/exiledbroker/analysis/impact.py`, `tests/test_impact.py`, section 7 of `findings.md`.
- **Do:**
  - Estimate `sigma_h` per item and market from hourly high/low (Parkinson) and from close-to-close changes, and compare the two.
  - Calibrate `y` in `impact ≈ y · sigma · sqrt(Q / V)`: regress hourly |Δlog price| on sqrt(volume / the item's typical volume). Our volumes are unsigned, so this is a proxy; say so.
  - Find out what `low_stock` / `high_stock` mean, using pages on disk only (stock against ratio and against the next hour's price).
  - Compare the depth of the Chaos and Divine markets for the same item.
- **Decide:**
  - Is the estimate good enough to show as "about −7%", or only as a band (low / medium / high impact)?
  - Should E load the stock fields? Give the rows and bytes it would add.
- **Done when:** the finding is written, with a recommended `y` and the formula's caveats for the page's copy.
- **Conclusion (2026-10-24, [finding 7](findings.md#7-stack-impact-cant-be-measured-from-hourly-data-show-a-stack-as-hours-of-the-markets-trading-and-dont-load-the-stock-fields)): there's no `y` to recommend.** Hourly average prices bounce back hour to hour (consecutive moves correlate −0.38), so quiet hours move more than busy ones and a stack's impact is lost in the noise; volumes are unsigned too. The page shows a stack as hours of the market's trading (bands at ¼ h and 1 h), Chaos market first (it carries ~88% of an item's value traded). The stock fields add nothing to either question: E doesn't load them (64 bytes a row, 28 MB for a league window).

### D. Finding 8: mechanic paths and the launch outlook (P1–P2, research)
- **Owns:** `src/exiledbroker/analysis/mechanics.py`, `tests/test_analysis_mechanics.py`, section 8 of `findings.md`.
- **Do:**
  - Build each basket's index per league. Reuse the relative launch curves (`analysis/launch_patterns._curves_sql`, `weighted_curve`): an equal-weighted geometric mean of price over the day-1 median, with recency weights (half-life 2 leagues).
  - Check whether mechanics have a usual path, and how wide the spread between leagues is.
  - **Launch outlook, walk-forward:** rank mechanics for each league using only the earlier leagues, as the Launch picks do (`services/launch_picks`), and score the ranking against what happened.
  - Define "Easy to sell": an Amihud-style ratio |r| / Chaos volume, the share of hours traded, and the median hourly Chaos volume.
  - Pick the score's factors and weights for `rank_score`.
- **Decide:**
  - Index definition, band (min/max or IQR) and the `change_*` units.
  - Whether "usual" means anything after day 14. If not, `usual` is null after day 14 and the page says why.
- **Done when:** the finding is written with walk-forward results and the contract's `mechanics` and `outlook` fields are confirmed.
- **Conclusion (2026-10-24, [finding 8](findings.md#8-mechanics-each-has-its-own-launch-path-but-leagues-shift-it-the-launch-outlook-carries-over-easy-to-sell-is-stable)):**
  - **Index and usual:** the index is in Divines. `usual` is past leagues' recency-weighted index, with their min and max as the range (IQR covers too little), null after day 13.
  - **Changes** are fractional.
  - **The outlook is a premium** (window price over days 12–14's), so its field is renamed from `growth` to `premium`.
  - **Weights:** Easy to sell is Amihud 0.5, Chaos traded per item 0.25, hours traded 0.25. The score is above-usual 0.4, outlook 0.3, Easy to sell 0.3. Both are in `analysis/mechanics`.
  - **Data source:** D reads `cross_market_hour`, not `price_observation`, which lacks most basket items. E's `item_day_history` has D's `item_days` columns.

### E. Data: keep what the page reads (after A, C)
- **Owns:**
  - `normalize/exchange_loader.py` (keep rule, `LOADER_VERSION`)
  - `storage/schema.sql` (new tables appended after the existing ones)
  - capture code beside `services/launch_picks.capture`
  - `tests/test_incremental_load.py`, `tests/test_performance.py` additions.
- **Do:**
  - Widen `_keep_used_items` to the basket items. Measure the rows added per league and per live hour, against what the page reads.
  - Add a reduced history so the server can rank mechanics without past leagues' hours. **Recommended:** per-item daily medians for basket items over days 0–14 (`item_day_history`: league, league_start, item_id, day, chaos, chaos_volume, about 37k rows for five leagues), so a basket edit needs no recompute from local data. Capture it when a fortnight ends, alongside `launch_picks.refresh`.
  - If C says yes, load the stock fields.
  - Bump `LOADER_VERSION`, and with the user, rebuild locally from pages on disk (zero requests; check `ingest_run`).
- **Cost to state in the change:**
  - The hosted rebuild re-reads `exchange_page` from Postgres, so it makes no requests.
  - The backup empties the rebuilt league, gives back its space (`VACUUM FULL`) and re-uploads it. That's free ingress, but give the size.
  - Note the Postgres growth.
- **Done when:** a rebuild on a copy gives the expected rows, the budgets are updated with reasons, and `test_postgres` passes.

**Done (2026-10-24, branch `farm-e`).**
- **The keep rule doesn't change.** B, C and D all read `cross_market_hour`, which already holds every item that traded against Chaos. The Farming page reads nothing from the trimmed `price_observation`. So E skips the widening, the `LOADER_VERSION` bump, the rebuild and the backup's re-upload of the league. Per the rule "store only what the site reads", widening it would have stored rows that nothing reads.
- **Stock fields:** not loaded, per C's finding 7.
- **The reduced history is `item_day_history`,** in `storage/schema.sql`. Each finished league's days 0–13 become one row per basket item and day:
  - columns: `league`, `league_start`, `item_id`, `day`, `chaos`, `divine`, `chaos_volume`, `hours`, `absret`, `day_hours`
  - D's `item_days` columns exactly; on Mirage and Settlers the captured rows equal D's to the last digit.
  - Basket items are every mechanic's outputs, groups and legacy outputs: 760 items. That gives 46,679 rows for the five exchange-era leagues (8.3k–9.8k a league), against `launch_history`'s 12,332. On Postgres that's 10 MB, about 2 MB a league.
- **The code is `services/item_history.py`:**
  - `league_days`: the plain-SQL reduction, on either engine.
  - `capture(con, league, items)`: replaces a league's rows. Hosted, its reads and the DELETE go through `db.pushdown`. The tests check that nothing copies `cross_market_hour` or `price_observation` out of Postgres, and that the aggregate ran there.
  - `refresh(con, settings, live)`: captures each complete league not yet captured, and the live one only once its fortnight is over, as `launch_picks.refresh` does.
  - `captured_leagues`, and `history(con, leagues)` for F to read.
  - Tests are in `tests/test_item_history.py`: DuckDB, Postgres, and the hosted writer.
- **Locally:** `eb farming history` captures every complete league (9 s). Re-run it after editing `config/mechanics.toml`, then `eb site seed`. A basket edit doesn't recapture leagues already in the history.
- **For D and F:** use `item_history.league_days` / `history` rather than a second copy of the SQL. For the live league's own days, `league_days` on `cross_market_hour` gives the same shape.
- **For I:**
  - The pipeline calls `item_history.refresh(con, settings, live)` beside `launch_picks.refresh`.
  - `eb site seed` and the backup sync copy `item_day_history`: about 10 MB uploaded once, then a league's ~2 MB when its fortnight ends.
  - `site.drop_leagues` keeps it, like `launch_history`.
  - The per-pass checks are two small queries; budget them in `test_performance.py` when they're wired in.
- **Merged and captured (2026-10-24):** `farm-e` is on `main` (`01b826a`, pushed), and `eb farming history` ran on the main checkout's database: 46,679 rows, 5 leagues, 760 items. Copying it to the site's Postgres waits for I (seed and backup).

### F. Services (after A, E; formulas from B, C, D)
- **Owns:** `src/exiledbroker/services/farming.py`, `tests/test_farming.py`, new entries in `tests/test_postgres.py` (`_cases`, `LIVE_QUERIES`).
- **Do:**
  - Implement the contract's data: `mechanics` (SQL medians, `percentile_cont`, `nullif` on every division, filter by `league_id`), `outlook` from the reduced history, `items` (last 3 days' `volume_h`, `sigma_h`, `hours_traded` per market from `cross_market_hour`), and `hours` and `impact`.
  - The constants from past leagues (the hour profile if B says so, `y`) ship as a locally built JSON report, like `backtest_report`, with a `stamp`.
  - Handle the cases: no league data (pre_launch: outlook only), one hour, no Divine rate yet, single league, an item never traded in the Divine market.
- **Done when:** DuckDB and Postgres give the same answers and the page's reads are within a budget in `test_performance.py`.

### G. API (after F)
- **Owns:**
  - `api/routes/farming.py`, the models in `api/models.py` (the farming part)
  - `api/warm.py` (`default_views` adds `farming_view(league)` for each trading league)
  - `tests/test_api.py` (allowed route set, every endpoint after every replayed hour), `web/openapi.json`, `web/src/api/schema.d.ts` (`npm run gen:api`).
- **Done when:** the route is cached and warmed, 404 for an unknown league, 503 with no data, and the replay fixture passes hour by hour.

### H. Frontend (after the contract; mock until G lands)
- **Owns:**
  - `web/src/pages/Farming.tsx` and its test
  - `web/src/lib/impact.ts` (+ test)
  - the route in `App.tsx`, the nav link in `components/Layout.tsx`
  - the hook in `src/api/queries.ts`.
- **Do:**
  - Mechanic ranking cards: trend against the usual band, liquidity and score. Use the Market recap's card style; green and red mean profit and loss only.
  - A Launch outlook section, shown first in pre_launch and launch week.
  - A sell helper: pick an item, type a quantity, and see the expected drop in each market and which is better. The best hours appear as a small lazy-loaded ECharts bar in local time, with the verdict in words.
  - States: no data (503), pre_launch (outlook plus the countdown from `/api/status`), waiting for first trades, stale feed, no Divine market for an item.
  - Remember settings (`rememberSettings`) and keep controls in the URL (`useParam`).
  - Check at 375 px with device emulation.
- **Done when:** `npm run typecheck && npm run lint && npm test && npm run build` pass, and the page works against `eb serve` on the replay fixture.

**Built (2026-10-24, on `main`):**
- **What's there:** `pages/Farming.tsx` with mechanic cards, the launch outlook, the sell helper and best hours. `lib/impact.ts` holds the sell helper's maths and the local-time hour profiles. The page has its route, nav link and `useFarming` hook.
- **Tested:** every state (no data, no league, pre-launch countdown, waiting for trades, stale feed, no Divine market or rate, no usual after day 13). Checked at 375 px with device emulation.
- **Types:** generated from the API (`Schemas['Farming']` and friends in `api/client.ts`); `useFarming` calls `api.GET('/api/farming/{league}')`. The schema's `impact.bands` is a list, so `lib/impact.bandsOf` takes its two edges (else the contract's ¼ h and 1 h). `MechanicHours` has no `shown` flag: the response carries only the baskets whose own profile holds.
- **ECharts isn't used:** it left the site on 2026-10-23, so the hour bars are plain token-coloured elements.
- **Contract:** the page follows B's `hours` and D's `premium`.
- **Follow-ups (`farm-h2`, `farm-h3`):** C's `impact` as hours of trading, B's best hours as a sentence, the generated types.
- **Checked on real data (2026-10-24, `farm-h3`):** `eb farming history` and `eb farming build` on a copy of the research database, then `eb serve` with the built page, at 375 px (device emulation) and 1280 px in both themes; no horizontal overflow. `/api/farming/Allflame` is 112 kB of JSON, 21 kB gzipped, built cold in about 0.1–0.4 s (26 queries, 41k rows read on DuckDB); a warmed request takes 2–5 ms, and `If-None-Match` gets a 304. What real data changed on the page:
  - The sell helper opened on the alphabetically first item, a card that trades 0.1 an hour. It now opens on the item with the most Chaos traded an hour (Stacked Deck), and the item list is grouped by mechanic.
  - The Divine market is the bigger one for some items (Stacked Deck 10×, lifeforce 15×): the lead sentence now says so, not only when it's smaller.
  - A top-band stack's advice said "over several hours" for 75 days of trading: the lead and the card now share `spreadOver` (at least N hours, or several days).
  - `sigma_h` is a log standard deviation and reaches 2.2 for thin items, which read as "±220%". From 0.3 on it reads as a factor, "×2.2 either way" (`lib/impact.swing`), and a trickle reads "under 0.1" an hour rather than "0".
  - "−25% below where it usually is" lost its sign, and "1 past league'" its apostrophe s.

### I. Pipeline, seed and backup (after E, F)
- **Owns:** `ingest/pipeline.py`, `storage/site.py` (seed and drop), `storage/backup.py` (new tables in the sync), `tests/test_pipeline.py`, `tests/test_backup.py`, `tests/test_league_switch.py` additions.
- **Do:**
  - The hosted pass captures the reduced history when a fortnight ends.
  - `eb site seed` and `--hosted` copy the new tables.
  - The backup syncs them incrementally, with no new row reads from the backup; say the bytes if any.
  - A league switch keeps the history and drops the old league's rows.
  - Rerun the league-switch replay and `deploy/railway-sim/run.py switch` with the Farming view warmed.
- **Done when:** both replays pass and the simulation's bill is updated in `hosting.md`.

### J. Docs (last)
- **Owns:** `README.md` (Status, The site table, Next steps), `docs/decisions.md`, `docs/roadmap.md`, `docs/data.md`, `docs/hosting.md`, and this file's checkboxes.
- **Done when:** the README lists the Farming page and its endpoint, the decisions above are logged with dates, and data.md describes the new tables and keep rule.

## Ownership of shared files

Two workstreams editing the same file is where parallel work breaks. Only the owner below edits these; others send their change to the owner or note it here.

| File | Owner |
|---|---|
| `storage/schema.sql`, `normalize/exchange_loader.py` | E |
| `tests/test_postgres.py` | F |
| `tests/test_performance.py` | E (load budgets), F (read budgets): separate functions only |
| `api/models.py`, `api/warm.py`, `tests/test_api.py`, `web/openapi.json` | G |
| `web/src/App.tsx`, `components/Layout.tsx`, `src/api/queries.ts` | H |
| `docs/findings.md` | B, C, D each add only their own section, numbered 6, 7, 8 |
| `docs/decisions.md`, `README.md` | J (others list their decisions in their findings section) |
| `cli.py` | first-come; add commands in separate functions (`eb farming build` for the report) |

## Starting an agent

Give each agent this prompt, with its letter:

> Read CLAUDE.md and docs/farming.md. You are workstream <X>. Create your own worktree (`git worktree add ../eb-farm-<x> -b farm-<x>`), and work only on the files your workstream owns. Follow the rules in "Rules for every agent". Commit on your branch with tests passing, tick your checklist below, and report what you decided, what you measured and any contract changes.

## Checklist

- [x] A: baskets drafted (2026-10-24: 21 mechanics, 408 names, all resolve; `eb mechanics check`)
- [x] A: user review done (2026-10-24: 23 mechanics, 474 names, every output in the core pool; then Breach, Harbinger and Sanctum dropped: 20 mechanics, 431 names)
- [x] B: finding 6 (hour of day) (2026-10-24: `analysis/hours.py`, `hours.report` is the `hours` constant; contract's `hours` updated; rerun on the reviewed baskets. On `main` via `farm-c`)
- [x] C: finding 7 (impact, depth, stock fields) (2026-10-24: `analysis/impact.py`; no calibrated y, impact shown as hours of trading in bands; don't load the stock fields; Chaos market first. Contract's `impact` updated. On `main` via `farm-c`)
- [x] D: finding 8 (mechanic paths, walk-forward outlook, Easy to sell) (2026-10-24: `analysis/mechanics.py`, on A's reviewed baskets; contract's `mechanics` and `outlook` confirmed, outlook `growth` renamed `premium`. On `main`, `8eca3a4`)
- [x] Contract confirmed after B, C, D (2026-10-24: `hours`, `impact`, `mechanics` and `outlook` all from the findings)
- [x] E: keep rule (2026-10-24: unchanged, the Farming page reads `cross_market_hour`)
- [x] E: reduced history (2026-10-24, branch `farm-e`: `item_day_history`, 46,679 rows / 10 MB for five leagues; `eb farming history`)
- [x] E: rebuild with the user (not needed: no keep-rule change, no `LOADER_VERSION` bump)
- [ ] F: `services/farming.py`, Postgres parity, budgets
- [ ] G: `/api/farming/{league}` cached and warmed
- [x] H: Farming page, all states, 375 px (2026-10-24, on `main`; checked on a mock of the contract; best hours follow B's `hours`, the outlook D's `premium`)
- [x] H: follow-ups: sell helper as hours of trading (C's `impact`), best hours as a sentence (B), generated types and a check against `eb serve` once G lands (2026-10-24, `farm-h3`: checked on a copy of the research database, see H's "Checked on real data")
- [ ] I: pipeline capture, seed, backup, league-switch replay, simulation bill
- [ ] J: docs
