"""Stack impact and market depth: how much does dumping Q units move the price?
(finding 7 in docs/findings.md). Research only, on pages already on disk; feeds the
Farming page's `impact` and the sell helper's `sigma_h` (docs/farming.md).

The page estimates impact ≈ y · sigma_h · sqrt(Q / volume_h) (the square-root law). Here:
- `sigma_h`, an item's hourly volatility in one market, two ways: Parkinson from each
  hour's lowest and highest trade, and close-to-close from consecutive hours' averages;
- `y`, from how far an hour's price moves against how much traded in it, relative to
  the item's typical hour. GGG's volumes are unsigned (no buyer or seller side), so this
  measures how much busier hours move, not who pushed: a proxy, not a trade-level fit;
- what `lowest_stock` / `highest_stock` (not loaded today) add: whether traded volume
  over stock explains moves better than volume over typical volume, and whether the
  two sides' stock predicts the next hour.

    python -m exiledbroker.analysis.impact          # the tables in finding 7
"""

import math

import numpy as np
import polars as pl

from exiledbroker.analysis import backtest as bt
from exiledbroker.config import get_settings
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.normalize.tracked import CHAOS_METADATA, DIVINE_METADATA
from exiledbroker.storage import db

LAUNCH_DAYS = 14
MIN_HOURS = 48  # traded hours an item-market needs for its own sigma
MIN_PRICE = 1.0  # Chaos; cheaper items trade at coarse whole-number ratios
# Bins of volume over the item's typical (median) hour, for the impact curve.
BINS = (0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, math.inf)


def markets(con, settings, league: str) -> pl.DataFrame:
    """Every loaded hour's markets against Chaos and Divine for the league's items, one
    row per (hour, item, market) with a book, traded or not: units traded (`vol`), the
    average price in that market's currency (`p`, null untraded), the hour's lowest and
    highest price, and both sides' stock: units of the item on offer (`stock_x`) and of
    the currency (`stock_ref`), each at its lowest and highest in the hour."""
    hours = [
        cx.to_ts(r[0])
        for r in db.rows(
            con,
            "SELECT hour FROM exchange_hour_loaded "
            "WHERE league_id = (SELECT id FROM league WHERE name = ?) ORDER BY hour",
            [league],
        )
    ]
    rows = []
    for m in cx.market_rows(settings, league, hours):
        for x, ref, sx, sr in ((m["b"], m["a"], "b", "a"), (m["a"], m["b"], "a", "b")):
            if ref not in (CHAOS_METADATA, DIVINE_METADATA) or x in (CHAOS_METADATA,):
                continue
            if x == DIVINE_METADATA and ref == DIVINE_METADATA:
                continue
            rows.append(
                {
                    "hour": m["hour"],
                    "metadata_id": x,
                    "market": "chaos" if ref == CHAOS_METADATA else "divine",
                    "vol": m[f"volume_traded_{sx}"],
                    "vol_ref": m[f"volume_traded_{sr}"],
                    "lo_x": m[f"lowest_ratio_{sx}"],
                    "lo_ref": m[f"lowest_ratio_{sr}"],
                    "hi_x": m[f"highest_ratio_{sx}"],
                    "hi_ref": m[f"highest_ratio_{sr}"],
                    "stock_x_lo": m[f"lowest_stock_{sx}"],
                    "stock_x_hi": m[f"highest_stock_{sx}"],
                    "stock_ref_lo": m[f"lowest_stock_{sr}"],
                    "stock_ref_hi": m[f"highest_stock_{sr}"],
                }
            )
    names = db.frame(
        con, "SELECT id AS item_id, metadata_id FROM item WHERE metadata_id IS NOT NULL"
    )
    launched = db.scalar(con, "SELECT launched_at FROM league WHERE name = ?", [league])
    traded = (pl.col("vol") > 0) & (pl.col("vol_ref") > 0)
    a = pl.col("lo_ref") / pl.col("lo_x").replace(0, None)
    b = pl.col("hi_ref") / pl.col("hi_x").replace(0, None)
    return (
        pl.DataFrame(rows, infer_schema_length=None)
        .join(names, on="metadata_id")
        .with_columns(
            p=pl.when(traded).then(pl.col("vol_ref") / pl.col("vol")),
            lo=pl.when(traded).then(pl.min_horizontal(a, b)),
            hi=pl.when(traded).then(pl.max_horizontal(a, b)),
            day_offset=(pl.col("hour") - launched).dt.total_hours() / 24,
            league=pl.lit(league),
        )
        .drop("lo_x", "lo_ref", "hi_x", "hi_ref")
    )


