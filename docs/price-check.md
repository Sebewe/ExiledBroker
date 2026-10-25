# Price check page: the work plan

This plan comes from an interview with the user on 2026-10-25. It replaces the Farming page with a **Price check** page built around one item at a time. That page shows how the item's price moves in this league, in Chaos and in Divines, and what past leagues suggest it does next: sell now, hold, or no clear signal. It also carries the stack seller, which was the part of the Farming page the user liked. The plan is split into workstreams like [farming.md](farming.md). Tick items off here as they land, and record the reasoning in [decisions.md](decisions.md).

## Status (2026-10-25)

A, D and E started 2026-10-25. A's research goes first: it decides whether there is a verdict at all (see "The bar"). E's backend removal is done on its branch (below); it merges after D's frontend, or with it.

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

## Workstreams

```
A research (model, backtest, finding 9) ─► B data ─► C services + API ─┐
D frontend (scaffold on the contract now, fill after C) ───────────────┼─► F pipeline, seed, backup, perf, docs
E Farming removal (after D has moved the stack seller) ────────────────┘
```

A, D and E's audit start now. B waits for A's verdict on what history the model needs. C waits for A and B. E removes code only after D has moved the stack seller; until then it audits and prepares. Rules for every agent are [farming.md's](farming.md#rules-for-every-agent), restating [CLAUDE.md](../CLAUDE.md): no requests to GGG, no Supabase, own worktree (`git worktree add ../eb-pc-<letter> -b pc-<letter>`), research on a copy of the database, SQL in `services/` runs on Postgres, the page reads only precomputed views.

### A. Prediction research (first; decides the verdict)
- **Owns:** `src/exiledbroker/analysis/price_outlook.py`, `tests/test_price_outlook.py`, finding 9 in `docs/findings.md`.
- **Do:**
  - Build the backtest set: for each past league, item and hour (days 0–13, hourly) or day (later, daily from the dumps), the forward change in Chaos and in Divines over 24 h and 3 days.
  - Candidate models, from simple up: no change (the baseline); the item's past-league median path from this day; its group's or mechanic's path when it has under 2 past leagues; momentum (last 24 h / 3 d move); the past path conditioned on momentum.
  - Score leave-one-league-out: direction accuracy on moves bigger than the noise (the item's hourly swing), mean error against no change, and whether the band (low–high) covers what it claims (e.g. an 80% band holds 80% of outcomes).
  - Measure separately for days 0–2, 2–7, 7–14 and later, and for thick and thin markets. A verdict may hold only in launch week, or only for liquid items. Ship it only where it beats no change.
  - Measure the dumps' coverage of exchange items, and whether pre-Settlers leagues help or hurt.
  - Score in Divines (decided). Report how often a Chaos verdict would disagree, as context.
- **Done when:** finding 9 states, per phase, which model wins (or that none beats no change), the verdict thresholds, the band width, and what history the server needs to compute it. The user reads it before B and C go on.

### B. Data the model needs, hosted
- **Owns:** a reduced history table (name decided with A), its capture in `services/`, `storage/schema.sql` additions, `eb` command to build it locally.
- **Do:** store only what A's model reads. Likely a small table of past leagues' forward-change quantiles per item (or group) and day, built locally from the DuckDB and the dumps and seeded, like `farming_report`, rather than whole daily paths. Size it (rows, MB on Postgres) and say what it adds to the backup.
- **Done when:** the table builds locally, seeds, and its size is in `docs/hosting.md`.

### C. Services and API
- **Owns:** `src/exiledbroker/services/price_check.py`, `api/routes/price_check.py`, `api/warm.py` additions, `tests/test_api.py` / `tests/test_postgres.py` cases.
- **Do:** two precomputed responses (the contract below). The per-item response is bounded: only core-pool exchange item ids (404 otherwise), so a visitor can't make it read anything new. It is computed once per data version per item, with a seek on `cross_market_hour` by league, item and time. Measure it: if building all ~1,000 every hour is cheap, warm them all; otherwise warm the index's movers and the most-traded items and build the rest on first request. Budget it in `tests/test_performance.py`.
- **Done when:** both endpoints pass on DuckDB and Postgres, `web/openapi.json` is regenerated and the route list in `tests/test_api.py` is updated.

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

### E. Remove the Farming page
- **Backend: done 2026-10-25** (branch `worktree-agent-a8925f19c7eca44dc`, to merge after or with D). Removed: `services/farming.py`, `services/item_history.py`, `analysis/mechanics.py`, `api/routes/farming.py` (and its warm view), the Farming response models, `eb farming history`, the pass's capture, `item_day_history`'s seed and backup sync, the simulation's Farming traffic and checks, and their tests. `item_day_history` is dropped by `schema.sql` (`DROP TABLE IF EXISTS`) on the next pass, sync and local write. Kept: `farming_report` and `eb farming build`, read through `services/sell_helper.py` (`constants(con, day_offset)` → `{hours, impact}`, `markets()` for the stack seller's per-market trading; the `FarmingHours` / `FarmingImpact` / `FarmingMarket` models stay in `api/models.py`, unreferenced until C uses them); `config/mechanics.toml`, `normalize/mechanics.py`, `eb mechanics check`, `analysis/hours.py` and the core pool's `mechanics` lists. `web/openapi.json` is regenerated without the route; `src/api/schema.d.ts` and the frontend (D's) follow at the merge. The frontend files (`Farming.tsx`, its test, `queries.ts`' hook) are D's to remove.
- **Owns:** `web/src/pages/Farming.tsx` and its test, `services/farming.py`, `api/routes/farming.py`, `analysis/mechanics.py`, `services/item_history.py`, and their tests and docs.
- **Do:** after D has moved what it keeps, remove the page, `/api/farming/{league}`, the mechanic ranking and outlook, and `item_day_history` and its capture, seed and backup steps. Keep `farming_report`'s hour and stack constants (renamed if C wants), and `config/mechanics.toml` if it labels items. Mark `farming.md` superseded and update README, `decisions.md`, `hosting.md`.

### F. Pipeline, seed, backup, performance, docs
- **Owns:** `ingest/pipeline.py`, `eb site seed`, `storage/backup.py` changes, `tests/test_performance.py`, README.
- **Do:** wire B's table into seed and the backup (say the bytes a pass reads), warm C's views, run `eb perf report`. The Railway bill simulation runs only if the user asks.

## The response contract (draft; A may change the verdict fields)

`GET /api/price-check/{league}`: the search list and the movers, one per data version.

```jsonc
{
  "league": "Allflame", "latest_hour": "2026-10-25T09:00:00Z", "day_offset": 91.4,
  "items": [{ "item_id": "currency:screaming-essence-of-greed", "name": "Screaming Essence of Greed",
              "label": "Essence", "chaos": 1.4, "volume_h": 3200.0, "verdict_24h": "hold" }],
  "movers": [/* item ids, strongest calls first, ≤ 20 */]
}
```

`GET /api/price-check/{league}/{item_id}`: one item.

```jsonc
{
  "item_id": "…", "name": "…",
  "series": [/* hourly: [hour, chaos, divine] over launch fortnight + latest 14 days; null where untraded */],
  "outlook": {
    "h24": {"verdict": "sell" | "hold" | "none", "typical": -0.03, "low": -0.09, "high": 0.02, "leagues": 4, "basis": "item" | "group"},
    "d3":  {…},
    "unit": "divine"                     // the verdict judges in Divines
  },
  "stack": {"chaos": {"price": 1.4, "volume_h": 3200.0, "sigma_h": 0.031, "hours_traded": 0.92}, "divine": {…} | null},
  "launch_premium": {"day1": 3.4, "days2_4": 1.8, "days5_10": 1.2} | null,
  "hours": {/* the best-hour sentence's inputs, from farming_report */}
}
```

Prices are in Chaos and the browser converts with `divine_chaos` as today. The stack quantity never reaches the server.
