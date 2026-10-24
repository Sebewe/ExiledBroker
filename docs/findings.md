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

## 2. Items sold for Divines fetch more than the same items sold for Chaos (preliminary)

*`cross_market.summarize` / `across_leagues` (the former Arbitrage page). All four exchange-era leagues.*

- **How common:** 63k–86k item-hours per league traded in both the Chaos and the Divine market.
- **The gap:** the median price via Divines (X/Divine price × the hour's rate) was **13–19% above** the direct Chaos price.
- **It survives worst-case prices.** Chaos → item → Divines → Chaos, buying at the hour's highest Chaos price, selling at its lowest Divine price and converting at its lowest rate, was still positive in **15–26% of item-hours** (over +2% in 14–25%). The reverse loop was positive in about 1%, so the premium runs one way.
- **Recurring in all four leagues** (share of hours positive in the worst league): Rogue's Marker (66%), Essence Scarab of Stability (47%), Tainted Jeweller's Orb (46%), Timeless Eternal and Karui Emblems (~36%), Enkindling Orb (26%).
- **With the page's defaults** (2% buffer, 1c floor): the Chaos-first loop paid in 17.2% of 297,778 cross-market item-hours, Divines-first in 0.9%. 21 items paid in at least 25% of hours in every league. Even a 50% buffer leaves 6.2% paying, which is the first thing to check in-game: an edge that size is either a persistent mispricing or a quirk of how GGG reports ratios.
- **Acting on it an hour late doesn't capture it** (finding 4): a loop that paid last hour pays again 39–60% of the time, but at worst-case prices the misses cost about as much as the wins bring in.
- **Caveats:** these are hourly summaries, not an order book, so a gap within an hour doesn't prove one player could catch both sides. It isn't confirmed whether GGG's low/high ratios are executed trades or listings. Gold fees and integer trade ratios aren't modelled, and many items' overlap volume is small.

## 3. In chaos, currency and cards inflate over the launch fortnight; farmed consumables deflate

*`group_curves`, in Chaos. Median of each item's price ÷ its day-1 price, day 13.*

| Group | Settlers | Mercenaries | Keepers | Mirage |
|---|---|---|---|---|
| Currency | 0.85 | 1.13 | 1.28 | 1.84 |
| Divination cards | 0.83 | 1.73 | 1.09 | 2.29 |
| High-tier essences | 0.79 | 0.55 | 0.49 | 1.38 |
| Scarabs | 1.37 | 0.41 | 0.65 | 0.56 |

- **Currency** and **cards** inflate in chaos in three of four leagues. Settlers, the exchange's first league, is the exception.
- **Essences and scarabs** mostly lose value, as expected for consumables whose supply grows with farming (exceptions: Mirage essences, Settlers scarabs).
- **In Divines almost everything sinks**, because the Divine inflates fastest (86 → 266c in Mirage). That's why group timing defaults to Chaos.

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

## Still to do

Run the tools across all four exchange-era leagues and write up the patterns that repeat.
