"""The Farming page (docs/farming.md, workstream F): which mechanics to farm, the launch
outlook, and the sell helper's inputs, for one league, as the contract's one document.

Every number reuses a definition already decided in research (findings 6–8):
- **Past leagues** come from the reduced history (`item_history.history`, the leagues
  captured before the one served), read through `analysis/mechanics`: `index` and
  `usual` for the usual path and its range, `premiums` and `outlook` for the launch
  outlook, `liquidity` and `easy_to_sell` for Easy to sell before the league has 3 days.
- **The live league** is reduced in SQL to small frames of the same shape
  (`item_history.league_days` over its day 0 and over its latest 3 days, plus medians
  over the latest 24 hours), so no hourly row reaches Python. Its index is
  `analysis/mechanics.index` with each item's latest 24-hour median standing in as a
  day of the league.
- **Hour of day and stack impact** (findings 6 and 7) are constants built locally from
  past leagues' hours (`eb farming build`, which needs numpy: the site image has none)
  and stored as one JSON document in `farming_report`, like the Backtest report.

SQL here must stay Postgres-compatible: the hosted site's Postgres serves the same queries.
"""

import json
import math
from datetime import UTC, datetime, timedelta

import polars as pl

from exiledbroker.analysis import launch_patterns as lp
from exiledbroker.analysis import mechanics as mx
from exiledbroker.config import Settings, get_settings
from exiledbroker.ingest.core_pool import load_pool
from exiledbroker.normalize import mechanics as basket_config
from exiledbroker.services import item_history
from exiledbroker.services.scoring import rank_score
from exiledbroker.storage import db

