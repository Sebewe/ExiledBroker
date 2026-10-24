"""Mechanic paths, the launch outlook and Easy to sell (finding 8 in docs/findings.md).
Research on the local database, for the Farming page's `mechanics` and `outlook`
(docs/farming.md, workstream D).

Everything rests on one reduced table, `item_days`: per league, basket item and day of
the league, the median hourly price (Chaos, and Divines at the same hour's rate), the
Chaos traded, the hours traded and the median hourly move. It's the shape of the
reduced history the server will keep (workstream E), so whatever is decided here can be
computed hosted without past leagues' hours. Prices come from `cross_market_hour`, which
has every item that traded against Chaos (`price_observation` keeps only some, so many
basket items would be missing from the launch curves in `launch_patterns`).

- **Index:** a mechanic's equal-weighted geometric mean of its items' price over their
  day-0 median (the first 24 hours; `launch_patterns`' relative curves, per basket).
- **Usual:** past leagues' index at the same day of the league, and their spread.
  `walk_forward_usual` predicts each league from the earlier ones only.
- **Outlook:** a mechanic's launch premium per window: its items' median Divine price in
  the window over their median on the fortnight's last days (12–14), so above 1 means
  its drops were worth more then than once the market settled. `walk_forward_outlook`
  ranks each league's mechanics from the earlier leagues and scores it against what
  happened.
- **Easy to sell:** per mechanic, the median item's Amihud-style ratio (typical hourly
  move over Chaos traded an hour), share of hours traded and Chaos traded an hour.

Baskets are `{mechanic: (name, [item_id])}`, from config/mechanics.toml (workstream A),
legacy outputs included so past leagues' curves have them.

    python -m exiledbroker.analysis.mechanics          # the tables in finding 8
"""

import itertools
import math
import statistics
from pathlib import Path

import polars as pl

from exiledbroker.analysis import launch_patterns as lp
from exiledbroker.config import get_settings
from exiledbroker.services.scoring import rank_score
from exiledbroker.storage import db

LAUNCH_DAYS = 14
MIN_BASELINE_HOURS = 6  # day-0 hours an item needs for a baseline (as group_curves)
MIN_ITEMS = 3  # items a basket needs on a day for an index (2 is too noisy: finding 8)
HALF_LIFE = 2.0  # leagues
WINDOWS = {"day1": (0, 1), "days2_4": (1, 4), "days5_10": (4, 10)}  # [first, end) day
SETTLED = (11, 14)  # days 12–14, 1-based: the Launch picks' sale days
MIN_PAST_LEAGUES = 2  # past leagues a usual (and its range) needs
RECENT_DAYS = 3  # the live league's Easy to sell looks back this far
# Easy to sell, a percentile among mechanics (`services/scoring.rank_score`). Amihud and
# Chaos traded per item say much the same (rank correlation −0.95); hours traded adds
# breadth. Together they persist from league to league at 0.86 (finding 8).
LIQUIDITY_FACTORS = {
    "amihud": ("amihud", False),
    "item_cv_h": ("item_cv_h", True),
    "traded": ("traded", True),
}
LIQUIDITY_WEIGHTS = {"amihud": 0.5, "item_cv_h": 0.25, "traded": 0.25}
# The mechanics' score: above its usual (persists: 0.9 three days on), the launch
# outlook for the window the league is in, and Easy to sell. A factor that's null for
# every mechanic (no usual after day 13, no window after day 10) drops out.
SCORE_FACTORS = {
    "trend": ("vs_usual", True),
    "outlook": ("premium", True),
    "liquidity": ("liquidity", True),
}
SCORE_WEIGHTS = {"trend": 0.4, "outlook": 0.3, "liquidity": 0.3}
Baskets = dict[str, tuple[str, list[str]]]


def baskets(con, path: Path | None = None, legacy: bool = True) -> Baskets:
    """Workstream A's baskets as item ids (outputs and groups, plus legacy outputs)."""
    from exiledbroker.normalize import mechanics as mx

    ms = mx.load(path or getattr(get_settings(), "mechanics_file", Path("config/mechanics.toml")))
    return {m.id: (m.name, mx.output_ids(con, m, legacy=legacy)) for m in ms}


