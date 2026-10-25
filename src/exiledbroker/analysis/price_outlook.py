"""Sell now, hold or no clear signal: can a verdict beat "no change"? (finding 9 in
docs/findings.md; workstream A of docs/price-check.md).

Research on a local copy of the database. For each past league, exchange item and
decision time, the backtest set holds the forward change of the item's price over the
next 24 hours and the next 3 days, in Divines (the verdict's unit, decided by the user)
and in Chaos (context only), plus what a server would know at that moment: the item's
recent move (momentum), how thick its market is and its typical hourly swing.

- **Price now** is the median of the item's traded hours over the last `SMOOTH_HOURS`
  (at least `SMOOTH_MIN` of them). An hour's price rests on whatever traded and the
  next hour undoes half of it (finding 7: consecutive moves correlate −0.37), so a
  single hour is no anchor. In Divines each hour is the Chaos market's price over that
  hour's Divine rate (carried forward over hours without one).
- **The outcome** is what selling fetches: the median over the next `SMOOTH_HOURS`
  (sell now) against the same hours 24 or 72 hours on (hold). It shares no price with
  what's known at the decision; measured from the price now instead, the bounce makes
  "sell after a rise" look like a forecast (finding 9).
- **Hourly** (`hourly_rows`): days 0–13 of every exchange league, decision times every
  `STEP_HOURS`, plus Allflame's later days (the only league with later hours).
- **Daily** (`daily_rows`): the poe.ninja dumps, whole leagues, one decision a day.
  Their non-currency prices are whole Chaos (an essence at 1c reads 1.0), so a day
  below `DUMP_MIN_CHAOS` is dropped: rounding alone would move it by 10% or more.

Candidate models (`predict`), fitted on the training leagues only:

- `zero`: no change (the baseline).
- `drift`: every item's median change at this point of past leagues (the market's path).
- `group`: the item's category's median change at this point of past leagues.
- `item`: the item's own median change at this point of past leagues (needs
  `MIN_LEAGUES`), else its group's.
- `momentum`: b × the item's last move over the same horizon.
- `item+mom`: a × item + b × momentum.
- `shrunk`: a × item, so a path that overpromised in training is scaled down. This is
  the one that ships (`MODEL`, `SHIP`, `build`).

Weights are fitted per phase and market thickness (least squares, no intercept).

Scoring (`score`) is leave-one-league-out: each league is predicted from the others,
and the training rows' own path features are built without their league either (nested),
so the fitted weights see what a held-out league sees. Per phase, market thickness,
horizon and model: mean absolute error against no change's (skill > 0 beats it), the
direction hit rate on moves bigger than the item's hourly swing, the band's coverage,
and the verdicts' payoff: a "hold" earns the move, a "sell" the move avoided.

    python -m exiledbroker.analysis.price_outlook <db copy>          # the tables in finding 9
"""

import sys
from pathlib import Path

import duckdb
import polars as pl

from exiledbroker.storage import db

HORIZONS = {"h24": 24, "d3": 72}  # hours
DAILY_HORIZONS = {"h24": 1, "d3": 3}  # days
PHASES = (("days 0-2", 0.0, 2.0), ("days 2-7", 2.0, 7.0), ("days 7-14", 7.0, 14.0))
LATER = "later"
SMOOTH_HOURS = 6
SMOOTH_MIN = 2  # traded hours a price now needs
STEP_HOURS = 6  # decision times, hourly set
TRAIL_HOURS = 72  # thickness and swing look back this far
THICK_SHARE = 0.8  # thick: traded in 80% of the last 72 hours...
THICK_CHAOS_H = 300.0  # ... and the median hour traded at least 300c (finding 6's liquid)
BIN_HOURS = 12  # past leagues' paths are pooled per half-day of the league
MIN_LEAGUES = 2  # past leagues an item's own path needs
DUMP_MIN_CHAOS = 10.0  # dump prices are whole Chaos: below this, rounding is ≥ 5%
CLIP = 1.0  # log changes are clipped to ±1 (×2.7) for fitting and scoring
BAND = (0.1, 0.9)  # the band claims 80%
TAUS = (0.02, 0.05, 0.10)  # verdict thresholds tried on the typical change
MODELS = ("zero", "drift", "group", "item", "momentum", "item+mom", "shrunk")
UNITS = ("div", "chaos")


def phase_of(day: pl.Expr) -> pl.Expr:
    out = pl.lit(LATER)
    for name, _first, end in reversed(PHASES):
        out = pl.when(day < end).then(pl.lit(name)).otherwise(out)
    return out


# --- Backtest set, hourly --------------------------------------------------------------


def load_hourly(con, league: str) -> tuple[pl.DataFrame, pl.DataFrame]:
    """A league's traded hours (item, hour since launch, Chaos price, Chaos traded, item
    category) and its hours (each loaded hour with that hour's Divine rate, if any)."""
    lid = "(SELECT id FROM league WHERE name = ?)"
    prices = db.frame(
        con,
        f"""
        SELECT ? AS league, c.item_id, coalesce(i.category, 'other') AS grp,
               CAST(round(c.day_offset * 24) AS INTEGER) AS hour,
               c.chaos_price AS chaos, c.chaos_price * c.chaos_volume AS cv
        FROM cross_market_hour c LEFT JOIN item i ON i.id = c.item_id
        WHERE c.league_id = {lid} AND c.chaos_price > 0 AND c.chaos_volume > 0
        """,
        [league, league],
    )
    hours = db.frame(
        con,
        f"""
        SELECT ? AS league, CAST(round(day_offset * 24) AS INTEGER) AS hour,
               median(divine_rate) FILTER (WHERE divine_rate > 0) AS rate
        FROM cross_market_hour WHERE league_id = {lid}
        GROUP BY 2
        """,
        [league, league],
    )
    return prices, hours


