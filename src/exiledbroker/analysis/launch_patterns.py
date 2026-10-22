"""How unique prices move over a league's first two weeks."""

from datetime import date

import duckdb
import polars as pl

from exiledbroker.normalize.dump_loader import SOURCE as DAILY
from exiledbroker.normalize.exchange_loader import SOURCE as HOURLY
from exiledbroker.storage import db

# The currency exchange arrived with Settlers; earlier leagues are context only.
EXCHANGE_ERA = date(2024, 7, 26)
TIERS = [  # by divine price on the base day
    (50.0, "chase (≥50 div)"),
    (5.0, "mid (5–50 div)"),
    (0.5, "low (0.5–5 div)"),
    (0.0, "cheap (<0.5 div)"),
]


def _tier(col: str) -> pl.Expr:
    expr = pl.lit(TIERS[-1][1])
    for floor, label in reversed(TIERS[:-1]):
        expr = pl.when(pl.col(col) >= floor).then(pl.lit(label)).otherwise(expr)
    return expr


def unique_moves(
    con: duckdb.DuckDBPyConnection,
    since: date | None = date(2023, 12, 1),
    base_day: int = 2,
    end_day: int = 14,
    confidence: str | None = "High",
) -> pl.DataFrame:
    """One row per unique per challenge league: divine price on base_day and end_day.

    Day 1 is mostly low-confidence, so the default base is day 2. With `confidence`
    set, both prices must have it, to keep thin early listings out.
    """
    rows = db.frame(
        con,
        """
        SELECT l.name AS league, l.start_at, i.id AS item_id, i.canonical_name AS name,
               i.category, p.day_offset, p.divine_value, p.confidence
        FROM price_observation p
        JOIN item i ON i.id = p.item_id
        JOIN league l ON l.id = p.league_id
        WHERE p.source = ? AND l.kind = 'challenge' AND i.category LIKE 'Unique%'
          AND l.start_at >= ? AND p.day_offset IN (?, ?) AND p.divine_value > 0
        """,
        [DAILY, since or date(2000, 1, 1), base_day, end_day],
    )
    if confidence:
        rows = rows.filter(pl.col("confidence") == confidence)
    keys = ["league", "start_at", "item_id", "name", "category"]
    base = rows.filter(pl.col("day_offset") == base_day).select(*keys, base=pl.col("divine_value"))
    end = rows.filter(pl.col("day_offset") == end_day).select(*keys, end=pl.col("divine_value"))
    return (
        base.join(end, on=keys)
        .with_columns(ratio=pl.col("end") / pl.col("base"), tier=_tier("base"))
        .with_columns(exchange_era=pl.col("start_at") >= pl.lit(EXCHANGE_ERA))
    )


def by_tier(moves: pl.DataFrame, per_league: bool = True) -> pl.DataFrame:
    """Median end/base ratio and share of items that rose, per tier (and league)."""
    keys = ["tier", "league", "start_at"] if per_league else ["tier"]
    out = moves.group_by(keys).agg(
        pl.len().alias("items"),
        pl.col("league").n_unique().alias("leagues"),
        pl.col("ratio").median().alias("median_ratio"),
        (pl.col("ratio") > 1).mean().alias("share_up"),
    )
    order = {label: i for i, (_, label) in enumerate(TIERS)}
    out = out.with_columns(pl.col("tier").replace_strict(order).alias("_order"))
    sort = ["_order", "start_at"] if per_league else ["_order"]
    return out.sort(sort, descending=[False, True][: len(sort)]).drop("_order")


# --- Recency -----------------------------------------------------------------------


def recency_weights(leagues_newest_first: list[str], half_life: float = 2.0) -> dict[str, float]:
    """Weight per league: the newest is 1, and each `half_life` leagues back halves it."""
    return {name: 0.5 ** (i / half_life) for i, name in enumerate(leagues_newest_first)}


