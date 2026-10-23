"""Launch picks: what an average player should buy early in a league to keep up with
inflation, ranked from the past challenge leagues' hourly exchange prices.

For each buy window (day 1, days 2–4, days 5–10) and each tracked item, a league's
**growth** is the item's median Divine price in the sale days (12–14) over its median
Divine price in the window. Growth is in Divines on purpose: Chaos loses half its value
against Divines over a launch fortnight, so a pick has to beat simply holding Divines.

Candidates must be:
- **carried over**: traded in the window and the sale in at least MIN_LEAGUES of the
  reference leagues, which drops each league's own currency (Dead Man's Sulphur, the
  Mirage coins) and anything else that didn't stay;
- **affordable**: a typical unit price of at most BUDGET_DIVINES in the window;
- **liquid**: at least MIN_LIQUIDITY Divines traded a day, in the window and the sale,
  so a couple of Divines in and out doesn't move the market;
- **up** overall: a typical growth above 1.

They're ranked with `scoring.rank_score` on typical growth (recency-weighted geometric
mean, newest league weighted most), the worst league's growth, consistency (the
recency-weighted share of all reference leagues where it beat Divines, so a league it
didn't trade in counts against it) and liquidity. `build` writes the result into small tables; the site reads them with
`picks`. It needs the history, so it runs on the research database, never the worker.
"""

import math
from datetime import UTC, datetime, timedelta

import duckdb
import polars as pl

from exiledbroker.analysis import launch_patterns as lp
from exiledbroker.normalize.exchange_loader import SOURCE as HOURLY
from exiledbroker.services import leagues as league_ids
from exiledbroker.services.live import live_leagues
from exiledbroker.services.scoring import rank_score
from exiledbroker.storage import db

# window id -> (first day, last day), 1-based: day 1 is the first 24 hours
WINDOWS = {"day1": (1, 1), "days2_4": (2, 4), "days5_10": (5, 10)}
SELL = (12, 14)
REFERENCE_LEAGUES = 5
HALF_LIFE = 2.0  # leagues; the newest counts 1, two leagues back 0.5
MIN_LEAGUES = 3
BUDGET_DIVINES = 2.0
MIN_LIQUIDITY = 20.0  # Divines traded a day
TOP = 10  # picks kept per window
FACTORS = {
    "growth": ("growth", True),
    "worst": ("worst", True),
    "consistency": ("consistency", True),
    "liquidity": ("liquidity", True),
}
WEIGHTS = {"growth": 0.35, "worst": 0.25, "consistency": 0.25, "liquidity": 0.15}
CHAOS = "currency:chaos-orb"
BENCHMARKS = [CHAOS, "currency:divine-orb"]
TABLES = ["launch_window", "launch_pick", "launch_pick_league"]


def _window_case() -> tuple[str, list]:
    """SQL CASE naming the window (or the sale) an hour falls in, and its params."""
    whens, params = [], []
    for wid, (first, last) in [*WINDOWS.items(), ("sell", SELL)]:
        whens.append("WHEN p.day_offset >= ? AND p.day_offset < ? THEN ?")
        params += [first - 1, last, wid]
    return f"CASE {' '.join(whens)} END", params


def window_prices(con: duckdb.DuckDBPyConnection, leagues: list[str]) -> pl.DataFrame:
    """Per league, tracked item and window (or 'sell'): the median hourly Divine price
    and the Divines traded a day."""
    ids = league_ids.ids(con, leagues)
    case, case_params = _window_case()
    days = {wid: last - first + 1 for wid, (first, last) in [*WINDOWS.items(), ("sell", SELL)]}
    out = db.frame(
        con,
        f"""
        WITH h AS (
            SELECT p.league_id, p.item_id, {case} AS window_id, p.divine_value,
                   p.chaos_volume * p.divine_value / nullif(p.chaos_value, 0) AS divine_volume
            FROM price_observation p
            WHERE p.source = ? AND p.league_id IN ({league_ids.marks(ids)})
              AND p.day_offset >= 0 AND p.day_offset < ? AND p.divine_value > 0
              AND p.item_id IN (SELECT item_id FROM tracked_item)
        )
        SELECT l.name AS league, h.item_id, h.window_id,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY h.divine_value) AS divine,
               sum(h.divine_volume) AS divine_volume
        FROM h JOIN league l ON l.id = h.league_id
        WHERE h.window_id IS NOT NULL
        GROUP BY l.name, h.item_id, h.window_id
        """,
        [*case_params, HOURLY, *ids, SELL[1]],
    )
    return out.with_columns(
        per_day=pl.col("divine_volume") / pl.col("window_id").replace_strict(days)
    )