def hourly_grid(prices: pl.DataFrame, hours: pl.DataFrame) -> pl.DataFrame:
    """Every item × every hour from the league's first loaded hour to its last, with the
    price now, momentum, forward changes, thickness and swing. Hours that weren't
    loaded (Allflame's gap between its launch and its latest days) count as unknown,
    not as untraded."""
    hours = hours.with_columns(pl.col("hour").cast(pl.Int32))
    span = hours.group_by("league").agg(first=pl.col("hour").min(), last=pl.col("hour").max())
    clock = (
        span.with_columns(hour=pl.int_ranges("first", pl.col("last") + 1, dtype=pl.Int32))
        .explode("hour")
        .select("league", "hour")
        .join(hours.with_columns(loaded=pl.lit(True)), on=["league", "hour"], how="left")
        .sort("league", "hour")
        .with_columns(
            loaded=pl.col("loaded").fill_null(False),
            rate=pl.col("rate").forward_fill().over("league"),
        )
    )
    items = prices.select("league", "item_id", "grp").unique(["league", "item_id"])
    g = (
        items.join(clock, on="league")
        .join(
            prices.select("league", "item_id", pl.col("hour").cast(pl.Int32), "chaos", "cv"),
            on=["league", "item_id", "hour"],
            how="left",
        )
        .sort("league", "item_id", "hour")
    )
    return _series_features(g, ("league", "item_id"), SMOOTH_HOURS, SMOOTH_MIN, HORIZONS)


def _series_features(
    g: pl.DataFrame, keys: tuple[str, ...], smooth: int, smooth_min: int, horizons: dict
) -> pl.DataFrame:
    """Price now, momentum and forward changes on a complete, sorted per-item grid
    (one row per step; `chaos` null where untraded, `rate` the Divine rate)."""
    over = list(keys)
    g = g.with_columns(div=pl.col("chaos") / pl.col("rate"))
    g = g.with_columns(
        **{
            f"s_{u}": pl.col(u).rolling_median(smooth, min_samples=smooth_min).over(over)
            for u in ("div", "chaos")
        }
    )
    cols = {}
    for name, steps in horizons.items():
        for u in ("div", "chaos"):
            s = pl.col(f"s_{u}")
            # Selling now fills over the next `smooth` hours (their median), holding over
            # the same hours `steps` later: no price point is shared with what's known now.
            now, later = s.shift(-smooth).over(over), s.shift(-smooth - steps).over(over)
            cols[f"y_{name}_{u}"] = (later / now).log().clip(-CLIP, CLIP)
            cols[f"m_{name}_{u}"] = (s / s.shift(steps).over(over)).log().clip(-CLIP, CLIP)
    return g.with_columns(**cols)


def _trailing(g: pl.DataFrame) -> pl.DataFrame:
    """Thickness and swing over the last TRAIL_HOURS (hourly grid only)."""
    over = ["league", "item_id"]
    traded = pl.col("chaos").is_not_null()
    absret = (
        g.filter(traded)
        .with_columns(
            absret=(pl.col("chaos") / pl.col("chaos").shift(1).over(over)).log().abs(),
        )
        .select("league", "item_id", "hour", "absret")
    )
    g = g.join(absret, on=["league", "item_id", "hour"], how="left").sort(*over, "hour")
    w = TRAIL_HOURS
    return g.with_columns(
        share=(
            traded.cast(pl.Float64).rolling_sum(w, min_samples=1).over(over)
            / pl.col("loaded").cast(pl.Float64).rolling_sum(w, min_samples=1).over(over)
        ),
        cv_h=pl.when(pl.col("loaded"))
        .then(pl.col("cv").fill_null(0.0))
        .rolling_median(w, min_samples=1)
        .over(over),
        swing=pl.col("absret").rolling_median(w, min_samples=3).over(over),
    ).with_columns(
        thick=(pl.col("share") >= THICK_SHARE) & (pl.col("cv_h") >= THICK_CHAOS_H),
    )


def hourly_rows(prices: pl.DataFrame, hours: pl.DataFrame) -> pl.DataFrame:
    """The hourly backtest set: decision times every STEP_HOURS with a price now."""
    g = _trailing(hourly_grid(prices, hours))
    return (
        g.filter(pl.col("hour") % STEP_HOURS == 0, pl.col("loaded"), pl.col("s_div").is_not_null())
        .with_columns(
            day=pl.col("hour") / 24.0,
            bin=pl.col("hour") // BIN_HOURS,
            source=pl.lit("hourly"),
        )
        .with_columns(phase=phase_of(pl.col("day")))
        .select(_ROW_COLS)
    )


_ROW_COLS = [
    "league",
    "item_id",
    "grp",
    "source",
    "day",
    "bin",
    "phase",
    "thick",
    "swing",
    "s_div",
    "s_chaos",
    *[f"{k}_{h}_{u}" for k in ("y", "m") for h in HORIZONS for u in UNITS],
]


# --- Backtest set, daily (dumps) -------------------------------------------------------


def load_daily(con, league: str) -> pl.DataFrame:
    """A league's dump prices per item and day (Chaos and Divines)."""
    return db.frame(
        con,
        """
        SELECT ? AS league, p.item_id, coalesce(i.category, 'other') AS grp,
               CAST(p.day_offset AS INTEGER) AS day, p.chaos_value AS chaos,
               p.divine_value AS div
        FROM price_observation p JOIN item i ON i.id = p.item_id
        WHERE p.league_id = (SELECT id FROM league WHERE name = ?)
          AND p.source = 'poe.ninja-dump' AND p.chaos_value > 0 AND p.divine_value > 0
          AND p.item_id LIKE 'currency:%'
        """,
        [league, league],
    )