ITEM_DAY_SCHEMA = {
    "league": pl.String,
    "item_id": pl.String,
    "day": pl.Int32,
    "chaos": pl.Float64,
    "divine": pl.Float64,
    "chaos_volume": pl.Float64,
    "hours": pl.Int32,
    "absret": pl.Float64,
    "day_hours": pl.Int32,
}


def item_days(con, league: str, item_ids: list[str]) -> pl.DataFrame:
    """Per item and day of the league (0 = the first 24 hours): median hourly Chaos price,
    median Divine price (Chaos price over the same hour's Divine rate), Chaos traded,
    hours traded, the median |log change| between consecutive traded hours, and how
    many hours of that day had any trade at all (`day_hours`)."""
    if not item_ids:
        return pl.DataFrame(schema=ITEM_DAY_SCHEMA)
    marks = ", ".join("?" for _ in item_ids)
    out = db.frame(
        con,
        f"""
        WITH h AS (
            SELECT item_id, observed_at, CAST(floor(day_offset) AS INTEGER) AS day,
                   chaos_price AS p, chaos_price * chaos_volume AS cv,
                   chaos_price / nullif(divine_rate, 0) AS pd
            FROM cross_market_hour
            WHERE league_id = (SELECT id FROM league WHERE name = ?)
              AND chaos_price > 0 AND chaos_volume > 0 AND item_id IN ({marks})
        ),
        r AS (
            SELECT h.*, abs(ln(p / lag(p) OVER (PARTITION BY item_id ORDER BY observed_at)))
                        AS absret
            FROM h
        ),
        dh AS (
            SELECT CAST(floor(day_offset) AS INTEGER) AS day,
                   count(DISTINCT observed_at) AS day_hours
            FROM cross_market_hour
            WHERE league_id = (SELECT id FROM league WHERE name = ?)
            GROUP BY 1
        )
        SELECT ? AS league, r.item_id, r.day,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY r.p) AS chaos,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY r.pd) AS divine,
               sum(r.cv) AS chaos_volume, count(*) AS hours,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY r.absret) AS absret,
               max(dh.day_hours) AS day_hours
        FROM r JOIN dh ON dh.day = r.day
        GROUP BY r.item_id, r.day
        """,
        [league, *item_ids, league, league],
    )
    return out.cast(ITEM_DAY_SCHEMA) if not out.is_empty() else pl.DataFrame(schema=ITEM_DAY_SCHEMA)


def _membership(bks: Baskets) -> pl.DataFrame:
    return pl.DataFrame(
        [(m, i) for m, (_, ids) in bks.items() for i in ids],
        schema={"mechanic": pl.String, "item_id": pl.String},
        orient="row",
    )


# --- Index ---------------------------------------------------------------------------


def index(days: pl.DataFrame, bks: Baskets, unit: str = "chaos") -> pl.DataFrame:
    """Per league, mechanic and day: the geometric mean of price over the day-0 median
    across the basket's items (those with a baseline and a price that day), and how many
    items it rests on. Null where fewer than MIN_ITEMS items."""
    base = days.filter(pl.col("day") == 0, pl.col("hours") >= MIN_BASELINE_HOURS).select(
        "league", "item_id", base=unit
    )
    rel = (
        days.join(base, on=["league", "item_id"])
        .filter(pl.col(unit) > 0, pl.col("base") > 0)
        .with_columns(lr=(pl.col(unit) / pl.col("base")).log())
        .join(_membership(bks), on="item_id")
    )
    return (
        rel.group_by("league", "mechanic", "day")
        .agg(lr=pl.col("lr").mean(), items=pl.len().cast(pl.Int32))
        .with_columns(
            index=pl.when(pl.col("items") >= MIN_ITEMS).then(pl.col("lr").exp()),
        )
        .drop("lr")
        .sort("league", "mechanic", "day")
    )