REPORT = "farming_report"
LAUNCH_DAYS = mx.LAUNCH_DAYS
PRICE_HOURS = 24  # an item's price is its median over the latest 24 published hours
RECENT_HOURS = mx.RECENT_DAYS * 24  # volumes, swings, hours traded, Easy to sell
# The live index's moments, as stand-in days for `analysis/mechanics.index` (negative,
# so they can't meet a real day of the league): now, 24 hours and 7 days earlier.
NOW, DAY_AGO, WEEK_AGO = -1, -2, -8
AGO_HOURS = {NOW: 0, DAY_AGO: 24, WEEK_AGO: 7 * 24}
PRESENT_ONLY = -100  # day-0 rows passed to `liquidity` only to say what the league has
SCORED = [col for col, _ in mx.SCORE_FACTORS.values()]  # vs_usual, premium, liquidity
# Finding 7: a stack is shown as hours of the market's trading, not as a price drop.
IMPACT = {
    "y": None,
    "bands": [0.25, 1.0],
    "note": (
        "Hourly prices swing more than a stack moves them, so this shows how much of the "
        "market's trading your stack is, not a price drop."
    ),
}
DAY_SCHEMA = {
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


# --- The locally built report (hour of day, stack impact) ----------------------------


def store_report(con, doc: dict) -> None:
    """Replace the stored report (`eb farming build`)."""
    db.execute(con, f"DELETE FROM {REPORT}")
    db.execute(
        con,
        f"INSERT INTO {REPORT} (id, built_at, body) VALUES ('latest', ?, ?)",
        [datetime.now(UTC).replace(tzinfo=None), json.dumps(doc)],
    )


def report(con) -> dict | None:
    """The stored report, or None before `eb farming build`."""
    rows = db.rows(con, f"SELECT body FROM {REPORT} WHERE id = 'latest'")
    return json.loads(rows[0][0]) if rows else None


def built_at(con):
    """When the report was built (None before `eb farming build`)."""
    return db.scalar(con, f"SELECT max(built_at) FROM {REPORT}")


def hours_phase(doc: dict, day_offset: float | None) -> str:
    """The report's phase for a day of the league (its first phase before launch), from
    the phase bounds stored with it (`analysis/hours.PHASES`)."""
    phases = doc.get("phases") or []
    if day_offset is not None:
        for name, first, end in phases:
            if first <= day_offset and (end is None or day_offset < end):
                return name
    return phases[0][0] if phases else "d0_2"


def _hours(doc: dict | None, day_offset: float | None) -> dict | None:
    """The report's hour-of-day profiles for the league's phase, with only the baskets
    whose own profile is shown (any other uses the pooled `price`)."""
    if not doc:
        return None
    phase = hours_phase(doc, day_offset)
    rep = (doc.get("hours") or {}).get(phase)
    if rep is None:
        return None
    keep = ("price", "gain", "gap", "best", "worst", "null95", "verdict", "stability", "items")
    return {
        "phase": phase,
        "leagues": rep["leagues"],
        "days": rep["days"],
        "price": rep["price"],
        "price_divine_market": rep["price_divine_market"],
        "divine": rep["divine"],
        "volume": rep["volume"],
        "effect": rep["effect"],
        "effect_divine_market": rep["effect_divine_market"],
        "divine_effect": rep["divine_effect"],
        "mechanics": {
            mid: {k: m.get(k) for k in keep}
            for mid, m in (rep.get("mechanics") or {}).items()
            if m.get("shown")
        },
    }


# --- Baskets -----------------------------------------------------------------------


def baskets(con, settings: Settings) -> tuple[mx.Baskets, mx.Baskets]:
    """config/mechanics.toml as item ids: the current outputs (what the page shows) and
    the outputs plus legacy ones (past leagues' curves), in two queries for all
    mechanics together."""
    mechanics = basket_config.load_mechanics(settings)
    names = sorted({n for m in mechanics for n in m.outputs + m.legacy})
    known = basket_config.resolve(con, names)
    groups = sorted({g for m in mechanics for g in m.groups})
    in_group = {g: basket_config.group_items(con, (g,)) for g in groups}

    def ids(m, legacy: bool) -> list[str]:
        named = m.outputs + (m.legacy if legacy else ())
        out = {known[n] for n in named if n in known}
        return sorted(out.union(*(in_group[g] for g in m.groups)))

    current = {m.id: (m.name, ids(m, False)) for m in mechanics}
    every = {m.id: (m.name, ids(m, True)) for m in mechanics}
    return current, every


def _item_ids(bks: mx.Baskets) -> list[str]:
    return sorted({i for _, ids in bks.values() for i in ids})


# --- The live league, reduced in SQL -------------------------------------------------


def league_state(con, league: str) -> dict:
    """The league's start and launch, and its latest loaded hour and day of the league
    (null before the first trades), from the (league, time) index."""
    rows = db.rows(
        con,
        """
        SELECT l.start_at, l.launched_at,
               (SELECT max(x.observed_at) FROM cross_market_hour x
                WHERE x.league_id = l.id) AS latest
        FROM league l WHERE l.name = ?
        """,
        [league],
    )
    if not rows:
        return {"start_at": None, "launched_at": None, "latest": None, "day_offset": None}
    start, launched, latest = rows[0]
    day = None
    if latest is not None:
        day = db.scalar(
            con,
            """
            SELECT max(day_offset) FROM cross_market_hour
            WHERE league_id = (SELECT id FROM league WHERE name = ?) AND observed_at = ?
            """,
            [league, latest],
        )
    return {"start_at": start, "launched_at": launched, "latest": latest, "day_offset": day}


def prices(con, league: str, latest: datetime, item_ids: list[str]) -> pl.DataFrame:
    """Per item and moment (`ago`: NOW, DAY_AGO, WEEK_AGO), its median over the 24
    published hours ending then: the Chaos price, the Divine price at the same hour's
    rate (as `item_history.league_days`) and the Divine market's own price."""
    schema = {
        "item_id": pl.String,
        "ago": pl.Int32,
        "chaos": pl.Float64,
        "divine": pl.Float64,
        "divine_market": pl.Float64,
    }
    if not item_ids:
        return pl.DataFrame(schema=schema)
    end = latest + timedelta(hours=1)  # the latest hour itself included
    starts = {ago: end - timedelta(hours=h + PRICE_HOURS) for ago, h in AGO_HOURS.items()}
    ends = {ago: end - timedelta(hours=h) for ago, h in AGO_HOURS.items()}
    marks = ", ".join("?" for _ in item_ids)
    out = db.frame(
        con,
        f"""
        SELECT item_id,
               CASE WHEN observed_at >= ? THEN {NOW}
                    WHEN observed_at >= ? THEN {DAY_AGO}
                    ELSE {WEEK_AGO} END AS ago,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY chaos_price) AS chaos,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY chaos_price / nullif(divine_rate, 0))
                   AS divine,
               percentile_cont(0.5) WITHIN GROUP (
                   ORDER BY CASE WHEN divine_price > 0 AND divine_volume > 0
                                 THEN divine_price END) AS divine_market
        FROM cross_market_hour
        WHERE league_id = (SELECT id FROM league WHERE name = ?)
          AND ((observed_at >= ? AND observed_at < ?) OR (observed_at >= ? AND observed_at < ?))
          AND chaos_price > 0 AND chaos_volume > 0 AND item_id IN ({marks})
        GROUP BY 1, 2
        """,
        [
            starts[NOW],
            starts[DAY_AGO],
            league,
            starts[DAY_AGO],
            ends[NOW],
            starts[WEEK_AGO],
            ends[WEEK_AGO],
            *item_ids,
        ],
    )
    return out.cast(schema) if out.height else pl.DataFrame(schema=schema)


def markets(con, league: str, latest: datetime, item_ids: list[str]) -> pl.DataFrame:
    """Per item and market (`chaos`, `divine`) over the latest RECENT_HOURS: units of
    the item traded, hours it traded in, and `sigma`, the standard deviation of its
    hourly close-to-close log changes (consecutive hours only: finding 7's sigma_h,
    informative only)."""
    schema = {
        "market": pl.String,
        "item_id": pl.String,
        "volume": pl.Float64,
        "hours": pl.Int32,
        "sigma": pl.Float64,
    }
    if not item_ids:
        return pl.DataFrame(schema=schema)
    end = latest + timedelta(hours=1)
    marks = ", ".join("?" for _ in item_ids)
    legs = []
    for market, price, volume in (
        ("chaos", "chaos_price", "chaos_volume"),
        ("divine", "divine_price", "divine_volume"),
    ):
        legs.append(
            f"""
            SELECT '{market}' AS market, item_id, sum(v) AS volume, count(*) AS hours,
                   stddev_samp(r) FILTER (WHERE gap = INTERVAL '1 hour') AS sigma
            FROM (
                SELECT item_id, v,
                       ln(p / lag(p) OVER (PARTITION BY item_id ORDER BY observed_at)) AS r,
                       observed_at - lag(observed_at) OVER (
                           PARTITION BY item_id ORDER BY observed_at) AS gap
                FROM (
                    SELECT item_id, observed_at, {price} AS p, {volume} AS v
                    FROM cross_market_hour
                    WHERE league_id = (SELECT id FROM league WHERE name = ?)
                      AND observed_at >= ? AND observed_at < ?
                      AND {price} > 0 AND {volume} > 0 AND item_id IN ({marks})
                ) h
            ) t
            GROUP BY item_id
            """
        )
    params = [league, end - timedelta(hours=RECENT_HOURS), end, *item_ids]
    out = db.frame(con, " UNION ALL ".join(legs), params * 2)
    return out.cast(schema) if out.height else pl.DataFrame(schema=schema)


def _days(con, league: str, item_ids: list[str], first: datetime, end: datetime) -> pl.DataFrame:
    """`item_history.league_days` over [first, end), as `analysis/mechanics.item_days`."""
    out = item_history.league_days(con, league, item_ids, hours=(first, end))
    if not out.height:
        return pl.DataFrame(schema=DAY_SCHEMA)
    return out.with_columns(league=pl.lit(league)).select(list(DAY_SCHEMA)).cast(DAY_SCHEMA)


def live_frames(con, league: str, state: dict, item_ids: list[str]) -> dict[str, pl.DataFrame]:
    """The live league's reductions the page rests on: its day-0 rows (`base`), its rows
    over the latest RECENT_HOURS (`recent`) and the 24-hour medians (`prices`)."""
    launched, end = state["launched_at"], state["latest"] + timedelta(hours=1)
    base = pl.DataFrame(schema=DAY_SCHEMA)
    if launched is not None:
        base = _days(con, league, item_ids, launched, launched + timedelta(days=1))
    return {
        "base": base.filter(pl.col("day") == 0),
        "recent": _days(con, league, item_ids, end - timedelta(hours=RECENT_HOURS), end),
        "prices": prices(con, league, state["latest"], item_ids),
    }


# --- Mechanics -----------------------------------------------------------------------


def _live_index(base: pl.DataFrame, px: pl.DataFrame, league: str, every) -> dict:
    """The live index per mechanic at NOW, DAY_AGO and WEEK_AGO: `analysis/mechanics.index`
    with each moment's 24-hour medians as a day of the league over the day-0 medians."""
    moments = px.select(
        league=pl.lit(league),
        item_id="item_id",
        day="ago",
        chaos=pl.lit(None, pl.Float64),
        divine="divine",
        chaos_volume=pl.lit(None, pl.Float64),
        hours=pl.lit(0, pl.Int32),
        absret=pl.lit(None, pl.Float64),
        day_hours=pl.lit(None, pl.Int32),
    ).cast(DAY_SCHEMA)
    ix = mx.index(pl.concat([base, moments]), every, "divine").filter(pl.col("day") < 0)
    return {(r["mechanic"], r["day"]): r["index"] for r in ix.iter_rows(named=True)}


def _past_liquidity(hist: pl.DataFrame, every, past: list[str]) -> pl.DataFrame:
    """Easy to sell from past leagues' days 1–3 (before the live league has 3 days):
    each league's percentile among mechanics, recency-weighted over leagues."""
    liq = mx.liquidity(hist, every, 1, 1 + mx.RECENT_DAYS)
    if liq.is_empty():
        return pl.DataFrame(schema={"mechanic": pl.String, "liquidity": pl.Float64})
    w = lp.recency_weights(past, mx.HALF_LIFE)
    per = pl.concat([mx.easy_to_sell(g) for _, g in liq.group_by("league")])
    return (
        per.with_columns(w=pl.col("league").replace_strict(w, default=0.0))
        .group_by("mechanic")
        .agg(liquidity=(pl.col("liquidity") * pl.col("w")).sum() / pl.col("w").sum())
    )


def _score(df: pl.DataFrame) -> pl.DataFrame:
    """`analysis/mechanics.score`'s factors and weights, with a factor that's null for
    every mechanic given no weight, so it drops out of the score rather than scaling
    every mechanic's down."""
    weights = {
        name: (mx.SCORE_WEIGHTS[name] if df[col].is_not_null().any() else 0.0)
        for name, (col, _) in mx.SCORE_FACTORS.items()
    }
    out = rank_score(df.rename({"mechanic": "item_id"}), mx.SCORE_FACTORS, weights)
    return out.rename({"item_id": "mechanic"}).select("mechanic", "score")


def _value(row: dict | None, key: str):
    v = None if row is None else row.get(key)
    return None if v is None or (isinstance(v, float) and not math.isfinite(v)) else v


def _ratio(a, b):
    return a / b - 1 if a is not None and b else None


def _mechanics(
    league: str,
    day_offset: float,
    current,
    every,
    shown: dict[str, list[str]],
    live: dict[str, pl.DataFrame],
    hist: pl.DataFrame,
    past: list[str],
    outlook: pl.DataFrame,
) -> list[dict]:
    """Each mechanic's trend against its usual path, Easy to sell and score, best first
    (finding 8)."""
    day = math.floor(day_offset)
    base, recent, px = live["base"], live["recent"], live["prices"]
    ix = _live_index(base, px, league, every)

    usual = {}
    if not hist.is_empty() and day < LAUNCH_DAYS:
        us = mx.usual(mx.index(hist, every, "divine"), past).filter(pl.col("day") == day)
        usual = {r["mechanic"]: r for r in us.iter_rows(named=True)}

    live_liq = pl.DataFrame()
    if not recent.is_empty():
        days = pl.concat([recent, base.with_columns(day=pl.lit(PRESENT_ONLY, pl.Int32))])
        live_liq = mx.liquidity(days, every, int(recent["day"].min()), int(recent["day"].max()) + 1)
    volume = {r["mechanic"]: r["basket_cv_h"] for r in live_liq.iter_rows(named=True)}
    if day_offset >= mx.RECENT_DAYS:
        ranked = mx.easy_to_sell(live_liq) if not live_liq.is_empty() else pl.DataFrame()
    else:
        ranked = _past_liquidity(hist, every, past) if not hist.is_empty() else pl.DataFrame()
    liquidity = {r["mechanic"]: r["liquidity"] for r in ranked.iter_rows(named=True)}

    window = mx.window_at(day)
    premium = {}
    if window and not outlook.is_empty():
        premium = {
            r["mechanic"]: r["premium"]
            for r in outlook.filter(pl.col("window") == window).iter_rows(named=True)
        }
    priced = set(px.filter(pl.col("ago") == NOW)["item_id"].to_list())

    rows = []
    for mid, (name, _) in current.items():
        if not shown[mid]:
            continue  # nothing of it in the core drop pool: nothing to show or sell
        now, u = ix.get((mid, NOW)), usual.get(mid)
        usual_now = _value(u, "usual")
        rows.append(
            {
                "id": mid,
                "name": name,
                "items": len(shown[mid]),
                "priced_items": sum(i in priced for i in shown[mid]),
                "index": now,
                "usual": usual_now,
                "usual_low": _value(u, "low"),
                "usual_high": _value(u, "high"),
                "change_24h": _ratio(now, ix.get((mid, DAY_AGO))),
                "change_7d": _ratio(now, ix.get((mid, WEEK_AGO))),
                "chaos_volume_h": _value(volume, mid),
                "liquidity": _value(liquidity, mid),
                "vs_usual": now / usual_now if now is not None and usual_now else None,
                "premium": _value(premium, mid),
            }
        )
    if not rows:
        return []
    df = pl.DataFrame(
        [{"mechanic": r["id"], **{c: r[c] for c in SCORED}} for r in rows],
        schema={"mechanic": pl.String, **dict.fromkeys(SCORED, pl.Float64)},
    )
    scores = dict(_score(df).iter_rows())
    for r in rows:
        r["score"] = scores.get(r["id"])
        del r["vs_usual"], r["premium"]
    return sorted(rows, key=lambda r: (r["score"] is None, -(r["score"] or 0.0), r["id"]))


def _outlook(current, outlook: pl.DataFrame) -> list[dict]:
    if outlook.is_empty():
        return []
    out = []
    for mid, (name, _) in current.items():
        mine = outlook.filter(pl.col("mechanic") == mid)
        if mine.is_empty():
            continue
        windows = {r["window"]: r for r in mine.iter_rows(named=True)}
        out.append(
            {
                "id": mid,
                "name": name,
                "leagues": int(mine["leagues"].max()),
                "windows": {
                    w: (
                        {"premium": windows[w]["premium"], "worst": windows[w]["worst"]}
                        if w in windows
                        else None
                    )
                    for w in mx.WINDOWS
                },
            }
        )
    return out


# --- Items (the sell helper) ---------------------------------------------------------


def item_names(con, item_ids: list[str]) -> dict[str, str]:
    if not item_ids:
        return {}
    marks = ", ".join("?" for _ in item_ids)
    return dict(
        db.rows(con, f"SELECT id, canonical_name FROM item WHERE id IN ({marks})", item_ids)
    )


def _items(
    con,
    league: str,
    latest,
    current,
    shown: dict[str, list[str]],
    names: dict[str, str],
    live: dict[str, pl.DataFrame],
) -> list[dict]:
    """Shown basket outputs with a price in the latest 24 hours, each market's recent
    trading: price (median, latest 24 hours), units an hour, typical hourly swing and
    share of hours traded (latest 3 days). `divine` is null without Divine-market trades."""
    now = live["prices"].filter(pl.col("ago") == NOW, pl.col("chaos").is_not_null())
    wanted = sorted({i for ids in shown.values() for i in ids} & set(now["item_id"].to_list()))
    if not wanted:
        return []
    mk = markets(con, league, latest, wanted)
    # Hours with any trade in the span, as `analysis/mechanics.liquidity` counts them.
    span = live["recent"].group_by("day").agg(pl.col("day_hours").max())["day_hours"].sum()
    rows = pl.DataFrame(
        {"item_id": wanted, "name": [names[i] for i in wanted]},
        schema={"item_id": pl.String, "name": pl.String},
    )
    price = {r["item_id"]: r for r in now.iter_rows(named=True)}
    stats = {(r["market"], r["item_id"]): r for r in mk.iter_rows(named=True)}
    member = {i: [m for m in current if i in shown[m]] for i in wanted}

    def market(name: str, item_id: str, p) -> dict | None:
        s = stats.get((name, item_id))
        if s is None:
            return None
        return {
            "price": p,
            "volume_h": s["volume"] / span if span else None,
            "sigma_h": s["sigma"],
            "hours_traded": s["hours"] / span if span else None,
        }

    out = []
    for r in rows.sort("name", "item_id").iter_rows(named=True):  # text sorts in polars
        i, p = r["item_id"], price[r["item_id"]]
        out.append(
            {
                "item_id": i,
                "name": r["name"],
                "mechanics": member[i],
                "chaos": market("chaos", i, _value(p, "chaos")),
                "divine": market("divine", i, _value(p, "divine_market")),
            }
        )
    return out


# --- The page ------------------------------------------------------------------------


def farming(con, league: str, settings: Settings | None = None) -> dict:
    """The Farming page's document for one league (docs/farming.md, the response
    contract). Before the league's first trades only the outlook (and the first phase's
    hour profiles) are there."""
    settings = settings or get_settings()
    current, every = baskets(con, settings)
    state = league_state(con, league)
    latest, day_offset = state["latest"], state["day_offset"]

    captured = [lg for lg in item_history.captured_leagues(con) if lg != league]
    hist = item_history.history(con, captured) if captured else pl.DataFrame()
    if not hist.is_empty() and state["start_at"] is not None:
        hist = hist.filter(pl.col("league_start") < state["start_at"])  # past leagues only
    kept = set(hist["league"]) if not hist.is_empty() else set()
    past = [lg for lg in captured if lg in kept]  # newest first
    outlook = pl.DataFrame()
    if past:
        outlook = mx.outlook(mx.premiums(hist, every), past)

    if latest is None:
        phase = "pre_launch"
    else:
        phase = "launch" if day_offset < LAUNCH_DAYS else "later"

    mechanics, items = [], []
    if latest is not None:
        names = item_names(con, _item_ids(current))
        pool = load_pool(con, settings)
        shown = {  # what the page shows: the core drop pool's (CLAUDE.md, scope rules)
            mid: [
                i for i in ids if i in names and basket_config.in_pool(pool, names[i]) is not False
            ]
            for mid, (_, ids) in current.items()
        }
        live = live_frames(con, league, state, _item_ids(every))
        mechanics = _mechanics(league, day_offset, current, every, shown, live, hist, past, outlook)
        items = _items(con, league, latest, current, shown, names, live)

    doc = report(con)
    return {
        "league": league,
        "latest_hour": latest.replace(tzinfo=UTC) if latest is not None else None,
        "day_offset": day_offset,
        "phase": phase,
        "mechanics": mechanics,
        "outlook": _outlook(current, outlook),
        "items": items,
        "hours": _hours(doc, day_offset),
        "impact": doc.get("impact") if doc else None,
    }
