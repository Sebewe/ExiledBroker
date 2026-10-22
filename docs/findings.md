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

*`cross_market.summarize` / `across_leagues` (the Arbitrage page). All four exchange-era leagues.*

- **How common:** 63k–86k item-hours per league traded in both the Chaos and the Divine market.
- **The gap:** the median price via Divines (X/Divine price × the hour's rate) was **13–19% above** the direct Chaos price.
- **It survives worst-case prices.** Chaos → item → Divines → Chaos, buying at the hour's highest Chaos price, selling at its lowest Divine price and converting at its lowest rate, was still positive in **15–26% of item-hours** (over +2% in 14–25%). The reverse loop was positive in about 1%, so the premium runs one way.
- **Recurring in all four leagues** (share of hours positive in the worst league): Rogue's Marker (66%), Essence Scarab of Stability (47%), Tainted Jeweller's Orb (46%), Timeless Eternal and Karui Emblems (~36%), Enkindling Orb (26%).
- **With the page's defaults** (2% buffer, 1c floor): the Chaos-first loop paid in 17.2% of 297,778 cross-market item-hours, Divines-first in 0.9%. 21 items paid in at least 25% of hours in every league. Even a 50% buffer leaves 6.2% paying, which is the first thing to check in-game: an edge that size is either a persistent mispricing or a quirk of how GGG reports ratios.
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

## Still to do

Run the tools across all four exchange-era leagues and write up the patterns that repeat.