def _weighted(col: str) -> pl.Expr:
    return (pl.col(col) * pl.col("w")).sum() / pl.col("w").sum()


def rank(prices: pl.DataFrame, leagues: list[str]) -> dict[str, pl.DataFrame]:
    """Score every window from `window_prices`: 'windows', 'picks' and 'per_league'."""
    weights = lp.recency_weights(leagues, HALF_LIFE)
    sell = prices.filter(window_id="sell").select(
        "league", "item_id", sell="divine", sell_per_day="per_day"
    )
    moves = (
        prices.filter(pl.col("window_id") != "sell")
        .join(sell, on=["league", "item_id"])
        .with_columns(
            growth=pl.col("sell") / pl.col("divine"),
            liquidity=pl.min_horizontal("per_day", "sell_per_day"),
            w=pl.col("league").replace_strict(weights, default=0.0),
        )
    )
    per_item = (
        moves.filter(~pl.col("item_id").is_in(BENCHMARKS))
        .group_by("window_id", "item_id")
        .agg(
            log_growth=(pl.col("growth").log() * pl.col("w")).sum() / pl.col("w").sum(),
            worst=pl.col("growth").min(),
            rose=(pl.col("growth") > 1).sum().cast(pl.Int32),
            consistency=(pl.col("w") * (pl.col("growth") > 1)).sum() / sum(weights.values()),
            traded=pl.len().cast(pl.Int32),
            buy_divine=_weighted("divine"),
            liquidity=_weighted("liquidity"),
        )
        .with_columns(growth=pl.col("log_growth").exp())
        .drop("log_growth")
        .sort("window_id", "item_id")
    )
    affordable = (pl.col("buy_divine") <= BUDGET_DIVINES) & (pl.col("liquidity") >= MIN_LIQUIDITY)

    windows, picks = [], []
    for wid, (first, last) in WINDOWS.items():
        cands = per_item.filter(
            pl.col("window_id") == wid, affordable, pl.col("traded") >= MIN_LEAGUES
        ).filter(pl.col("growth") > 1)
        ranked = rank_score(cands, FACTORS, WEIGHTS).head(TOP)
        picks.append(ranked.with_columns(rank=pl.int_range(1, ranked.height + 1, dtype=pl.Int32)))
        # The benchmarks: Chaos held through, and the median affordable, liquid item.
        mine = moves.filter(window_id=wid)
        chaos = mine.filter(item_id=CHAOS)
        typical = (
            mine.filter(
                ~pl.col("item_id").is_in(BENCHMARKS),
                pl.col("divine") <= BUDGET_DIVINES,
                pl.col("liquidity") >= MIN_LIQUIDITY,
            )
            .group_by("league", "w")
            .agg(pl.col("growth").median())
        )
        windows.append(
            {
                "window_id": wid,
                "first_day": first,
                "last_day": last,
                "sell_first": SELL[0],
                "sell_last": SELL[1],
                "leagues": ",".join(leagues),
                "chaos_growth": _geo(chaos),
                "typical_growth": _geo(typical),
                "candidates": cands.height,
            }
        )
    picks_df = pl.concat(picks)
    kept = picks_df.select("window_id", "item_id")
    per_league = moves.join(kept, on=["window_id", "item_id"]).select(
        "window_id", "item_id", "league", "growth"
    )
    return {"windows": pl.DataFrame(windows), "picks": picks_df, "per_league": per_league}


def _geo(df: pl.DataFrame) -> float | None:
    """Recency-weighted geometric mean of `growth`."""
    df = df.filter(pl.col("growth") > 0)
    if df.is_empty() or df["w"].sum() == 0:
        return None
    return math.exp((df["growth"].log() * df["w"]).sum() / df["w"].sum())


