"""Past leagues' paths, what Price check's verdict reads (finding 9; workstream B of
docs/price-check.md).

The verdict is the item's own path from this point of past leagues, shrunk: per item
and half-day bin of the league (`bin` = hour since launch // 12), the median over
past leagues of each league's median change in Divines over the next 24 hours and the
next 3 days (`analysis/price_outlook`), times a weight fitted per phase and market
thickness. Three small tables hold it:

- `price_path_league`: each finished league's own path, one row per item with the
  bins as JSON lists (~900 rows a league). Captured once a league's launch fortnight
  is over (`capture`), so the served paths can be rebuilt without past leagues' hours,
  which the hosted site doesn't keep.
- `price_path`: what the site reads, per item and bin, the median over the captured
  leagues and how many leagues it rests on, kept only where at least 2 have it
  (`rebuild`, ~19k rows).
- `price_path_constant`: the weight and the band's residual quantiles per phase,
  thickness and horizon (12 rows), fitted with numpy (`fit`), so only locally
  (`eb price-check build`). They live in a table rather than in code because they're
  refitted from the data whenever a league is added; the verdict thresholds
  (`price_outlook.SHIP`) are a research decision and stay in code.

Locally `eb price-check build` captures every league with a complete fortnight,
rebuilds the paths and refits the constants; `eb site seed` copies the three tables.
Hosted, the pipeline's `refresh` captures the live league once its fortnight is over
and rebuilds the paths (the medians gain a league); the constants stay as fitted
until the next local build and seed.
"""

import json
from datetime import UTC, datetime

import polars as pl

from exiledbroker.analysis import price_outlook as po
from exiledbroker.config import Settings, get_settings
from exiledbroker.ingest.core_pool import load_pool
from exiledbroker.services import launch_picks
from exiledbroker.services.live import DIVINE_ID
from exiledbroker.storage import db

LEAGUES = "price_path_league"
PATHS = "price_path"
CONSTANTS = "price_path_constant"
TABLES = [LEAGUES, PATHS, CONSTANTS]
LAUNCH_DAYS = 14  # past leagues' hours are the launch fortnight's
DIGITS = 6  # stored log changes are rounded to this many decimals


# --- Which items ---------------------------------------------------------------------


def pool_names(con, settings: Settings | None = None) -> set[str] | None:
    """The current core pool's names (every listed group, cards included, plus the
    includes, minus the excludes), or None without snapshots (every item counts)."""
    pool = load_pool(con, settings or get_settings())
    if not pool.listed:
        return None
    names = set().union(*pool.listed.values(), *pool.include.values())
    return names - pool.exclude


# --- Capturing a league ----------------------------------------------------------------


def load(con, league: str) -> tuple[pl.DataFrame, pl.DataFrame]:
    """A league's launch fortnight as `price_outlook.hourly_rows` takes it: traded
    hours per item (with its name, for the pool) and each hour's Divine rate.
    Postgres-compatible (the hosted pipeline runs it on the site's database)."""
    lid = "(SELECT id FROM league WHERE name = ?)"
    prices = db.frame(
        con,
        f"""
        SELECT c.item_id, i.canonical_name AS name,
               CAST(round(c.day_offset * 24) AS INTEGER) AS hour,
               c.chaos_price AS chaos, c.chaos_price * c.chaos_volume AS cv
        FROM cross_market_hour c JOIN item i ON i.id = c.item_id
        WHERE c.league_id = {lid} AND c.day_offset < ?
          AND c.chaos_price > 0 AND c.chaos_volume > 0
        """,
        [league, LAUNCH_DAYS],
    )
    hours = db.frame(
        con,
        f"""
        SELECT CAST(round(day_offset * 24) AS INTEGER) AS hour,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY divine_rate)
                   FILTER (WHERE divine_rate > 0) AS rate
        FROM cross_market_hour WHERE league_id = {lid} AND day_offset < ?
        GROUP BY 1
        """,
        [league, LAUNCH_DAYS],
    )
    prices = prices.cast({"hour": pl.Int32, "chaos": pl.Float64, "cv": pl.Float64})
    hours = hours.cast({"hour": pl.Int32, "rate": pl.Float64})
    return prices.with_columns(league=pl.lit(league), grp=pl.lit("other")), hours.with_columns(
        league=pl.lit(league)
    )


def league_rows(con, league: str, names: set[str] | None) -> pl.DataFrame:
    """The league's backtest rows (`price_outlook.hourly_rows`), core-pool items only."""
    return _rows(*load(con, league), names)