def with_chaos_price(mk: pl.DataFrame, rate: pl.DataFrame) -> pl.DataFrame:
    """Adds `chaos` (the item's price in Chaos: the Divine market's at that hour's rate)
    and `cv` (Chaos traded), so both markets are measured the same way."""
    return (
        mk.join(rate.rename({"observed_at": "hour"}), on="hour", how="left")
        .with_columns(
            chaos=pl.when(pl.col("market") == "chaos")
            .then(pl.col("p"))
            .otherwise(pl.col("p") * pl.col("rate"))
        )
        .with_columns(cv=pl.col("chaos") * pl.col("vol"))
    )


def moves(mk: pl.DataFrame) -> pl.DataFrame:
    """Consecutive traded hours (exactly one hour apart) per item and market: `r`, the
    change in log average price; `lag_r`, the previous hour's (null unless that one was
    also an hour apart); `range`, ln(high / low) of the hour; the units traded over the
    item-market's median traded hour (`rel_vol`) and over the stock on offer at the
    hour's start, the previous hour's highest stock (`vol_stock`); and the previous
    hour's book `imbalance`: ln(currency bid / item offered, valued at the item's median
    price), less its mean for the item. The median price, not the previous hour's: with
    that, a high last price reads as a weak bid, and mean reversion poses as a signal."""
    t = mk.filter(pl.col("p").is_not_null() & (pl.col("p") > 0)).sort(
        "league", "item_id", "market", "hour"
    )
    by = ["league", "item_id", "market"]

    def prev(c: str) -> pl.Expr:
        return pl.col(c).shift(1).over(by)

    t = t.with_columns(
        gap=(pl.col("hour") - prev("hour")).dt.total_hours(),
        r=pl.col("p").log() - prev("p").log(),
        range=(pl.col("hi") / pl.col("lo")).log(),
        rel_vol=pl.col("vol") / pl.col("vol").median().over(by),
        vol_stock=pl.col("vol") / prev("stock_x_hi").replace(0, None),
        imbalance=(
            prev("stock_ref_hi") / (prev("stock_x_hi") * pl.col("p").median().over(by))
        ).log(),
    ).with_columns(
        lag_r=pl.when(prev("gap") == 1).then(prev("r")),
        imbalance=pl.when(pl.col("imbalance").is_finite()).then(pl.col("imbalance")),
    )
    return (
        t.filter(pl.col("gap") == 1)
        .drop("gap")
        .with_columns(imbalance=pl.col("imbalance") - pl.col("imbalance").mean().over(by))
    )


def sigmas(mv: pl.DataFrame) -> pl.DataFrame:
    """Per item and market with MIN_HOURS moves: close-to-close sigma (std of hourly log
    changes), Parkinson sigma (from each hour's high/low), the median Chaos traded an
    hour and the median price in Chaos."""
    return (
        mv.group_by("league", "item_id", "market")
        .agg(
            n=pl.len(),
            sigma_cc=pl.col("r").std(),
            sigma_pk=((pl.col("range") ** 2).mean() / (4 * math.log(2))).sqrt(),
            chaos_h=pl.col("cv").median(),
            chaos=pl.col("chaos").median(),
        )
        .filter(pl.col("n") >= MIN_HOURS)
    )