def daily_rows(daily: pl.DataFrame, thick: pl.DataFrame | None = None) -> pl.DataFrame:
    """The daily backtest set from the dumps: one decision a day per item, the price
    that day's dump value (no smoothing: it's already a day's figure). `thick` (league,
    item_id, thick) labels the market, e.g. from the item's last hourly days; without
    it every item counts as thin."""
    d = daily.filter(pl.col("chaos") >= DUMP_MIN_CHAOS)
    span = d.group_by("league").agg(first=pl.col("day").min(), last=pl.col("day").max())
    clock = (
        span.with_columns(day=pl.int_ranges("first", pl.col("last") + 1, dtype=pl.Int32))
        .explode("day")
        .select("league", "day")
    )
    items = d.select("league", "item_id", "grp").unique(["league", "item_id"])
    g = (
        items.join(clock, on="league")
        .join(
            d.select("league", "item_id", pl.col("day").cast(pl.Int32), "chaos", "div"),
            on=["league", "item_id", "day"],
            how="left",
        )
        .sort("league", "item_id", "day")
        .with_columns(s_div=pl.col("div"), s_chaos=pl.col("chaos"))
    )
    over = ["league", "item_id"]
    cols = {}
    for name, steps in DAILY_HORIZONS.items():
        for u in UNITS:
            s = pl.col(f"s_{u}")
            # Decided at the start of day d, knowing days up to d − 1; sold during d.
            cols[f"y_{name}_{u}"] = (s.shift(-steps).over(over) / s).log().clip(-CLIP, CLIP)
            known = s.shift(1).over(over)
            cols[f"m_{name}_{u}"] = (known / s.shift(1 + steps).over(over)).log().clip(-CLIP, CLIP)
    g = g.with_columns(**cols).with_columns(
        # A day's swing: the median |daily move| over the last 7 known days.
        swing=pl.col("m_h24_div").abs().rolling_median(7, min_samples=3).over(over),
    )
    if thick is not None:
        g = g.join(thick, on=["league", "item_id"], how="left")
    else:
        g = g.with_columns(thick=pl.lit(None, pl.Boolean))
    return (
        g.filter(pl.col("s_div").is_not_null())
        .with_columns(
            thick=pl.col("thick").fill_null(False),
            day=pl.col("day").cast(pl.Float64),
            bin=pl.col("day").cast(pl.Int64),
            source=pl.lit("daily"),
        )
        .with_columns(phase=phase_of(pl.col("day")))
        .select(_ROW_COLS)
    )


# --- Models ----------------------------------------------------------------------------


def paths(rows: pl.DataFrame, y: str) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Past leagues' median change from each bin of the league: per item (and how many
    leagues), per group, and for every item together. A league's median first, then the
    median over leagues, so a league with more items doesn't outweigh the others."""
    r = rows.filter(pl.col(y).is_not_null())
    item = (
        r.group_by("item_id", "bin", "league")
        .agg(v=pl.col(y).median())
        .group_by("item_id", "bin")
        .agg(item=pl.col("v").median(), item_n=pl.len().cast(pl.Int32))
    )
    grp = (
        r.group_by("grp", "bin", "league")
        .agg(v=pl.col(y).median())
        .group_by("grp", "bin")
        .agg(group=pl.col("v").median(), group_n=pl.len().cast(pl.Int32))
    )
    drift = (
        r.group_by("bin", "league")
        .agg(v=pl.col(y).median())
        .group_by("bin")
        .agg(drift=pl.col("v").median())
    )
    return item, grp, drift


def with_paths(rows: pl.DataFrame, past: pl.DataFrame, y: str) -> pl.DataFrame:
    """`rows` with the path features from `past` (other leagues): drift, group and item,
    each falling back to the coarser one where it's missing."""
    item, grp, drift = paths(past, y)
    out = (
        rows.join(item, on=["item_id", "bin"], how="left")
        .join(grp, on=["grp", "bin"], how="left")
        .join(drift, on="bin", how="left")
    )
    return (
        out.with_columns(
            drift=pl.col("drift").fill_null(0.0),
        )
        .with_columns(
            group=pl.when(pl.col("group_n") >= MIN_LEAGUES)
            .then(pl.col("group"))
            .otherwise(pl.col("drift")),
        )
        .with_columns(
            item=pl.when(pl.col("item_n") >= MIN_LEAGUES)
            .then(pl.col("item"))
            .otherwise(pl.col("group")),
            basis=pl.when(pl.col("item_n") >= MIN_LEAGUES)
            .then(pl.lit("item"))
            .otherwise(pl.lit("group")),
        )
    )


def _ols(df: pl.DataFrame, y: str, xs: list[str]) -> list[float]:
    """Least squares through the origin (no intercept: the paths carry the drift)."""
    import numpy as np

    d = df.select(y, *xs).drop_nulls(y).fill_null(0.0)
    if d.height < 20:
        return [0.0] * len(xs)
    a = d.select(xs).to_numpy()
    b = d.get_column(y).to_numpy()
    coef, *_ = np.linalg.lstsq(a, b, rcond=None)
    return [float(c) for c in coef]


def fit(train: pl.DataFrame, y: str, m: str) -> dict[tuple[str, bool], dict[str, list[float]]]:
    """Per phase and market thickness: the weights of momentum, item+momentum and the
    shrunk path."""
    out = {}
    for (phase, thick), part in train.group_by("phase", "thick"):
        out[(phase, thick)] = {
            "momentum": _ols(part, y, [m]),
            "item+mom": _ols(part, y, ["item", m]),
            "shrunk": _ols(part, y, ["item"]),
        }
    return out


