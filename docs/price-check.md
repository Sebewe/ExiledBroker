# Price check page: the work plan

This plan comes from an interview with the user on 2026-10-25. It replaces the Farming page with a **Price check** page built around one item at a time. That page shows how the item's price moves in this league, in Chaos and in Divines, and what past leagues suggest it does next: sell now, hold, or no clear signal. It also carries the stack seller, which was the part of the Farming page the user liked. The plan is split into workstreams like [farming.md](farming.md). Tick items off here as they land, and record the reasoning in [decisions.md](decisions.md).

## Status (2026-10-25)

A to F are done (2026-10-25); what's left is the 375 px device-emulation check of the page (D, below). The user read finding 9 and settled what the page shows outside the launch fortnight (below).

- [x] **B. Data** (2026-10-25): `services/price_paths.py`, `eb price-check build`. `price_path` (19,360 rows for 831 items, 3.05 MB on Postgres), `price_path_league` (each league's own path, 2.63 MB for five leagues), `price_path_constant` (12 rows): 5.75 MB, in `docs/hosting.md`. Seeded by `eb site seed`, backed up as one group (`storage/backup.py`), and the pipeline adds the live league once its fortnight is over (`price_paths.refresh`).
- [x] **C. Services and API** (2026-10-25): `services/price_check.py`, `api/routes/price_check.py`, the contract below. List ~24–27 kB gzipped, an item 5–9 kB.
- **To run after merging:** `eb price-check build` on the local database (seconds), then `eb site seed` (or `--hosted`) so the site has the paths.
- [x] **F. Pipeline, seed, backup, performance, docs** (2026-10-25): audited and tested, below.

- [x] **A. Prediction research** (2026-10-25): done, [finding 9](findings.md#9-sell-now-or-hold-past-leagues-paths-beat-no-change-in-the-launch-fortnight-mostly-as-sell-after-day-14-nothing-does). The verdict beats "no change" on days 0–13 (the item's own past-league path, shrunk per phase and thickness), in all five held-out leagues; mostly "Sell", and none in thin markets after day 7 or anywhere after day 13. B's table: per item and half-day bin, the 24 h and 3 d paths (~19k rows, ~2–3 MB), plus 12 constants.

## What we're building, and why

The Farming page's mechanic ranking didn't land (the user: "I don't think the current features are any good"). The stack seller did. A player holding a stack of something wants three answers in one place:

1. **What is it doing right now?** The item's price this league, in Chaos and in Divines.
2. **Sell now or hold?** A verdict for the next 24 hours and the next 3 days, from past leagues and the item's current movement.
3. **How do I sell it?** The stack seller (a stack as hours of the market's trading, finding 7) and when to list it (the best-hour sentence, finding 6).

Settled in the interview:
- **A new top-level tab, "Price check",** highlighted in the header (`featured`) and easy to use. It's the site's headline tool for players.
- **The Farming tab goes.** The mechanic ranking and the launch outlook table are removed. The useful parts move into Price check: the stack seller, the best-hour sentence and the item's own launch premium (what it paid on day 1, days 2–4 and days 5–10 in past leagues, from `launch_history`).
- **Items: every exchange item in the core pool** (about 1,000), not only the farming baskets. Uniques are out (no hourly data).
- **The chart: one chart, two lines.** The price in Chaos (left axis) and in Divines (right axis), so a player sees when an item "rose" in Chaos only because the Divine moved. Range picker: **3 days (default)**, 14 days, launch fortnight. Linear axes, UTC, lines break at missing hours (`lib/chartOptions.line`). The prediction is a shaded band continuing past the last hour.
- **The prediction: a verdict plus a range.** "Sell now", "Hold" or "No clear signal", backed by the band on the chart: what past leagues did from this point (typical, low, high). **Horizons: the next 24 hours and the next 3 days.**
- **The model is chosen by research** (A): the item's own past-league paths, its group's or mechanic's, current momentum, or a mix. Whatever backtests best.
- **The page opens on a search box and a list of movers:** the items with the strongest Sell / Hold calls right now, to click into. The search box is `components/ItemSearch`, widened to every item.

### The bar

**The verdict must beat "no change"** in a leave-one-league-out backtest, or it isn't shown. Without it, the page shows only the range and "No clear signal". This is stricter than the Farming page's "informative" bar on purpose: a wrong "Hold" costs a player money. Finding 8 is the warning here: "above its usual path" persisted without predicting the next move, and leagues shift paths by about ±60%.

## Data we have, and the gaps

| Need | Where it is | Gap |
|---|---|---|
| This league, hourly, Chaos and Divine | `cross_market_hour` (every item that traded against Chaos, with the same-hour Divine leg) | Hosted: launch fortnight + latest 14 days. Enough for the 3 d / 14 d / launch ranges. |
| Past leagues, hourly | Local DuckDB: Settlers, Mercenaries, Keepers, Mirage (and Allflame's launch) | **Days 0–13 only.** A 3-day horizon from day 91 has no hourly past. |
| Past leagues, daily, whole league | poe.ninja dumps, already on disk and loaded (`dump_loader`: currency, cards, scarabs, essences, fossils, resonators, oils, Delirium orbs, omens, tattoos) | Daily only. Some exchange items may be missing from the dumps (A measures coverage). Pre-Settlers leagues are before the exchange's structural break: A decides whether they help. |
| Item's launch premium | `launch_history` (window medians per item, hosted) | None. |
| Hour-of-day and stack constants | `farming_report` (built locally, seeded) | None; trimmed to what Price check reads (E). |

**No new requests** to GGG or poe.ninja are needed for any of this.

## Decided after the interview (2026-10-25)

1. **The verdict judges in Divines.** Chaos inflates quickly, at a pace that depends on the patch, so Divines are the peg dedicated players care about (the user). The chart still shows both lines. A reports the Chaos view only as context.
2. **`item_day_history` is dropped and `config/mechanics.toml` stays.** Nothing reads the table once the ranking is gone (~10 MB hosted, plus its capture, seed and backup steps). The config still feeds the core pool's farming lists and labels items in search ("Essence"). E removes the table (the user left it to us).

3. **Outside the launch fortnight the page shows no verdict** (the user, after finding 9). After day 13, or for an item with fewer than 2 past leagues, the item view shows the chart and the stack seller with the line "Calls appear in a league's first two weeks; after that past leagues don't predict the next few days." The movers list falls back to the biggest 24-hour moves in Divines, without Sell or Hold labels. The range is shown only on days 0–13. Extending it is for later.
5. **Movers are small cards** (the user, 2026-10-25): the 24-hour move, then the price, then the name, with a green border for a rise and a red one for a fall (in Divines). Between launches they're ranked by the amount changed in Divines, not the percentage, so a cheap item's swing doesn't outrank a real move. In the launch fortnight the strongest calls still come first.
6. **Best time to sell is the item's last 24 hours** (the user, 2026-10-25), not past leagues' hour-of-day profile: units traded (the exchange's volumes are unsigned, so sold and bought are one number) and their value, the busiest hour and the highest-priced hour (in Divines across both markets, ignoring hours under a quarter of the median hour's units), in local time. The per-item response carries `last_day`. Its `hours` field (past leagues' profile) is no longer shown.
7. **At past launches shows typical prices, not multipliers** (the user, 2026-10-25): each launch window's median price over past leagues (in Divines, shown in the visitor's unit) and how today's price compares ("Today it sells for 40% less"). The response's `launch_premium` became `launch_prices`.
8. **The launch fortnight's chart counts days since the league started** (the user, 2026-10-25): the x axis is "Day 0 … Day 13" ("Days since league start"), not UTC dates, and the hours before an item first traded are shaded "Not traded yet", so a late listing reads as untraded rather than missing. The 3-day and 14-day ranges keep the UTC time axis.
4. **Serving stays as it is for now:** the per-item response is a cached `View` like the others (computed once per data version, gzipped once, ETag). Optimising it (versioned URLs, loading only the 3-day range first, a compact series, a separate size-bounded item cache) is for later, once measured (the user).

## Workstreams

```
A research (model, backtest, finding 9) ─► B data ─► C services + API ─┐
D frontend (scaffold on the contract now, fill after C) ───────────────┼─► F pipeline, seed, backup, perf, docs
E Farming removal (after D has moved the stack seller) ────────────────┘
```

A, D and E's audit start now. B waits for A's verdict on what history the model needs. C waits for A and B. E removes code only after D has moved the stack seller; until then it audits and prepares. Rules for every agent are [farming.md's](farming.md#rules-for-every-agent), restating [CLAUDE.md](../CLAUDE.md): no requests to GGG, no Supabase, own worktree (`git worktree add ../eb-pc-<letter> -b pc-<letter>`), research on a copy of the database, SQL in `services/` runs on Postgres, the page reads only precomputed views.

### A. Prediction research (first; decides the verdict) — done 2026-10-25, finding 9
- **Owns:** `src/exiledbroker/analysis/price_outlook.py`, `tests/test_price_outlook.py`, finding 9 in `docs/findings.md`.
- **Do:**
  - Build the backtest set: for each past league, item and hour (days 0–13, hourly) or day (later, daily from the dumps), the forward change in Chaos and in Divines over 24 h and 3 days.
  - Candidate models, from simple up: no change (the baseline); the item's past-league median path from this day; its group's or mechanic's path when it has under 2 past leagues; momentum (last 24 h / 3 d move); the past path conditioned on momentum.
  - Score leave-one-league-out: direction accuracy on moves bigger than the noise (the item's hourly swing), mean error against no change, and whether the band (low–high) covers what it claims (e.g. an 80% band holds 80% of outcomes).
  - Measure separately for days 0–2, 2–7, 7–14 and later, and for thick and thin markets. A verdict may hold only in launch week, or only for liquid items. Ship it only where it beats no change.
  - Measure the dumps' coverage of exchange items, and whether pre-Settlers leagues help or hurt.
  - Score in Divines (decided). Report how often a Chaos verdict would disagree, as context.
- **Done when:** finding 9 states, per phase, which model wins (or that none beats no change), the verdict thresholds, the band width, and what history the server needs to compute it. The user reads it before B and C go on.

### B. Data the model needs, hosted — done 2026-10-25
- **Owns:** a reduced history table (name decided with A), its capture in `services/`, `storage/schema.sql` additions, `eb` command to build it locally.
- **Do:** store only what A's model reads. Likely a small table of past leagues' forward-change quantiles per item (or group) and day, built locally from the DuckDB and the dumps and seeded, like `farming_report`, rather than whole daily paths. Size it (rows, MB on Postgres) and say what it adds to the backup.
- **Done when:** the table builds locally, seeds, and its size is in `docs/hosting.md`.

### C. Services and API — done 2026-10-25
- **Owns:** `src/exiledbroker/services/price_check.py`, `api/routes/price_check.py`, `api/warm.py` additions, `tests/test_api.py` / `tests/test_postgres.py` cases.
- **Do:** two precomputed responses (the contract below). The per-item response is bounded: only core-pool exchange item ids (404 otherwise), so a visitor can't make it read anything new. It is computed once per data version per item, with a seek on `cross_market_hour` by league, item and time. Measure it: if building all ~1,000 every hour is cheap, warm them all; otherwise warm the index's movers and the most-traded items and build the rest on first request. Budget it in `tests/test_performance.py`.
- **Done when:** both endpoints pass on DuckDB and Postgres, `web/openapi.json` is regenerated and the route list in `tests/test_api.py` is updated.
- **Done:** the per-item query seeks `cross_market_hour` by league, item and time (`LIVE_QUERIES` in `tests/test_postgres.py`); every service query is compared between the engines; budgets in `tests/test_performance.py`; endpoint tests in `tests/test_price_check.py`. Serving is the existing `View` as the user asked: the list and the movers' items are warmed each hour (`api/warm.py`), any other item is built on its first request. Building all ~900 items every hour wasn't done: ~20 ms each, but ~900 cached responses would hold the LRU's 256 entries for one data version.

### D. Frontend
- **Owns:** `web/src/pages/PriceCheck.tsx` (+ test), components it adds, `Layout.tsx`'s NAV, `App.tsx`'s route.
- **Do:**
  - **The tab:** "Price check", `featured`, first in the nav. `/farming` redirects to it.
  - **Top of the page:** a big item search, then the movers list (verdict, 24 h move, price), each row opening the item. The item goes in the URL (`useParam`).
  - **Item view:**
    - A verdict card first: Sell now / Hold / No clear signal, for 24 h and 3 days, with a one-line reason ("in past leagues this fell 8% over the next 3 days from here").
    - Below it, the chart: Chaos and Divine lines, the 3 d / 14 d / launch picker, and the band.
    - Then the stack seller (moved from `Farming.tsx` with `lib/impact`), the best-hour sentence and the item's launch premium.
  - **States:** no data (503), waiting for first trades, a stale feed, an item with no Divine leg, an item with no history (no verdict), one hour of data. Check at phone width (375 px).
- Scaffold on the contract below with a stubbed `fetch` now; wire to C's real types after `npm run gen:api`.
- **Progress (2026-10-25, scaffold done):**
  - [x] Tab: "Price check" first in the nav, `featured`; `/farming` redirects to `/price-check` (Farming.tsx stays until E).
  - [x] Search (`ItemSearch size="lg"`, every item in the response, most traded first) and the movers list (price, 24 h move, item, verdict), each row a link setting `?item=`.
  - [x] Item view: verdict card (24 h and 3 days, one-line reason, judged in Divines), the chart (`components/LazyChart` + `lib/chartOptions`, ECharts back as a dependency; Chaos left, Divines right, 3 d / 14 d / launch fortnight in `?range=`, the outlook band past the latest hour), the stack seller and best-hour sentence (moved to `components/StackSeller`, `lib/impact` widened to any item with Chaos and Divine markets), the launch premium.
  - [x] States, tested in `PriceCheck.test.tsx` against a stubbed `fetch`: 503, no league, waiting for first trades, stale feed, no Divine leg, no history (no verdict), one hour, nothing in range, an unknown item (404), no clear calls. Phone width checked by layout (single-column cards, truncated names, wrapping controls), not yet in device emulation.
  - [x] Wired to C (2026-10-25): the generated types are exported from `client.ts` (`PriceCheckIndex`, `PriceCheckItem`, `Horizon`, `Outlook`, `SeriesPoint`; the sell helper's as `SellHours`, `StackImpact`, `StackMarket`, `HourEffect`, `MechanicHours`, `HourProfile`), the fetchers use `api.GET`, `priceCheckDraft.ts` is gone. After the fortnight the verdict card is the one line "Calls appear in a league's first two weeks; after that past leagues don't predict the next few days.", and the movers are the biggest 24-hour moves with no labels.
  - [ ] Check at 375 px in device emulation against C's real responses.

### E. Remove the Farming page
- **Backend: done 2026-10-25** (branch `worktree-agent-a8925f19c7eca44dc`, to merge after or with D). Removed: `services/farming.py`, `services/item_history.py`, `analysis/mechanics.py`, `api/routes/farming.py` (and its warm view), the Farming response models, `eb farming history`, the pass's capture, `item_day_history`'s seed and backup sync, the simulation's Farming traffic and checks, and their tests. `item_day_history` is dropped by `schema.sql` (`DROP TABLE IF EXISTS`) on the next pass, sync and local write. Kept: `farming_report` and `eb farming build`, read through `services/sell_helper.py` (`constants(con, day_offset)` → `{hours, impact}`, `markets()` for the stack seller's per-market trading; the `FarmingHours` / `FarmingImpact` / `FarmingMarket` models stay in `api/models.py`, unreferenced until C uses them); `config/mechanics.toml`, `normalize/mechanics.py`, `eb mechanics check`, `analysis/hours.py` and the core pool's `mechanics` lists. `web/openapi.json` is regenerated without the route; `src/api/schema.d.ts` and the frontend (D's) follow at the merge. The frontend files (`Farming.tsx`, its test, `queries.ts`' hook) are D's to remove.
- **Owns:** `web/src/pages/Farming.tsx` and its test, `services/farming.py`, `api/routes/farming.py`, `analysis/mechanics.py`, `services/item_history.py`, and their tests and docs.
- **Do:** after D has moved what it keeps, remove the page, `/api/farming/{league}`, the mechanic ranking and outlook, and `item_day_history` and its capture, seed and backup steps. Keep `farming_report`'s hour and stack constants (renamed if C wants), and `config/mechanics.toml` if it labels items. Mark `farming.md` superseded and update README, `decisions.md`, `hosting.md`.

### F. Pipeline, seed, backup, performance, docs — done 2026-10-25
- **Owns:** `ingest/pipeline.py`, `eb site seed`, `storage/backup.py` changes, `tests/test_performance.py`, README.
- **Do:** wire B's table into seed and the backup (say the bytes a pass reads), warm C's views, run `eb perf report`. The Railway bill simulation runs only if the user asks.
- **Done** (most of it landed with B and C; F audited it, closed the gaps and added the tests):
  1. **Seed.** `site.REPLACED_TABLES` holds the three price tables, so `eb site seed` and `--hosted` copy them whole (with `farming_report` and `launch_history`, which the item view reads, and `reference_data`, `tracked_item` and the league tables through the usual shared and per-league copies). `tests/test_price_check.py::test_every_table_price_check_reads_is_in_the_schema_and_seeded` scans the SQL of `price_check`, `price_paths`, `sell_helper` and `core_pool` and fails if a table they read isn't in `schema.sql` or isn't seeded; `tests/test_postgres.py::test_the_seed_copies_every_table_price_check_reads` seeds a miniature of every table and compares counts and the verdict constants between the engines. `config/` (`mechanics.toml`, the search labels) is baked into the image.
  2. **Backup.** The three price tables are one group (`storage/backup.py: PRICE_TABLES`), replaced whole when their stamp changes (a league captured, constants refitted: about 6 MB uploaded, once a league). A pass reads back the stamp only: **68 bytes** for five leagues (`_price_stamp`; `tests/test_backup.py` budgets it under 150, and the pass as a whole under 2 kB, `test_price_check_paths_are_backed_up_once_a_league`).
  3. **Pipeline at the league switch: the pipeline does it, nothing manual** (decision below). `price_paths.refresh` runs every pass after `launch_picks.refresh`, before `drop_leagues`: once the live league has data past its fortnight (`launch_picks._fortnight_over`, the same test the Launch history uses) it captures the league's own paths from its launch fortnight (which the server keeps: `keep_launch_days`) into `price_path_league` and rebuilds `price_path`'s medians, so the next league's verdicts include it. Allflame is captured at its day 14 while it is still the live league, long before the next league replaces it. It needs nothing the server lacks and is cheap: one primary-key lookup a pass, and once a league one read of the fortnight's traded hours (~250k rows, on Postgres itself through `db.pushdown`, not copied out by DuckDB's scanner) and a few MB written. Only the **constants** (the weight and band per phase) aren't refitted there, because the fit needs numpy, which the site image doesn't have. They stay as fitted from the five leagues until the next local `eb price-check build` and `eb site seed`; that is a refinement, not a requirement (the verdict thresholds are code). Tests: `tests/test_pipeline.py` (`test_a_finished_league_joins_price_checks_paths_once`, and the same on Postgres with the no-whole-table-copy check). **One thing to know:** `eb site seed` replaces the price tables whole from the local copy, so run `eb price-check build` locally (it captures every complete league, Allflame included) before any re-seed, or the server's captured league would be overwritten by an older local table.
  4. **Warmed views.** `warm.default_views` warms the list and the movers' items; `tests/test_api.py::test_default_pages_are_precomputed` asserts the requests the frontend makes (`usePriceCheck`, and `usePriceCheckItem` for a mover) make no database query after `warm()`, and now also that any other item is built on its first request and cached for the rest of the data version.
  5. **Performance.** `eb perf report` opens the database read-only (it runs the app on `site_session`, read-only, and counts rows with read-only sessions), so it was run on the local copy; it now measures both Price check endpoints (`perf.ENDPOINTS`). Allflame, day 91, cold cache, no flags against the previous report: the **list** reads 1,965 rows (140 kB) in 25 queries, 85 ms, and sends 145 kB (24–27 kB gzipped); the **item** (a mover) reads 677 rows beyond the list (51 kB), 121 ms for both, and sends 30 kB (5–9 kB gzipped). Budgets in `tests/test_performance.py` stay (rows and bytes at 30 hours, and no growth with history). The recorded numbers are in [hosting.md](hosting.md).
  6. **Postgres parity.** Every service query is in `_cases` and the live ones in `LIVE_QUERIES`; the fixture now seeds a miniature of every Price check table, so the paths, constants, launch prices and best-hour inputs are compared between the engines (and through `test_api_answers_the_same_on_postgres`), not compared empty.
  7. **Docs:** this section, [hosting.md](hosting.md), [go-live.md](go-live.md) (league switch), [decisions.md](decisions.md), README's Status and Site rows.

## The response contract (final, 2026-10-25)

The generated types (`web/openapi.json` → `web/src/api/schema.d.ts`) are the reference; the shapes in brief:

`GET /api/price-check/{league}` (`PriceCheckIndex`): the search list and the movers, one per data version.

```jsonc
{
  "league": "Allflame", "latest_hour": "2026-10-25T09:00:00Z", "day_offset": 91.4,   // null before trades
  "items": [{ "item_id": "currency:screaming-essence-of-greed", "name": "Screaming Essence of Greed",
              "label": "Essence",          // the mechanic that drops it (config/mechanics.toml), else its group
              "chaos": 1.4,                // the price now: median of its traded hours in the latest 6
              "volume_h": 3200.0,          // units an hour in its Chaos market, latest 3 days
              "verdict_24h": "none",       // "sell" | "hold" | "none"
              "change_24h": -0.08 }],      // the latest 24 hours' move in Divines (fraction), null if unknown
  "movers": ["…"],                         // item ids, ≤ 20
  "movers_mode": "moves"                   // "calls": strongest 24 h calls; "moves": biggest 24 h moves among thick markets, unlabelled
}
```

`GET /api/price-check/{league}/{item_id}` (`PriceCheckItem`): one item; 404 unless the league's list has it.

```jsonc
{
  "item_id": "…", "name": "…", "label": "…", "latest_hour": "…", "day_offset": 4.2,
  "thick": true, "change_24h": -0.06,
  "series": [["2026-10-25T09:00:00Z", 1.4, 0.007]],   // traded hours: [hour, Chaos, Divines at the hour's rate]
  "outlook": {
    "h24": {"verdict": "sell", "state": "judged", "typical": -0.12, "low": -0.30, "high": 0.09, "leagues": 5, "basis": "item"},
    "d3":  {"verdict": "none", "state": "later", "typical": null, "low": null, "high": null, "leagues": 0, "basis": "item"},
    "unit": "divine"
  },
  // state: "judged" (the model ran; only it has a band), "later" (past day 13, or past the
  // last bin with a path: ~day 13 for 24 h, ~day 11 for 3 d), "no_history" (< 2 past leagues).
  // typical / low / high are fractions (exp of the log change − 1).
  "stack": {"chaos": {"price": 1.4, "volume_h": 3200.0, "sigma_h": 0.031, "hours_traded": 0.92}, "divine": {…} | null},
  "launch_premium": {"day1": 3.4, "days2_4": 1.8, "days5_10": 1.2} | null,   // median over leagues, vs days 12–14
  "hours": {/* SellHours: the best-hour sentence's inputs (farming_report) */} | null,
  "impact": {"y": null, "bands": [0.25, 1.0], "note": "…"} | null
}
```

Prices are in Chaos and the browser converts with `divine_chaos` as today. The stack quantity never reaches the server.