def _rows(prices: pl.DataFrame, hours: pl.DataFrame, names: set[str] | None) -> pl.DataFrame:
    if names is not None:
        prices = prices.filter(pl.col("name").is_in(list(names)))
    if prices.is_empty() or hours.is_empty():
        return pl.DataFrame()
    return po.hourly_rows(prices.drop("name"), hours)


def divine_rows(hours: pl.DataFrame) -> pl.DataFrame:
    """Divine Orb's own backtest rows, in Chaos: each loaded hour's Divine rate is its
    price that hour, a thick market. Its path is the one in Chaos (`league_paths(rows,
    "chaos")`: in Divines it never moves), and it stays out of `fit`, whose weights are
    for changes in Divines."""
    priced = hours.filter(pl.col("rate") > 0)
    if priced.is_empty():
        return pl.DataFrame()
    prices = priced.select(
        "league",
        pl.lit(DIVINE_ID).alias("item_id"),
        pl.lit("other").alias("grp"),
        "hour",
        pl.col("rate").alias("chaos"),
        pl.lit(po.THICK_CHAOS_H).alias("cv"),
    )
    return po.hourly_rows(prices, hours)


def league_paths(rows: pl.DataFrame, unit: str = "div") -> pl.DataFrame:
    """One league's own path per item: its median change from each bin over each
    horizon (in Divines, or `unit`), as JSON lists by bin (null where it had none)."""
    if rows.is_empty():
        return pl.DataFrame(schema={"item_id": pl.String, **{h: pl.String for h in po.HORIZONS}})
    launch = rows.filter(pl.col("phase") != po.LATER)
    by_item: dict[str, dict[str, dict[int, float]]] = {}
    for h in po.HORIZONS:
        y = f"y_{h}_{unit}"
        med = (
            launch.filter(pl.col(y).is_not_null())
            .group_by("item_id", "bin")
            .agg(v=pl.col(y).median())
        )
        for item_id, b, v in med.iter_rows():
            by_item.setdefault(item_id, {k: {} for k in po.HORIZONS})[h][int(b)] = v

    def as_list(bins: dict[int, float]) -> str:
        if not bins:
            return "[]"
        return json.dumps([_round(bins.get(b)) for b in range(max(bins) + 1)])

    return pl.DataFrame(
        [
            {"item_id": item_id, **{h: as_list(paths[h]) for h in po.HORIZONS}}
            for item_id, paths in sorted(by_item.items())
        ],
        schema={"item_id": pl.String, **{h: pl.String for h in po.HORIZONS}},
    )


def _round(v: float | None) -> float | None:
    return None if v is None else round(v, DIGITS)


def _write(con, table: str, df: pl.DataFrame) -> None:
    """Insert a frame's rows on the pipeline's connection or the local DuckDB."""
    if df.is_empty():
        return
    con.register("_price_rows", df.to_arrow())
    try:
        con.execute(f"INSERT INTO {table} ({', '.join(df.columns)}) SELECT * FROM _price_rows")
    finally:
        con.unregister("_price_rows")


def capture(con, league: str, names: set[str] | None = None) -> pl.DataFrame:
    """Reduce a finished league's launch fortnight to its own paths in
    price_path_league (Divine Orb's in Chaos, `divine_rows`), replacing what was
    captured for it before. Returns the league's backtest rows (what `fit` needs, Divine
    Orb's left out). The read runs on the site's database itself (`db.pushdown`): once a
    league, the fortnight's traded hours (~250k rows)."""
    prices, hours = load(db.pushdown(con), league)
    rows = _rows(prices, hours, names)
    paths = pl.concat([league_paths(rows), league_paths(divine_rows(hours), "chaos")])
    if paths.is_empty():  # still mark it captured, so the pipeline doesn't try again
        paths = pl.DataFrame({"item_id": [""], **{h: ["[]"] for h in po.HORIZONS}})
    start = db.scalar(db.pushdown(con), "SELECT start_at FROM league WHERE name = ?", [league])
    db.execute(con, f"DELETE FROM {LEAGUES} WHERE league = ?", [league])
    _write(
        con,
        LEAGUES,
        paths.select(
            pl.lit(league).alias("league"),
            pl.lit(start, pl.Datetime("us")).alias("league_start"),
            "item_id",
            *po.HORIZONS,
        ),
    )
    return rows


def captured(con) -> list[str]:
    """Leagues in price_path_league, oldest first."""
    q = f"SELECT league, min(league_start) FROM {LEAGUES} GROUP BY league"
    return [r[0] for r in sorted(db.rows(con, q), key=lambda r: (r[1] is None, r[1], r[0]))]


# --- The served paths ------------------------------------------------------------------


