# Findings (phase 2)

Patterns from past leagues' launch fortnights. Each is reproducible locally from the functions named under it (`analysis/launch_patterns.py`, `services/`), with the leagues it rests on. The analysis tools aren't on the site.

Recent leagues are the best reference: the economy changes every league, and the currency exchange (Settlers, 2024-07) was a structural break. Summaries are recency-weighted (half-life 2 leagues by default).

## 1. Mid- and low-value uniques lose most of their value over launch week

*`unique_moves` + `by_tier`. Divine prices, day 2 → day 14, High confidence on both days, the six most recent challenge leagues (Affliction → Mirage).*

| Day-2 price | Median day-14 ÷ day-2 | Share that rose | Leagues where it held |
|---|---|---|---|
| chase (≥ 50 div) | ≈ 1.3–1.4× | ≈ 67% | small sample (6–16 item-leagues) |
| mid (5–50 div) | ≈ 0.27× | ≈ 26% | 6 of 6 |
| low (0.5–5 div) | ≈ 0.21× | ≈ 15% | 6 of 6 |
| cheap (< 0.5 div) | ≈ 0.69× | ≈ 26% | 6 of 6 |

- In every league, mid- and low-value uniques lost about **65–80%** of their divine price from day 2 to day 14 (60–70% from day 3).
- **Stronger in the exchange era:** a median of 0.18–0.22× in Settlers, Mercenaries, Keepers and Mirage, against 0.27–0.33× in Necropolis and Affliction.
- **Implication:** sell non-chase uniques as early as possible. Chase uniques are the exception, but there are too few to call it.
- **Caveats:** daily data only (uniques aren't on the exchange); survivorship (a price is needed on both days); High-confidence filtering drops the thinnest markets.
- **Uniques were dropped from scope on 2026-10-25** ([decisions.md](decisions.md#scope)): this finding stays as a record and isn't extended.

## 2. Items sold for Divines fetch more than the same items sold for Chaos (preliminary)

*`cross_market.summarize` / `across_leagues` (the former Arbitrage page). All five exchange-era leagues, first 14 days each (Allflame added 2026-10-25, its days 0–13 only).*

| First 14 days | Settlers | Mercenaries | Keepers | Mirage | Allflame |
|---|---|---|---|---|---|
| Item-hours in both markets | 63k | 79k | 75k | 86k | 91k |
| Median gap, via Divines over Chaos | +19% | +17% | +13% | +17% | +17% |
| Chaos-first loop positive at worst prices | 15% | 19% | 15% | 26% | 26% |
| Divines-first loop positive | 0.7% | 1.0% | 1.5% | 1.2% | 1.4% |

- **How common:** 63k–91k item-hours per league traded in both the Chaos and the Divine market.
- **The gap:** the median price via Divines (X/Divine price × the hour's rate) was **13–19% above** the direct Chaos price. It is widest on days 0–2 in every league (+22% to +38%) and settles at +11% to +23% after.
- **It survives worst-case prices.** Chaos → item → Divines → Chaos, buying at the hour's highest Chaos price, selling at its lowest Divine price and converting at its lowest rate, was still positive in **15–26% of item-hours** (over +2% in 14–25%). The reverse loop was positive in about 1%, so the premium runs one way. Allflame, like Mirage, sits at the top of the range: the premium hasn't shrunk as players got used to the exchange.
- **Recurring in all five leagues** (share of hours positive in the worst league; Allflame in brackets, never the worst): Rogue's Marker (66%; 84%), Essence Scarab of Stability (47%; 50%), Tainted Jeweller's Orb (46%; 74%), Timeless Eternal and Karui Emblems (~36%; 86%, 70%), Enkindling Orb (26%; 31%).
- **With the page's defaults** (2% buffer, items with 24 hours in both markets): the Chaos-first loop paid in 17.2% of 297,778 cross-market item-hours in the first four leagues, Divines-first in 0.9%; Allflame adds 89,794 item-hours at 24% and 1.3% (all five: 18.9% of 387,572). On a looser rule (a median price over 1c, no 24-hour minimum), 22 items paid in at least 25% of hours in every one of the first four leagues, and 21 in all five; with the 24-hour minimum it's 8 in both. Even a 50% buffer leaves 6.2% paying, which is the first thing to check in-game: an edge that size is either a persistent mispricing or a quirk of how GGG reports ratios.
- **The paying items repeat** (finding 10): of the 35 items that paid in at least 25% of hours in all four earlier leagues, 33 did again in Allflame (the other two, Domination Scarab of Evolution and Expedition Scarab of Verisium Powder, barely traded in both markets there).
- **Acting on it an hour late doesn't capture it** (finding 4): a loop that paid last hour pays again 39–60% of the time, but at worst-case prices the misses cost about as much as the wins bring in.
- **Caveats:** these are hourly summaries, not an order book, so a gap within an hour doesn't prove one player could catch both sides. It isn't confirmed whether GGG's low/high ratios are executed trades or listings. Gold fees and integer trade ratios aren't modelled, and many items' overlap volume is small.

## 3. Currency and cards hold their value best over the launch fortnight, essences and scarabs worst; in Chaos, the level follows the Divine

*`group_curves` and `launch_curves` (24-hour buckets, items with at least 6 traded hours on day 1). Median of each item's price ÷ its day-1 price (the median of its first 24 hours), day 13, **Chaos / Divines**. Rerun 2026-10-25 with Allflame on today's core pool, which since 2026-10-22 puts catalysts, fragments and oils in the currency group, so its row is split.*

| Group | Settlers | Mercenaries | Keepers | Mirage | Allflame |
|---|---|---|---|---|---|
| Currency list (with catalysts) | 0.93 / 0.43 | 1.09 / 0.60 | 1.12 / 0.85 | 1.80 / 0.55 | 2.73 / 1.00 |
| Fragments | 1.09 / 0.50 | 1.07 / 0.60 | 0.81 / 0.65 | 1.72 / 0.58 | 2.13 / 0.78 |
| Oils | 0.75 / 0.35 | 0.65 / 0.34 | 0.52 / 0.41 | 1.50 / 0.50 | 1.64 / 0.64 |
| Divination cards | 0.83 / 0.38 | 1.73 / 0.88 | 1.09 / 0.85 | 2.29 / 0.70 | 1.79 / 0.65 |
| High-tier essences | 0.79 / 0.38 | 0.56 / 0.32 | 0.49 / 0.41 | 1.42 / 0.47 | 1.15 / 0.44 |
| Scarabs | 1.37 / 0.60 | 0.41 / 0.22 | 0.65 / 0.48 | 0.56 / 0.18 | 1.39 / 0.51 |
| The Divine's Chaos price | ×2.27 (72 → 163c) | ×1.88 (98 → 183c) | ×1.33 (86 → 114c) | ×3.15 (84 → 266c) | ×2.85 (79 → 225c) |

- **The order repeats; the level doesn't.** Of the four main groups (currency, cards, essences, scarabs), essences and scarabs are the two weakest in four of five leagues, as expected for consumables whose supply grows with farming, and the currency list and cards the two strongest. Settlers, the exchange's first league, is the exception both ways (scarabs strongest, cards about as weak as essences).
- **In Chaos, a group's move mostly tracks the Divine.** Where the Divine climbed most (Mirage ×3.15, Allflame ×2.85), groups ended above their day-1 Chaos price: every one in Allflame, essences and scarabs included, and all but scarabs in Mirage. Where it climbed least (Keepers ×1.33), most groups ended below. So the earlier claim, that currency and cards inflate in Chaos while consumables deflate, **holds fully in only two of five leagues** (Mercenaries, Keepers): Settlers' currency and cards fell, Mirage's essences rose (×1.42), and Allflame broke it outright, with essences ×1.15 and scarabs ×1.39.
- **In Divines nearly everything sinks, in every league**: the median core-pool item ended at 0.44–0.65 of its day-1 price, essences at 0.32–0.47 every time; only Allflame's currency list held flat (1.00). That is why group timing defaults to Chaos, and why the Launch picks and Price check judge in Divines (finding 10).
- The four-league version of this table (before 2026-10-22) had the 88-name currency list: 0.85, 1.13, 1.28, 1.84 in Chaos. The other rows are unchanged.

## 4. Backtest: the Launch picks pay; the hourly tools at best break even

*`analysis/backtest.py` (`eb backtest run`; the Backtest page). Settlers, Mercenaries, Keepers, Mirage and Allflame (first 14 days each, plus Allflame's latest 14), built 2026-10-23, with the Market recap's volume floor (loops: at least 500c and 10 items through both markets in the hour; cards: a full set traded).*

A dummy trader with 100 Divines does only what the site said at the time. Hourly tools (the Market recap) are acted on in the hour after the recap's hour, since GGG publishes an hour only after it ends: the top 3 picks, at most 10 Divines a trade and 10% of what traded that hour, in whole items. Launch picks are tested walk-forward, ranked only from the leagues before the one traded. Every trade is priced **fair** (the hour's average price, 1% lost per trade) and **harsh** (the hour's worst traded price for the trader; for launch picks, the median hourly high to buy and low to sell). Something unsold within 6 hours is a total loss.

| Strategy | Fair | Harsh |
|---|---|---|
| Launch picks, day 1 (×, in Divines, by days 12–14) | ×2.1 to ×5.9 | **×1.2 to ×3.5** (typical affordable item ×0.20 to ×0.35) |
| Launch picks, days 2–4 | ×2.0 to ×3.1 | ×1.3 to ×2.1 |
| Launch picks, days 5–10 | ×1.4 to ×1.8 | ×0.84 to ×1.2 |
| Loops, recap's top 3 (div/h) | +0.49 to +1.60 | −0.33 to −0.04 |
| Loops, paid every hour of the last 3 (div/h) | +0.07 to +0.81 | **+0.01 to +0.19** |
| Card turn-ins, top 3 (div/h) | +0.04 to +0.84 | −2.20 to 0.00 |
| Card turn-ins, paid every hour of the last 3 (div/h) | +0.02 to +0.89 | −2.42 to 0.00 |
| Rising, top 3 (buy, sell 2 hours later; div/h) | −0.96 to −0.23 | −7.75 to −1.53 |

- **The Launch picks are the only tool that clearly pays under harsh prices**, in every league tested: day-1 picks returned 21–186 Divines on 75–100 staked, while the typical affordable item lost most of its value in Divines. They ride the fortnight's biggest move rather than an hour's spread. Individual picks still lose (Allflame's day-1 Gift to the Goddess came back ×0.35), so the list pays as a basket.
- **The recap's loops carry real information but not enough.** A flagged loop paid again the next hour 39–60% of the time against 1–11% for other liquid loops. Acting on every one loses a little at harsh prices; requiring it to have paid every hour of the last 3 brings it to about break even (a fraction of a Divine an hour, not a few).
- **Fair prices flatter loops.** Liquid items look 5–10% dearer in Divines than in Chaos on average whether or not the recap flags them; that's most likely the buy/sell spread, which a trader pays, so the fair figures are a ceiling.
- **Card turn-ins lose with market orders**: thin card markets swing so much within an hour that buying at the hour's high wipes out the margin.
- **Limit orders priced from the recap's hour help cards a lot** (`card_limit_trades`). A buy order at that hour's lowest card price, placed only if the set still pays at the reward's lowest price that hour; the reward sold at the next worst price:

  | Card orders (div/h, first 14 days; Allflame's latest 14 in brackets) | Result | Orders filled |
  |---|---|---|
  | Market: buy at the next hour's high, sell at the low | −2.20 to −0.23 (0.00) | 24% |
  | Limit buy, filled if any trade went under the bid | −0.05 to +0.54 (+0.01) | 16% |
  | Limit buy and a sell order at the recap hour's average reward price | **+0.51 to +0.97** (+0.01) | 16% |
  | Either limit, filled only if the hour's average crossed the order | −0.02 to +0.01 | 0.3% (11 of 4,068) |

  Whether the orders fill is the open question: hourly data shows each hour's range, not the queue at each price. If one trade past the price means a fill, the limits turn cards into the best hourly strategy tested; if the hour's average has to cross it, almost nothing fills. Late in a league (Allflame's latest 14 days) there was nothing either way.
- **The same limit orders on loops help less** (`loop_limit_trades`): the item bought with a bid at the recap hour's lowest price, sold the hour after, Divines always converted at the worst rate. Every loop the recap flags still pays from its hour's low, so every one gets an order:

  | Loop orders (div/h, first 14 days; Allflame's latest 14 in brackets) | Result | Orders filled |
  |---|---|---|
  | Market: buy at the next hour's high, sell the hour after at the low | −1.23 to −0.50 (−0.20) | 79% |
  | Limit buy, filled if any trade went under the bid | +0.01 to +0.21 (+0.10) | 19% |
  | Limit buy and a sell order at the recap hour's average in the other currency | **+0.04 to +0.29** (+0.24) | 19% |
  | Either limit, filled only if the hour's average crossed the order | −0.01 to +0.02 (+0.02) | 1.4% (52 of 3,672) |

  About what steady loops make with market orders, from fewer trades, and unlike cards it held up late in the league. The same fill caveat applies.
- **Where in the range to place the orders** (`bid_at` / `ask_at`: 0 = the recap hour's lowest trade, 1 = its highest). A 5 × 5 grid of bid and ask levels (min, 25%, 50%, 75%, max) on Mirage's and Allflame's first 14 days, then the best settings checked on Settlers, Mercenaries and Keepers:

  | Div/h, touch / strict fill | Settlers | Mercenaries | Keepers | Mirage | Allflame |
  |---|---|---|---|---|---|
  | Loops: bid at the low, ask the average | +0.10 / 0.00 | +0.18 / 0.00 | +0.04 / −0.01 | +0.29 / +0.02 | +0.26 / 0.00 |
  | Loops: bid 25%, ask 75% | +0.34 / +0.03 | +0.66 / +0.03 | +0.24 / +0.01 | +0.90 / +0.10 | +0.90 / +0.06 |
  | **Loops: bid 50%, ask 75%** | +0.25 / +0.05 | +0.52 / +0.13 | +0.20 / +0.01 | +0.78 / +0.32 | +0.76 / +0.16 |
  | Cards: bid at the low, ask the average | +0.79 / +0.01 | +0.97 / −0.02 | +0.59 / 0.00 | +0.66 / 0.00 | +0.51 / 0.00 |
  | Cards: bid 25%, ask 50% | +0.93 / +0.07 | +0.78 / −0.03 | +0.56 / 0.00 | +0.62 / −0.02 | +0.52 / 0.00 |

  For loops, a higher bid fills far more often (about two thirds of orders at touch from 25% up, against a fifth at the low) and pays more; bid 50%, ask 75% is the only setting positive under both fill models in every league, so it's the one on the page. Gains in the three leagues it wasn't picked on are smaller, as expected of a setting picked from 25. For cards, bidding higher lets in sets that no longer pay, and no setting beat the low bid reliably.
- **The Rising list is not a buy signal**: risers fall after the hour they're published, at fair prices too.
- **Thin markets flattered the first run.** Before the volume floor, many recap loops were markets with an edge over 1,000% from a couple of items traded; their few fills made acting on every loop look break-even. With the floor (now on the page too), it loses a little. The landing page was renamed from Missed opportunities to Market recap, without the "sat on the table" totals, and words its picks as options to check.
- **Caveats:** no order book, so real fills sit between fair and harsh; one trader at small sizes; today's core pool and loot-filter card list (a small head start); five leagues, the first ones with few earlier leagues to rank picks from.

- **Whole-number orders (2026-10-23).** Exchange orders are whole numbers on both sides and fill in whole lots (`missed.whole`: the smallest lot within 1% of the target, up to 20 items for an item worth a currency unit or more, up to 50 units for one worth less: 21c for 2, 5c for 64 Orbs of Alteration, 1 Divine for 1,926). With the loop and card limit orders placed that way and filled lot by lot, the results above shrink, the loops most: selling a cheap item for Divines takes a lot of hundreds or thousands of items, more than one hour's share often covers.

  | Div/h, first 14 days, touch / strict fill | Fractional orders | Whole lots (on the page now) |
  |---|---|---|
  | Cards, limit orders | +0.51 to +0.97 / −0.02 to +0.01 | +0.37 to +0.68 / −0.02 to +0.01 |
  | Loops, limit orders at the low | +0.04 to +0.29 / −0.01 to +0.02 | +0.01 to +0.22 / −0.01 to +0.02 |
  | Loops, mid-range orders | +0.20 to +0.78 / +0.01 to +0.32 | +0.03 to +0.47 / 0.00 to +0.25 (fills halve) |

  Allflame's latest 14 days, mid-range loops: +0.37 / +0.07. The mid-range levels were tuned before whole lots; a re-tune might find better ones.

## 5. Patient flips on volatile items: real only if GGG's hourly lows and highs are real trades

*`analysis/flips.py` (`python -m exiledbroker.analysis.flips`; on the Backtest page via `backtest.flip_results`: Chaos market, whole-Chaos lots, bid 10%, ask 75%, cut 1% an hour). Settlers, Mercenaries, Keepers, Mirage and Allflame, first 14 days each, built 2026-10-23.*

**The idea.** Pick a random hour in a league's first 14 days and put capital into the Market recap's 3 most volatile liquid items that hour. Volatile means the widest traded range (high − low over the average), among items with at least 10k Chaos traded in the hour, a price of at least 5c and a range of at most 50%. Bid 10% of the way up that hour's range, filled the next hour or cancelled. List at 75% up from the hour after. Cut the ask by a fixed percentage every hour it doesn't sell, for up to 72 hours, then dump what's left at that hour's low. 300 random entry hours per league (seeded), at most 10 Divines and 10% of the hour's traded units per position.

**Correction (2026-10-23): place flips in the Chaos market, in whole-number lots.** Exchange orders are whole numbers on both sides (so many Chaos for so many items) and fill in whole lots, so a bid of 2.05 Divines for one item can't be placed: it takes 41 Divines for 20. The first version also priced from the combined Chaos and Divine markets, and the Divine market sets the hour's high about half the time and its low about a quarter of the time (Mirage and Allflame), because items worth a few Divines trade there at whole numbers (2:1, 3:1): a step of 31–36% of the price for one item. The median candidate's range is 29% combined but 20% in the Chaos market alone; Voidborn Reliquary Key's 22% was 3% in Chaos. The test now uses the Chaos market only (`flips.chaos_prices`), with orders in whole Chaos for the smallest lot of up to 20 items within 1% of the target price (`missed.whole`: bid rounded down, ask rounded up, the ask's total cut in whole Chaos), filled lot by lot, and a range of at least 10% (narrower leaves too little between the bid and the ask). The returns barely changed, because the top picks each hour are cheaper items with a wide range in Chaos too, and finer orders (51c for 10) can sit between the coarse trades (5c and 6c each) that make that range:

| Bid 10%, ask 75%, cut 1%/h | Both markets (first version) | Chaos market | Chaos market, whole lots (now) |
|---|---|---|---|
| Touch | +34% | +32% | +33% (52% of bids filled) |
| Even | +32% | +29% | +30% |
| Peaked | +29% | +26% | +26% |
| Strict | +6.6% | +6.6% | +6.6% (3% filled; by league +17%, −11%, +5%, +4%, +17%) |

The tables below are from the first version. The Market recap lists the latest hour's flips from the Chaos market with these whole-lot orders.

**Volatility lasts.** The picks' range barely shrinks over the next day, and almost all of them keep trading:

| Range of the picks | When picked | +1 h | +3 h | +6 h | +24 h | Typical liquid item | Still volatile after 24 h |
|---|---|---|---|---|---|---|---|
| Settlers | 48% | 49% | 49% | 49% | 49% | 55% | 41% |
| Mercenaries | 48% | 46% | 43% | 45% | 42% | 39% | 57% |
| Keepers | 48% | 43% | 41% | 40% | 39% | 34% | 60% |
| Mirage | 49% | 46% | 44% | 43% | 44% | 39% | 60% |
| Allflame | 49% | 46% | 45% | 44% | 44% | 39% | 61% |

("Still volatile": a range at least half the pick's and above the typical item's; over 90% still trade every hour a day later.) So the hour's delay before the data is published costs little. But with the 50% cap these aren't rare events: the typical liquid item already trades across a 34–55% range within an hour. The strategy is really a standing two-sided offer on items that always trade across a wide range, and the spikes the cap removes (often over 1,000%) are single odd trades nobody can repeat.

**Results.** How much of the range one trader can actually trade at is the whole question, so each fill goes through four models: one trade past the price fills you (touch); volume spread evenly over the hour's range (even); spread in a triangle peaked at the hour's average (peaked); or the hour's average must go past the price (strict). Return is profit over capital put in, across all positions.

| Bid 10%, ask 75% | Bought (of 4,500 tries) | Won | Return | Median hours to sell out |
|---|---|---|---|---|
| Touch, cut 2%/h | 2,456 | 100% | +34% | 2 |
| Even, cut 2%/h | 2,284 | 99% | +31% | 2 |
| Peaked, cut 2%/h | 1,929 | 99% | +27% | 3 |
| **Strict, cut 1%/h** | **138** | **76%** | **+6.6%** (Settlers −3%, Mirage +12%) | **18** (5% dumped) |
| Strict, cut 2%/h | 138 | 70% | +4.9% | 13 |
| Strict, cut 5%/h | 138 | 43% | −1.5% | 8 |
| Strict, cut 10%/h | 138 | 20% | −6.6% | 5 |

- Under the first three models the range is tradeable and the flip almost always sells within a few hours at the first ask: +20–35% a trade, consistent across all five leagues. Asking higher (90% up) earns more and still sells (+33–41%); bidding higher (25% up) fills more often and earns less.
- Under strict fills it's a thin, slow strategy: only 3% of bids fill, a sale takes most of a day, and it pays only with small price cuts (1–2% an hour). Cutting faster gives the gain away. Bidding higher to fill more often erases it (25% up: +1.4%; 50% up: −6%).
- **Restrictions that matter:** cap the range (about 50%: wider is junk); a volume floor (about 10k Chaos an hour); a bid low in the range (10–25% up) and an ask high (75–90%); patience, with cuts of no more than 1–2% an hour and holds up to a day; never sell at the next hour's market (finding 4: that loses).
- **The open question** is the same as for the loops (finding 2): it isn't confirmed whether GGG's hourly lowest and highest ratios are executed trades or listings. If they are trades that happen in any size, this is the best hourly strategy tested. If they are mostly single small trades or stale listings, it's the strict row: small, slow and not consistent across leagues. Hourly data can't settle it; a few hours of real orders in-game would.
- **Not yet modelled:** capital sitting in unsold positions against the 100-Divine bank (holds of up to a day can tie up far more than one hour's trades), and several traders quoting the same items.

## 6. Hour of day: sell in the evening (UTC) in the first week, buy Divines around noon; after that it barely matters

*`analysis/hours.py` (`python -m exiledbroker.analysis.hours`; `hours.report` is the Farming page's `hours`, [farming.md](farming.md)). Settlers, Mercenaries, Keepers, Mirage and Allflame, first 14 days each, plus Allflame's days 76–90; liquid items only (traded in 80% of the hours, median ≥ 300c an hour; 350–580 items a league). Built 2026-10-24. Workstream B.*

**Method.** Each item-hour's log price minus the item's mean over the 25 hours centred on it, so a launch-week trend doesn't pose as a time-of-day effect (a UTC-day mean would make late hours look dear whenever prices rise). The median over items per day and hour is then averaged over days. The noise floor shuffles the hours within each day 500 times; the "gain" must beat its 95th percentile. Stability is how well each league's profile matches the other leagues' (mean leave-one-league-out correlation). The effect fades fast as a league ages, so the league is split into phases: days 0–2, 2–7, 7–14 and later.

**Pooled, by UTC hour** (gain = the best hour over the 24-hour average; gap = best over worst):

| Phase | Days (league-days) | Chaos market | Divine market | The Divine's Chaos price | Stability |
|---|---|---|---|---|---|
| Days 0–2 | 10 | **+5.4%** at 23:00, worst 06:00 (gap 7.8%; floor 3.7%) | noise (floor 4.8%) | noise (floor 10%) | 0.69 |
| Days 2–7 | 30 | **+2.1%** at 23:00, worst 06:00 (gap 3.8%; floor 1.2%) | **+1.7%** at 21:00, worst 08:00 (gap 4.0%) | **+4.1%** at 23:00, **cheapest at 12:00** (gap 8.1%) | 0.75 |
| Days 7–14 | 40 | +0.8% at 19:00 (gap 1.6%): **small** | +0.6%: small | **+2.2%** at 23:00, cheapest at 12:00 (gap 4.3%) | 0.36 |
| Later (Allflame only) | 14 | +1.6% at 22:00, just over its floor (1.4%): small, one league | noise | noise | — |

- **Items are dearest in the evening, UTC (18:00–00:00), and cheapest early morning (04:00–09:00)**, in every league: each league's own best hour is between 18:00 and 00:00 on days 2–7, and the profiles agree across leagues (0.75). The size shrinks with the league: about 5% on days 0–2, 2% on days 2–7, under 1% from day 7.
- **The Divine has its own, stronger cycle**: dear in Chaos at 22:00–01:00 and cheap at 10:00–13:00, by ±4% on days 2–7 and ±2% on days 7–14. Converting Chaos to Divines around noon UTC instead of midnight saves about 8% on days 2–7 and 4% on days 7–14. This is the largest effect that lasts into the second week.
- **Don't convert Chaos prices to Divines to judge the Divine market.** Chaos price ÷ the Divine rate peaks at 12:00 (because the Divine is cheap then), but the Divine market's own prices peak in the evening like the Chaos market's, more weakly (correlation of the two 0.3 on days 2–7, 0.06 on days 7–14). The gap between them is a daily cycle in the Chaos↔Divine loops (finding 2), worth a look for loop timing later.
- **Volume** is twice as high at 15:00–21:00 as at 02:00–07:00 (5.5% of the day an hour against 2.8%), the same on days 2–7, 7–14 and later. 38% of a day's Chaos trades in those 7 evening hours. So the best hours to sell are also the deepest: a stack moves the price least then (finding 7). On days 0–2 the share by hour is only launch-day growth (tenfold), so the page shows none.
- **Mechanics differ.** Where a basket's own profile holds across leagues (stability ≥ 0.5) and beats its noise floor, it's much stronger than the pool, and not always in the evening. On the reviewed baskets (`config/mechanics.toml`, 23 mechanics; outputs plus legacy outputs, since this reads past leagues):

  | Basket (items traded) | Days 0–2 | Days 2–7 | Days 7–14 |
  |---|---|---|---|
  | Essence (59) | +9.8% at 21:00 | **+10.4% at 23:00**, worst 06:00 (stability 0.90) | +4.9% at 00:00 (0.71) |
  | Eldritch altars (12) | +11% at 00:00 | +5.8% at 22:00 (0.82) | |
  | Legion (16) | | **+12.9% at 11:00**, worst 02:00 (0.85) | |
  | Boss rush (41) | | +3.0% at 18:00 (0.69) | +2.0% at 20:00 (0.59) |
  | Beyond (9), Ritual (8) | | +4.7% at 14:00, +3.3% at 23:00 | |
  | Blight (10), Delve (29) | +20%, +13% at 22–23:00 | | |
  | Atlas memories (12), Necropolis (5) | | | +3.3% at 21:00, +5.9% at 11:00 |
  | Heist (3), Betrayal (3) | evening | evening (0.85, 0.76) | Betrayal +3.9% at 01:00 |

  The other mechanics (Breach, Delirium, Runegrafts, Harvest, Harbinger, Expedition, Abyss, Ultimatum, Tattoos, Sanctum and the divination cards) don't hold across leagues: the page uses the pooled profile for them. Essence, Eldritch altars and Legion come out the same on the draft baskets and on the earlier provisional name rules (`hours.PROVISIONAL`, which also counted each mechanic's scarabs: there Ultimatum and Abyss looked stable, but that came from their scarabs, which the config lists as inputs). Heist and Betrayal rest on 3 items each. `python -m exiledbroker.analysis.hours` reads the config (`hours.farming_baskets`), so the list follows any later basket change.
- **Per item is noise.** Forecasting a league's item profiles from the same items in the other leagues does worse than forecasting no pattern in 3 of 5 leagues (mean squared error 28.5 vs 19.4 in Settlers, 31.3 vs 28.4 in Mercenaries, 39.5 vs 38.2 in Allflame, ×10⁻⁴); the pooled profile is about as good as nothing in all five (`hours.item_vs_pooled`).
- **Day of week**: not separable here. Every league launches on a Friday, so in a launch fortnight the weekday is the league's day, and the launch-day surge swamps any weekly rhythm. A side note only; Allflame's later days (two weeks) are too few to say.

**Decided (for the Farming page):**
- **Pooled, plus a basket's own profile where it is stable.** Not per item. The page shows the pooled profile, and a basket's own only when it holds across leagues and beats its noise floor (`report[phase]['mechanics'][m]['shown']`).
- **Small** means the best hour beats the 24-hour average by under 1% (about one order step, 1c on 100c, and well inside an hour's typical move), or doesn't beat the noise floor, or comes from fewer than 2 leagues. The page then says "time of day barely matters" rather than hiding the chart. By that rule the pooled Chaos price is worth it on days 0–7 and small after; the Divine's cycle is worth it on days 2–14.
- **From past leagues, per phase, shipped as a constant** (built locally like the backtest report), not from the live league's recent days. Forecasting days 7–14 from the league's own days 4–7 (`hours.recent_vs_past`) does worse than predicting nothing in 3 of 4 leagues (Keepers 1.12 vs 0.24, Allflame 0.99 vs 0.22 ×10⁻⁴), because the effect shrinks after the first week; earlier leagues' days 7–14 are about as good as nothing, which is the right size. The page picks the phase from the live league's `day_offset`; before launch it shows days 0–2. The later phase rests on one league and stays "small" until a second league has later days.
- **The contract's `hours` grew** (in [farming.md](farming.md#the-response-contract-fixed-first-so-f-g-and-h-work-in-parallel)): the phase, the Divine market's profile, the Divine's own cycle (when to convert), and the stable baskets' profiles. Fractions, not log points.

## 7. Stack impact can't be measured from hourly data; show a stack as hours of the market's trading, and don't load the stock fields

*`analysis/impact.py` (`python -m exiledbroker.analysis.impact`), from the pages already on disk (no requests). Settlers, Mercenaries, Keepers, Mirage and Allflame: every loaded hour's Chaos and Divine markets, traded or not (2.0 million market-hours; items priced at least 1c), 1.37 million hour-to-hour moves. Built 2026-10-24. Workstream C.*

**What the page wanted.** The square-root law, impact ≈ y · σ_h · √(Q / V): dumping Q units into a market that trades V an hour moves the price by a multiple of its hourly volatility. The plan was to calibrate y from how much further prices move in busier hours.

**Busier hours move less, not more.** Mean |hourly move| in units of the item's σ, by units traded over its typical (median) hour:

| Volume / typical hour | < 0.25 | 0.25–0.5 | 0.5–1 | 1–2 | 2–4 | 4–8 | ≥ 8 |
|---|---|---|---|---|---|---|---|
| Chaos market, all items | 1.04 | 0.77 | 0.65 | 0.55 | 0.50 | 0.45 | 0.35 |
| Liquid items only (460) | 1.15 | 0.80 | 0.63 | 0.52 | 0.41 | 0.39 | 0.35 |
| Liquid, over two hours (raw \|Δ\|) | 22% | 13% | 9.3% | 7.9% | 9.0% | 9.8% | 7.6% |

The fitted y is negative in every league (−0.15 to −0.39) and every phase, in both markets. The reason is the data, not the market: an hour's price is the average of whatever traded, so a quiet hour's price rests on one or two trades and lands anywhere, and the next hour undoes it (**consecutive moves correlate −0.36 to −0.39 in every league**). That noise is several times any impact a stack makes, and GGG's volumes are unsigned (no buyer or seller side), so a busy hour of selling can't be told from a busy hour of buying. Over two hours, which lets the bounce cancel, the move stops shrinking at about the typical volume but never grows with it. No trade-level data, no y.

**σ_h is noisy too.** Close-to-close (std of hourly log changes) has a median of 21% an hour in the Chaos market (27% for 1–10c items, 11% above 100c), inflated by that bounce. Parkinson (from each hour's lowest and highest trade) is twice that (47%), inflated by whole-number ratios and single odd trades, and the two rank items differently (rank correlation 0.23 in the Chaos market, 0.09 in the Divine). Neither is a volatility a trader would recognise.

**Stock fields: don't load them.** `lowest_stock` / `highest_stock` are each side's units on offer in the market at its thinnest and fullest moment of the hour: never decreasing from lowest to highest, very persistent (hour-to-hour correlation 0.99, typical change 10%), and about one hour's trading deep (the median hour trades 0.95 of the highest stock; 48% of hours trade more than it, so the book refills within the hour). The two sides hold similar value (median about 1.2–1.3k Chaos each). But they add nothing here:
- Volume over stock explains moves no better than volume alone (flat 0.75 → 0.61 σ; correlation −0.06).
- The bid/offer imbalance doesn't predict the next hour. At the previous hour's price it seemed to (quintiles −2.2% to +2.6%), but that was the bounce: a high last price reads as a weak bid. Valued at the item's median price and with the last move held fixed, its correlation with the next move is −0.02 to −0.06 in every league, the wrong way round, against −0.38 for the reversal alone.
- Cost: 4 integers a leg, two legs a row, 64 bytes per `cross_market_hour` row: 28 MB for Allflame's window (439k rows), about a tenth of the hosted window, for no use the page has.

**Chaos against Divine market.** For the 3,349 item-leagues with both markets, the Divine market carries a median 12% of an item's value traded and trades in 38% as many hours, its hourly price is 1.18× as jumpy as the same item's in Chaos, and it has 1.6× as much of the item on offer: listings that sit. The Chaos market takes a stack better for nearly every item.

**Decided (for the Farming page):**
- **No "about −7%".** The sell helper shows the stack as **hours of the market's typical trading**, Q / volume_h, per market, in bands: under a quarter of an hour sells into the market as it is; a quarter to one hour is a large part of the hour's trading; over an hour is more than the market trades in an hour, so split it and list over several hours. The copy says why: hourly prices swing more than a stack moves them, so a percentage would be invented.
- **Chaos market by default**; the Divine market is shown only as its own hours of trading, which are usually several times more.
- **E doesn't load the stock fields.** `items[].sigma_h` stays only as an informative "typical hourly swing" (close-to-close, Chaos market, last 3 days), not an input to impact. The contract's `impact` changes accordingly ([farming.md](farming.md#the-response-contract-fixed-first-so-f-g-and-h-work-in-parallel)).

## 8. Mechanics: each has its own launch path but leagues shift it; the launch outlook carries over; Easy to sell is stable

*`analysis/mechanics.py` (`python -m exiledbroker.analysis.mechanics`; removed with the Farming page on 2026-10-25, last in commit `2bc4248`). Settlers, Mercenaries, Keepers, Mirage and Allflame, first 14 days each, plus Allflame's days 76–89; workstream A's reviewed baskets (`config/mechanics.toml`, 20 mechanics once Breach, Harbinger and Sanctum were dropped) with their legacy outputs, from `cross_market_hour` (every item that traded against Chaos; `price_observation` keeps too few basket items). Built 2026-10-24. Workstream D.*

**Method.** Everything comes from one reduced table, `item_days`: per league, basket item and day of the league, the median hourly price (Chaos, and Divines at the same hour's rate), Chaos traded, hours traded and the median hourly move. That is the shape of the reduced history workstream E keeps, so the page can be computed hosted without past leagues' hours. A mechanic's **index** is the equal-weighted geometric mean of its items' daily price over their day-0 median (items with at least 6 hours on day 0; at least 3 items). Every test is **walk-forward**: Mirage, Keepers and Allflame are each predicted from only the leagues before them (2, 3 and 4 leagues; recency-weighted, half-life 2 leagues).

**A usual path, per mechanic, days 1–13** (log error; 0.48 ≈ ±60%; 611 mechanic-days):

| Usual from earlier leagues | Index in Divines | Index in Chaos |
|---|---|---|
| Recency-weighted, the mechanic's own | **0.48** | 0.56 |
| Median of past leagues | 0.48 | 0.56 |
| Pooled (every mechanic's together) | 0.70 | 0.78 |
| No change since day 0 | 0.76 | 0.85 |
| Inside past leagues' min–max / interquartile range | 35% / 18% | 39% / 20% |

- **Mechanics have their own paths**: the mechanic's own usual beats a pooled one and "no change" in every league. In Divines it's tighter than in Chaos (Chaos's own slide adds noise). The weighted and plain medians tie.
- **But leagues shift them a lot**, mostly by a level that lasts. The error is small for big, stable baskets (Boss rush 0.13, Divination cards 0.14, Essence 0.15, Delirium 0.21, Eldritch altars 0.23, Delve 0.30) and large where a league changed the mechanic (Legion 0.60, Ultimatum 0.65, Tattoos 0.89, Necropolis 1.10). Building each past league's index from only the items the target league has (a matched basket) doesn't help (0.51), so it's the mechanics that move, not the baskets' make-up.
- **Where a mechanic sits against its usual persists**: the rank correlation across mechanics of index ÷ usual with the same three days later is 0.56 from day 1, 0.84 from day 2 and 0.90–0.96 from days 3–10. **It doesn't predict the next days' change** (rank correlation with the following 3 days' move against the usual's: −0.21 to +0.31 by day, no consistent sign; draft baskets). So "above usual" means its drops are worth more than usual now and probably for the next few days: a reason to farm it, not a forecast to hold.
- **A two-item basket is too noisy**: allowing 2 items raised the error to 0.58 and lowered the outlook's correlation (day 1 0.80 → 0.71), measured while Breach and Harbinger (2 current outputs each) were still in. So an index needs 3.
- **After day 14 there is no usual**: Allflame's days 76–89 sit anywhere from 0.08× (Runegrafts) to 3.7× (Abyss) of its day-13 index, and only one league has later days.

**Launch outlook: the launch premium carries over.** A mechanic's premium in a window is its items' median Divine price then over their median on days 12–14 (when the market has settled; the Launch picks' sale days), geometric mean over its items. Above 1, its drops were worth more then than later. Ranked from earlier leagues (recency-weighted geometric mean):

| Window | Rank correlation with what happened | The last league alone | Predicted top 3 in the actual top 3 (chance) |
|---|---|---|---|
| Day 1 | **0.81** | 0.79 | 1.7 (0.5) |
| Days 2–4 | **0.71** | 0.68 | 1.7 (0.5) |
| Days 5–10 | **0.63** | 0.52 | 2.0 (0.5) |

By league (Mirage / Keepers / Allflame): day 1 0.75 / 0.94 / 0.74, days 2–4 0.79 / 0.65 / 0.69, days 5–10 0.66 / 0.42 / 0.80. From all five leagues (premium, worst league):

| Mechanic | Day 1 | Days 2–4 | Days 5–10 |
|---|---|---|---|
| Expedition | **×4.6** (2.8) | **×3.1** (1.8) | **×1.8** (1.3) |
| Essence | **×3.4** (3.1) | ×1.5 (1.2) | ×1.1 (0.89) |
| Beyond | **×3.4** (2.0) | ×1.4 (1.1) | ×1.1 (0.82) |
| Legion | **×2.6** (2.0) | ×1.1 (0.71) | ×0.87 (0.72) |
| Runegrafts (2–4) | ×2.1 (1.1) | **×2.5** (1.4) | ×1.2 (0.97) |
| Blight | ×1.7 (1.3) | ×0.97 (0.88) | ×0.88 (0.79) |
| Boss rush | ×1.7 (1.4) | ×1.4 (0.99) | ×1.1 (0.90) |
| Divination cards | ×1.5 (1.2) | ×1.2 (0.95) | ×1.1 (0.98) |
| Tattoos | ×0.77 (0.43) | ×1.7 (0.62) | ×1.2 (0.90) |
| Delve | ×0.78 (0.60) | ×0.85 (0.67) | ×0.92 (0.82) |
| Heist | ×0.47 (0.27) | ×0.66 (0.42) | ×0.93 (0.75) |
| Delirium | ×0.46 (0.36) | ×0.55 (0.41) | ×0.83 (0.75) |
| Betrayal (3–4) | ×0.19 (0.13) | ×0.31 (0.21) | ×0.60 (0.53) |

(Ultimatum, Atlas memories, Harvest, Eldritch altars, Ritual and Necropolis sit between ×0.75 and ×1.4; Abyss rests on one league.) Expedition's, Essence's, Beyond's and Legion's drops are worth two to five times their settled price on day 1, in every league; Delirium's, Heist's and Betrayal's are cheapest at launch and gain value as the league goes on.

**Easy to sell.** Per mechanic: the median item's Amihud-style ratio (median hourly |move| over Chaos traded an hour), its Chaos traded an hour, and the mean share of hours its items traded (an item the league has that didn't trade counts as 0). Rank correlation across mechanics from one league to the next:

| Factor | Days 1–3 | Days 11–13 | Days 1–3 → 11–13, same league |
|---|---|---|---|
| Amihud | 0.90 | 0.91 | 0.78 |
| Chaos traded per item | 0.92 | 0.88 | 0.79 |
| Share of hours traded | 0.77 | 0.83 | 0.75 |
| **Combined (0.5 / 0.25 / 0.25)** | **0.89** | **0.90** | |

Amihud and Chaos traded per item say nearly the same (rank correlation −0.95); hours traded adds breadth. Allflame, days 11–13: easiest Betrayal, Harvest, Heist, Eldritch altars, Atlas memories; hardest Divination cards (the median card trades 160c an hour), Expedition, Essence, Tattoos, Ritual. The basket's total Chaos traded is the most persistent (0.92) but measures the basket's size (359 cards), not how easily one drop sells, so it's shown, not scored.

**Decided (for the Farming page; the contract in [farming.md](farming.md) is updated):**
- **Index in Divines**: the geometric mean over the basket's items (at least 3, each with 6 hours on day 0) of price over its day-0 median. Live, an item's price is its median over the last 24 hours, so the index compares with the usual for the league's day (`floor(day_offset)`).
- **`usual`**: the recency-weighted geometric mean of past leagues' index on that day (like the launch curves; the plain median ties), needing at least 2 past leagues; **`usual_low` / `usual_high` are the past leagues' min and max**, labelled as their range, not a forecast (it held the next league 36% of the time with 2–4 leagues behind it; the interquartile range only 19%). **Null after day 13**, and the page says why.
- **`change_24h` / `change_7d`** are fractional changes of the index (0.04 = +4%).
- **The outlook is a premium**, so its field is renamed `growth` → **`premium`**: the window's median Divine price over days 12–14's, geometric mean over items, recency-weighted over leagues; `worst` the lowest league's; `leagues` how many.
- **`liquidity`**: Amihud 0.5, Chaos traded per item 0.25, share of hours traded 0.25 (`rank_score`), over the live league's last 3 days (from past leagues' days 1–3 before then: they carry over at about 0.77).
- **`score`**: `rank_score` over index ÷ usual 0.4, the current window's outlook premium 0.3 and liquidity 0.3 (`analysis/mechanics.SCORE_*`). A factor that's null for every mechanic drops out: after day 10 there's no window, after day 13 no usual (then the score is Easy to sell alone). The weights are a judgment: with no drop rates, there's no farming profit to fit them to.
- **For workstream E**: the reduced history needs `item_days`' columns (`analysis/mechanics.ITEM_DAY_SCHEMA`), not only the price and Chaos traded: the Divine price (index and outlook), hours traded and each day's traded hours (Easy to sell), and the median hourly move (Amihud). Days 0–13, every basket item including legacy outputs that traded: about 690 items and 9,100 rows a league (45k for the five).
- **Dropped by the user (2026-10-24)**: Harbinger (no longer in the game; Fracturing Orbs are core drops nobody can target-farm), Breach (its currency comes from glands not listed on trade, with highly variable rewards) and Sanctum (mostly raw currency). They were also the three mechanics with fewer than 3 current outputs. Of the rest, Abyss has a usual path in one league only, and Necropolis and Tattoos change too much between leagues for their usual to mean much.

## 9. Sell now or hold: past leagues' paths beat "no change" in the launch fortnight, mostly as "sell"; after day 14 nothing does

*`analysis/price_outlook.py` (`python -m exiledbroker.analysis.price_outlook <copy of the database>`, under a minute). Settlers, Mercenaries, Keepers, Mirage and Allflame, days 0–13 hourly (`cross_market_hour`), plus Allflame's days 76–90; the poe.ninja dumps for later days and for five pre-Settlers leagues (Sanctum → Necropolis). The current core pool's exchange items (886; 720–870 traded a league). Judged in Divines (the user's decision), Chaos as context. Built 2026-10-25. Workstream A of [price-check.md](price-check.md).*

**The backtest set.** Every 6 hours, for every item with a price: the *price now* (median of its traded hours over the last 6, at least 2, in Divines at each hour's Divine rate) and what a server knows then (its last 24 h / 3 d move, its market's thickness and its typical hourly swing). The outcome is the log change from **selling now** (the median over the next 6 hours) to **holding** (the same 6 hours 24 or 72 hours later). 191k item-decisions on days 0–13, 31k on Allflame's later days. Thick means traded in 80% of the last 72 hours and a median hour of at least 300c (finding 6's liquid): 5–20% of a league's decisions on days 0–2, 37–61% on days 2–7, 54–71% on days 7–14.

*Why the outcome starts after the decision:* measured from the price now, momentum looked like a forecast (thin markets on days 7–14 and Allflame's later days, skill +0.06, verdicts paying in 5 of 5 leagues), but that was the bounce of finding 7: a price now that rests on one lucky trade comes back. Measured from the next hours' fills, which a seller can actually get, it's gone (skill 0.00).

**Models**, each league predicted from the other four (leave-one-league-out), and the training rows' own paths built without their league either, so the fitted weights see what a new league sees: no change; the market's drift (every item's median change at this point of past leagues, per half-day of the league); the item's group's; **the item's own path** (median over past leagues of each league's median change from this half-day, needing 2 leagues); momentum; path + momentum; and the **shrunk path** (weight × the item's path, the weight fitted per phase and thickness). Skill is 1 − mean |error| ÷ no change's (above 0 beats it); in brackets, in how many of the 5 held-out leagues it did.

| Phase | Market | 24 h: drift | group | item | momentum | **shrunk** | 3 d: item | **shrunk** |
|---|---|---|---|---|---|---|---|---|
| Days 0–2 | thin | 0.03 (4) | 0.07 (4) | 0.17 (5) | 0.01 (5) | **0.18 (5)** | 0.28 (5) | **0.26 (5)** |
| Days 0–2 | thick | 0.13 (5) | 0.14 (5) | 0.38 (5) | 0.06 (5) | **0.38 (5)** | 0.55 (5) | **0.54 (5)** |
| Days 2–7 | thin | 0.00 (3) | 0.00 (2) | −0.08 (0) | 0.00 (3) | **0.01 (5)** | −0.02 (1) | **0.04 (5)** |
| Days 2–7 | thick | 0.02 (4) | 0.02 (5) | 0.02 (4) | 0.03 (4) | **0.07 (5)** | 0.14 (5) | **0.16 (5)** |
| Days 7–14 | thin | 0.00 (3) | 0.00 (3) | −0.11 (0) | 0.00 (3) | 0.00 (1) | −0.09 (0) | 0.00 (5) |
| Days 7–14 | thick | 0.01 (4) | 0.00 (2) | −0.07 (0) | 0.00 (1) | **0.01 (5)** | −0.01 (3) | **0.04 (5)** |
| Later (Allflame, hourly) | both | — | — | — | 0.00 (1) | — | — | — |
| Later (dumps, 4 leagues) | both | −0.02 | −0.04 | −0.17…−0.23 (0) | −0.01 (0) | 0.00 (0–1) | −0.14…−0.20 (0) | 0.00 (0–2) |

- **The item's own path is the signal; shrunk, it beats no change in every phase of the launch fortnight**, in all 5 held-out leagues. The raw path overpromises after day 2 (worse than no change); the fitted weight scales it down: about 0.7–0.96 on days 0–2, 0.2–0.7 on days 2–7, 0.01–0.44 on days 7–14 (thin markets lowest). Path + momentum ties with it (momentum adds 0.00–0.01), so the shipped model is the **shrunk path** alone.
- **It's an item's own path, not its group's or the market's.** Category paths add little over the drift, and an item with under 2 past leagues falling back to its group's path has no skill (−0.03 to 0.00), so it gets no verdict.
- **Days 0–2 are mostly "sell": the Divine climbs** (Mirage: 18c at launch, 145c on day 3), so nearly everything falls in Divines. The drift alone captures part of it (0.03–0.18); the item's path two to three times more.
- **After day 14 nothing beats no change.** Allflame's later hours (one league, no past league to take a path from) give momentum nothing. The dumps' later days (Settlers → Mirage to day 122–318; for Mirage, currency only after day 62) give every model skill ≤ 0 at 1 and 3 days. A later-league "Hold" or "Sell" would be a guess.

**The verdict.** "Sell" when the typical change (weight × path) is at or below −τ, "Hold" at or above +τ, else "No clear signal". τ is chosen per phase, thickness, horizon and direction: the smallest of 5%, 8%, 10%, 15% at which that call hit at least 60% of the time pooled and 55% in every held-out league (`choose`; `SHIP` in the module). Holds pass the bar less often than sells.

| Phase | Market | 24 h: sell (hit, worst league, share of decisions) | 24 h: hold | 3 d: sell | 3 d: hold |
|---|---|---|---|---|---|
| Days 0–2 | thin | ≤ −5%: 75%, 65%, 57% | ≥ +5%: 69%, 57%, 26% | ≤ −5%: 77%, 70%, 64% | ≥ +5%: 72%, 63%, 28% |
| Days 0–2 | thick | ≤ −5%: 89%, 84%, 70% | none (worst league 47%) | ≤ −5%: 93%, 88%, 74% | none |
| Days 2–7 | thin | ≤ −8%: 61%, 56%, 4% | none | ≤ −5%: 67%, 63%, 40% | ≥ +8%: 63%, 55%, 15% |
| Days 2–7 | thick | ≤ −5%: 74%, 69%, 30% | ≥ +5%: 62%, 58%, 12% | ≤ −5%: 76%, 71%, 52% | ≥ +5%: 63%, 59%, 21% |
| Days 7–14 | thin | none | none | none | none |
| Days 7–14 | thick | ≤ −5%: 64%, 57%, 2% | none | ≤ −10%: 70%, 56%, 8% | ≥ +5%: 67%, 58%, 20% |
| Later | both | none | none | none | none |

The median move that followed a call: days 0–2 sells −24% (thin) / −31% (thick) over 24 h, holds +23%; days 2–7 thick sells −12%, holds +5%; days 7–14 thick 3-day holds +13%, sells −16%. The 3-day verdict needs a path 3 days and 6 hours ahead within the fortnight, so it stops at about day 11, and the 24-hour one at about day 13.

**The band** is the typical change plus the 10th and 90th percentile of the training leagues' residuals for the phase and thickness: it claims 80% and holds 79–81% of held-out outcomes pooled, but 68–95% in single leagues. It is wide, as the hourly data is: over 24 hours a median of −26% … +25% for thick items on days 2–7 (−21% … +25% on days 7–14) and −40% … +63% for thin ones (−46% … +84% on days 7–14); over 3 days −38% … +40% thick and −51% … +90% thin on days 2–7. Scaling it by the item's own hourly swing covers the same and is no narrower, so it's per phase and thickness.

**Chaos would say something else often, the opposite rarely.** The same model fitted in Chaos makes different calls on 39% (24 h) / 32% (3 d) of the decisions either makes on days 0–2, 47% / 43% on days 2–7 and 76% / 32% on days 7–14, nearly always one calling and the other not. They're opposite on 9–13% on days 0–2 (Chaos "hold" while the Divine climbs) and ≤ 3% after. Chaos verdicts judged in Divines hit less often (24 h, at ±5%: days 0–2 thick 78% against 84%, days 2–7 thick 69% against 70%).

**The dumps' coverage of exchange items** is wide but rounded: 94–98% of the core pool's exchange items appear in a league's dumps (94–98% of the Chaos traded), but non-currency dumps carry whole Chaos (an essence at 1c reads 1.0), so only 53–58% of items ever price at 10c or more, where rounding is under 10% (56–72% of the Chaos traded). Mirage's non-currency dumps stop at day 62. They're fit only for the later days, where nothing works anyway.

**Pre-Settlers leagues don't help.** Adding five (Sanctum → Necropolis) to the dumps' paths doesn't rescue the later days (skill still ≤ 0) and, on days 2–7, raises the thin markets' skill (0.05 → 0.08 at 24 h) while the band's coverage falls to 66–72%: pre-exchange daily prices were calmer, so their residuals understate today's swings. The hourly days 0–13 of the five exchange leagues are better data for the launch fortnight than any daily dump.

**Caveats.** The model and thresholds were chosen on the same five held-out leagues, so expect a little less on the sixth. Decisions every 6 hours overlap (a 3-day window holds 12 of them), so the per-league counts are the robust part, not the pooled rates. Payoffs are log changes in Divines before any trading friction. A league that changes an item's mechanic (finding 8's Necropolis, Tattoos) breaks its path; the weight and the band absorb that on average, not per item.

**Decided (for Price check; the contract in [price-check.md](price-check.md) holds with the fields below):**
- **Ship the verdict on days 0–13 only, from the shrunk item path, in Divines.** "No clear signal" in thin markets after day 7, everywhere after day 13 (after day 11 for 3 days), and for items with under 2 past leagues; `basis` is always `"item"` (no group fallback). `typical` = weight × path, `low` / `high` = typical + the band's quantiles (log changes; the page shows them as percentages), `leagues` = the path's leagues.
- **The live inputs come from the hosted `cross_market_hour`** (launch fortnight + latest 14 days): the price now (last 6 hours' median of Chaos price ÷ the hour's Divine rate, at least 2 traded hours), thickness (the last 72 hours' share of hours traded ≥ 0.8 and median Chaos traded an hour ≥ 300), and the league's hour for the half-day bin and the phase. No momentum.
- **What B stores: one small table, built locally from the exchange leagues' days 0–13 and seeded.** Per item and half-day bin of the league (`bin` = hour since launch // 12): the 24-hour path (bins 0–25) and the 3-day path (bins 0–21), each with its leagues count, only where at least 2 leagues have it: **35.3k item-bin-horizon rows for 827 items (19.4k rows with the two horizons as columns)**, item ids 28 bytes on average, so about 2–3 MB on Postgres with its primary key (item_id, bin), a one-off upload to the backup and nothing after (it changes only when a league finishes). Plus 12 constants (weight, band low and high per phase × thickness × horizon) and the thresholds, which can live in code (`price_outlook.build` returns both; `SHIP`). It grows by nothing per hour; when a league finishes, its fortnight is one more league in the medians (rebuild and reseed, like the Launch history).
- **Not stored:** past leagues' later days (nothing to predict with), the dumps, pre-Settlers leagues, momentum and group paths.

## 10. What repeats across the five exchange-era leagues

*`launch_patterns.launch_curves` + `turning_points` (6- and 24-hour buckets, items with at least 6 traded hours on day 1) and `group_curves` on today's core pool (682 items: the currency list, fragments, oils, cards, essences, scarabs); `cross_market.summarize`'s per-item loop shares and `divination.turn_in_summary`'s per-card margins (both recomputed with `day_offset < 14`, since the services read every loaded hour and Allflame also has its latest 14 days); findings 4, 6, 8 and 9 for what they already ran on all five. Settlers, Mercenaries, Keepers, Mirage and Allflame, first 14 days each (all five have the full 336 hours). Walk-forward checks rank each league only from the leagues before it. Built 2026-10-25, read-only, under a minute in all.*

**Holds in at least four of five leagues** (Settlers / Mercenaries / Keepers / Mirage / Allflame):

| Pattern | Leagues | Numbers |
|---|---|---|
| The Divine climbs against Chaos | 5 of 5 | first 24 hours' median → day 13: ×2.27 / ×1.88 / ×1.33 / ×3.15 / ×2.85 (day 1 → day 13: ×1.16 to ×2.66) |
| Most core-pool items lose value in Divines | 5 of 5 | median day 13 ÷ day 1: 0.44 / 0.56 / 0.65 / 0.46 / 0.65; only 26–38% of items rose |
| Items peak in Divines in the first days | 5 of 5 | 70 / 56 / 61 / 63 / 55% of items peak on days 1–4 (18–29% on days 10–14); every group's median curve peaks on days 1–3.75, in all 20 group-leagues. Mostly the row above seen another way: curves start at 1.0 on day 1, so an item that only falls "peaks" on day 1; it isn't an independent timing rule |
| Which items rise and which fall repeats | 4 of 4 league pairs; 3 walk-forward leagues | an item's day-13 move against the previous league's: rank correlation 0.71 / 0.80 / 0.68 / 0.65; walk-forward from the median of earlier leagues 0.80 / 0.72 / 0.68 (Keepers, Mirage, Allflame), the right direction in Divines for 88 / 83 / 80% of items |
| Essences and scarabs are the weakest groups, the currency list and cards the strongest | 4 of 5 (not Settlers) | finding 3 |
| Items fetch more via Divines than via Chaos | 5 of 5 | median gap +19 / +17 / +13 / +17 / +17%, widest on days 0–2 in every league (+22% to +38%) |
| The Chaos-first loop pays at worst prices, the reverse doesn't | 5 of 5 | 15 / 19 / 15 / 26 / 26% of item-hours against 0.7–1.5% |
| The same loop items pay | 5 of 5 | 33 items paid in ≥ 25% of hours in every league (tattoos, Shrieking essences, Omens, Tainted orbs, Rogue's Marker, Timeless emblems, crests); an item's share against the previous league's: rank correlation 0.68–0.84; walk-forward, the earlier leagues' top 20 paid ≥ 25% of hours in the next league 70 / 95 / 95% of the time (median share 0.58 / 0.80 / 0.81 against 0.15 / 0.30 / 0.31 for all items) |
| Card sets trade below their reward | 5 of 5 | median card's median-hour margin +17 / +20 / +20 / +16 / +27%; 79–93% of cards positive; 30 of the 57 cards with an exchange-priced reward pay in at least half their hours in every league, 39 in four or more; only 2 pay in one league alone (The Fool, Brother's Gift, both only in Allflame) |
| Evening UTC dearest on days 2–7; the Divine cheapest around noon | 5 of 5 | finding 6 |
| Mechanics' launch premiums and ease of selling carry over | 3 walk-forward leagues | finding 8 (rank correlation 0.81 / 0.71 / 0.63 by window; Easy to sell 0.89) |
| An item's own past path, shrunk, beats "no change" on days 0–13 | 5 of 5 held out | finding 9 |
| The Launch picks pay at harsh prices | 4 of 4 tested (Settlers has no earlier league to rank from) | finding 4 (day-1 picks ×1.2 to ×3.5 in Divines) |

**Doesn't repeat:**
- **Group levels in Chaos.** They follow the Divine (finding 3): in Allflame every group ended above its day-1 Chaos price (in Mirage all but scarabs), in Keepers most ended below. "Currency and cards inflate, consumables deflate in Chaos" holds fully in two of five (Mercenaries, Keepers).
- **The day a group or an item turns.** In Chaos, a group's median curve peaks anywhere from day 1 to day 13.75 depending on the league (Allflame: every group peaked on days 12–13.5, as the Divine kept climbing). Per item, the peak day against the previous league's: rank correlation 0.70 / 0.55 / 0.31 / 0.37, within 2 days only 62 / 49 / 38 / 40% of the time, and weakening. Only the Divine-terms "early peak" above is a timing rule.
- **The size of the moves.** Walk-forward in Chaos, Allflame's items rose more than the earlier leagues said across the board (bottom fifth predicted ×0.27, came in at ×0.59; top fifth ×4.7 against ×5.6): a level shift from the Divine. In Divines the levels were closer (×0.14 against ×0.21; ×2.6 against ×2.3).
- **The loops' timing within the fortnight.** The share of paying hours (items at 1c or more) fades from days 0–2 to days 7–14 in Keepers (22% → 10%) but grows in Allflame (19% → 25%); no shape repeats.
- **Which cards pay best.** Nearly every card pays in most hours (the median card in 81–93% of hours), but the order changes: walk-forward rank correlation of the cards' paying share 0.81 / 0.40 / 0.66, and a top-10 card is barely more likely to pay than any other.
- **Settlers** is the odd league out in most rows that hold in four of five: the exchange's first league, with fewer items trading (47 cards with a day-1 baseline against 147–196 later).

**What it means for the site:**
- **Launch picks:** the basis holds. Items' launch moves repeat walk-forward (0.68–0.80), and in Divines both the direction and the size carry over better than in Chaos, so ranking in Divines from the newest leagues, recency-weighted, is right. Expect the multiples to shift with the next league's Divine; the list pays as a basket (finding 4), not item by item.
- **Market recap:** the loops that pay are mostly the same few dozen items every league, and a past-league record predicts the next league well (70–95% of the top 20 kept paying). A small precomputed "paid in every past league" mark on a loop would be a cheap, honest hint (a table of ~35 item ids from past leagues); not built, for the user to decide. Card sets trading below their reward is structural, not a moment to catch: only limit orders capture it (finding 4), so the recap keeps showing cards as orders to place.
- **Price check:** in Divines, most items fall from day 1 in every league (and so "peak" on days 1–4), which is why finding 9's verdict is mostly "Sell" early. The Divine's own climb (5 of 5) is the one call that needs no item history: Chaos held through the fortnight lost 25–68% against Divines.
- **For the next league (~2026-11-13):** convert spare Chaos to Divines on day 0–1; sell drops for Divines on days 1–4, essences and scarabs first; the Chaos → item → Divines premium is widest on days 0–2. If the league changes the exchange or a mechanic, expect the level to move (Settlers, finding 8's Necropolis and Tattoos) while the ranking mostly holds.

**Caveats.** Five leagues, and only three for the walk-forward checks. Today's core pool and followed cards are applied to every league, so items that left the game are missing and survivors are slightly favoured. The 24-hour day-1 baseline needs 6 traded hours, which drops the thinnest items, especially in Settlers. Loops and card margins are hourly summaries, not an order book (finding 2's caveats), and the paying-share thresholds (25% of hours, half the hours) were picked here, not tuned out of sample.

## 11. Demand: volume, price and stock don't make a buy label; one launch-week lead to paper-trade; "Being dumped" describes, it doesn't save money

*`analysis/demand.py` (`readings`, `with_excess`, `labels`, `lolo`, `summary`; `stock` / `stock_features` read the pages on disk; `python -m exiledbroker.analysis.demand <copy of the database> [--stock]`, seconds). Settlers, Mercenaries, Keepers, Mirage and Allflame, days 0–13, plus Allflame's days 76–90; today's core pool, no uniques; liquid = the Market recap's rule over the 6-hour window (≥ 2,000c traded an hour on average, ≥ 5c). Trades through `analysis/backtest.py`'s dummy trader. Built 2026-10-25, read-only, no requests; two independent audits rebuilt the headline numbers (no lookahead found) and their corrections are applied here. Workstream A of [demand.md](demand.md).*

**Method.** Per item and loaded hour t, over hours t−5..t and both legs: value traded in Divines against the same 6 hours on the previous 3 days (at least 1, so readings start on day 1), the 6-hour price move in Divines, and the stock. **Outcomes start after the decision**: buy at the median of hours t+1..t+3, sell at the same three hours 24 h or 72 h later (finding 9). A label is judged on its **excess**: its move minus the same hour's median over liquid items, since most items fall in Divines over the fortnight (finding 10) and "Being dumped → falls" is true of nearly everything. Thresholds are chosen on four leagues and scored on the fifth.

**What the stock fields are.** `lowest_stock` / `highest_stock` are each side's book at its thinnest and fullest moment of the hour: the item side is sellers' listings, the currency side buyers' Chaos or Divines (extracted from all 2,016 loaded pages: 2.3M item-market-hours, 1,128 items).
- **No cap and no pinned values**: they look like the whole book, not only listings near the best price.
- **Slow and about an hour deep**: level autocorrelation 0.99, median hourly change 11–13%; the median highest stock is 1.5 hours of trading, and 38–48% of hours trade more than the book held, so it refills within the hour.
- **Two separate books**: buyers' and sellers' stock correlate 0.48 within an item; buyers hold 0.95× the sellers' value in the Chaos market, 0.35× in the Divine.
- **Buyers arrive late**: buyers' stock exists in 0–48% of markets in hour 0, 62–79% by hour 24. After day 13 books are 13 hours of trading deep against 0.8 at launch, so a threshold would be per phase.

**Labels** (liquid, days 0–13, held out; Leagues = how many of 5 have the label's sign). Intervals resample 5-day blocks (outcomes overlap across days; 1-day blocks for the momentum rows). *Money* is the arithmetic mean against matched liquid items, unclipped.

| Label (rule chosen held out) | Signals | Raw / hit | Excess, log [95%] | Excess, money | Leagues | Beyond the same 3-day move |
|---|---|---|---|---|---|---|
| Demand rising (volume ≥ 3× usual, price ≥ +10%), 24 h | 12,029 | +1.7% / 56% | +2.3% [−1.2, +3.5] | +5.2% | 5 | −2.6% (0 of 5) |
| Demand rising, 72 h | 11,760 | +2.7% / 56% | +6.1% [+2.5, +8.6] | +11.2% | 5 | −1.3% |
| Being dumped (volume ≥ 3× the market's ratio, price ≤ −10%), 24 h | 785 | −9.8% / 59% | −9.0% [−13.7, −5.7] | **−3.6%** | 5 | −10% on days 0–6 (4 of 5) |
| Being dumped, 72 h | 6,816 | −13.3% / 57% | −10.1% [−15.7, −2.8] | −3.3% | 4 | |
| Busier (volume ≥ 1.5× the market's ratio), 24 h | | +1.3% / 54% | +1.4% | | 5 | in units instead: −1.7% |
| *3-day move against the market, bottom fifth (nothing fitted), 72 h* | 33,513 | −17.3% / 67% | −18.8% [−21.6, −15.9] | | 5 | |
| *3-day move, top fifth, 72 h* | 32,637 | +9.6% / 65% | +8.1% [+6.0, +10.0] | | 5 | |
| All liquid item-hours, for scale | | −0.7% (24 h), −2.2% (72 h) | 0 | | | |

- **"Demand rising" is 3-day momentum under another name**: once the item's 3-day move against the market is known it adds nothing (−0.8% on days 0–6, 2 of 5; −12% on days 7–13, 0 of 5).
  - **Only items that stay labelled carry it**: first hour of each run +0.6% [−0.8, +1.9]; each item weighted equally −6.2%; it fails for scarabs and essences.
  - **It's mostly the launch ramp**: 80% of signals fall on days 1–4, when a quarter of liquid item-hours pass the rule. +2% to +12% on days 0–7, −4% to −21% on days 7–14, in every league.
  - **Executable, it shrinks further**: a trader acting in hour t+1 pays about 1.3 points above the three-hour median entry for rising items, so 24 h is about +1%.
- **Volume in Divines stands in for price**: value traded rises when an item holds its price. In units, "Busier" turns negative, and with the 3-day move held fixed more volume predicts a slightly worse outcome in all 5 leagues.
- **"Being dumped" is real but small in money.** It survives every log-scale check (first hour of each run −7.6%; against finding 9's item path −8.0%, 5 of 5; against the same 3-day move −10% on days 0–6, −19% on days 7–13), but in money it's −3.6% at 24 h: 9% of dumped items rebound over 50% within a day, mostly scarabs. About 150 signals a league fortnight.
- **After day 13** (Allflame only) every label reverses: rising −10%, dumped +10%.

**Does stock add anything?** A rank model of the 72 h excess, held out (IC = mean per-hour rank correlation):

| Added to volume, price, price level and group | 72 h IC gain [95%] | Leagues improved |
|---|---|---|
| All stock features | +0.013 [+0.002, +0.027] | 4 of 5 |
| Drain only (6-hour mean of 1 − lowest ÷ highest of the sellers' stock) | +0.015 [+0.003, +0.027] | 4 of 5 |
| Buyers-against-sellers imbalance only | −0.004 | 2 of 5 |

- **The imbalance adds nothing**: buyers' stock is counted in currency, so it repeats the price move (as in finding 7).
- **Drain adds a little**: a calm book, one trading didn't empty, goes with better outcomes.
- **"Rising on a calm book"** (rising, drain ≤ 0.4, imbalance not falling) looks strong by the loose test and weak by the strict one: 72 h, 1,403 signals, raw +14.0%, 65% hit, excess +17.0% [+9.7, +23.9], +8.6% beyond a no-stock model, but **+2.0% [−5.7, +9.7] against items with the same 3-day move, 2 of 5 leagues**. It reverses on days 7–13 (−6%), is about 0 with items weighted equally, and its edge fades league by league: rising signals passing minus failing the filter, +31 / +18 / +24 / +10 / −1 points from Settlers to Allflame. Drain was found on pooled data; only its threshold was held out.

**Mechanics** (`config/mechanics.toml`'s 20 baskets, liquid items, days 1–13, held out):
- **Rising: no robust signal.** +5.8% at 24 h, but first hour of each run +2.0%, mechanics weighted equally −0.1%, each league × mechanic once −2.6%; one cluster (Mercenaries' Necropolis, 66 signals) is +45%.
- **Busier says nothing about price** (1 of 5 leagues).
- **Dumped holds on days 1–6 only**: −10.3% at 24 h, −16.3% at 72 h (5 of 5), −5.7% / −7.3% with mechanics weighted equally. Strongest for Runegrafts, Beyond, Tattoos, Divination and Essence; positive for Heist, Necropolis and Blight.
- The calm-book filter on baskets (+29% at 72 h, days 1–6) isn't independent confirmation: a signal's top item carries 50–70% of the basket's weight, and the filter was fixed on the same leagues.

**The past-launch baseline for an item's first 2 days** (the item's median 6-hour volume at that hour of other leagues' launches, scaled by total market volume). It covers 91–100% of active item-hours against 54–73% for own history, and tracks volume better (rank correlation 0.80–0.88 against 0.56–0.70). Only a baseline from **earlier** leagues is deployable:

| Hours 6–47, active items (≥ 500c an hour, ≥ 5c), held out | Signals | Excess [95%] |
|---|---|---|
| Rising, earlier leagues only (4 leagues), 24 h / 72 h | 3,687 / 3,686 | +6.9% / +5.7%; from all other leagues +3.2% / −0.8% (3 / 1 of 5): not stable |
| Dumped, earlier leagues only, 24 h / 72 h | 632 / 517 | −17.6% [−23.4, −10.6] / −23.8% [−35.8, −11.0] |
| A price fall alone, no volume condition | | −24.8% / −27.4% |

In the first 2 days a falling price says most of what a "dumped" reading would. (A first run's −32% / −43% used later leagues in the baseline.)

**Trading it** (the backtest's dummy trader: 100 Divines, acting in hour t+1 in the Chaos market, at most 10 Divines and 10% of the hour's units a trade, unsold within 6 hours = lost). Return on capital deployed, launch fortnight, 72 h hold; per league Settlers / Mercenaries / Keepers / Mirage / Allflame. 3–5% a side is finding 4's 5–10% round trip; harsh (buy at the hour's high, sell at its low) is a worst case, since the median liquid item's hourly range is 30–50%.

| Strategy | Trades | 3% a side | 5% a side (per league) | Harsh | Matched random: 5% / harsh |
|---|---|---|---|---|---|
| Demand rising | ≈ 290 | +3.7% | −0.7% (−12 / −4 / +3 / −3 / +9) | −27% | −8.9% / −29% |
| **Rising on a calm book** | ≈ 190 | +27.2% | **+21.9%** (+5 / +28 / +34 / +9 / +24) | −1% to −3% (positive only in Mercenaries, Keepers) | −4.8% / −29% |
| Calmest 10% of books, no label | ≈ 710 | +14.5% | +9.2% (−3 / +5 / +15 / +7 / +15) | −6% | −6.1% / – |
| 3-day move, top fifth | ≈ 350 | +11.8% | +7.3% (−1 / +18 / +5 / +12 / −2) | −16% | −5.3% / – |
| The recap's Rising rule, 72 h | 671 | | | −47% (all lose) | beats random in 0 of 5 |
| Holding Divines | | 0 | 0 | 0 | |

- **Rising on a calm book is the one lead**: about 27 points better than random buys at the same hours in all 5 leagues under every price assumption, positive in all 5 up to 5% a side, break-even at about 15% a side.
- **It's launch weekend**: at 5% a side, entries on days 1–2 return +52%, later ones +0.1% (without the bank's limit: day 1 +58%, day 2 +29%, day 3 +11%, day 4 +7%, then about 0). Not just the Launch picks again: trades outside that league's walk-forward picks still return +20%.
- **It's small**: about 40 trades and 200 Divines deployed a league fortnight, about +40 Divines at 5% a side, against the Launch picks' +21 to +186 at harsh prices (finding 4).
- **Longer holds** (chosen after seeing the results): harsh +14% to +17% at 96 h, +28% to +31% at 120 h, from about 5 launch weekends; Allflame about 0 at 120 h (−13% weighting trades equally), Settlers loses at every hold.
- **After day 13** every strategy loses, worse than random (calm-book rising −56% harsh).
- **"Being dumped" saves nothing**: exiting the Launch picks on the flag takes the harsh basket from ×1.92 to ×1.85 or ×1.57, worse than exiting at a random hour; a holder selling on the flag does 3.0% worse than selling a random liquid item (3 of 5). The 3-day bottom fifth is the better "sell these first" hint (+8% against selling at random at 72 h, 5 of 5), but saves only +2.2% [−1.7, +5.9] in absolute terms.

**Caveats.**
- Small effective samples: hourly signals overlap and the lead rests on about 5 launch weekends. Per-league signs and first-hour counts are the robust part; "5 of 5" is a sign test on five.
- Thresholds came from small grids (54 configurations a label in the first pass, 10 for the stock filter).
- Fills are unobservable (finding 5): the truth sits between fair and harsh, and the trader pays only the Chaos market's spread.
- All five leagues launched on a Friday evening UTC, so phase effects (days 1–2, the turn after day 7) are confounded with weekends.
- Today's core pool: liquid items outside it (retired currencies, delve and socketable items) show far stronger rising moves (+9% / +21% at 24 / 72 h, a few items), which a new league can't know in advance.
- The liquid rule averages the window; the recap tests the latest hour, a little stricter.

**Decided:**
- **Stock's buyers-against-sellers imbalance is out**: it adds nothing over price and volume (as finding 7). Only the sellers' drain carries a little.
- **No "Demand rising", "Busier" or mechanic "farm this" label**: none beats the item's own 3-day move held out, and none pays as a buy at realistic spreads.
- **No label after day 13**: every reading reverses there.

**Decided by the user (2026-10-25): Demand is shelved.** The signals are too sparse and inconsistent to build on: no paper trade of the calm-book lead, no stock fields loaded, no demand descriptions or labels on the site. `analysis/demand.py` stays only so this finding can be reproduced.

## 12. Cards with random rewards: two Delirium Orb cards beat their floor at typical prices, nothing survives harsh prices in the launch fortnight

*`analysis/card_ev.py` (`python -m exiledbroker.analysis.card_ev`), pools in `config/card_rewards.toml`. Daily median Chaos prices from `cross_market_hour`, days 0–13, Settlers, Mercenaries, Keepers, Mirage and Allflame (and Allflame's later days). Built 2026-10-26.*

**The question.** 15 followed cards give a random reward ("5x Fossil", "10x Delirium Orb") rather than one named item, so the turn-in tool couldn't price them. GGG doesn't publish the weights, so a set is valued three ways each day: the **floor** (the cheapest item the reward can roll: a set that costs less pays whatever rolls, with no assumption about the weights), the **median** item and the plain **average** (both assume equal odds; the average flatters, since dear outcomes are usually the rare ones). A day counts only when the card traded and at least 80% of its pool did. Four rewards can't be priced at all: Incursion Vials don't trade on the exchange, and "Quality Currency", "Vendor Refresh Currency" and "Currency" aren't defined pools.

| Card (set → reward) | Floor margin by league (Settlers / Mercenaries / Keepers / Mirage / Allflame) | Days the floor paid | At harsh prices |
|---|---|---|---|
| Disdain (5 → 1 Delirium Orb) | −49% / **+46%** / **+32%** / **+28%** / **+45%** (+1.1c to +2.4c a set) | 62–71% in 4 of 5 | floor 0% to −25%, median 0% to +17% |
| Dementophobia (11 → 10 Delirium Orbs) | +1% / **+9%** / **+8%** / −2% / +2% (median item: +12% to +23%, 5–14c a set) | 36–71% | floor −23% to −48% |
| The Tinkerer's Table (5 → 5 Fossils) | −17% / **+23%** / −44% / +8% / +9% (median item: +27% to +192%) | 18–79% | floor −24% to −67% |
| The Long Con (4 → 1 conqueror's Exalted Orb) | −5% to −62%; **median item +20% to +60% in 5 of 5** | 0–43% | median item +1% to +26% in 5 of 5; 7–13 cards traded a day |
| Three Voices (3 → 3 Essences) | −50% to +58%, but a set costs 0.3–1.5c | 0–64% | – |
| Harmony of Souls, The Cacophony (Shrieking / Deafening Essences), Imperfect Memories (Astrolabe), The Journey (tattoo), The Tireless Extractor (Oils), The Gambler (any card) | negative at the floor in every league (The Gambler and the Oils by 90%+: their pools include near-worthless items) | – | – |

- **At typical prices two cards beat their floor in most leagues:** Disdain (+28% to +46% in four leagues, a couple of Chaos a set) and, thinly, Dementophobia (+2% to +9%, but 700–2,700 cards traded a day). Those are turn-ins that pay whatever rolls.
- **At harsh prices nothing pays at the floor in the launch fortnight.** Buying the cards at the hours' highs and selling the reward at the lows erases a margin that size, as finding 4 found for the hourly tools. Only a limit order captures it.
- **The Long Con pays on the median item in every league,** at harsh prices too (+1% to +26%), but it's a bet on equal odds across four orbs GGG doesn't publish, in a market of about 10 cards a day.
- **After the fortnight (Allflame only)** Disdain and Dementophobia beat their floor on every day, at harsh prices too (+140% and +25%), but only 12–56 cards trade a day, and it's one league.
- **Caveats:** daily medians, not hours a trader can act in; the pools are broad on purpose (an item the card can't give can only lower the floor), but if a card's real pool is narrower, its true floor is higher; gold fees and the time to collect a set aren't included, as for fixed turn-ins.

**Decided (2026-10-26):** the Market recap's card turn-ins will include random-reward cards valued at their floor, with a note that the value is the worst roll ([decisions](decisions.md)). The pools reach the server as a small table resolved at load time. Not built yet.

## 13. Recipes: splinters, a few essence and oil upgrades and one Harvest crest change beat their inputs at typical prices; nothing survives harsh prices, and the scarab vendor never pays

*`analysis/recipes.py` (`python -m exiledbroker.analysis.recipes`, about a second; the first run's per-league table was cut by polars, so a few leagues' hour shares are missing above), recipes in `config/recipes.toml`. Days 0–13 of Settlers, Mercenaries, Keepers, Mirage and Allflame. Combines and vendor upgrades are priced each hour both items traded in the Chaos market; rerolls are priced daily at their floor, as for random card rewards (finding 12). Fair prices are the hour's average. Harsh prices buy the inputs at the hour's high and sell at the low (or in Divines at the worst rate). Built 2026-10-26, read-only, no requests.*

| Recipe | Fair median margin: worst league / median league | Hours it paid (leagues shown in full) | Harsh, worst league |
|---|---|---|---|
| 300 Simulacrum Splinters → Simulacrum | +12% / +18%, positive in 5 of 5 | 91–99% | −63% |
| 100 Ritual Splinters → Ritual Vessel | +12% / +21%, 5 of 5 | 61–74% | −50% |
| 20 Exalted Shards → Exalted Orb | +8% / +13%, 3 of 3 traded | 68–84% | −67% |
| 3 Shrieking → 1 Deafening Essence of Suffering | +4% / +21% (Allflame +61%), 5 of 5 | 56–87% | −13% (Settlers +3%) |
| 3 Opalescent → 1 Silver Oil | +3% / +3%, 5 of 5 | 67–78% | −33% |
| 3 Shrieking → 1 Deafening Essence of Anguish, Doubt | Allflame +60% to +69% (harsh +5% to +33%), elsewhere −28% to +17% | – | – |
| Scarab vendor (3 identical for 1 random other) | at the floor −66% to −88% for every scarab in every league | 0% | – |
| Harvest change, Al-Hezmin's Crest → another crest | +1% / +17% (Allflame +73%), 5 of 5; 0.03–1.85c a crest, which pays for 1–53 Vivid Lifeforce | 57–93% | −60% |
| Harvest change, Delirium Orbs, Breach splinters, Breachstones | about 0% at best, mostly negative | – | – |

- **Splinters and a few upgrades trade below what they make, every league.** The size is like card sets (finding 10's +16% to +27%), and so is the catch: at harsh prices every recipe loses in nearly every league, so only limit orders would capture it (finding 4).
- **Most vendor upgrades lose, and the low tiers are dust.** Whispering to Wailing essences cost the 1c minimum each, so 3 for 1 loses two thirds by construction. Only 5 of the 118 recipes priced paid in every league they traded (the five above).
- **The scarab vendor never pays at the floor.** Scarabs trade within a narrow band of each other, so 3 for the cheapest other loses about two thirds. Whether it pays on average depends on GGG's unpublished weights: the floor can't say.
- **Harvest: one lead, Al-Hezmin's Crest.** It is the cheapest crest every league, so changing it into any other pays at the floor. Whether that's profit depends on the craft's Vivid Lifeforce cost a crest, which GGG doesn't publish: in Mercenaries, Keepers and Allflame the gain covers about 43–53 units, in Settlers 7 and Mirage 1. **To check in game.** The other change crafts are at best break-even before lifeforce.
- **Caveats:** some shard markets are too thin to price (Alteration, Alchemy and Transmutation shards traded in 5–31 hours, at whole-number minimums), and the strongly negative splinter recipes (Breach, the Karui, Vaal and Eternal emblems) are worth checking against the in-game stack size before reading anything into them. Gold fees and the time to gather a set aren't modelled.

## 14. Cross-rate triangles: the item-to-item markets are priced in line; the gaps that pay are new-league currencies and cheap orbs at whole-number ratios

*`analysis/triangles.py` (`python -m exiledbroker.analysis.triangles`, about 20 seconds), over the raw pages on disk. Days 0–13 of the five exchange leagues. A triangle buys A in the Chaos (or Divine) market, trades A for B in the A/B market and sells B, all in one hour; worst prices take each leg's worst ratio. Loops are listed only if their cross market traded at least 100c (or 0.5 div) an hour. Built 2026-10-26, read-only, no requests.*

| | Settlers | Mercenaries | Keepers | Mirage | Allflame |
|---|---|---|---|---|---|
| Item-to-item markets | 1,768 | 834 | 1,023 | 811 | 991 |
| Share of traded market-hours | 12% | 6% | 9% | 7% | 7% |
| Median fair gap of a loop | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| Loop-hours paying at worst prices, via Chaos / Divines | 7% / 30% | 17% / 35% | 17% / 28% | 21% / 32% | 24% / 33% |

- **The cross markets agree with the Chaos and Divine prices.** The median loop's fair gap is 0.0% in every league; the share that "pays" at worst prices is mostly dust-priced pairs and wide hourly ranges, the same effect as finding 2's loops.
- **Nothing pays above the trade floor in every league.** The best repeat is Orb of Fusing → Orb of Alteration via Divines (paid in 15–49% of hours, in all five), with Fusing, Chromatic Orb and Orb of Regret → Exalted Orb via Divines in three. These are cheap orbs priced in Divines at whole-number ratios (finding 5's correction): their cross markets trade under 1 Divine an hour, so it isn't money.
- **What does pay is new-league currency.** In Allflame, Orb of Fusing or Gemcutter's Prism → Dead Man's Sulphur → Chaos paid at worst prices in 70–95% of hours (+300% to +500% fair gap), on 116–160c of cross trading an hour. In Mirage, the coins (Knowledge → Skill → Power) paid in 39–44% of hours on about 130c an hour. One league each, so it's a lead for the untried "new league's own currency" study, not a rule. Chromatic Orb → Exalted Orb via Chaos paid in 33–43% of hours in Mercenaries and Keepers (~135c an hour).
- **Lifeforce and the Shaper/Elder fragment pairs are efficient:** they trade in every league and pay in 0–14% of hours.

## Still to do

- **Check two leads from findings 13 and 14 in game:** the Vivid Lifeforce cost of changing an Al-Hezmin's Crest, and whether the new league's own currency trades at a discount in other currencies' markets at launch (Dead Man's Sulphur, the Mirage coins).
- **Check in-game whether GGG's hourly lowest and highest ratios are executed trades** (findings 2, 4, 5). It's the one question hourly data can't answer, and it decides whether the loops' limit orders, the card limit orders and the volatile flips are real.
- **Rerun finding 10 on the next league once its fortnight completes (~2026-11-27).** The sixth league is the first real out-of-sample check of these patterns; the Launch picks and Price check's paths gain it as one more league (rebuild and reseed).
- **Patch notes (phase 3)** to explain the level shifts that past prices can't (finding 3's group levels, finding 8's Necropolis and Tattoos).
- **A `days` limit on `cross_market.summarize` and `divination.turn_in_summary`** (and so `turn_ins_across_leagues`): they read every loaded hour, so for Allflame they mix its latest 14 days into launch comparisons. Finding 10 filtered in its own queries.