def impact_curve(mv: pl.DataFrame, sg: pl.DataFrame, x: str = "rel_vol") -> pl.DataFrame:
    """Mean |move| in units of the item's close-to-close sigma, by bin of `x` (volume over
    the typical hour, or over stock): the square-root law says it grows with sqrt(x)."""
    d = mv.join(
        sg.select("league", "item_id", "market", "sigma_cc"), on=["league", "item_id", "market"]
    )
    d = d.filter(pl.col(x).is_not_null() & (pl.col("sigma_cc") > 0)).with_columns(
        z=pl.col("r").abs() / pl.col("sigma_cc"),
        bin=pl.col(x).cut(list(BINS[1:-1]), left_closed=True),
    )
    return d.group_by("bin").agg(x=pl.col(x).median(), z=pl.col("z").mean(), n=pl.len()).sort("x")


def fit_y(mv: pl.DataFrame, sg: pl.DataFrame, x: str = "rel_vol") -> dict:
    """Least squares of |r| / sigma = a + y · sqrt(x) over moves: `a` is the move an hour
    has anyway (√(2/π) ≈ 0.8 for pure noise), `y` how much more each sqrt(x) adds; with
    the correlation of the two (`r`)."""
    d = (
        mv.join(
            sg.select("league", "item_id", "market", "sigma_cc"), on=["league", "item_id", "market"]
        )
        .filter(pl.col(x).is_not_null() & (pl.col("sigma_cc") > 0) & (pl.col(x) > 0))
        .select(z=pl.col("r").abs() / pl.col("sigma_cc"), s=pl.col(x).sqrt().clip(0, 4))
    )
    if d.height < 3:
        return {"a": math.nan, "y": math.nan, "r": math.nan, "n": d.height}
    z, s = d["z"].to_numpy(), d["s"].to_numpy()
    y, a = np.polyfit(s, z, 1)
    return {"a": float(a), "y": float(y), "r": float(np.corrcoef(s, z)[0, 1]), "n": d.height}


