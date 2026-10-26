# Demand

This plan comes from an interview with the user on 2026-10-25. **Demand** tells a trader which items, and which mechanics' drops, are drawing buyers right now, and which are being dumped. It is shown on Price check and the Market recap. The work is split into workstreams like [price-check.md](price-check.md). Tick items off here as they land, and record the reasoning in [decisions.md](decisions.md).

## Status (2026-10-25)

**A is done ([finding 11](findings.md#11-demand-volume-price-and-stock-dont-make-a-buy-label-one-launch-week-lead-to-paper-trade-being-dumped-describes-it-doesnt-save-money)); B–E are on hold until the user decides.** The research found no demand signal to build on, apart from one lead that isn't proven yet:
- **No label passes the plan's bar.** "Demand rising", "Busier" and a mechanic "farm this" label don't beat the item's own 3-day move against the market when tested leave one league out. They also lose money as buys at realistic spreads. Every reading reverses after day 13.
- **"Being dumped" is real but small.** It's −9% in log terms, but only about −3.6% in money against the market, and it saves nothing as an exit or a no-buy rule. It's honest only as a description on days 1–6.
- **Stock: the buyers-against-sellers imbalance is out.** It repeats the price move. Only the sellers' "drain" (how far trading emptied the book within the hour) adds a little.
- **The one lead is "rising on a calm book"** (rising, with drain ≤ 0.4). It beat random buys by about 27 points in all 5 leagues, and it returned +22% at 5% a side over 3 days, positive in every league. But almost all of that comes from entries on launch days 1–2. It's about +40 Divines per league fortnight, it adds only +2% against the 3-day move, and its edge fades in the newest leagues.

**Recommendation (for the user to decide):**
- **Don't build B–E now.**
- **Paper-trade the lead on the next league (~2026-11-13).** Run it locally with `analysis/demand.py` on the pages as they arrive, with no loading and no requests beyond the live feed.
- **If it holds, build a reduced version:**
  - B loads only the item-side `lowest_stock` / `highest_stock` per leg, for kept items (about 14 MB for Allflame's window).
  - C computes the one rule, on days 1–4 only.
  - D shows it as a short Market recap list, worded as an option to check.
  - The past-launch baseline table isn't needed: in the first 2 days a falling price says what it would.
- **If the user wants plain readings anyway** ("trading 3× its usual, price −12%"), they need no stock and no new table. They're mostly finding 9's verdict again, though.

## What the data can say

- **Volume has no side.** GGG's hourly exchange history gives, per market (an item against Chaos, or against Divines), the units traded each way and the lowest and highest ratio. Every trade is both a purchase and a sale, so purchases and sales can't be counted apart from volume ([finding 7](findings.md#7-stack-impact-cant-be-measured-from-hourly-data-show-a-stack-as-hours-of-the-markets-trading-and-dont-load-the-stock-fields)).
- **Stock may have a side.** Each market also reports `lowest_stock` and `highest_stock` for both currencies in the pair over the hour. In an item/Chaos market, the item's stock is what sellers have listed, and the Chaos stock is what buyers have put up to buy it. Buyer stock against seller stock (both in Divine-equivalent) is a candidate **order-book imbalance**: buyers piling up and listings thinning would be demand; listings piling up while buyers stay put would be a dump. The fields are in every stored page and aren't loaded today (finding 7 dropped them for stack impact, a different question). Loading them needs no requests: the loader re-reads pages already on disk (locally) or in `exchange_page` (hosted).
- **Unknowns A must answer:** what exactly the stock numbers count (all listings, or only those near the best ratio; capped or not), how noisy they are hour to hour, and whether they add anything over volume and price.

## Decisions from the interview

- **Signal: volume and price, plus stock if the research supports it.** Volume against its usual level, read with the price move (busier and rising: demand; busier and falling: dumping), and the stock imbalance as a third input, **gated on research**. If stock doesn't add signal over volume and price, demand ships on volume and price alone, and the finding records why stock was dropped.
- **Purpose:** spot items whose demand is rising before the price fully moves (buy or farm), avoid dumps, and see which mechanics' drops are wanted (what to farm). Not "sell into demand" (the stack seller covers selling).
- **A description always, a label only where it's proven.** Every reading shows the facts ("trading 3× its usual over the last 6 hours, price +8% in Divines, buyers' stock up 40%"). A **"Demand rising"** or **"Being dumped"** label is added only where the backtest shows it's followed by the move it implies, beating "no change" in leave-one-league-out tests, as Price check's verdict must ([finding 9](findings.md#9-sell-now-or-hold-past-leagues-paths-beat-no-change-in-the-launch-fortnight-mostly-as-sell-after-day-14-nothing-does)). Otherwise no label.
- **Levels: per item and per mechanic.** Mechanics are `config/mechanics.toml`'s baskets (Essence, Breach, Delirium, …), rolled up from their items.
- **Window: the last 6 hours**, against the same 6 hours of the day on the item's previous days, which cancels the daily cycle ([finding 6](findings.md#6-hour-of-day-sell-in-the-evening-utc-in-the-first-week-buy-divines-around-noon-after-that-it-barely-matters)) and keeps one odd hour from dominating (finding 7's bounce).
- **Baseline: the item's own recent days.** While an item has less than 2 days of its own history (the first days of a league), compare against what it traded at the same hours of past launches, scaled. A new item with no history says "not enough history yet".
- **Market: both legs combined.** Volume and stock in Divine-equivalent across the Chaos and Divine markets; the price move in Divines, as Price check judges.
- **Liquidity:** lists (the recap and the movers) show only liquid items, by the recap's existing "liquid markets" rule. Price check's item view shows demand for any item, marked "thin market" below that rule.
- **Placement:**
  - **Market recap:** two short lists, about 5–10 each: demand rising most and being dumped, items and mechanics, liquid only, each linking to Price check.
  - **Price check:** a demand card in the item view, next to the verdict and the stack seller, and a demand mark in the movers list.
- **Uniques are out** (2026-10-25), as everywhere.

## Constraints (from CLAUDE.md, applied here)

- **No new requests.** Stock comes from pages already stored. The research reads pages on disk only.
- **No new route if avoidable.** Demand rides in the existing precomputed responses (`/api/missed/{league}`, `/api/price-check/{league}` and the item endpoint), computed once per data version and warmed. `tests/test_api.py` fails on a new route.
- **Store only what the site reads.** Stock columns only for the items whose hourly rows are kept (`exchange_loader._keep_used_items`), and only the fields the signal uses. The past-launch baseline is a reduced table (per item, day offset and hour bucket: median volume, plus stock if kept), captured when a league's fortnight ends like `launch_history`, never past leagues' hourly rows on the server.
- **Summaries in SQL**, Postgres-compatible, league-filtered by id, with `nullif` on every division; new queries go into `tests/test_postgres.py`'s `_cases` and `LIVE_QUERIES`.
- **Every state:** no data (503), waiting for first trades, one hour, under 2 days (past-launch baseline), a stale feed, an item with no Divine leg, a thin market.

## Workstreams

### A. Research (gates everything else)
- **Owns:** a new finding in `docs/findings.md`, `analysis/demand.py` (reusable research tool), and a local, read-only stock extract from pages on disk.
- **Do:**
  1. Extract `lowest_stock` / `highest_stock` for both sides of each kept item's Chaos and Divine markets from the stored pages of the five exchange-era leagues (no requests), and describe what they look like: coverage, typical size against volume, hour-to-hour noise, signs of capping or of counting only near-best listings.
  2. Build the candidate readings per item-hour over the last 6 hours: volume against the same hours on previous days, the price move in Divines, and stock imbalance and its change.
  3. Test whether **Demand rising** (busier, price up and/or buyers' stock up against sellers') is followed by a rise over the next 24 hours and 3 days, and **Being dumped** by a further fall, in Divines, at prices a trader can get (next hours' fills, as finding 9 learned), against "no change", leave one league out. Volume and price alone vs with stock.
  4. The same rolled up per mechanic.
  5. The past-launch baseline: does scaling past launches' same-hour volume work for an item's first 2 days?
  6. Thresholds, the liquidity rule, and whether labels are shown on days 0–13 only (as Price check's verdict) or all league.
- **Outcome:** a finding with the numbers and a decision: stock in or out, which labels are shown and when, the thresholds. B–E follow it.

### B. Data
- **Do (if stock is in):** load the chosen stock fields in `normalize/exchange_loader.py` for kept items only (`schema.sql`: `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, both engines); bump `LOADER_VERSION` so leagues rebuild from stored pages (no requests; the hosted pipeline re-reads `exchange_page`). Say the storage growth on the hosted database and the backup (a rebuilt league is emptied and `VACUUM FULL`ed before copying, so the 500 MB plan isn't doubled).
- **Either way:** the reduced past-launch baseline table and its capture when a fortnight ends (pipeline), seeded by `eb site seed`, synced by the backup (say the bytes a pass reads).

### C. Service and API
- **Do:** `services/demand.py`: per item and per mechanic, the 6-hour reading against its baseline, the label where A allows, thin-market flag; in SQL. Add the fields to the Market recap's and Price check's response models; regenerate `web/openapi.json` and `src/api/schema.d.ts`; warm in `api/warm.py`. Budgets in `tests/test_performance.py`.

### D. Frontend
- **Do:** the Market recap's two lists (rising, dumped; items and mechanics), the Price check demand card and the movers' demand mark. Profit/loss colours stay reserved for money (labels use neutral or accent tokens, not green/red, unless they are money), tabular figures, tooltips explaining the reading. Vitest for every state listed above; 375 px.

### E. Pipeline, seed, backup, performance, docs
- **Do:** wire B's table into the pass, the seed and the backup; `eb perf report`; README (Site table, Status), `decisions.md`, `hosting.md`, `CLAUDE.md` where it lists tables or rules.