def usual(ix: pl.DataFrame, leagues: list[str], how: str = "weighted") -> pl.DataFrame:
    """Past leagues' index per mechanic and day from `leagues` (newest first): the
    `usual` (recency-weighted geometric mean, or the plain `median`), the min/max and
    the interquartile range, and how many leagues it rests on."""
    w = lp.recency_weights(leagues, HALF_LIFE)
    past = ix.filter(pl.col("league").is_in(leagues), pl.col("index").is_not_null()).with_columns(
        w=pl.col("league").replace_strict(w, default=0.0), lr=pl.col("index").log()
    )
    centre = (
        ((pl.col("lr") * pl.col("w")).sum() / pl.col("w").sum()).exp()
        if how == "weighted"
        else pl.col("index").median()
    )
    return (
        past.group_by("mechanic", "day")
        .agg(
            usual=centre,
            low=pl.col("index").min(),
            high=pl.col("index").max(),
            q1=pl.col("index").quantile(0.25, "linear"),
            q3=pl.col("index").quantile(0.75, "linear"),
            leagues=pl.len().cast(pl.Int32),
        )
        .filter(pl.col("leagues") >= MIN_PAST_LEAGUES)
    )


def matched(days: pl.DataFrame, bks: Baskets, target: str, unit: str = "chaos") -> pl.DataFrame:
    """Every league's index on the items `target` has a baseline for, so past leagues'
    paths are of the same basket as the target's (a basket's make-up changes between
    leagues as items are added or leave the game)."""
    have = days.filter(
        pl.col("league") == target, pl.col("day") == 0, pl.col("hours") >= MIN_BASELINE_HOURS
    )["item_id"]
    return index(days.filter(pl.col("item_id").is_in(have.implode())), bks, unit)


def walk_forward_usual(
    ix: pl.DataFrame,
    leagues: list[str],
    min_past: int = 2,
    days: pl.DataFrame | None = None,
    bks: Baskets | None = None,
    unit: str = "chaos",
) -> pl.DataFrame:
    """Each league (`leagues` newest first) against the usual from the leagues before
    it, per mechanic and day 1–13: log error of the weighted usual, the median and a
    pooled usual (every mechanic's together: no mechanic-specific path), and whether
    the league fell inside the min/max band and the interquartile band. With `days` and
    `bks`, past leagues use the target's items only (`matched`)."""
    rows = []
    full = ix
    for i, target in enumerate(leagues):
        past = leagues[i + 1 :]
        if len(past) < min_past:
            continue
        ix = full if days is None or bks is None else matched(days, bks, target, unit)
        mine = ix.filter(
            pl.col("league") == target,
            pl.col("day").is_between(1, LAUNCH_DAYS - 1),
            pl.col("index").is_not_null(),
        )
        u = usual(ix, past).rename({"usual": "weighted"})
        m = usual(ix, past, "median").select("mechanic", "day", median="usual")
        w = lp.recency_weights(past, HALF_LIFE)
        pooled = (
            ix.filter(pl.col("league").is_in(past), pl.col("index").is_not_null())
            .with_columns(w=pl.col("league").replace_strict(w, default=0.0))
            .group_by("day")
            .agg(pooled=((pl.col("index").log() * pl.col("w")).sum() / pl.col("w").sum()).exp())
        )
        rows.append(
            mine.join(u, on=["mechanic", "day"])
            .join(m, on=["mechanic", "day"])
            .join(pooled, on="day")
            .with_columns(
                target=pl.lit(target),
                err_weighted=(pl.col("index") / pl.col("weighted")).log(),
                err_median=(pl.col("index") / pl.col("median")).log(),
                err_pooled=(pl.col("index") / pl.col("pooled")).log(),
                err_flat=pl.col("index").log(),  # "no change since day 0"
                in_minmax=pl.col("index").is_between(pl.col("low"), pl.col("high")),
                in_iqr=pl.col("index").is_between(pl.col("q1"), pl.col("q3")),
            )
        )
    return pl.concat(rows) if rows else pl.DataFrame()


def spread(ix: pl.DataFrame) -> pl.DataFrame:
    """Per mechanic: the typical spread between leagues (sd of log index across leagues,
    averaged over days 1–13) next to how far its path sits from the pooled path."""
    d = ix.filter(pl.col("day").is_between(1, LAUNCH_DAYS - 1), pl.col("index").is_not_null())
    d = d.with_columns(lr=pl.col("index").log())
    pooled = d.group_by("league", "day").agg(pool=pl.col("lr").median())
    per = (
        d.join(pooled, on=["league", "day"])
        .group_by("mechanic", "day")
        .agg(sd=pl.col("lr").std(), own=(pl.col("lr") - pl.col("pool")).mean(), n=pl.len())
        .filter(pl.col("n") >= 3)
    )
    return (
        per.group_by("mechanic")
        .agg(between_leagues=pl.col("sd").mean(), vs_pooled=pl.col("own").abs().mean())
        .sort("mechanic")
    )