def imbalance_signal(mv: pl.DataFrame) -> dict:
    """Does the book's imbalance at the end of one hour predict the next hour's move,
    beyond the last move's reversal? Correlations with r of the imbalance and of the last
    move, the imbalance's coefficient with the last move held fixed, and the mean r in
    each quintile of imbalance."""
    d = mv.filter(pl.col("imbalance").is_not_null() & pl.col("lag_r").is_not_null())
    if d.height < 10:
        return {"corr": math.nan, "reversal": math.nan, "beta": math.nan, "quintiles": []}
    imb, lag, r = (d[c].to_numpy() for c in ("imbalance", "lag_r", "r"))
    beta = np.linalg.lstsq(np.column_stack([imb, lag, np.ones(len(r))]), r, rcond=None)[0]
    rank = pl.col("imbalance").rank("ordinal") - 1
    q = d.with_columns(qn=(rank * 5 // d.height + 1).cast(pl.String))
    return {
        "corr": float(np.corrcoef(imb, r)[0, 1]) if imb.std() > 0 else math.nan,
        "reversal": float(np.corrcoef(lag, r)[0, 1]),
        "beta": float(beta[0]),
        "quintiles": q.group_by("qn").agg(r=pl.col("r").mean(), n=pl.len()).sort("qn").to_dicts(),
    }


def liquid(mv: pl.DataFrame, units: float = 50, chaos: float = 2000) -> pl.DataFrame:
    """Moves of item-markets whose median traded hour has at least `units` units and
    `chaos` Chaos traded."""
    by = ["league", "item_id", "market"]
    keep = (
        mv.group_by(by)
        .agg(u=pl.col("vol").median(), c=pl.col("cv").median())
        .filter((pl.col("u") >= units) & (pl.col("c") >= chaos))
        .select(by)
    )
    return mv.join(keep, on=by)


def two_hour(mv: pl.DataFrame) -> pl.DataFrame:
    """Mean |move| over one hour and over two (the hour before to the hour after), by bin
    of volume over the typical hour: a lasting impact would grow with volume over two
    hours even where one hour's noise hides it."""
    by = ["league", "item_id", "market"]
    d = (
        mv.sort(*by, "hour")
        .with_columns(
            nxt=pl.col("r").shift(-1).over(by),
            gap=(pl.col("hour").shift(-1).over(by) - pl.col("hour")).dt.total_hours(),
        )
        .filter(pl.col("gap") == 1)
    )
    return (
        d.with_columns(bin=pl.col("rel_vol").cut(list(BINS[1:-1]), left_closed=True))
        .group_by("bin")
        .agg(
            x=pl.col("rel_vol").median(),
            one=pl.col("r").abs().mean(),
            two=(pl.col("r") + pl.col("nxt")).abs().mean(),
            n=pl.len(),
        )
        .sort("x")
    )


def depth(mk: pl.DataFrame) -> pl.DataFrame:
    """Chaos against Divine market for items with a book in both: the median per item of
    the Divine market's share of Chaos traded, its share of the hours traded, and both
    sides' stock in Chaos (item offered at the hour's price, currency bid)."""
    per = (
        mk.filter(pl.col("chaos").is_not_null())
        .group_by("league", "item_id", "market")
        .agg(
            cv=pl.col("cv").sum(),
            hours=pl.len(),
            offered=(pl.col("stock_x_hi") * pl.col("chaos")).median(),
        )
    )
    w = per.pivot(on="market", index=["league", "item_id"], values=["cv", "hours", "offered"])
    need = ["cv_chaos", "cv_divine", "hours_chaos", "hours_divine"]
    if not all(c in w.columns for c in need):
        return pl.DataFrame()
    return w.drop_nulls(need).with_columns(
        divine_share=pl.col("cv_divine") / (pl.col("cv_chaos") + pl.col("cv_divine")),
        divine_hours=pl.col("hours_divine") / pl.col("hours_chaos"),
        offered_ratio=pl.col("offered_divine") / pl.col("offered_chaos"),
    )


def stock_cost(mk: pl.DataFrame, cross_rows: int) -> dict:
    """What loading the stock fields would add to `cross_market_hour`: 4 integers a leg
    (lowest and highest stock of the item and of the currency), two legs a row, 8 bytes
    each; for `cross_rows` rows. Rows with a book but no trade aren't in that table."""
    per_row = 2 * 4 * 8
    return {"bytes_per_row": per_row, "rows": cross_rows, "mb": cross_rows * per_row / 1e6}


def main() -> None:
    settings = get_settings()
    con = db.connect(settings.db_path, read_only=True)
    leagues = bt.hourly_leagues(con)
    mk = pl.concat(
        [with_chaos_price(markets(con, settings, lg), bt._rate(con, lg)) for lg in leagues],
        how="diagonal_relaxed",
    )
    mk = mk.filter(pl.col("chaos").is_null() | (pl.col("chaos") >= MIN_PRICE))
    mv = moves(mk)
    sg = sigmas(mv)
    print(f"{mk.height} market-hours, {mv.height} hour-to-hour moves, {sg.height} item-markets")

    print("\n== sigma_h: close-to-close vs Parkinson (median over item-markets) ==")
    for (market,), g in sg.group_by("market"):
        ratio = (g["sigma_cc"] / g["sigma_pk"]).median()
        rank = g.select(pl.corr("sigma_cc", "sigma_pk", method="spearman"))[0, 0]
        print(
            f"{market:6s} n={g.height:5d} close-to-close {g['sigma_cc'].median():.3f} "
            f"Parkinson {g['sigma_pk'].median():.3f} ratio {ratio:.2f} rank corr {rank:.2f}"
        )
    for lo, hi in ((1, 10), (10, 100), (100, 1e9)):
        g = sg.filter(
            (pl.col("market") == "chaos") & pl.col("chaos").is_between(lo, hi, closed="left")
        )
        print(
            f"  Chaos market, {lo:g}–{hi:g}c: sigma_cc {g['sigma_cc'].median():.3f} "
            f"Parkinson {g['sigma_pk'].median():.3f} ({g.height} items)"
        )
    print("  by phase (Chaos market, median sigma_cc over items):")
    for name, a, b in (
        ("days 0-2", 0, 2),
        ("days 2-7", 2, 7),
        ("days 7-14", 7, 14),
        ("later", 14, 1e9),
    ):
        s = sigmas(mv.filter(pl.col("day_offset").is_between(a, b, closed="left")))
        s = s.filter(pl.col("market") == "chaos")
        if s.height:
            print(f"    {name:9s} {s['sigma_cc'].median():.3f} ({s.height})")

    print("\n== impact: mean |move| / sigma by volume over the typical hour ==")
    for (market,), g in mv.group_by("market"):
        print(f"-- {market}")
        print(impact_curve(g, sg))
        print("   fit:", fit_y(g, sg))
        print("   fit on volume / stock:", fit_y(g, sg, "vol_stock"))
    print(impact_curve(mv.filter(pl.col("market") == "chaos"), sg, "vol_stock"))
    print("by phase (Chaos market):")
    for name, a, b in (
        ("days 0-2", 0, 2),
        ("days 2-7", 2, 7),
        ("days 7-14", 7, 14),
        ("later", 14, 1e9),
    ):
        g = mv.filter(
            (pl.col("market") == "chaos") & pl.col("day_offset").is_between(a, b, closed="left")
        )
        print(f"  {name:9s}", fit_y(g, sg))
    print("by league (Chaos market):")
    for lg in leagues:
        g = mv.filter((pl.col("market") == "chaos") & (pl.col("league") == lg))
        print(f"  {lg:11s}", fit_y(g, sg))

    print("\n== liquid items only (≥ 50 units and 2000c a typical hour), Chaos market ==")
    liq = liquid(mv.filter(pl.col("market") == "chaos"))
    print(f"{liq['item_id'].n_unique()} items, {liq.height} moves; fit:", fit_y(liq, sg))
    print(two_hour(liq))

    print("\n== book imbalance → next hour's move, with the last move's reversal ==")
    for (market,), g in mv.group_by("market"):
        s = imbalance_signal(g)
        print(
            f"{market:6s} corr {s['corr']:+.3f} reversal {s['reversal']:+.3f} "
            f"beta {s['beta']:+.4f} |",
            " ".join(f"Q{q['qn']} {q['r']:+.4f}" for q in s["quintiles"]),
        )
    for lg in leagues:
        s = imbalance_signal(mv.filter((pl.col("market") == "chaos") & (pl.col("league") == lg)))
        print(f"  {lg:11s} corr {s['corr']:+.3f} reversal {s['reversal']:+.3f}")

    print("\n== Chaos vs Divine market, items with both ==")
    dp = depth(mk)
    if dp.height:
        print(
            dp.select(
                items=pl.len(),
                divine_share=pl.col("divine_share").median(),
                divine_hours=pl.col("divine_hours").median(),
                offered_ratio=pl.col("offered_ratio").median(),
            )
        )
        sw = sg.pivot(on="market", index=["league", "item_id"], values="sigma_cc").drop_nulls()
        print(
            f"sigma_cc Divine / Chaos, same item: {(sw['divine'] / sw['chaos']).median():.2f} "
            f"({sw.height} items)"
        )

    rows = db.scalar(
        con,
        "SELECT count(*) FROM cross_market_hour "
        "WHERE league_id = (SELECT id FROM league WHERE name = ?)",
        [leagues[-1]],
    )
    print(f"\n== stock fields' cost for {leagues[-1]}'s window ==", stock_cost(mk, rows))


if __name__ == "__main__":
    main()
