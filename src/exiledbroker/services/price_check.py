"""The Price check page (docs/price-check.md, workstream C): one league's search list
and movers, and one item's view, each one small document per data version.

- **The items** are the core pool's exchange items (`price_paths.pool_names`) that
  have traded in the league's hosted window, named and labelled for the search box
  (the mechanic that drops it, from config/mechanics.toml, else its price group).
- **What a server knows now** (`features`, reduced in SQL from `cross_market_hour`):
  the price now (the median of the item's traded hours in the latest 6, in Chaos and
  in Divines at each hour's rate; the verdict needs at least 2), the same 24 hours
  earlier (so the 24-hour move, in Divines), and the market's thickness over the
  latest 72 loaded hours (finding 9: traded in 80% of them, and a median hour of at
  least 300c traded, untraded hours counting as 0).
- **The outlook** (`outlook`): typical = weight × the item's path from this half-day
  bin of the league (`price_paths`), the band typical + the residual quantiles, the
  verdict `price_outlook.ship_verdict`. Sent as fractions (exp − 1: −0.08 is −8%), in
  Divines. Outside days 0–13, or for an item under 2 past leagues, there is no verdict
  and no band (the user, after finding 9).
- **The movers**: in the launch fortnight, the strongest 24-hour calls; otherwise (or
  with no call at all) the biggest 24-hour moves among thick markets, by the amount
  changed in Divines rather than the percentage (the user), with no Sell or Hold labels
  (`movers_mode`). Thin markets are left out of the moves: their
  hourly prices rest on a trade or two and bounce back (finding 7).
- **One item** adds its hourly series over the hosted window (Chaos, and Divines at the
  hour's rate), the stack seller's inputs (`sell_helper.markets`), its launch premium
  (`launch_history`) and the best-hour inputs (`sell_helper.constants`).

SQL here must stay Postgres-compatible and aggregates in SQL: the hosted site's
Postgres serves the same queries.
"""

import math
from datetime import UTC, datetime, timedelta

import polars as pl

from exiledbroker.analysis import price_outlook as po
from exiledbroker.config import Settings, get_settings
from exiledbroker.normalize import mechanics as basket_config
from exiledbroker.services import price_paths, sell_helper
from exiledbroker.storage import db

NOW_HOURS = po.SMOOTH_HOURS  # the price now: the latest 6 hours' median
NOW_MIN = po.SMOOTH_MIN  # ... of at least 2 traded hours, for a verdict
TRAIL_HOURS = po.TRAIL_HOURS  # thickness, volume and the stack seller: the latest 72
PRICE_HOURS = 24  # the stack seller's price per market: the latest 24 hours' median
MOVERS = 20
LAUNCH_DAYS = 14  # the verdict's days (0–13)
SIGNIFICANT = 6  # series prices are rounded to this many significant digits
GROUP_LABELS = {
    "currency": "Currency",
    "essence": "Essence",
    "scarab": "Scarab",
    "divination": "Divination card",
}
PREMIUM_WINDOWS = ("day1", "days2_4", "days5_10")


# --- The league and its items --------------------------------------------------------


def league_state(con, league: str) -> dict:
    """The league's launch, latest traded hour and that hour's day of the league
    (null before the first trades), from the (league, time) index."""
    rows = db.rows(
        con,
        """
        SELECT l.launched_at,
               (SELECT max(x.observed_at) FROM cross_market_hour x
                WHERE x.league_id = l.id) AS latest
        FROM league l WHERE l.name = ?
        """,
        [league],
    )
    if not rows or rows[0][1] is None:
        return {"launched_at": rows[0][0] if rows else None, "latest": None, "day_offset": None}
    launched, latest = rows[0]
    day = db.scalar(
        con,
        """
        SELECT max(day_offset) FROM cross_market_hour
        WHERE league_id = (SELECT id FROM league WHERE name = ?) AND observed_at = ?
        """,
        [league, latest],
    )
    return {"launched_at": launched, "latest": latest, "day_offset": day}


def labels(settings: Settings) -> dict[str, str]:
    """Item name → label for the search box: the first mechanic in
    config/mechanics.toml whose outputs (or groups) have it."""
    out: dict[str, str] = {}
    groups = {}
    for m in basket_config.load_mechanics(settings):
        for name in m.outputs:
            out.setdefault(name, m.name)
        for g in m.groups:
            groups.setdefault(g, m.name)
    return out | {f"group:{g}": name for g, name in groups.items()}


