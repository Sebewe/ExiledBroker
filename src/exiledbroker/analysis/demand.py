"""Demand: is an item drawing buyers or being dumped, and does that pay? (finding 11 in
docs/findings.md; workstream A of docs/demand.md).

Research on a local copy of the database and the pages already on disk; read-only, no
requests. Per league, core-pool item and loaded hour `t`:

- **Readings** (`readings`), over the window t−5..t (`W` hours, both legs): value traded
  in Divine-equivalent (`v6`) and in units (`u6`) against the same window on the previous
  `BASE_DAYS` days (`ratio`, `uratio`: needs `BASE_MIN` earlier days), the 6-hour price
  move in Divines (`m6`), and the 24-hour and 3-day moves (`m24`, `m72`). Liquid is the
  Market recap's rule (`services/missed.MIN_VOLUME` Chaos traded an hour, here averaged
  over the window, and `MIN_PRICE`).
- **Outcomes** start after the decision, since hour `t` is published only after it ends:
  entry is the median price over t+1..t+3, exit the same three hours 24 or 72 hours later
  (`y24`, `y72`, log, clipped at ±`CLIP`). Harsh: buy at the entry hours' median high and
  sell at the exit hours' median low (`yh*`); for a holder, sell at the low now against
  the low later (`ys*`). `with_excess` subtracts the same league-hour's median over liquid
  items (`x*`; most items fall in Divines over the fortnight, finding 10), adds the volume
  ratio relative to that hour's market (`rel`) and the 3-day move against the market
  (`rm72`, quintile `q72`).
- **Stock** (`stock`, `stock_features`): each market's `lowest_stock` / `highest_stock`
  read from the stored pages (`impact.markets`), summed over both legs: sellers' units
  (`S6`) and buyers' currency in Divines (`B6`), the imbalance change against the same
  hours on earlier days (`dI`) and the **drain**, the 6-hour mean of 1 − lowest ÷ highest
  of the sellers' stock (how far trading emptied the book within the hour).
- **Labels** (`labels`): "Demand rising" (`ratio ≥ 3`, `m6 ≥ +10%`), "Being dumped"
  (`rel ≥ 3`, `m6 ≤ −10%`), and "rising on a calm book" (rising with `drain ≤ 0.4` and
  `dI ≥ 0`). The defaults are the leave-one-league-out choices of finding 11; `lolo`
  re-chooses them on the other leagues and scores the held-out one, `summary` reports raw
  and excess means, hit rates and a block bootstrap over league-days.

None of the labels is shipped: finding 11 explains why.

    python -m exiledbroker.analysis.demand <db copy> [--stock]   # finding 11's label tables
"""

import itertools
import sys

import duckdb
import numpy as np
import polars as pl

from exiledbroker.analysis import impact
from exiledbroker.analysis import price_outlook as po
from exiledbroker.services.missed import MIN_PRICE, MIN_VOLUME
from exiledbroker.storage import db

W = 6  # reading window, hours (t-5..t)
FWD = 3  # entry and exit: the median of 3 hours
CLIP = 1.0  # log changes clipped to ±1
BASE_DAYS = 3  # the baseline: the same window on the previous 3 days...
BASE_MIN = 1  # ... needing at least 1 (so readings start on day 1)
LAUNCH_DAYS = 14
RISING = {"ratio": 3.0, "move": 0.10}
DUMPED = {"rel": 3.0, "move": 0.10}
CALM = {"drain": 0.4, "dI": 0.0}
# The grid `lolo` chooses from (finding 11: 54 configurations a label in the first pass).
RATIOS = (1.5, 2.0, 3.0)
MOVES = (0.03, 0.05, 0.10)
MIN_TRAIN_N = 50  # signals each training league needs for a configuration to be eligible
OUTCOMES = ("y24", "y72", "yh24", "yh72", "ys24", "ys72")


