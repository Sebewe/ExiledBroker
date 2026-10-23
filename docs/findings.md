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

## 5. Patient flips on volatile items: real only if GGG's hourly lows and highs are real trades

*`analysis/flips.py` (`python -m exiledbroker.analysis.flips`). Settlers, Mercenaries, Keepers, Mirage and Allflame, first 14 days each, built 2026-10-23. Research only; not on the site.*

**The idea.** Pick a random hour in a league's first 14 days and put capital into the Market recap's 3 most volatile liquid items that hour. Volatile means the widest traded range (high − low over the average), among items with at least 10k Chaos traded in the hour, a price of at least 5c and a range of at most 50%. Bid 10% of the way up that hour's range, filled the next hour or cancelled. List at 75% up from the hour after. Cut the ask by a fixed percentage every hour it doesn't sell, for up to 72 hours, then dump what's left at that hour's low. 300 random entry hours per league (seeded), at most 10 Divines and 10% of the hour's traded units per position.

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

## Still to do

Run the tools across all four exchange-era leagues and write up the patterns that repeat.