def items(con, league: str, settings: Settings | None = None) -> pl.DataFrame:
    """The core pool's exchange items that traded in the league's hosted window:
    item_id, name, label. Sorted by name (in polars: Postgres sorts by locale)."""
    settings = settings or get_settings()
    traded = db.frame(
        con,
        """
        SELECT i.id AS item_id, i.canonical_name AS name,
               (SELECT min(t.group_id) FROM tracked_item t WHERE t.item_id = i.id) AS grp
        FROM item i
        WHERE i.id IN (
            SELECT DISTINCT item_id FROM cross_market_hour
            WHERE league_id = (SELECT id FROM league WHERE name = ?)
              AND chaos_price > 0 AND chaos_volume > 0)
        """,
        [league],
    )
    schema = {"item_id": pl.String, "name": pl.String, "label": pl.String}
    if traded.is_empty():
        return pl.DataFrame(schema=schema)
    names = price_paths.pool_names(con, settings)
    if names is not None:
        traded = traded.filter(pl.col("name").is_in(list(names)))
    named = labels(settings)
    rows = [
        {
            "item_id": r["item_id"],
            "name": r["name"],
            "label": named.get(r["name"])
            or named.get(f"group:{r['grp']}")
            or GROUP_LABELS.get(r["grp"] or ""),
        }
        for r in traded.iter_rows(named=True)
    ]
    return pl.DataFrame(rows, schema=schema).sort("name", "item_id")


# --- What a server knows now ---------------------------------------------------------


FEATURES = {
    "item_id": pl.String,
    "chaos_now": pl.Float64,
    "div_now": pl.Float64,
    "n_now": pl.Int64,
    "div_ago": pl.Float64,
    "n_ago": pl.Int64,
    "traded": pl.Int64,
    "units": pl.Float64,
    "loaded": pl.Int64,
    "cv_h": pl.Float64,
}


def features(con, league: str, latest: datetime, item_id: str | None = None) -> pl.DataFrame:
    """Per item (or the one `item_id`) that traded in the latest TRAIL_HOURS: the price
    now in Chaos and in Divines (median of the traded hours in the latest NOW_HOURS,
    and how many), the Divine price 24 hours earlier, hours traded and units traded,
    the loaded hours, and the median Chaos traded an hour over the loaded hours
    (untraded ones as 0). One aggregate over the latest 72 hours' rows, in SQL."""
    first = latest - timedelta(hours=TRAIL_HOURS - 1)
    now = latest - timedelta(hours=NOW_HOURS - 1)
    ago_end = latest - timedelta(hours=PRICE_HOURS)
    ago = ago_end - timedelta(hours=NOW_HOURS - 1)
    one = "AND c.item_id = ?" if item_id else ""
    lid = "(SELECT id FROM league WHERE name = ?)"
    params = [league, first, latest, *([item_id] if item_id else []), league, first, latest]
    out = db.frame(
        con,
        f"""
        WITH h AS (
            SELECT c.item_id, c.observed_at, c.chaos_price AS chaos, c.chaos_volume AS units,
                   c.chaos_price * c.chaos_volume AS cv,
                   c.chaos_price / nullif(c.divine_rate, 0) AS div
            FROM cross_market_hour c
            WHERE c.league_id = {lid} AND c.observed_at >= ? AND c.observed_at <= ?
              AND c.chaos_price > 0 AND c.chaos_volume > 0 {one}
        ),
        hrs AS (
            SELECT hour FROM exchange_hour_loaded
            WHERE league_id = {lid} AND hour >= ? AND hour <= ?
        ),
        grid AS (
            SELECT i.item_id, coalesce(h.cv, 0) AS cv
            FROM (SELECT DISTINCT item_id FROM h) i CROSS JOIN hrs
            LEFT JOIN h ON h.item_id = i.item_id AND h.observed_at = hrs.hour
        ),
        thick AS (
            SELECT item_id, percentile_cont(0.5) WITHIN GROUP (ORDER BY cv) AS cv_h
            FROM grid GROUP BY item_id
        ),
        stats AS (
            SELECT item_id,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY chaos)
                       FILTER (WHERE observed_at >= ?) AS chaos_now,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY div)
                       FILTER (WHERE observed_at >= ?) AS div_now,
                   count(div) FILTER (WHERE observed_at >= ?) AS n_now,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY div)
                       FILTER (WHERE observed_at >= ? AND observed_at <= ?) AS div_ago,
                   count(div) FILTER (WHERE observed_at >= ? AND observed_at <= ?) AS n_ago,
                   count(*) AS traded, sum(units) AS units
            FROM h GROUP BY item_id
        )
        SELECT s.item_id, s.chaos_now, s.div_now, s.n_now, s.div_ago, s.n_ago, s.traded,
               s.units, (SELECT count(*) FROM hrs) AS loaded, t.cv_h
        FROM stats s LEFT JOIN thick t ON t.item_id = s.item_id
        """,
        [*params, now, now, now, ago, ago_end, ago, ago_end],
    )
    if out.is_empty():
        return pl.DataFrame(schema=FEATURES)
    return out.select(list(FEATURES)).cast(FEATURES)