def predict(rows: pl.DataFrame, weights: dict, m: str) -> pl.DataFrame:
    """Each model's typical change, as columns `p_<model>`."""

    def w(model: str, i: int) -> pl.Expr:
        e = pl.lit(0.0)
        for (phase, thick), ws in weights.items():
            cell = (pl.col("phase") == phase) & (pl.col("thick") == thick)
            e = pl.when(cell).then(pl.lit(ws[model][i])).otherwise(e)
        return e

    mom = pl.col(m).fill_null(0.0)
    return rows.with_columns(
        p_zero=pl.lit(0.0),
        p_drift=pl.col("drift"),
        p_group=pl.col("group"),
        p_item=pl.col("item"),
        p_momentum=w("momentum", 0) * mom,
        **{"p_item+mom": w("item+mom", 0) * pl.col("item") + w("item+mom", 1) * mom},
        p_shrunk=w("shrunk", 0) * pl.col("item"),
    )


def band_quantiles(train: pl.DataFrame, y: str) -> pl.DataFrame:
    """Per phase, thickness and model: the residual quantiles that make the band, raw
    and in units of the item's swing (`z`)."""
    lo, hi = BAND
    long = _long(train, y)
    return long.group_by("phase", "thick", "model").agg(
        r_lo=pl.col("res").quantile(lo),
        r_hi=pl.col("res").quantile(hi),
        z_lo=(pl.col("res") / pl.col("scale")).quantile(lo),
        z_hi=(pl.col("res") / pl.col("scale")).quantile(hi),
    )


def _long(rows: pl.DataFrame, y: str) -> pl.DataFrame:
    keep = ["league", "item_id", "phase", "thick", "day", "swing", "basis", y]
    if "basis" not in rows.columns:
        rows = rows.with_columns(basis=pl.lit("none"))
    return (
        rows.filter(pl.col(y).is_not_null())
        .select(*keep, *[f"p_{mo}" for mo in MODELS])
        .unpivot(index=keep, variable_name="model", value_name="pred")
        .with_columns(
            model=pl.col("model").str.strip_prefix("p_"),
            res=pl.col(y) - pl.col("pred"),
            scale=pl.col("swing").fill_null(0.05).clip(0.01, 1.0),
        )
    )


def backtest(
    rows: pl.DataFrame, unit: str, horizon: str, targets: list[str] | None = None
) -> pl.DataFrame:
    """Leave one league out: each target league's rows (default: every league's)
    predicted from all the other leagues in `rows`, with each model's typical change and
    band. Long format, one row per row × model."""
    y, m = f"y_{horizon}_{unit}", f"m_{horizon}_{unit}"
    leagues = rows.get_column("league").unique().sort().to_list()
    out = []
    for target in targets or leagues:
        others = [lg for lg in leagues if lg != target]
        # Nested: a training row's path comes from neither its league nor the target.
        train = pl.concat(
            [
                with_paths(
                    rows.filter(league=lg),
                    rows.filter(pl.col("league").is_in([o for o in others if o != lg])),
                    y,
                )
                for lg in others
            ]
        )
        weights = fit(train, y, m)
        bands = band_quantiles(predict(train, weights, m), y)
        test = predict(
            with_paths(rows.filter(league=target), rows.filter(pl.col("league").is_in(others)), y),
            weights,
            m,
        )
        long = _long(test, y).join(bands, on=["phase", "thick", "model"], how="left")
        out.append(
            long.with_columns(
                lo=pl.col("pred") + pl.col("r_lo"),
                hi=pl.col("pred") + pl.col("r_hi"),
                zlo=pl.col("pred") + pl.col("z_lo") * pl.col("scale"),
                zhi=pl.col("pred") + pl.col("z_hi") * pl.col("scale"),
            ).drop("r_lo", "r_hi", "z_lo", "z_hi")
        )
    return pl.concat(out).rename({y: "y"})


# --- Scoring ---------------------------------------------------------------------------


def verdict(pred: pl.Expr, tau: float) -> pl.Expr:
    """ "sell" below −tau, "hold" above +tau, else "none"."""
    return (
        pl.when(pred <= -tau)
        .then(pl.lit("sell"))
        .when(pred >= tau)
        .then(pl.lit("hold"))
        .otherwise(pl.lit("none"))
    )


def score(bt: pl.DataFrame, by: list[str], taus: tuple[float, ...] = TAUS) -> pl.DataFrame:
    """Per `by` (e.g. phase, thick, model): rows, mean |error| over no change's (skill =
    1 − ratio; above 0 beats it), the direction hit rate on moves bigger than the swing,
    the bands' coverage and width, and per threshold the share of rows with a verdict,
    its hit rate and its mean payoff (hold earns y, sell earns −y)."""
    big = pl.col("y").abs() > pl.col("swing").fill_null(0.0)
    signed = pl.col("pred").sign()
    aggs = [
        pl.len().alias("n"),
        pl.col("league").n_unique().alias("leagues"),
        ((pl.col("y") - pl.col("pred")).abs().mean() / pl.col("y").abs().mean()).alias("mae_ratio"),
        ((signed == pl.col("y").sign()).filter(big & (signed != 0)).mean()).alias("dir_hit"),
        ((pl.col("y") >= pl.col("lo")) & (pl.col("y") <= pl.col("hi"))).mean().alias("cover"),
        (pl.col("hi") - pl.col("lo")).median().alias("width"),
        ((pl.col("y") >= pl.col("zlo")) & (pl.col("y") <= pl.col("zhi"))).mean().alias("zcover"),
        (pl.col("zhi") - pl.col("zlo")).median().alias("zwidth"),
    ]
    for tau in taus:
        t = f"{round(tau * 100)}"
        called = pl.col("pred").abs() >= tau
        gain = (signed * pl.col("y")).filter(called)
        aggs += [
            called.mean().alias(f"called_{t}"),
            (gain > 0).mean().alias(f"hit_{t}"),
            gain.mean().alias(f"gain_{t}"),
        ]
    return bt.group_by(by).agg(aggs).with_columns(skill=1 - pl.col("mae_ratio")).sort(by)