def load(con, league: str) -> tuple[pl.DataFrame, pl.DataFrame]:
    """A league's `cross_market_hour` rows (hour since launch) and each loaded hour's
    Divine rate."""
    lid = "(SELECT id FROM league WHERE name = ?)"
    rows = db.frame(
        con,
        f"""
        SELECT c.item_id, coalesce(i.category, 'other') AS grp,
               CAST(round(c.day_offset * 24) AS INTEGER) AS hour,
               c.chaos_price, c.chaos_volume, c.chaos_low, c.chaos_high,
               c.divine_price, c.divine_volume
        FROM cross_market_hour c LEFT JOIN item i ON i.id = c.item_id
        WHERE c.league_id = {lid}
        """,
        [league],
    )
    hours = db.frame(
        con,
        f"""
        SELECT CAST(round(day_offset * 24) AS INTEGER) AS hour,
               median(divine_rate) FILTER (WHERE divine_rate > 0) AS rate
        FROM cross_market_hour WHERE league_id = {lid} GROUP BY 1
        """,
        [league],
    )
    return rows, hours


def _clock(hours: pl.DataFrame) -> pl.DataFrame:
    """Every hour from the first to the last loaded one; `loaded` marks the loaded ones
    (an unloaded hour is unknown, not zero), the Divine rate carried forward."""
    hours = hours.with_columns(pl.col("hour").cast(pl.Int32))
    span = pl.int_range(hours["hour"].min(), hours["hour"].max() + 1, dtype=pl.Int32, eager=True)
    return (
        pl.DataFrame({"hour": span})
        .join(hours.with_columns(loaded=pl.lit(True)), on="hour", how="left")
        .sort("hour")
        .with_columns(pl.col("loaded").fill_null(False), pl.col("rate").forward_fill())
    )


def _baseline(col: str) -> pl.Expr:
    """Median of `col` at t−24k, k = 1..BASE_DAYS, if at least BASE_MIN exist."""
    prev = pl.concat_list(
        [pl.col(col).shift(24 * k).over("item_id") for k in range(1, BASE_DAYS + 1)]
    )
    prev = prev.list.drop_nulls()
    return pl.when(prev.list.len() >= BASE_MIN).then(prev.list.median())