def persistence(ix: pl.DataFrame, leagues: list[str], lag: int = 3) -> pl.DataFrame:
    """Does a mechanic above its usual stay above it? Per league (from the earlier
    leagues' usual) and day, the rank correlation across mechanics of index ÷ usual on
    that day and `lag` days later."""
    rows = []
    for i, target in enumerate(leagues):
        past = leagues[i + 1 :]
        if len(past) < 2:
            continue
        v = (
            ix.filter(league=target)
            .join(usual(ix, past), on=["mechanic", "day"])
            .with_columns(vs=(pl.col("index") / pl.col("usual")).log())
            .filter(pl.col("vs").is_not_null())
            .select("mechanic", "day", "vs")
        )
        later = v.with_columns(day=pl.col("day") - lag).rename({"vs": "vs_later"})
        j = v.join(later, on=["mechanic", "day"])
        for (day,), g in j.group_by("day"):
            rho = _spearman(g["vs"], g["vs_later"]) if g.height >= 6 else math.nan
            if not math.isnan(rho):
                rows.append({"target": target, "day": day, "rho": rho})
    return pl.DataFrame(rows)


def _spearman(a: pl.Series, b: pl.Series) -> float:
    """Rank correlation; NaN when either side has no spread."""
    if a.n_unique() < 2 or b.n_unique() < 2:
        return math.nan
    df = pl.DataFrame({"a": a, "b": b})
    return float(df.select(pl.corr("a", "b", method="spearman")).item())


# --- Launch outlook ------------------------------------------------------------------


def premiums(days: pl.DataFrame, bks: Baskets) -> pl.DataFrame:
    """Per league, mechanic and window: the launch premium, the geometric mean over the
    basket's items of their median Divine price in the window over their median on the
    settled days (SETTLED), and how many items it rests on (at least MIN_ITEMS)."""
    case = pl.lit(None, dtype=pl.String)
    for wid, (lo, hi) in WINDOWS.items():
        case = pl.when(pl.col("day").is_between(lo, hi - 1)).then(pl.lit(wid)).otherwise(case)
    tagged = days.filter(pl.col("divine") > 0).with_columns(window=case)
    win = (
        tagged.filter(pl.col("window").is_not_null())
        .group_by("league", "item_id", "window")
        .agg(p=pl.col("divine").median())
    )
    settled = (
        days.filter(pl.col("divine") > 0, pl.col("day").is_between(SETTLED[0], SETTLED[1] - 1))
        .group_by("league", "item_id")
        .agg(s=pl.col("divine").median())
    )
    return (
        win.join(settled, on=["league", "item_id"])
        .join(_membership(bks), on="item_id")
        .with_columns(lr=(pl.col("p") / pl.col("s")).log())
        .group_by("league", "mechanic", "window")
        .agg(premium=pl.col("lr").mean().exp(), items=pl.len().cast(pl.Int32))
        .filter(pl.col("items") >= MIN_ITEMS)
        .sort("league", "mechanic", "window")
    )


def outlook(pr: pl.DataFrame, leagues: list[str]) -> pl.DataFrame:
    """The outlook from past leagues (`leagues` newest first): per mechanic and window,
    the recency-weighted geometric mean premium, the worst league's and the count."""
    w = lp.recency_weights(leagues, HALF_LIFE)
    return (
        pr.filter(pl.col("league").is_in(leagues))
        .with_columns(w=pl.col("league").replace_strict(w, default=0.0))
        .group_by("mechanic", "window")
        .agg(
            premium=((pl.col("premium").log() * pl.col("w")).sum() / pl.col("w").sum()).exp(),
            worst=pl.col("premium").min(),
            leagues=pl.len().cast(pl.Int32),
        )
    )


