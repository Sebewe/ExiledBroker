"""Patient flips on volatile items: enter at a random hour, list high, cut the ask hourly
(finding 5 in docs/findings.md). Research only, on the local database; not on the site.

At each entry hour H (picked at random in a league's first 14 days, leaving MAX_HOLD
hours after it) the trader takes the top 3 liquid volatile items as the Market recap
ranks them: the widest traded range (high − low over the average) among items with at
least MIN_VOLUME Chaos traded that hour, a price of at least MIN_PRICE and a range of at
most MAX_RANGE (wider ranges are almost always one odd trade). Orders are priced from
H's range, 0 at its lowest trade and 1 at its highest:
- a bid `bid_at` up, filled in H+1 or cancelled;
- an ask `ask_at` up from H+2 on, cut by `cut` every hour it doesn't sell out, until
  MAX_HOLD hours have passed; what's left is then dumped at that hour's low (lost if
  the item doesn't trade).

Hourly data shows each hour's average, lowest and highest trade, not how much traded at
each price, so every fill goes through one of four models (`share_past`):
- touch: a trade went past the price, and the order takes up to CAPTURE of the units;
- even: volume spread evenly over the hour's range, the order taking CAPTURE of the
  share past its price;
- peaked: the same with volume in a triangle peaked at the hour's average;
- strict: the hour's average went past the price; up to CAPTURE of the units.
At most TRADE_DIVINES a position. Sales can be partial; the rest stays listed.

    python -m exiledbroker.analysis.flips          # the tables in finding 5
"""

import random
from datetime import timedelta

import polars as pl

from exiledbroker.analysis import backtest as bt
from exiledbroker.config import get_settings
from exiledbroker.storage import db

H = timedelta(hours=1)
MAX_HOLD = 72  # hours an unsold position is kept listed
ENTRIES = 300  # random entry hours per league
CAPTURE = 0.10
TRADE_DIVINES = 10.0
TOP = 3
MIN_VOLUME = 10_000.0  # Chaos traded in the entry hour
MIN_PRICE = 5.0
MAX_RANGE = 0.5
MODELS = ("touch", "even", "peaked", "strict")


def share_past(model: str, price: pl.Expr, side: str) -> pl.Expr:
    """Share of an hour's units traded past `price` (below it for a buy, above for a
    sale), from that hour's `lo_`, `p_` (average) and `hi_` columns."""
    lo, p, hi = pl.col("lo_"), pl.col("p_"), pl.col("hi_")
    if model in ("touch", "strict"):
        edge = lo if model == "touch" else p
        edge = edge if side == "buy" else (hi if model == "touch" else p)
        hit = price > edge if side == "buy" else price < edge
        return pl.when(hit).then(1.0).otherwise(0.0)
    if model == "even":
        below = ((price - lo) / (hi - lo)).clip(0, 1)
    else:  # peaked: a triangle from lo to hi, its peak at the hour's average
        below = (
            pl.when(price <= lo)
            .then(0.0)
            .when(price >= hi)
            .then(1.0)
            .when(price <= p)
            .then((price - lo) ** 2 / ((hi - lo) * (p - lo)))
            .otherwise(1 - (hi - price) ** 2 / ((hi - lo) * (hi - p)))
        )
    below = below.fill_nan(0.0)
    return below if side == "buy" else 1 - below


def prices(con, league: str) -> pl.DataFrame:
    """A league's hourly prices of the tracked items, with each hour's range."""
    tracked = [r[0] for r in db.rows(con, "SELECT DISTINCT item_id FROM tracked_item")]
    return (
        bt._prices(con, league)
        .filter(pl.col("item_id").is_in(tracked), pl.col("item_id") != bt.CHAOS)
        .with_columns(rng=(pl.col("hi") - pl.col("lo")) / pl.col("p"))
    )


def entry_hours(px: pl.DataFrame, league: str, seed: int = 7, n: int = ENTRIES) -> list:
    """`n` random hours in the first 14 days with MAX_HOLD hours after them."""
    last = 14 - (MAX_HOLD + 2) / 24
    hours = sorted(px.filter(pl.col("day_offset") < last)["observed_at"].unique().to_list())
    return sorted(random.Random(f"{seed}-{league}").sample(hours, min(n, len(hours))))