def readings(league: str, rows: pl.DataFrame, hours: pl.DataFrame) -> pl.DataFrame:
    """One row per item and loaded hour with a price or trades in its window: the
    readings (hours ≤ t only) and the outcomes (hours > t only)."""
    clock = _clock(hours)
    g = (
        rows.select("item_id", "grp")
        .unique("item_id")
        .join(clock, how="cross")
        .join(
            rows.drop("grp").with_columns(pl.col("hour").cast(pl.Int32)),
            on=["item_id", "hour"],
            how="left",
        )
        .sort("item_id", "hour")
    )
    traded = (pl.col("chaos_price") > 0) & (pl.col("chaos_volume") > 0)
    chaos_value = pl.when(traded).then(pl.col("chaos_price") * pl.col("chaos_volume"))
    loaded = pl.col("loaded")
    g = g.with_columns(
        p=pl.when(traded).then(pl.col("chaos_price") / pl.col("rate")),
        pc=pl.when(traded).then(pl.col("chaos_price")),
        hi=pl.when(traded).then(pl.col("chaos_high") / pl.col("rate")),
        lo=pl.when(traded).then(pl.col("chaos_low") / pl.col("rate")),
        cv=pl.when(loaded).then(chaos_value.fill_null(0.0)),
        vd=pl.when(loaded).then(
            chaos_value.fill_null(0.0) / pl.col("rate")
            + (pl.col("divine_price") * pl.col("divine_volume")).fill_null(0.0)
        ),
        units=pl.when(loaded).then(
            pl.when(traded).then(pl.col("chaos_volume")).otherwise(0).cast(pl.Float64)
            + pl.col("divine_volume").fill_null(0).cast(pl.Float64)
        ),
    )
    o = "item_id"
    g = g.with_columns(
        v6=pl.col("vd").rolling_sum(W, min_samples=W).over(o),
        u6=pl.col("units").rolling_sum(W, min_samples=W).over(o),
        cv6=pl.col("cv").rolling_mean(W, min_samples=W).over(o),
        s6=pl.col("p").rolling_median(W, min_samples=2).over(o),
        s6c=pl.col("pc").rolling_median(W, min_samples=2).over(o),
    )

    def move(k: int) -> pl.Expr:
        return (pl.col("s6") / pl.col("s6").shift(k).over(o)).log().clip(-CLIP, CLIP)

    g = g.with_columns(
        m6=move(W), m24=move(24), m72=move(72), base=_baseline("v6"), ubase=_baseline("u6")
    ).with_columns(
        ratio=pl.when(pl.col("base") > 0).then(pl.col("v6") / pl.col("base")),
        uratio=pl.when(pl.col("ubase") > 0).then(pl.col("u6") / pl.col("ubase")),
    )
    med = {c: pl.col(c).rolling_median(FWD, min_samples=2).over(o) for c in ("p", "hi", "lo")}
    g = g.with_columns(_p=med["p"], _hi=med["hi"], _lo=med["lo"])

    def ahead(c: str, h: int) -> pl.Expr:  # the median over hours t+h+1..t+h+3
        return pl.col(c).shift(-FWD - h).over(o)

    out = {}
    for h in (24, 72):
        out[f"y{h}"] = (ahead("_p", h) / ahead("_p", 0)).log().clip(-CLIP, CLIP)
        out[f"yh{h}"] = (ahead("_lo", h) / ahead("_hi", 0)).log().clip(-CLIP, CLIP)
        out[f"ys{h}"] = (ahead("_lo", h) / ahead("_lo", 0)).log().clip(-CLIP, CLIP)
    g = g.with_columns(**out).with_columns(
        league=pl.lit(league),
        day=pl.col("hour") / 24.0,
        liquid=((pl.col("cv6") >= MIN_VOLUME) & (pl.col("s6c") >= MIN_PRICE)).fill_null(False),
    )
    return g.filter(loaded, pl.col("s6").is_not_null() | (pl.col("v6") > 0)).select(
        "league", "item_id", "grp", "hour", "day", "rate", "s6", "s6c", "m6", "m24", "m72",
        "v6", "u6", "cv6", "base", "ratio", "uratio", "liquid", *OUTCOMES,
    )  # fmt: skip