def hourly_league_names(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Challenge leagues with hourly exchange data, newest first."""
    q = """
        SELECT l.name FROM league l
        JOIN ingest_load il ON il.league_id = l.id AND il.source = ?
        WHERE l.kind = 'challenge'
        ORDER BY l.start_at DESC
    """
    return [r[0] for r in db.rows(con, q, [HOURLY])]


def daily_league_names(con: duckdb.DuckDBPyConnection, since: date | None = None) -> list[str]:
    """Challenge leagues with daily dump data, newest first."""
    q = """
        SELECT l.name FROM league l
        JOIN ingest_load il ON il.league_id = l.id AND il.source = ?
        WHERE l.kind = 'challenge' AND l.start_at >= ?
        ORDER BY l.start_at DESC
    """
    return [r[0] for r in db.rows(con, q, [DAILY, since or date(2000, 1, 1)])]


# --- Launch curves (hourly) ----------------------------------------------------------

UNIT_COLUMN = {"chaos": "chaos_value", "divine": "divine_value"}
CURVE_SCHEMA = {
    "league": pl.String,
    "item_id": pl.String,
    "name": pl.String,
    "bucket_day": pl.Float64,
    "value": pl.Float64,
    "relative": pl.Float64,
    "volume": pl.Float64,
    "baseline_hours": pl.UInt32,
}


def launch_curves(
    con: duckdb.DuckDBPyConnection,
    item_ids: list[str],
    leagues: list[str],
    unit: str = "chaos",
    bucket_hours: int = 6,
    days: int = 14,
) -> pl.DataFrame:
    """Hourly prices bucketed (volume-weighted) per league, plus `relative`: the price
    divided by that item's day-1 price in the same league, so leagues with different
    price levels share one scale (1.0 = day-1 price).

    The day-1 price is the median of its hourly prices in the first 24 hours: thin
    early markets (e.g. a few junk Mirror trades) would skew an average.
    `baseline_hours` says how many hours it rests on."""
    if unit not in UNIT_COLUMN:
        raise ValueError(f"unit must be one of {', '.join(UNIT_COLUMN)}")
    if not item_ids or not leagues:
        return pl.DataFrame(schema=CURVE_SCHEMA)
    col = UNIT_COLUMN[unit]
    rows = db.frame(
        con,
        f"""
        SELECT l.name AS league, i.id AS item_id, i.canonical_name AS name,
               p.day_offset, p.{col} AS value, p.volume
        FROM price_observation p
        JOIN item i ON i.id = p.item_id
        JOIN league l ON l.id = p.league_id
        WHERE p.source = ? AND p.{col} IS NOT NULL AND p.volume > 0
          AND p.day_offset >= 0 AND p.day_offset < ?
          AND i.id IN ({", ".join("?" for _ in item_ids)})
          AND l.name IN ({", ".join("?" for _ in leagues)})
        """,
        [HOURLY, days, *item_ids, *leagues],
    )
    if rows.is_empty():
        return pl.DataFrame(schema=CURVE_SCHEMA)
    width = bucket_hours / 24
    keys = ["league", "item_id", "name"]
    bucketed = (
        rows.with_columns(bucket_day=(pl.col("day_offset") / width).floor() * width)
        .group_by(*keys, "bucket_day")
        .agg(
            ((pl.col("value") * pl.col("volume")).sum() / pl.col("volume").sum()).alias("value"),
            pl.col("volume").sum(),
        )
    )
    day1 = (
        rows.filter(pl.col("day_offset") < 1)
        .group_by(keys)
        .agg(pl.col("value").median().alias("day1"), pl.len().alias("baseline_hours"))
    )
    return (
        bucketed.join(day1, on=keys, how="left")
        .with_columns(
            relative=pl.col("value") / pl.col("day1"),
            baseline_hours=pl.col("baseline_hours").fill_null(0).cast(pl.UInt32),
        )
        .drop("day1")
        .sort(*keys, "bucket_day")
        .select(list(CURVE_SCHEMA))
    )


def weighted_curve(curves: pl.DataFrame, weights: dict[str, float]) -> pl.DataFrame:
    """Recency-weighted mean of `relative` per bucket across leagues (one item)."""
    if curves.is_empty():
        return pl.DataFrame(
            schema={"bucket_day": pl.Float64, "relative": pl.Float64, "leagues": pl.UInt32}
        )
    w = curves.drop_nulls("relative").with_columns(
        weight=pl.col("league").replace_strict(weights, default=0.0)
    )
    return (
        w.group_by("bucket_day")
        .agg(
            ((pl.col("relative") * pl.col("weight")).sum() / pl.col("weight").sum()).alias(
                "relative"
            ),
            pl.col("league").n_unique().alias("leagues"),
        )
        .sort("bucket_day")
    )


def turning_points(curve: pl.DataFrame) -> dict:
    """Day of the low and of the peak of a relative curve (and their values)."""
    c = curve.drop_nulls("relative")
    if c.is_empty():
        return {"low_day": None, "low": None, "peak_day": None, "peak": None}
    low, peak = c.sort("relative").row(0, named=True), c.sort("relative").row(-1, named=True)
    return {
        "low_day": low["bucket_day"],
        "low": low["relative"],
        "peak_day": peak["bucket_day"],
        "peak": peak["relative"],
    }


# --- Group timing (hourly) -----------------------------------------------------------


def group_curves(
    con: duckdb.DuckDBPyConnection,
    group_id: str,
    leagues: list[str],
    unit: str = "chaos",
    bucket_hours: int = 6,
    min_baseline_hours: int = 6,
) -> pl.DataFrame:
    """Median relative curve per league across a tracked group's items.

    Items need at least `min_baseline_hours` traded hours on day 1 for a baseline."""
    ids = [
        r[0]
        for r in db.rows(con, "SELECT item_id FROM tracked_item WHERE group_id = ?", [group_id])
    ]
    curves = launch_curves(con, ids, leagues, unit, bucket_hours)
    if curves.is_empty():
        return pl.DataFrame(
            schema={
                "league": pl.String,
                "bucket_day": pl.Float64,
                "relative": pl.Float64,
                "items": pl.UInt32,
            }
        )
    return (
        curves.filter(pl.col("baseline_hours") >= min_baseline_hours)
        .drop_nulls("relative")
        .group_by("league", "bucket_day")
        .agg(pl.col("relative").median(), pl.col("item_id").n_unique().alias("items"))
        .sort("league", "bucket_day")
    )


# --- Card turn-ins across leagues ----------------------------------------------------


def turn_ins_across_leagues(
    con: duckdb.DuckDBPyConnection, leagues: list[str], weights: dict[str, float]
) -> pl.DataFrame:
    """Per card and league: profitable share of hours and average margin %; plus a
    recency-weighted summary across leagues (in chaos; margins are ratios, so the
    unit doesn't matter)."""
    from exiledbroker.services.divination import turn_in_summary

    frames = []
    for league in leagues:
        s = turn_in_summary(con, league, "chaos").filter(pl.col("hours") > 0)
        if not s.is_empty():
            frames.append(
                s.select(
                    "item_id",
                    "name",
                    "filter_tier",
                    "stack_size",
                    "reward_quantity",
                    "reward_name",
                    "hours",
                    "profitable_share",
                    "avg_margin_pct",
                ).with_columns(league=pl.lit(league))
            )
    if not frames:
        return pl.DataFrame()
    per = pl.concat(frames).with_columns(
        weight=pl.col("league").replace_strict(weights, default=0.0)
    )
    return (
        per.group_by(
            "item_id", "name", "filter_tier", "stack_size", "reward_quantity", "reward_name"
        )
        .agg(
            pl.col("league").n_unique().alias("leagues"),
            ((pl.col("profitable_share") * pl.col("weight")).sum() / pl.col("weight").sum()).alias(
                "weighted_profitable_share"
            ),
            ((pl.col("avg_margin_pct") * pl.col("weight")).sum() / pl.col("weight").sum()).alias(
                "weighted_margin_pct"
            ),
            pl.col("profitable_share").min().alias("worst_league_share"),
            pl.struct("league", "avg_margin_pct").alias("by_league"),
        )
        .sort("weighted_margin_pct", descending=True)
    )