def per_league(bt: pl.DataFrame, by: list[str], tau: float) -> pl.DataFrame:
    """How many held-out leagues each `by` cell's verdicts paid in (mean payoff > 0) and
    beat no change's error in, out of how many."""
    t = score(bt, [*by, "league"], (tau,))
    g = f"gain_{round(tau * 100)}"
    return (
        t.group_by(by)
        .agg(
            leagues=pl.len(),
            skill_won=(pl.col("skill") > 0).sum(),
            paid=(pl.col(g) > 0).sum(),
            worst_gain=pl.col(g).min(),
        )
        .sort(by)
    )


def disagreement(
    bt_div: pl.DataFrame, bt_chaos: pl.DataFrame, model: str, tau: float
) -> pl.DataFrame:
    """How often the same model's verdict in Chaos differs from its verdict in Divines,
    among rows where either makes a call, per phase."""
    key = ["league", "item_id", "day"]
    d = bt_div.filter(model=model).select(*key, "phase", vd=verdict(pl.col("pred"), tau))
    c = bt_chaos.filter(model=model).select(*key, vc=verdict(pl.col("pred"), tau))
    j = d.join(c, on=key).filter((pl.col("vd") != "none") | (pl.col("vc") != "none"))
    return (
        j.group_by("phase")
        .agg(
            calls=pl.len(),
            differ=(pl.col("vd") != pl.col("vc")).mean(),
            opposite=(
                ((pl.col("vd") == "sell") & (pl.col("vc") == "hold"))
                | ((pl.col("vd") == "hold") & (pl.col("vc") == "sell"))
            ).mean(),
        )
        .sort("phase")
    )


# --- Report ----------------------------------------------------------------------------


def exchange_leagues(con) -> list[str]:
    return [
        r[0]
        for r in db.rows(
            con,
            """
            SELECT l.name FROM league l
            WHERE l.kind = 'challenge'
              AND EXISTS (SELECT 1 FROM cross_market_hour c WHERE c.league_id = l.id)
            ORDER BY l.start_at
            """,
        )
    ]


def core_pool_ids(con) -> set[str] | None:
    """The current core pool's exchange items (by name), or None without snapshots."""
    from exiledbroker.config import get_settings
    from exiledbroker.ingest.core_pool import load_pool

    pool = load_pool(con, get_settings())
    if not pool.listed:
        return None
    names = set().union(*pool.listed.values()) | set().union(*pool.include.values(), set())
    names -= pool.exclude
    marks = ", ".join("?" for _ in names)
    return {
        r[0]
        for r in db.rows(
            con, f"SELECT id FROM item WHERE canonical_name IN ({marks})", sorted(names)
        )
    }


def dump_coverage(con, league: str, pool: set[str] | None) -> dict:
    """Of the league's exchange items (core pool), how many the dumps have at all, how
    many on a day priced ≥ DUMP_MIN_CHAOS, and their share of the Chaos traded."""
    ex = db.frame(
        con,
        """
        SELECT item_id, sum(chaos_price * chaos_volume) AS cv
        FROM cross_market_hour WHERE league_id = (SELECT id FROM league WHERE name = ?)
          AND chaos_price > 0
        GROUP BY 1
        """,
        [league],
    )
    if pool is not None:
        ex = ex.filter(pl.col("item_id").is_in(list(pool)))
    dumps = (
        load_daily(con, league)
        .group_by("item_id")
        .agg(usable=(pl.col("chaos") >= DUMP_MIN_CHAOS).any())
    )
    j = ex.join(dumps, on="item_id", how="left")
    total = j.get_column("cv").sum()
    return {
        "league": league,
        "exchange_items": j.height,
        "in_dumps": j.filter(pl.col("usable").is_not_null()).height,
        "usable": j.filter(pl.col("usable").fill_null(False)).height,
        "cv_in_dumps": j.filter(pl.col("usable").is_not_null()).get_column("cv").sum() / total,
        "cv_usable": j.filter(pl.col("usable").fill_null(False)).get_column("cv").sum() / total,
    }


def thresholds(
    bt: pl.DataFrame, model: str, taus: tuple[float, ...], by: tuple[str, ...] = ("phase", "thick")
) -> pl.DataFrame:
    """Per `by` cell and threshold, for one model: the share of rows that get a verdict,
    its hit rate and mean payoff pooled, and the worst held-out league's payoff and hit
    rate (a league with under 30 calls doesn't count towards the worst)."""
    b = bt.filter(model=model)
    out = []
    for tau in taus:
        v = b.with_columns(
            called=pl.col("pred").abs() >= tau, gain=pl.col("pred").sign() * pl.col("y")
        )
        pooled = v.group_by(by).agg(
            called=pl.col("called").mean(),
            hit=(pl.col("gain") > 0).filter(pl.col("called")).mean(),
            gain=pl.col("gain").filter(pl.col("called")).mean(),
        )
        lg = (
            v.filter(pl.col("called"))
            .group_by(*by, "league")
            .agg(n=pl.len(), hit=(pl.col("gain") > 0).mean(), gain=pl.col("gain").mean())
            .filter(pl.col("n") >= 30)
            .group_by(by)
            .agg(
                leagues=pl.len(),
                paid=(pl.col("gain") > 0).sum(),
                worst_gain=pl.col("gain").min(),
                worst_hit=pl.col("hit").min(),
            )
        )
        out.append(pooled.join(lg, on=list(by), how="left").with_columns(tau=pl.lit(tau)))
    return pl.concat(out).sort(*by, "tau")


