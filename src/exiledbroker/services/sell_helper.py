"""The sell helper's inputs, kept from the retired Farming page for Price check
(docs/price-check.md, workstreams C and E): the best-hour sentence and the stack seller.

- **Hour of day and stack impact** (findings 6 and 7) are constants built locally from
  past leagues' hours (`eb farming build`, which needs numpy: the site image has none)
  and stored as one JSON document in `farming_report`, like the Backtest report.
  `constants` returns the league's phase's hour profiles and the impact note.
- **An item's recent trading per market** (`markets`): units traded, hours traded and
  the typical hourly swing over the latest 3 days, reduced in SQL.

SQL here must stay Postgres-compatible: the hosted site's Postgres serves the same queries.
"""

import json
from datetime import UTC, datetime, timedelta

import polars as pl

from exiledbroker.storage import db

REPORT = "farming_report"
RECENT_HOURS = 3 * 24  # volumes, swings and hours traded: the latest 3 days
# Finding 7: a stack is shown as hours of the market's trading, not as a price drop.
IMPACT = {
    "y": None,
    "bands": [0.25, 1.0],
    "note": (
        "Hourly prices swing more than a stack moves them, so this shows how much of the "
        "market's trading your stack is, not a price drop."
    ),
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


def hours(doc: dict | None, day_offset: float | None) -> dict | None:
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


def constants(con, day_offset: float | None) -> dict:
    """The stored constants for a day of the league: `hours` (that phase's profiles)
    and `impact`, both null until `eb farming build` has been run and seeded."""
    doc = report(con)
    return {"hours": hours(doc, day_offset), "impact": doc.get("impact") if doc else None}


# --- An item's recent trading (the stack seller) -------------------------------------


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