def walk_forward_outlook(pr: pl.DataFrame, leagues: list[str], min_past: int = 2) -> pl.DataFrame:
    """Each league ranked from the earlier ones: per window, the rank correlation between
    the predicted and actual premiums, the same for the last league alone, and how many
    of the predicted top 3 were in the actual top 3 (chance: 9 / mechanics)."""
    rows = []
    for i, target in enumerate(leagues):
        past = leagues[i + 1 :]
        if len(past) < min_past:
            continue
        pred = outlook(pr, past)
        last = pr.filter(league=past[0]).select("mechanic", "window", last="premium")
        act = pr.filter(league=target).select("mechanic", "window", actual="premium")
        for wid in WINDOWS:
            j = (
                act.filter(window=wid)
                .join(pred.filter(window=wid), on=["mechanic", "window"])
                .join(last.filter(window=wid), on=["mechanic", "window"], how="left")
            )
            if j.height < 4:
                continue
            top = set(j.sort("premium", descending=True)["mechanic"][:3])
            real = set(j.sort("actual", descending=True)["mechanic"][:3])
            jl = j.drop_nulls("last")
            rows.append(
                {
                    "target": target,
                    "window": wid,
                    "mechanics": j.height,
                    "rho": _spearman(j["premium"], j["actual"]),
                    "rho_last": _spearman(jl["last"], jl["actual"]) if jl.height >= 4 else None,
                    "top3": len(top & real),
                    "chance": 9 / j.height,
                }
            )
    return pl.DataFrame(rows)


# --- Easy to sell --------------------------------------------------------------------


def liquidity(days: pl.DataFrame, bks: Baskets, first: int, end: int) -> pl.DataFrame:
    """Per league and mechanic over days [first, end): the median item's Amihud-style
    ratio (median hourly |move| over Chaos traded an hour; lower is easier) and Chaos
    traded an hour, the mean share of hours its items traded (an item the league has
    but that didn't trade then counts as 0), and the basket's Chaos traded an hour."""
    span = pl.col("day").is_between(first, end - 1)
    hours = days.filter(span).group_by("league", "day").agg(pl.col("day_hours").max())
    hours = hours.group_by("league").agg(span_hours=pl.col("day_hours").sum())
    present = days.select("league", "item_id").unique()  # traded at some point in the league
    per_item = (
        days.filter(span)
        .group_by("league", "item_id")
        .agg(
            absret=pl.col("absret").median(),
            cv=pl.col("chaos_volume").sum(),
            h=pl.col("hours").sum(),
        )
    )
    per_item = (
        present.join(per_item, on=["league", "item_id"], how="left")
        .join(hours, on="league")
        .with_columns(
            cv_h=pl.col("cv").fill_null(0) / pl.col("span_hours"),
            traded=pl.col("h").fill_null(0) / pl.col("span_hours"),
        )
        .with_columns(amihud=pl.col("absret") / pl.when(pl.col("cv_h") > 0).then(pl.col("cv_h")))
    )
    return (
        per_item.join(_membership(bks), on="item_id")
        .group_by("league", "mechanic")
        .agg(
            amihud=pl.col("amihud").median(),
            traded=pl.col("traded").mean(),
            item_cv_h=pl.col("cv_h").median(),
            basket_cv_h=pl.col("cv_h").sum(),
            items=pl.len().cast(pl.Int32),
        )
        .sort("league", "mechanic")
    )


def liquidity_persistence(liq: pl.DataFrame, leagues: list[str]) -> dict[str, float]:
    """Mean rank correlation across mechanics, league to the next, of each factor."""
    out = {}
    for col in ("amihud", "traded", "item_cv_h", "basket_cv_h"):
        rhos = []
        for newer, older in itertools.pairwise(leagues):
            j = liq.filter(league=newer).join(
                liq.filter(league=older).select("mechanic", prev=col), on="mechanic"
            )
            if j.height >= 4:
                rhos.append(_spearman(j[col], j["prev"]))
        out[col] = statistics.fmean(rhos) if rhos else math.nan
    return out


def easy_to_sell(liq: pl.DataFrame) -> pl.DataFrame:
    """One league's `liquidity` rows with `liquidity`: the percentile among mechanics."""
    out = rank_score(liq.rename({"mechanic": "item_id"}), LIQUIDITY_FACTORS, LIQUIDITY_WEIGHTS)
    return out.rename({"item_id": "mechanic", "score": "liquidity"}).drop(
        [f"{f}_rank" for f in LIQUIDITY_FACTORS]
    )