def calls(bt: pl.DataFrame, by: list[str], tau: float) -> pl.DataFrame:
    """Per `by` and verdict (sell / hold): how many rows, their share of all rows, the
    hit rate (the price did move that way) and the median move that followed."""
    v = bt.with_columns(verdict=verdict(pl.col("pred"), tau))
    total = v.group_by(by).agg(all=pl.len())
    return (
        v.filter(pl.col("verdict") != "none")
        .group_by(*by, "verdict")
        .agg(
            n=pl.len(),
            hit=((pl.col("verdict") == "hold") == (pl.col("y") > 0)).mean(),
            median_y=pl.col("y").median(),
        )
        .join(total, on=by)
        .with_columns(share=pl.col("n") / pl.col("all"))
        .drop("all")
        .sort(*by, "verdict")
    )


def later_hourly(rows: pl.DataFrame, unit: str, horizon: str) -> pl.DataFrame:
    """The later days' hourly rows (Allflame only: no past league has later hours), with
    momentum's weight fitted on the other leagues' days 7–14. No path exists here, so
    the models are no change and momentum (the others are set to no change)."""
    y, m = f"y_{horizon}_{unit}", f"m_{horizon}_{unit}"
    test = rows.filter(pl.col("phase") == LATER, pl.col(y).is_not_null())
    leagues = test.get_column("league").unique().to_list()
    train = rows.filter(
        pl.col("phase") == "days 7-14", ~pl.col("league").is_in(leagues), pl.col(y).is_not_null()
    )
    b = _ols(train, y, [m])[0]
    zero = {f"p_{mo}": pl.lit(0.0) for mo in MODELS}
    pred = lambda df: (
        df.with_columns(**zero)
        .with_columns(p_momentum=b * pl.col(m).fill_null(0.0))
        .with_columns(**{"p_item+mom": pl.col("p_momentum")})
    )
    train = pred(train.with_columns(phase=pl.lit(LATER)))
    bands = band_quantiles(train, y)
    return (
        _long(pred(test), y)
        .join(bands, on=["phase", "thick", "model"], how="left")
        .with_columns(
            lo=pl.col("pred") + pl.col("r_lo"),
            hi=pl.col("pred") + pl.col("r_hi"),
            zlo=pl.col("pred") + pl.col("z_lo") * pl.col("scale"),
            zhi=pl.col("pred") + pl.col("z_hi") * pl.col("scale"),
        )
        .drop("r_lo", "r_hi", "z_lo", "z_hi")
        .rename({y: "y"})
        .filter(pl.col("model").is_in(["zero", "momentum"]))
    )


POST_SETTLERS = ("Settlers", "Mercenaries", "Keepers", "Mirage")
PRE_SETTLERS = ("Sanctum", "Crucible", "Ancestor", "Affliction", "Necropolis")


def thick_late(rows: pl.DataFrame) -> pl.DataFrame:
    """Per league and item: thick if it was thick on most of days 11–14's decisions
    (labels the dumps' items, which have no volume)."""
    return (
        rows.filter(pl.col("day") >= 11, pl.col("day") < 14)
        .group_by("league", "item_id")
        .agg(thick=pl.col("thick").mean() >= 0.5)
    )


# --- What ships (finding 9) -----------------------------------------------------------

MODEL = "shrunk"
# The verdict's threshold on the typical change per (phase, thick, horizon, verdict):
# the smallest at which that call hit ≥ 60% pooled and ≥ 55% in every held-out league
# (`choose`, finding 9). Missing: that call is never made ("No clear signal").
SHIP = {
    ("days 0-2", False, "h24", "sell"): 0.05,
    ("days 0-2", False, "h24", "hold"): 0.05,
    ("days 0-2", True, "h24", "sell"): 0.05,
    ("days 2-7", False, "h24", "sell"): 0.08,
    ("days 2-7", True, "h24", "sell"): 0.05,
    ("days 2-7", True, "h24", "hold"): 0.05,
    ("days 7-14", True, "h24", "sell"): 0.05,
    ("days 0-2", False, "d3", "sell"): 0.05,
    ("days 0-2", False, "d3", "hold"): 0.05,
    ("days 0-2", True, "d3", "sell"): 0.05,
    ("days 2-7", False, "d3", "sell"): 0.05,
    ("days 2-7", False, "d3", "hold"): 0.08,
    ("days 2-7", True, "d3", "sell"): 0.05,
    ("days 2-7", True, "d3", "hold"): 0.05,
    ("days 7-14", True, "d3", "sell"): 0.10,
    ("days 7-14", True, "d3", "hold"): 0.05,
}


def ship_verdict(phase: str, thick: bool, horizon: str, typical: float | None) -> str:
    """The shipped verdict for one item: "sell", "hold" or "none"."""
    if typical is None:
        return "none"
    sell = SHIP.get((phase, thick, horizon, "sell"))
    hold = SHIP.get((phase, thick, horizon, "hold"))
    if sell is not None and typical <= -sell:
        return "sell"
    if hold is not None and typical >= hold:
        return "hold"
    return "none"