def positions(
    px: pl.DataFrame,
    rate: pl.DataFrame,
    when: list,
    model: str,
    bid_at: float = 0.1,
    ask_at: float = 0.75,
    cut: float = 0.02,
) -> pl.DataFrame:
    """One row per position bought: cost and value in Divines, profit, return, and
    `sold_at` (hours after the entry hour it sold out; MAX_HOLD + 1 if dumped)."""
    at = pl.DataFrame({"observed_at": when}).cast({"observed_at": px.schema["observed_at"]})
    sig = (
        px.join(at, on="observed_at")
        .filter(
            pl.col("cv") >= MIN_VOLUME,
            pl.col("p") >= MIN_PRICE,
            pl.col("rng") > 0,
            pl.col("rng") <= MAX_RANGE,
        )
        .sort(["observed_at", "rng"], descending=[False, True])
        .group_by("observed_at", maintain_order=True)
        .head(TOP)
        .with_columns(
            bid=pl.col("lo") + bid_at * (pl.col("hi") - pl.col("lo")),
            ask0=pl.col("lo") + ask_at * (pl.col("hi") - pl.col("lo")),
        )
        .select("observed_at", "item_id", "bid", "ask0")
    )
    items = px.join(sig.select("item_id").unique(), on="item_id")

    def hour(k: int) -> pl.DataFrame:
        """Each item's prices k hours after the entry hour, keyed by the entry hour."""
        return items.select(
            "item_id",
            observed_at=pl.col("observed_at") - k * H,
            p_="p",
            lo_="lo",
            hi_="hi",
            units_="units",
        )

    def take(price: pl.Expr, side: str) -> pl.Expr:
        share = share_past(model, price, side).fill_null(0)
        return (pl.col("units_").fill_null(0) * CAPTURE * share).floor()

    hour_cols = ["p_", "lo_", "hi_", "units_"]
    t = sig.join(hour(1), on=["observed_at", "item_id"], how="left").join(
        rate.select(observed_at=pl.col("observed_at") - H, rate="rate"), on="observed_at"
    )
    t = (
        t.with_columns(
            held=pl.min_horizontal(
                take(pl.col("bid"), "buy"), (TRADE_DIVINES * pl.col("rate") / pl.col("bid")).floor()
            ).fill_null(0)
        )
        .drop(hour_cols)
        .filter(pl.col("held") >= 1)
        .with_columns(
            left=pl.col("held").cast(pl.Float64),
            got=pl.lit(0.0),
            sold_at=pl.lit(None, dtype=pl.Int64),
        )
    )
    for k in range(2, 2 + MAX_HOLD):
        ask = pl.col("ask0") * (1 - cut) ** (k - 2)
        t = t.join(hour(k), on=["observed_at", "item_id"], how="left")
        sold = pl.min_horizontal(pl.col("left"), take(ask, "sell"))
        t = t.with_columns(got=pl.col("got") + sold * ask, left=pl.col("left") - sold)
        if k == 1 + MAX_HOLD:  # what's left is dumped at the last hour's low
            t = t.with_columns(
                got=pl.col("got") + pl.col("left") * pl.col("lo_").fill_null(0),
                dumped=pl.col("left") > 0,
                left=pl.lit(0.0),
            )
        t = t.with_columns(
            sold_at=pl.when(pl.col("sold_at").is_null() & (pl.col("left") <= 0))
            .then(k)
            .otherwise(pl.col("sold_at"))
        ).drop(hour_cols)
    return t.with_columns(
        cost=pl.col("held") * pl.col("bid") / pl.col("rate"),
        value=pl.col("got") / pl.col("rate"),
    ).with_columns(
        profit=pl.col("value") - pl.col("cost"), ret=pl.col("value") / pl.col("cost") - 1
    )


def summary(t: pl.DataFrame, tried: int) -> dict:
    """Totals over positions: how many bought of those tried, the share that made money,
    median and overall return (profit over cost), median hours to sell out, share dumped."""
    if t.is_empty():
        return {"tried": tried, "bought": 0}
    return {
        "tried": tried,
        "bought": t.height,
        "won": float((t["profit"] > 0).mean()),
        "median_return": float(t["ret"].median()),
        "return": float(t["profit"].sum() / t["cost"].sum()),
        "profit": float(t["profit"].sum()),
        "hours": float(t["sold_at"].median()),
        "dumped": float(t["dumped"].mean()),
    }


def main() -> None:
    con = db.connect(get_settings().db_path, read_only=True)
    leagues = bt.hourly_leagues(con)
    data = {lg: (prices(con, lg), bt._rate(con, lg)) for lg in leagues}
    for model in MODELS:
        for bid_at, ask_at, cut in (
            (0.1, 0.75, 0.01),
            (0.1, 0.75, 0.02),
            (0.1, 0.75, 0.05),
            (0.1, 0.75, 0.10),
            (0.1, 0.9, 0.01),
            (0.25, 0.75, 0.01),
        ):
            per = []
            for lg, (px, rate) in data.items():
                per.append(positions(px, rate, entry_hours(px, lg), model, bid_at, ask_at, cut))
            s = summary(pl.concat(per), ENTRIES * TOP * len(data))
            leagues_ret = " ".join(
                f"{(t['profit'].sum() / t['cost'].sum()):+.0%}" if t.height else "–" for t in per
            )
            print(
                f"{model:6s} bid {bid_at:.2f} ask {ask_at:.2f} cut {cut:4.0%}/h: "
                f"bought {s['bought']}/{s['tried']}, "
                + (
                    f"won {s['won']:.0%}, return {s['return']:+.1%}, "
                    f"median {s['hours']:.0f}h to sell, {s['dumped']:.0%} dumped | {leagues_ret}"
                    if s["bought"]
                    else "nothing bought"
                )
            )


if __name__ == "__main__":
    main()
