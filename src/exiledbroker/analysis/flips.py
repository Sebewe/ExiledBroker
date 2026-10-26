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
from exiledbroker.services import missed
from exiledbroker.storage import db

H = timedelta(hours=1)
MAX_HOLD = 72  # hours an unsold position is kept listed
ENTRIES = 300  # random entry hours per league
CAPTURE = 0.10
TRADE_DIVINES = 10.0
TOP = 3
# The Market recap's flip rules (services/missed), so the page and the test agree.
MIN_VOLUME = missed.FLIP_MIN_VOLUME  # Chaos traded in the entry hour
MIN_PRICE = missed.MIN_PRICE
MAX_RANGE = missed.FLIP_MAX_RANGE
MIN_RANGE = missed.FLIP_MIN_RANGE
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


def chaos_prices(con, league: str) -> pl.DataFrame:
    """The same, from the Chaos market alone (cross_market_hour's Chaos side): the
    Divine market's whole-number trades of items worth a few Divines (2:1, 3:1) widen
    the combined range without being a price anyone can trade at in Chaos."""
    tracked = [r[0] for r in db.rows(con, "SELECT DISTINCT item_id FROM tracked_item")]
    return (
        db.frame(
            con,
            """
            SELECT item_id, observed_at, day_offset, chaos_price AS p, chaos_low AS lo,
                   chaos_high AS hi, chaos_volume AS units, chaos_price * chaos_volume AS cv
            FROM cross_market_hour
            WHERE league_id = (SELECT id FROM league WHERE name = ?) AND chaos_price > 0
            """,
            [league],
        )
        .filter(pl.col("item_id").is_in(tracked), pl.col("item_id") != bt.CHAOS)
        .with_columns(rng=(pl.col("hi") - pl.col("lo")) / pl.col("p"))
        .sort("observed_at")
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
    whole_lots: bool = False,
) -> pl.DataFrame:
    """One row per position bought: cost and value in Divines, profit, return, and
    `sold_at` (hours after the entry hour it sold out; MAX_HOLD + 1 if dumped).
    `whole_lots`: orders in whole Chaos for whole lots (`missed.whole`), filled lot by
    lot, the ask's total cut in whole Chaos."""
    at = pl.DataFrame({"observed_at": when}).cast({"observed_at": px.schema["observed_at"]})
    sig = (
        candidates(px.join(at, on="observed_at"))
        .sort(["observed_at", "rng"], descending=[False, True])
        .group_by("observed_at", maintain_order=True)
        .head(TOP)
    )
    return hold(px, rate, sig, model, bid_at, ask_at, cut, whole_lots)


def candidates(px: pl.DataFrame) -> pl.DataFrame:
    """The item-hours liquid and volatile enough for the Market recap to list a flip."""
    return px.filter(
        pl.col("cv") >= MIN_VOLUME,
        pl.col("p") >= MIN_PRICE,
        pl.col("rng") >= MIN_RANGE,
        pl.col("rng") <= MAX_RANGE,
    )


def hold(
    px: pl.DataFrame,
    rate: pl.DataFrame,
    sig: pl.DataFrame,
    model: str,
    bid_at: float = 0.1,
    ask_at: float = 0.75,
    cut: float = 0.02,
    whole_lots: bool = False,
    max_hold: int | None = None,
) -> pl.DataFrame:
    """`positions` for the entries `sig` (item-hours of `px`), each kept listed at most
    `max_hold` hours (MAX_HOLD by default). One row per position bought, keyed by its
    entry hour."""
    max_hold = MAX_HOLD if max_hold is None else max_hold
    sig = (
        sig.select("observed_at", "item_id", "lo", "hi")
        .with_columns(
            bid=pl.col("lo") + bid_at * (pl.col("hi") - pl.col("lo")),
            ask0=pl.col("lo") + ask_at * (pl.col("hi") - pl.col("lo")),
        )
        .select("observed_at", "item_id", "bid", "ask0")
    )
    if whole_lots:  # the Market recap's orders: whole Chaos for whole lots
        buy_lot, bid_total = missed.whole(pl.col("bid"), "buy")
        sell_lot, ask_total = missed.whole(pl.col("ask0"), "sell")
        sig = sig.with_columns(
            buy_lot=buy_lot, sell_lot=sell_lot, ask_total=ask_total, bid_total=bid_total
        ).with_columns(bid=pl.col("bid_total") / pl.col("buy_lot"))
    else:
        sig = sig.with_columns(buy_lot=pl.lit(1), sell_lot=pl.lit(1), ask_total=pl.col("ask0"))
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

    def lots(units: pl.Expr, lot: str) -> pl.Expr:
        return (units / pl.col(lot)).floor() * pl.col(lot)

    t = (
        t.with_columns(
            held=lots(
                pl.min_horizontal(
                    take(pl.col("bid"), "buy"),
                    (TRADE_DIVINES * pl.col("rate") / pl.col("bid")).floor(),
                ),
                "buy_lot",
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
    for k in range(2, 2 + max_hold):
        # The listing's total comes down each hour; with whole lots, in whole Chaos.
        total = pl.col("ask_total") * (1 - cut) ** (k - 2)
        ask = (total.ceil() if whole_lots else total) / pl.col("sell_lot")
        t = t.join(hour(k), on=["observed_at", "item_id"], how="left")
        sold = lots(pl.min_horizontal(pl.col("left"), take(ask, "sell")), "sell_lot")
        t = t.with_columns(got=pl.col("got") + sold * ask, left=pl.col("left") - sold)
        if k == 1 + max_hold:  # what's left is dumped at the last hour's low
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