def choose(
    bt: pl.DataFrame,
    taus: tuple[float, ...] = (0.05, 0.08, 0.10, 0.15),
    min_hit: float = 0.60,
    min_worst: float = 0.55,
    min_calls: int = 30,
) -> pl.DataFrame:
    """Per phase, thickness and direction (sell / hold), the smallest threshold at which
    the model's calls in that direction hit at least `min_hit` pooled and `min_worst`
    in every held-out league with `min_calls` calls, and all leagues have them. Cells
    with no such threshold get no verdict in that direction."""
    b = bt.filter(model=MODEL)
    leagues = b.get_column("league").n_unique()
    rows = []
    for tau in taus:
        v = b.with_columns(verdict=verdict(pl.col("pred"), tau)).filter(pl.col("verdict") != "none")
        v = v.with_columns(hit=(pl.col("verdict") == "hold") == (pl.col("y") > 0))
        per = v.group_by("phase", "thick", "verdict", "league").agg(
            n=pl.len(), h=pl.col("hit").mean()
        )
        agg = (
            v.group_by("phase", "thick", "verdict")
            .agg(n=pl.len(), hit=pl.col("hit").mean())
            .join(
                per.filter(pl.col("n") >= min_calls)
                .group_by("phase", "thick", "verdict")
                .agg(worst=pl.col("h").min(), leagues=pl.len()),
                on=["phase", "thick", "verdict"],
                how="left",
            )
            .with_columns(tau=pl.lit(tau))
        )
        rows.append(agg)
    grid = pl.concat(rows)
    ok = grid.filter(
        pl.col("hit") >= min_hit, pl.col("worst") >= min_worst, pl.col("leagues") == leagues
    )
    return (
        ok.sort("tau")
        .group_by("phase", "thick", "verdict", maintain_order=True)
        .first()
        .sort("phase", "thick", "verdict")
    )


def shipped(bt: pl.DataFrame, horizon: str) -> pl.DataFrame:
    """The shipped rule on a backtest: per phase, thickness and verdict, the share of
    rows called, the hit rate pooled and in the worst league, and the median move."""
    cells = pl.DataFrame(
        [
            (ph, th, SHIP.get((ph, th, horizon, "sell")), SHIP.get((ph, th, horizon, "hold")))
            for ph, th in {(k[0], k[1]) for k in SHIP if k[2] == horizon}
        ],
        schema={"phase": pl.String, "thick": pl.Boolean, "sell": pl.Float64, "hold": pl.Float64},
        orient="row",
    )
    b = bt.filter(model=MODEL).join(cells, on=["phase", "thick"], how="left")
    v = b.with_columns(
        verdict=pl.when(pl.col("pred") <= -pl.col("sell"))
        .then(pl.lit("sell"))
        .when(pl.col("pred") >= pl.col("hold"))
        .then(pl.lit("hold"))
        .otherwise(pl.lit("none"))
    ).with_columns(hit=(pl.col("verdict") == "hold") == (pl.col("y") > 0))
    total = v.group_by("phase", "thick").agg(all=pl.len())
    called = v.filter(pl.col("verdict") != "none")
    worst = (
        called.group_by("phase", "thick", "verdict", "league")
        .agg(h=pl.col("hit").mean(), n=pl.len())
        .filter(pl.col("n") >= 30)
        .group_by("phase", "thick", "verdict")
        .agg(worst_hit=pl.col("h").min(), leagues=pl.len())
    )
    return (
        called.group_by("phase", "thick", "verdict")
        .agg(n=pl.len(), hit=pl.col("hit").mean(), median_y=pl.col("y").median())
        .join(total, on=["phase", "thick"])
        .join(worst, on=["phase", "thick", "verdict"], how="left")
        .with_columns(share=pl.col("n") / pl.col("all"))
        .drop("all")
        .sort("phase", "thick", "verdict")
    )


def build(rows: pl.DataFrame, unit: str = "div") -> tuple[pl.DataFrame, pl.DataFrame]:
    """What the server needs, from every past league's hourly rows (days 0–13):

    - `paths`: per item, half-day bin of the league (`bin` = hour // 12) and horizon,
      the median over past leagues of each league's median change (`path`), and how
      many leagues (`leagues`); only where at least MIN_LEAGUES have it.
    - `constants`: per phase, thickness and horizon, the path's weight and the band's
      residual quantiles (low, high), fitted on nested leave-one-league-out features
      like the backtest's training step, and the verdict threshold (null: no verdict).

    The typical change is weight × path; the band is typical + low … typical + high."""
    leagues = rows.get_column("league").unique().sort().to_list()
    launch = rows.filter(pl.col("phase") != LATER)
    out_paths, out_consts = [], []
    for h in HORIZONS:
        y, m = f"y_{h}_{unit}", f"m_{h}_{unit}"
        item, _, _ = paths(launch, y)
        out_paths.append(
            item.filter(pl.col("item_n") >= MIN_LEAGUES).select(
                "item_id", "bin", horizon=pl.lit(h), path="item", leagues="item_n"
            )
        )
        train = pl.concat(
            [
                with_paths(
                    launch.filter(league=lg),
                    launch.filter(pl.col("league").is_in([o for o in leagues if o != lg])),
                    y,
                )
                for lg in leagues
            ]
        )
        weights = fit(train, y, m)
        bands = band_quantiles(predict(train, weights, m), y).filter(model=MODEL)
        for (phase, thick), ws in weights.items():
            band = bands.filter(phase=phase, thick=thick)
            out_consts.append(
                {
                    "phase": phase,
                    "thick": thick,
                    "horizon": h,
                    "weight": ws[MODEL][0],
                    "low": band.get_column("r_lo")[0] if band.height else None,
                    "high": band.get_column("r_hi")[0] if band.height else None,
                    "sell_below": SHIP.get((phase, thick, h, "sell")),
                    "hold_above": SHIP.get((phase, thick, h, "hold")),
                }
            )
    consts = pl.DataFrame(out_consts).sort("horizon", "phase", "thick")
    return pl.concat(out_paths).sort("item_id", "horizon", "bin"), consts