def medians(per_league: pl.DataFrame) -> pl.DataFrame:
    """Per item and bin, the median over leagues of each league's path, and how many
    leagues have it, per horizon; a horizon with fewer than MIN_LEAGUES is null, and a
    bin with neither horizon is dropped."""
    out = None
    for h in po.HORIZONS:
        long = (
            per_league.select(
                "league", "item_id", pl.col(h).str.json_decode(pl.List(pl.Float64)).alias("v")
            )
            .with_columns(bin=pl.int_ranges(0, pl.col("v").list.len(), dtype=pl.Int32))
            .explode("v", "bin")
            .filter(pl.col("v").is_not_null())
            .group_by("item_id", "bin")
            .agg(path=pl.col("v").median(), n=pl.len().cast(pl.Int32))
            .filter(pl.col("n") >= po.MIN_LEAGUES)
            .select("item_id", "bin", pl.col("path").alias(h), pl.col("n").alias(f"{h}_leagues"))
        )
        out = (
            long
            if out is None
            else out.join(long, on=["item_id", "bin"], how="full", coalesce=True)
        )
    schema = {
        "item_id": pl.String,
        "bin": pl.Int32,
        "h24": pl.Float64,
        "h24_leagues": pl.Int32,
        "d3": pl.Float64,
        "d3_leagues": pl.Int32,
    }
    if out is None or out.is_empty():
        return pl.DataFrame(schema=schema)
    return out.select(list(schema)).cast(schema).sort("item_id", "bin")


def rebuild(con) -> int:
    """Replace price_path with the medians of every captured league's path. Returns
    the rows written."""
    # Through `con`, not pushed down: in the pipeline's transaction it must see the
    # league just captured (a few MB, once a league).
    per_league = db.frame(con, f"SELECT league, item_id, h24, d3 FROM {LEAGUES}")
    paths = medians(per_league.cast({c: pl.String for c in per_league.columns}))
    db.execute(con, f"DELETE FROM {PATHS}")
    _write(con, PATHS, paths)
    return paths.height


# --- The fitted constants (locally: numpy) ---------------------------------------------


def fit(con, rows: pl.DataFrame, leagues: list[str]) -> int:
    """Refit the weight and band per phase, thickness and horizon on every captured
    league's rows (`price_outlook.build`, leave-one-league-out nested as in finding 9),
    and replace price_path_constant. Returns the rows written."""
    _, consts = po.build(rows)
    built = datetime.now(UTC).replace(tzinfo=None)
    df = consts.select(
        "phase",
        "thick",
        "horizon",
        "weight",
        "low",
        "high",
        leagues=pl.lit(",".join(leagues)),
        built_at=pl.lit(built, pl.Datetime("us")),
    )
    db.execute(con, f"DELETE FROM {CONSTANTS}")
    _write(con, CONSTANTS, df)
    return df.height


def build(con, settings: Settings | None = None) -> dict:
    """`eb price-check build`, on the local research database: capture every league
    with a complete launch fortnight (in one transaction), rebuild the served paths and
    refit the constants. Returns what was built."""
    names = pool_names(con, settings)
    leagues = list(reversed(launch_picks.complete_leagues(con)))  # oldest first
    con.execute("BEGIN TRANSACTION")
    try:
        frames = [capture(con, lg, names) for lg in leagues]
        db.execute(con, f"DELETE FROM {LEAGUES} WHERE league NOT IN (SELECT name FROM league)")
        paths = rebuild(con)
        rows = pl.concat([f for f in frames if not f.is_empty()]) if leagues else pl.DataFrame()
        consts = fit(con, rows, leagues) if rows.height else 0
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    items = db.scalar(con, f"SELECT count(DISTINCT item_id) FROM {PATHS}")
    return {"leagues": leagues, "items": items, "paths": paths, "constants": consts}


# --- The hosted pipeline ---------------------------------------------------------------


def refresh(con, live: str | None, settings: Settings | None = None) -> str | None:
    """Once the live league's launch fortnight is over, capture it and rebuild the
    paths (one more league in the medians). Returns the league captured, else None.
    Runs every hosted pass, so the checks run on the site's database itself
    (`db.pushdown`): a primary-key lookup, and the fortnight check `launch_picks` makes."""
    if live is None:
        return None
    site = db.pushdown(con)
    if db.rows(site, f"SELECT 1 FROM {LEAGUES} WHERE league = ? LIMIT 1", [live]):
        return None
    if not launch_picks._fortnight_over(site, live):
        return None
    con.execute("BEGIN TRANSACTION")
    try:
        capture(con, live, pool_names(con, settings))
        rebuild(con)
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    return live