def with_excess(df: pl.DataFrame) -> pl.DataFrame:
    """Adds each outcome's excess over the same league-hour's median among liquid items
    (`x24`, `xh24`, ...), the volume ratio relative to that hour's (`rel`), and the 3-day
    move against it (`rm72`) with its quintile among liquid items (`q72`, 1 = weakest)."""
    key = ["league", "hour"]
    mkt = (
        df.filter("liquid")
        .group_by(key)
        .agg(
            *[pl.col(c).median().alias(f"mkt_{c}") for c in OUTCOMES],
            mkt_ratio=pl.col("ratio").median(),
            mkt_m72=pl.col("m72").median(),
        )
    )
    df = df.join(mkt, on=key, how="left").with_columns(
        **{f"x{c[1:]}": pl.col(c) - pl.col(f"mkt_{c}") for c in OUTCOMES},
        rel=pl.col("ratio") / pl.col("mkt_ratio"),
        rm72=pl.col("m72") - pl.col("mkt_m72"),
    )
    ranked = pl.col("liquid") & pl.col("rm72").is_not_null()
    rank = pl.when(ranked).then(pl.col("rm72")).rank("ordinal").over(key)
    n = ranked.sum().over(key)
    return df.with_columns(q72=pl.when(ranked).then((5 * (rank - 1) // n + 1).cast(pl.Int8)))


def stock(con, settings, league: str) -> pl.DataFrame:
    """Each loaded hour's stock per item, both legs summed, from the stored pages (no
    requests): sellers' units on offer at the hour's fullest and thinnest (`sell_hi`,
    `sell_lo`), and buyers' currency in Divines (`buy_hi`, `buy_lo`; a Chaos leg's at the
    hour's Divine rate). `impact.markets` reads the pages."""
    mk = impact.markets(con, settings, league).with_columns(
        hour=(pl.col("day_offset") * 24).round().cast(pl.Int32)
    )
    _rows, hours = load(con, league)
    return stock_per_hour(mk, hours)


def stock_per_hour(mk: pl.DataFrame, hours: pl.DataFrame) -> pl.DataFrame:
    """`impact.markets` rows (with `hour`) summed per item and hour, buyers' side in
    Divines at the hour's rate (carried forward)."""
    rate = _clock(hours).select("hour", "rate")
    chaos = pl.col("market") == "chaos"
    ref = {
        side: pl.when(chaos).then(pl.col(f"stock_ref_{side}") / pl.col("rate"))
        .otherwise(pl.col(f"stock_ref_{side}").cast(pl.Float64))
        for side in ("hi", "lo")
    }  # fmt: skip
    return (
        mk.join(rate, on="hour", how="left")
        .group_by("item_id", "hour")
        .agg(
            sell_hi=pl.col("stock_x_hi").sum().cast(pl.Float64),
            sell_lo=pl.col("stock_x_lo").sum().cast(pl.Float64),
            buy_hi=ref["hi"].sum(),
            buy_lo=ref["lo"].sum(),
        )
        .sort("item_id", "hour")
    )


def stock_features(st: pl.DataFrame, rd: pl.DataFrame) -> pl.DataFrame:
    """`rd` (one league's readings) with the stock features over the same window: `S6`
    and `B6` (6-hour means of sellers' units and buyers' Divines), `imb` (log of buyers'
    Divines over sellers' stock valued at `s6`), `dI` (its change against the same window
    on earlier days, which takes the price out) and `drain6`. An hour is loaded if its
    page listed any market (it's in `st`); there, a market missing from the page counts
    as an empty book, while an unloaded hour stays unknown."""
    o = "item_id"
    clock = _clock(st.select("hour").unique().with_columns(rate=pl.lit(None, pl.Float64)))
    vals = ["sell_hi", "sell_lo", "buy_hi", "buy_lo"]
    g = (
        rd.select("item_id")
        .unique()
        .join(clock.select("hour", "loaded"), how="cross")
        .join(st, on=["item_id", "hour"], how="left")
        .join(rd.select("item_id", "hour", "s6"), on=["item_id", "hour"], how="left")
        .with_columns(pl.when("loaded").then(pl.col(c).fill_null(0.0)).alias(c) for c in vals)
        .sort("item_id", "hour")
    )
    g = g.with_columns(
        drain=pl.when(pl.col("sell_hi") > 0).then(1 - pl.col("sell_lo") / pl.col("sell_hi")),
        S6=pl.col("sell_hi").rolling_mean(W, min_samples=W).over(o),
        B6=pl.col("buy_hi").rolling_mean(W, min_samples=W).over(o),
    ).with_columns(
        drain6=pl.col("drain").rolling_mean(W, min_samples=3).over(o),
        lI=pl.when((pl.col("B6") > 0) & (pl.col("S6") > 0)).then(
            (pl.col("B6") / pl.col("S6")).log()
        ),
    )
    g = g.with_columns(
        imb=pl.when(pl.col("s6") > 0).then(pl.col("lI") - pl.col("s6").log()),
        dI=(pl.col("lI") - _baseline("lI")).clip(-3, 3),
    )
    return rd.join(
        g.select("item_id", "hour", "S6", "B6", "imb", "dI", "drain6"),
        on=["item_id", "hour"],
        how="left",
    )


def labels(df: pl.DataFrame, rising=RISING, dumped=DUMPED, calm=CALM) -> pl.DataFrame:
    """Boolean label columns (null inputs never label)."""
    up = (pl.col("ratio") >= rising["ratio"]) & (pl.col("m6") >= rising["move"])
    out = {
        "rising": up.fill_null(False),
        "dumped": ((pl.col("rel") >= dumped["rel"]) & (pl.col("m6") <= -dumped["move"])).fill_null(
            False
        ),
    }
    if "drain6" in df.columns:
        calm_book = (pl.col("drain6") <= calm["drain"]) & (pl.col("dI") >= calm["dI"])
        out["calm_rising"] = (up & calm_book).fill_null(False)
    if "q72" in df.columns:
        out["lagging"] = (pl.col("q72") == 1).fill_null(False)
        out["leading"] = (pl.col("q72") == 5).fill_null(False)
    return df.with_columns(**out)


def boot_ci(sig: pl.DataFrame, col: str, block_days: int = 1, n: int = 1000, seed: int = 7):
    """95% interval of the mean of `col`, resampling blocks of `block_days` league-days
    (outcomes overlap across neighbouring hours and days, so wider blocks are honester)."""
    g = (
        sig.filter(pl.col(col).is_not_null())
        .with_columns(block=(pl.col("hour") // (24 * block_days)))
        .group_by("league", "block")
        .agg(s=pl.col(col).sum(), k=pl.len())
    )
    if g.height < 3:
        return (float("nan"), float("nan"))
    s, k = g["s"].to_numpy(), g["k"].to_numpy()
    idx = np.random.default_rng(seed).integers(0, len(s), size=(n, len(s)))
    return tuple(np.percentile(s[idx].sum(1) / k[idx].sum(1), [2.5, 97.5]))


def summary(sig: pl.DataFrame, h: str = "24", sign: int = 1, block_days: int = 1) -> dict:
    """A label's signals (rows where it's set): count, raw and excess mean, hit rates
    (the move in the label's direction), harsh mean, the interval of the excess, and the
    leagues where the excess has the label's sign."""
    y, x = f"y{h}", f"x{h}"
    sig = sig.filter(pl.col(y).is_not_null(), pl.col(x).is_not_null())
    if sig.height == 0:
        return {"n": 0}
    harsh = f"yh{h}" if sign > 0 else f"ys{h}"
    out = sig.select(
        n=pl.len(),
        items=pl.col("item_id").n_unique(),
        raw=pl.col(y).mean(),
        hit=((pl.col(y) * sign) > 0).mean(),
        excess=pl.col(x).mean(),
        hit_excess=((pl.col(x) * sign) > 0).mean(),
        harsh=pl.col(harsh).mean(),
    ).to_dicts()[0]
    out["lo"], out["hi"] = boot_ci(sig, x, block_days)
    per = sig.group_by("league").agg(pl.col(x).mean())
    out["leagues"] = int((per[x] * sign > 0).sum())
    out["of"] = per.height
    return out


def lolo(df: pl.DataFrame, make, cfgs, sign: int, h: str = "24") -> pl.DataFrame:
    """Leave one league out: for each league, the configuration (from `cfgs`; `make(cfg)`
    is the label's expression) with the best mean excess in the label's direction on the
    other leagues, each needing `MIN_TRAIN_N` signals, then that configuration's signals
    on the held-out league, with a `cfg` column."""
    x = f"x{h}"
    df = df.filter(pl.col(x).is_not_null())
    table = {}
    for cfg in cfgs:
        g = (
            df.filter(make(cfg).fill_null(False))
            .group_by("league")
            .agg(n=pl.len(), m=pl.col(x).mean())
        )
        table[cfg] = {r["league"]: (r["n"], r["m"]) for r in g.iter_rows(named=True)}
    out = []
    leagues = sorted(df["league"].unique().to_list())
    for held in leagues:
        best, best_s = None, -np.inf
        for cfg, per in table.items():
            vals = [per.get(lg) for lg in leagues if lg != held]
            if any(v is None or v[0] < MIN_TRAIN_N for v in vals):
                continue
            s = sign * float(np.mean([v[1] for v in vals]))
            if s > best_s:
                best, best_s = cfg, s
        if best is not None:
            part = df.filter(pl.col("league") == held, make(best).fill_null(False))
            out.append(part.with_columns(cfg=pl.lit(str(best))))
    return pl.concat(out) if out else df.head(0).with_columns(cfg=pl.lit(""))


def rising_cfgs():
    """`lolo`'s grid for "Demand rising": (ratio column, threshold, move)."""
    return list(itertools.product(("ratio", "rel"), RATIOS, MOVES))


def rising_expr(cfg) -> pl.Expr:
    col, th, mv = cfg
    return (pl.col(col) >= th) & (pl.col("m6") >= mv)


def dumped_expr(cfg) -> pl.Expr:
    col, th, mv = cfg
    return (pl.col(col) >= th) & (pl.col("m6") <= -mv)


def build(con, settings=None, with_stock: bool = False) -> pl.DataFrame:
    """Readings for every exchange league's core-pool items, with excess (and stock
    features, reading the pages on disk, when `with_stock`)."""
    pool = po.core_pool_ids(con)
    frames = []
    for lg in po.exchange_leagues(con):
        rows, hours = load(con, lg)
        if pool is not None:
            rows = rows.filter(pl.col("item_id").is_in(list(pool)))
        rd = readings(lg, rows, hours)
        if with_stock:
            rd = stock_features(stock(con, settings, lg), rd)
        frames.append(rd)
    return with_excess(pl.concat(frames, how="diagonal_relaxed"))


def _line(name: str, s: dict) -> str:
    if not s.get("n"):
        return f"| {name} | 0 | | | | | |"
    return (
        f"| {name} | {s['n']:,} ({s['items']} items) | {s['raw']:+.1%} / {s['hit']:.0%} "
        f"| **{s['excess']:+.1%}** [{s['lo']:+.1%}, {s['hi']:+.1%}] | {s['hit_excess']:.0%} "
        f"| {s['leagues']} of {s['of']} | {s['harsh']:+.1%} |"
    )


def main(path: str, with_stock: bool = False) -> None:  # pragma: no cover - research output
    from exiledbroker.config import get_settings

    con = duckdb.connect(path, read_only=True)
    df = build(con, get_settings(), with_stock)
    con.close()
    liquid = df.filter("liquid")
    for phase, part in (
        ("days 0-13", liquid.filter(pl.col("day") < LAUNCH_DAYS)),
        ("after day 13", liquid.filter(pl.col("day") >= LAUNCH_DAYS)),
    ):
        for h in ("24", "72"):
            print(f"\n## Liquid, {phase}, {h} h, held out (leave one league out)\n")
            print(
                "| Label | Signals | Raw mean / hit | Excess [95%, 5-day blocks] | Excess hit | Leagues | Harsh |"
            )
            print("|---|---|---|---|---|---|---|")
            for name, make, sign in (
                ("Demand rising", rising_expr, 1),
                ("Being dumped", dumped_expr, -1),
            ):
                sig = lolo(part, make, rising_cfgs(), sign, h)
                print(_line(name, summary(sig, h, sign, block_days=5)))
            lab = labels(part)
            for name, col, sign in (
                ("Rising on a calm book (fixed)", "calm_rising", 1),
                ("3-day move, bottom fifth", "lagging", -1),
                ("3-day move, top fifth", "leading", 1),
            ):
                if col in lab.columns:
                    print(_line(name, summary(lab.filter(col), h, sign, block_days=5)))


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1], "--stock" in sys.argv[2:])