def with_moves(f: pl.DataFrame) -> pl.DataFrame:
    """Thickness, and the 24-hour move in Divines (a fraction) where both ends have a
    price of at least NOW_MIN traded hours."""
    ok = (pl.col("n_now") >= NOW_MIN) & (pl.col("n_ago") >= NOW_MIN) & (pl.col("div_ago") > 0)
    share = pl.col("traded") / pl.col("loaded").cast(pl.Float64)
    thick = (
        (pl.col("loaded") > 0) & (share >= po.THICK_SHARE) & (pl.col("cv_h") >= po.THICK_CHAOS_H)
    )
    return f.with_columns(
        thick=thick.fill_null(False),
        change_24h=pl.when(ok).then(pl.col("div_now") / pl.col("div_ago") - 1),
    )


# --- The outlook -------------------------------------------------------------------------


def phase_of(day: float | None) -> str:
    """Finding 9's phase of a day of the league; "later" from day 14 (no verdict)."""
    if day is None or day < 0:
        return po.LATER
    for name, first, end in po.PHASES:
        if first <= day < end and day < LAUNCH_DAYS:
            return name
    return po.LATER


def league_hour(day: float | None) -> int | None:
    return None if day is None else round(day * 24)


def constants(con) -> dict[tuple[str, bool, str], dict]:
    rows = db.frame(
        con, f"SELECT phase, thick, horizon, weight, low, high FROM {price_paths.CONSTANTS}"
    )
    return {(r["phase"], bool(r["thick"]), r["horizon"]): r for r in rows.iter_rows(named=True)}


def paths(con, bin_: int, item_id: str | None = None) -> pl.DataFrame:
    """The served paths at one bin of the league: every item's, or one item's (a
    primary-key lookup)."""
    one = " AND item_id = ?" if item_id else ""
    out = db.frame(
        con,
        f"SELECT item_id, h24, h24_leagues, d3, d3_leagues FROM {price_paths.PATHS} "
        f"WHERE bin = ?{one}",
        [bin_, *([item_id] if item_id else [])],
    )
    schema = {
        "item_id": pl.String,
        "h24": pl.Float64,
        "h24_leagues": pl.Int64,
        "d3": pl.Float64,
        "d3_leagues": pl.Int64,
    }
    return out.cast(schema) if out.height else pl.DataFrame(schema=schema)


def last_bins(con) -> dict[str, int | None]:
    """The last bin each horizon has a path in (past it, the fortnight has no path to
    take: about day 13 for 24 hours, day 11 for 3 days)."""
    row = db.rows(
        con,
        f"SELECT max(bin) FILTER (WHERE h24 IS NOT NULL), max(bin) FILTER (WHERE d3 IS NOT NULL) "
        f"FROM {price_paths.PATHS}",
    )[0]
    return {"h24": row[0], "d3": row[1]}


def _frac(x: float | None) -> float | None:
    return None if x is None or not math.isfinite(x) else math.expm1(x)


def horizon(
    h: str,
    day: float | None,
    thick: bool,
    priced: bool,
    path: float | None,
    leagues: int | None,
    consts: dict,
    last_bin: int | None,
) -> dict:
    """One horizon's outlook. `state`: "judged" (the model ran: a verdict, possibly
    "none", and the band), "later" (outside the days past leagues' paths cover) or
    "no_history" (under 2 past leagues have this item here)."""
    phase = phase_of(day)
    hour = league_hour(day)
    bin_ = None if hour is None else hour // po.BIN_HOURS
    c = consts.get((phase, thick, h))
    empty = {"typical": None, "low": None, "high": None, "leagues": leagues or 0, "basis": "item"}
    if bin_ is None or phase == po.LATER or (last_bin is not None and bin_ > last_bin):
        return {"verdict": "none", "state": "later", **empty}
    if path is None or c is None:
        return {"verdict": "none", "state": "no_history", **empty}
    typical = c["weight"] * path
    verdict = po.ship_verdict(phase, thick, h, typical) if priced else "none"
    low = None if c["low"] is None else typical + c["low"]
    high = None if c["high"] is None else typical + c["high"]
    return {
        "verdict": verdict,
        "state": "judged",
        "typical": _frac(typical),
        "low": _frac(low),
        "high": _frac(high),
        "leagues": int(leagues or 0),
        "basis": "item",
    }