def window_at(day: int | None) -> str | None:
    """The launch window a day of the league (0-based) falls in, if any."""
    if day is None:
        return None
    return next((w for w, (lo, hi) in WINDOWS.items() if lo <= day < hi), None)


def score(df: pl.DataFrame) -> pl.DataFrame:
    """Score mechanics with columns `mechanic`, `vs_usual` (index ÷ usual), `premium`
    (the outlook for the current window) and `liquidity`; best first."""
    out = rank_score(df.rename({"mechanic": "item_id"}), SCORE_FACTORS, SCORE_WEIGHTS)
    return out.rename({"item_id": "mechanic"}).drop([f"{f}_rank" for f in SCORE_FACTORS])


# --- Report --------------------------------------------------------------------------


def load(con, bks: Baskets, leagues: list[str]) -> pl.DataFrame:
    ids = sorted({i for _, xs in bks.values() for i in xs})
    return pl.concat([item_days(con, lg, ids) for lg in leagues])


def _rmse(col: str) -> pl.Expr:
    return (pl.col(col) ** 2).mean().sqrt().round(2)


def main() -> None:  # pragma: no cover - research printout
    import duckdb

    s = get_settings()
    con = duckdb.connect(str(s.db_path), read_only=True)
    bks = baskets(con)
    leagues = lp.hourly_league_names(con)
    days = load(con, bks, leagues)
    names = {m: n for m, (n, _) in bks.items()}
    named = pl.col("mechanic").replace_strict(names).alias("name")
    pl.Config.set_tbl_rows(100)
    pl.Config.set_tbl_cols(20)
    pl.Config.set_float_precision(2)

    print("== Usual path, walk-forward (each league from the earlier ones), days 1–13")
    for unit in ("chaos", "divine"):
        wf = walk_forward_usual(index(days, bks, unit), leagues)
        print(
            unit,
            wf.select(
                weighted=_rmse("err_weighted"),
                median=_rmse("err_median"),
                pooled=_rmse("err_pooled"),
                flat=_rmse("err_flat"),
                in_minmax=pl.col("in_minmax").mean().round(2),
                in_iqr=pl.col("in_iqr").mean().round(2),
                n=pl.len(),
            ),
        )
    ix = index(days, bks, "divine")
    wf = walk_forward_usual(ix, leagues)
    print(
        wf.group_by("mechanic")
        .agg(rmse=_rmse("err_weighted"), pooled=_rmse("err_pooled"), flat=_rmse("err_flat"))
        .with_columns(named)
        .sort("rmse")
    )
    u = usual(ix, leagues).filter(pl.col("day").is_in([1, 3, 7, 13]))
    print("\n== Usual index (Divines) and past leagues' range, all leagues")
    print(
        u.with_columns(
            cell=pl.format("{} ({}–{})", *(pl.col(c).round(2) for c in ("usual", "low", "high")))
        )
        .pivot(on="day", index="mechanic", values="cell")
        .with_columns(named)
        .sort("mechanic")
    )
    p = persistence(ix, leagues)
    print("\n== Above usual, 3 days later (rank correlation by day)")
    print(p.group_by("day").agg(pl.col("rho").mean()).sort("day"))

    pr = premiums(days, bks)
    print("\n== Outlook walk-forward")
    wo = walk_forward_outlook(pr, leagues)
    print(wo.sort("target", "window"))
    print(wo.group_by("window").agg(pl.col("rho", "rho_last", "top3", "chance").mean()))
    o = outlook(pr, leagues).with_columns(
        cell=pl.format("{} (worst {})", pl.col("premium").round(2), pl.col("worst").round(2))
    )
    print(o.pivot(on="window", index="mechanic", values="cell").with_columns(named))

    for first, end in ((1, 4), (11, 14)):
        liq = liquidity(days, bks, first, end)
        print(
            f"\n== Easy to sell, days {first}–{end - 1}: persistence",
            liquidity_persistence(liq, leagues),
        )
    print(easy_to_sell(liquidity(days, bks, 11, 14).filter(league=leagues[0])).with_columns(named))


if __name__ == "__main__":  # pragma: no cover
    main()