def build(con: duckdb.DuckDBPyConnection, leagues: list[str] | None = None) -> dict[str, int]:
    """Rank the picks from the newest REFERENCE_LEAGUES leagues whose launch fortnight
    is complete, and replace the launch tables with them. Returns rows per table."""
    if leagues is None:
        leagues = complete_leagues(con)[:REFERENCE_LEAGUES]
    out = rank(window_prices(con, leagues), leagues) if leagues else None
    built = datetime.now(UTC).replace(tzinfo=None)
    rows = {t: 0 for t in TABLES}
    con.execute("BEGIN TRANSACTION")
    try:
        for table in TABLES:
            con.execute(f"DELETE FROM {table}")
        if out is not None and out["picks"].height:
            names = db.frame(
                con,
                f"""
                SELECT i.id AS item_id, i.canonical_name AS name, min(t.group_id) AS group_id
                FROM item i JOIN tracked_item t ON t.item_id = i.id
                WHERE i.id IN ({league_ids.marks(out["picks"]["item_id"].to_list())})
                GROUP BY i.id, i.canonical_name
                """,
                out["picks"]["item_id"].to_list(),
            )
            picks = out["picks"].join(names, on="item_id")
            frames = {
                "launch_window": out["windows"].with_columns(built_at=pl.lit(built)),
                "launch_pick": picks.select(
                    "window_id",
                    "item_id",
                    "rank",
                    "name",
                    "group_id",
                    "score",
                    "growth",
                    "worst",
                    "rose",
                    "traded",
                    "buy_divine",
                    "liquidity",
                ),
                "launch_pick_league": out["per_league"],
            }
            for table, df in frames.items():
                con.register("_rows", df.to_arrow())
                con.execute(f"INSERT INTO {table} ({', '.join(df.columns)}) SELECT * FROM _rows")
                con.unregister("_rows")
                rows[table] = df.height
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    return rows


def complete_leagues(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Challenge leagues, newest first, whose hourly data reaches the end of the sale
    days (a live league still in its launch fortnight isn't a reference yet)."""
    q = """
        SELECT l.name FROM league l
        WHERE l.kind = 'challenge' AND EXISTS (
            SELECT 1 FROM price_observation p
            WHERE p.league_id = l.id AND p.source = ? AND p.item_id = ?
              AND p.day_offset >= ?)
        ORDER BY l.start_at DESC
    """
    return [r[0] for r in db.rows(con, q, [HOURLY, CHAOS, SELL[1] - 1])]


def windows(con) -> pl.DataFrame:
    return db.frame(con, "SELECT * FROM launch_window ORDER BY first_day")


def picks(con) -> pl.DataFrame:
    return db.frame(con, "SELECT * FROM launch_pick ORDER BY window_id, rank")


def pick_leagues(con) -> pl.DataFrame:
    return db.frame(con, "SELECT window_id, item_id, league, growth FROM launch_pick_league")


LIVE_HOURS = 6  # a live price older than this is too stale to show


def launch_board(con) -> list[dict]:
    """The Launch market page: each window with its benchmarks and ranked picks, each
    pick with its growth per reference league (newest first) and, for the newest
    league with trades, its latest Divine price (null if it hasn't traded lately)."""
    wins = windows(con)
    if wins.is_empty():
        return []
    ps, per = picks(con), pick_leagues(con)
    live = live_leagues(con).filter(pl.col("latest_hour").is_not_null()).head(1)
    league = live["name"][0] if live.height else None
    prices: dict[str, float] = {}
    if league and ps.height:
        ids = sorted(set(ps["item_id"].to_list()))
        latest = live["latest_hour"][0]
        q = f"""
            SELECT p.item_id, p.divine_value, p.observed_at FROM price_observation p
            WHERE p.league_id = (SELECT id FROM league WHERE name = ?) AND p.source = ?
              AND p.observed_at > ? AND p.divine_value > 0
              AND p.item_id IN ({league_ids.marks(ids)})
        """
        rows = db.rows(con, q, [league, HOURLY, latest - timedelta(hours=LIVE_HOURS), *ids])
        for item_id, value, _ in sorted(rows, key=lambda r: r[2]):
            prices[item_id] = value  # the latest hour wins
    out = []
    for w in wins.to_dicts():
        order = w["leagues"].split(",")
        mine = ps.filter(window_id=w["window_id"]).sort("rank")
        rows = []
        for p in mine.to_dicts():
            grown = dict(
                per.filter(window_id=w["window_id"], item_id=p["item_id"])
                .select("league", "growth")
                .iter_rows()
            )
            leagues = [{"league": lg, "growth": grown.get(lg)} for lg in order]
            rows.append({**p, "leagues": leagues, "live_divine": prices.get(p["item_id"])})
        built = w["built_at"].replace(tzinfo=UTC)  # a list, not a frame: mark UTC here
        out.append({**w, "built_at": built, "leagues": order, "live_league": league, "picks": rows})
    return out