def outlooks(con, day: float | None, f: pl.DataFrame, item_id: str | None = None) -> dict:
    """item_id → {h24, d3, unit} for the items in `f` (with_moves' frame)."""
    hour = league_hour(day)
    consts = constants(con)
    last = last_bins(con) if consts else {"h24": None, "d3": None}
    ps: dict[str, dict] = {}
    if hour is not None and 0 <= hour < LAUNCH_DAYS * 24 and consts:
        ps = {
            r["item_id"]: r for r in paths(con, hour // po.BIN_HOURS, item_id).iter_rows(named=True)
        }
    out = {}
    for r in f.iter_rows(named=True):
        p = ps.get(r["item_id"], {})
        priced = (r["n_now"] or 0) >= NOW_MIN
        out[r["item_id"]] = {
            h: horizon(
                h, day, bool(r["thick"]), priced, p.get(h), p.get(f"{h}_leagues"), consts, last[h]
            )
            for h in po.HORIZONS
        } | {"unit": "divine"}
    return out


def _no_features(item_id: str) -> pl.DataFrame:
    """An item that hasn't traded in the latest TRAIL_HOURS: nothing known now."""
    counts = {"n_now": 0, "n_ago": 0, "traded": 0, "loaded": 0}
    row = {k: None for k in FEATURES} | counts | {"item_id": item_id}
    return with_moves(pl.DataFrame([row], schema=FEATURES))


# --- The page's two documents -----------------------------------------------------------


def index(con, league: str, settings: Settings | None = None) -> dict:
    """`GET /api/price-check/{league}`: the search list (every core-pool exchange item
    that traded in the league's window, each with its price now, units traded an hour,
    24-hour verdict and 24-hour move in Divines) and the movers (≤ MOVERS item ids)."""
    state = league_state(con, league)
    latest, day = state["latest"], state["day_offset"]
    doc = {
        "league": league,
        "latest_hour": latest.replace(tzinfo=UTC) if latest is not None else None,
        "day_offset": day,
        "items": [],
        "movers": [],
        "movers_mode": "moves",
    }
    if latest is None:
        return doc
    listed = items(con, league, settings)
    f = with_moves(features(con, league, latest))
    rows = listed.join(f, on="item_id", how="left")
    looks = outlooks(con, day, rows.filter(pl.col("traded").is_not_null()))
    out = []
    for r in rows.iter_rows(named=True):
        o = looks.get(r["item_id"])
        h24 = o["h24"] if o else None
        loaded = r["loaded"] or 0
        out.append(
            {
                "item_id": r["item_id"],
                "name": r["name"],
                "label": r["label"],
                "chaos": _sig(r["chaos_now"]),
                "volume_h": _sig(r["units"] / loaded) if loaded and r["units"] else None,
                "verdict_24h": h24["verdict"] if h24 else "none",
                "change_24h": _sig(r["change_24h"]),
                "_typical": h24["typical"] if h24 else None,
                "_thick": bool(r["thick"]),
                # The amount changed in Divines: what the moves are ranked by (the user).
                "_amount": abs(r["div_now"] - r["div_ago"])
                if r["change_24h"] is not None
                else None,
            }
        )
    calls = [x for x in out if x["verdict_24h"] != "none" and x["_typical"] is not None]
    if calls:
        calls.sort(key=lambda x: (-abs(x["_typical"]), x["item_id"]))
        doc["movers"], doc["movers_mode"] = [x["item_id"] for x in calls[:MOVERS]], "calls"
    else:
        moves = [x for x in out if x["_thick"] and x["change_24h"] is not None]
        moves.sort(key=lambda x: (-x["_amount"], x["item_id"]))
        doc["movers"] = [x["item_id"] for x in moves[:MOVERS]]
    doc["items"] = [{k: v for k, v in x.items() if not k.startswith("_")} for x in out]
    return doc


def series(con, league: str, item_id: str) -> list[list]:
    """The item's traded hours over the hosted window: [hour, Chaos, Divines at the
    hour's rate] (a primary-key range: league, item, time)."""
    rows = db.rows(
        con,
        """
        SELECT observed_at, chaos_price, chaos_price / nullif(divine_rate, 0)
        FROM cross_market_hour
        WHERE league_id = (SELECT id FROM league WHERE name = ?) AND item_id = ?
          AND chaos_price > 0 AND chaos_volume > 0
        ORDER BY observed_at
        """,
        [league, item_id],
    )
    return [[t.replace(tzinfo=UTC), _sig(c), _sig(d)] for t, c, d in rows]


def _sig(x) -> float | None:
    """`x` to SIGNIFICANT significant digits (smaller JSON; null for NaN / inf)."""
    if x is None:
        return None
    x = float(x)
    if not math.isfinite(x):
        return None
    if x == 0:
        return 0.0
    return round(x, SIGNIFICANT - 1 - math.floor(math.log10(abs(x))))


def stack(con, league: str, latest: datetime, item_id: str, loaded: int) -> dict:
    """The stack seller's inputs per market: price in that market's currency (median,
    latest 24 hours), units traded an hour, the typical hourly swing and the share of
    hours traded (latest 3 days). A market it hasn't traded in is null."""
    mk = {
        r["market"]: r
        for r in sell_helper.markets(con, league, latest, [item_id]).iter_rows(named=True)
    }
    end = latest + timedelta(hours=1)
    price = db.rows(
        con,
        """
        SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY chaos_price)
                   FILTER (WHERE chaos_price > 0 AND chaos_volume > 0),
               percentile_cont(0.5) WITHIN GROUP (ORDER BY divine_price)
                   FILTER (WHERE divine_price > 0 AND divine_volume > 0)
        FROM cross_market_hour
        WHERE league_id = (SELECT id FROM league WHERE name = ?) AND item_id = ?
          AND observed_at >= ? AND observed_at < ?
        """,
        [league, item_id, end - timedelta(hours=PRICE_HOURS), end],
    )[0]

    def market(name: str, p) -> dict | None:
        s = mk.get(name)
        if s is None:
            return None
        return {
            "price": None if p is None else float(p),
            "volume_h": s["volume"] / loaded if loaded else None,
            "sigma_h": s["sigma"],
            "hours_traded": s["hours"] / loaded if loaded else None,
        }

    return {"chaos": market("chaos", price[0]), "divine": market("divine", price[1])}


def launch_premium(con, item_id: str) -> dict | None:
    """What the item was worth in each launch window of past leagues against its price
    in the sale days (12–14), in Divines: the median over the captured leagues."""
    rows = db.rows(
        con,
        """
        SELECT w.window_id,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY w.divine / nullif(s.divine, 0))
        FROM launch_history w
        JOIN launch_history s
          ON s.league = w.league AND s.item_id = w.item_id AND s.window_id = 'sell'
        WHERE w.item_id = ? AND w.window_id <> 'sell' AND s.divine > 0
        GROUP BY w.window_id
        """,
        [item_id],
    )
    got = {w: None if v is None else float(v) for w, v in rows}
    if not any(got.get(w) is not None for w in PREMIUM_WINDOWS):
        return None
    return {w: got.get(w) for w in PREMIUM_WINDOWS}


def item(con, league: str, item_id: str, entry: dict) -> dict:
    """`GET /api/price-check/{league}/{item_id}`: one item of the index (`entry`, its
    row there): its series, outlook, stack inputs, launch premium and best-hour inputs."""
    state = league_state(con, league)
    latest, day = state["latest"], state["day_offset"]
    f = with_moves(features(con, league, latest, item_id)) if latest is not None else pl.DataFrame()
    if f.is_empty():
        f = _no_features(item_id)
    row = f.row(0, named=True)
    look = outlooks(con, day, f, item_id)[item_id]
    helper = sell_helper.constants(con, day)
    return {
        "item_id": item_id,
        "name": entry["name"],
        "label": entry["label"],
        "latest_hour": latest.replace(tzinfo=UTC) if latest is not None else None,
        "day_offset": day,
        "thick": bool(row["thick"]),
        "change_24h": row["change_24h"],
        "series": series(con, league, item_id),
        "outlook": look,
        "stack": stack(con, league, latest, item_id, row["loaded"] or 0)
        if latest is not None
        else {"chaos": None, "divine": None},
        "launch_premium": launch_premium(con, item_id),
        "hours": helper["hours"],
        "impact": helper["impact"],
    }