def main(path: str) -> None:  # pragma: no cover - research output
    pl.Config.set_tbl_rows(400)
    pl.Config.set_tbl_cols(40)
    pl.Config.set_tbl_width_chars(250)
    pl.Config.set_float_precision(3)
    pl.Config.set_tbl_hide_dataframe_shape(True)
    pl.Config.set_tbl_hide_column_data_types(True)
    out = Path(path).with_suffix("")
    con = duckdb.connect(path, read_only=True)
    pool = core_pool_ids(con)
    leagues = exchange_leagues(con)
    print("leagues", leagues, "core pool", None if pool is None else len(pool))
    frames = []
    for lg in leagues:
        prices, hours = load_hourly(con, lg)
        if pool is not None:
            prices = prices.filter(pl.col("item_id").is_in(list(pool)))
        frames.append(hourly_rows(prices, hours))
    rows = pl.concat(frames)
    rows.write_parquet(f"{out}_hourly_rows.parquet")
    print(
        rows.group_by("league", "phase")
        .agg(pl.len(), items=pl.col("item_id").n_unique(), thick=pl.col("thick").mean())
        .sort("league", "phase")
    )
    launch = rows.filter(pl.col("phase") != LATER)
    bts = {}
    for unit in UNITS:
        for h in HORIZONS:
            bt = pl.concat([backtest(launch, unit, h), later_hourly(rows, unit, h)])
            bt.write_parquet(f"{out}_bt_{unit}_{h}.parquet")
            bts[unit, h] = bt
    for h in HORIZONS:
        bt = bts["div", h]
        print(f"\n== Divines, {h}: skill (1 - error / no change's) per model, and leagues won")
        s = score(bt, ["phase", "thick", "model"], (0.05,)).join(
            per_league(bt, ["phase", "thick", "model"], 0.05), on=["phase", "thick", "model"]
        )
        print(
            s.filter(pl.col("model") != "zero")
            .with_columns(cell=pl.format("{} ({})", pl.col("skill").round(3), "skill_won"))
            .pivot(on="model", index=["phase", "thick"], values="cell")
            .sort("phase", "thick")
        )
        print(f"== {MODEL}, {h}: thresholds")
        print(thresholds(bt.filter(pl.col("phase") != LATER), MODEL, (0.03, 0.05, 0.08, 0.1)))
        print(f"== thresholds per direction (choose), {h}")
        print(choose(bt.filter(pl.col("phase") != LATER)))
        print(f"== shipped rule, {h}")
        print(shipped(bt, h))
        print(f"== band ({BAND[0]:.0%}-{BAND[1]:.0%} of residuals), {MODEL}, {h}")
        b = bt.filter(model=MODEL)
        inside = (pl.col("y") >= pl.col("lo")) & (pl.col("y") <= pl.col("hi"))
        print(
            b.group_by("phase", "thick", "league")
            .agg(c=inside.mean())
            .group_by("phase", "thick")
            .agg(cover_min=pl.col("c").min(), cover_max=pl.col("c").max())
            .join(
                b.group_by("phase", "thick").agg(
                    cover=inside.mean(),
                    low=(pl.col("lo") - pl.col("pred")).median().exp() - 1,
                    high=(pl.col("hi") - pl.col("pred")).median().exp() - 1,
                ),
                on=["phase", "thick"],
            )
            .sort("phase", "thick")
        )
        print(f"== Chaos against Divines, {h}")
        print(disagreement(bt, bts["chaos", h], MODEL, 0.05))

    print("\n== Dumps' coverage of the core pool's exchange items")
    print(pl.DataFrame([dump_coverage(con, lg, pool) for lg in POST_SETTLERS]))
    thick = thick_late(rows)
    daily = {}
    for lg in (*PRE_SETTLERS, *POST_SETTLERS):
        d = load_daily(con, lg)
        if pool is not None:
            d = d.filter(pl.col("item_id").is_in(list(pool)))
        daily[lg] = daily_rows(d, thick.filter(league=lg))
    post = pl.concat([daily[lg] for lg in POST_SETTLERS])
    both = pl.concat(list(daily.values()))
    for h in DAILY_HORIZONS:
        for name, rs in (("post", post), ("pre+post", both)):
            bt = backtest(rs, "div", h, targets=list(POST_SETTLERS))
            bt.write_parquet(f"{out}_daily_{name}_div_{h}.parquet")
            s = score(bt, ["phase", "thick", "model"], (0.05,)).join(
                per_league(bt, ["phase", "thick", "model"], 0.05),
                on=["phase", "thick", "model"],
            )
            print(f"== Dumps, {name} leagues' paths, Divines, {h}")
            print(
                s.filter(pl.col("model").is_in(["item", "shrunk", "momentum", "item+mom"]))
                .select("phase", "thick", "model", "n", "skill", "skill_won", "cover", "width")
                .sort("phase", "thick", "model")
            )

    pths, consts = build(rows)
    pths.write_parquet(f"{out}_paths.parquet")
    print("\n== What the server needs")
    print(consts)
    print(
        pths.group_by("horizon").agg(
            rows=pl.len(), items=pl.col("item_id").n_unique(), bins=pl.col("bin").n_unique()
        )
    )


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1])
