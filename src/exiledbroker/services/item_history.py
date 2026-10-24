"""The Farming page's reduced history (docs/farming.md, workstream E): each finished
league's launch fortnight as one row per basket item and day of the league, so the
server ranks mechanics against past leagues without keeping their hours.

A row holds what finding 8 (`analysis/mechanics.item_days`) ranks on: the median hourly
Chaos price, the median Divine price at the same hour's rate, the Chaos traded, the
hours traded, the median hourly move and how many hours of that day had any trade.
Prices come from `cross_market_hour`, which has every item that traded against Chaos,
so the exchange loader's keep rule doesn't need widening for the Farming page.

Basket items are config/mechanics.toml's outputs, groups and legacy outputs. A basket
edit changes what's captured only for leagues captured after it: recapture the past
leagues locally (`eb farming history`) and seed them (`eb site seed`).
"""

import polars as pl

from exiledbroker.config import Settings
from exiledbroker.normalize import mechanics
from exiledbroker.services import launch_picks
from exiledbroker.storage import db

HISTORY = "item_day_history"
LAUNCH_DAYS = 14  # days 0–13: the launch fortnight
COLUMNS = (
    "league",
    "league_start",
    "item_id",
    "day",
    "chaos",
    "divine",
    "chaos_volume",
    "hours",
    "absret",
    "day_hours",
)


def basket_items(con, settings: Settings) -> list[str]:
    """Every basket's item ids, legacy outputs included (past leagues traded them)."""
    ids = {
        item_id
        for m in mechanics.load_mechanics(settings)
        for item_id in mechanics.output_ids(con, m, legacy=True)
    }
    return sorted(ids)


def league_days(con, league: str, item_ids: list[str]) -> pl.DataFrame:
    """One row per item and day of the launch fortnight (0 = the first 24 hours), from
    the league's hours in `cross_market_hour`. Plain SQL, so it runs on Postgres too."""
    if not item_ids:
        return pl.DataFrame()
    marks = ", ".join("?" for _ in item_ids)
    return db.frame(
        con,
        f"""
        WITH h AS (
            SELECT item_id, observed_at, CAST(floor(day_offset) AS INTEGER) AS day,
                   chaos_price AS p, chaos_price * chaos_volume AS cv,
                   chaos_price / nullif(divine_rate, 0) AS pd
            FROM cross_market_hour
            WHERE league_id = (SELECT id FROM league WHERE name = ?)
              AND day_offset >= 0 AND day_offset < ?
              AND chaos_price > 0 AND chaos_volume > 0 AND item_id IN ({marks})
        ),
        r AS (
            SELECT h.*,
                   abs(ln(p / lag(p) OVER (PARTITION BY item_id ORDER BY observed_at)))
                       AS absret
            FROM h
        ),
        dh AS (
            SELECT CAST(floor(day_offset) AS INTEGER) AS day,
                   count(DISTINCT observed_at) AS day_hours
            FROM cross_market_hour
            WHERE league_id = (SELECT id FROM league WHERE name = ?)
              AND day_offset >= 0 AND day_offset < ?
            GROUP BY 1
        )
        SELECT r.item_id, r.day,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY r.p) AS chaos,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY r.pd) AS divine,
               sum(r.cv) AS chaos_volume, count(*) AS hours,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY r.absret) AS absret,
               max(dh.day_hours) AS day_hours
        FROM r JOIN dh ON dh.day = r.day
        GROUP BY r.item_id, r.day
        """,
        [league, LAUNCH_DAYS, *item_ids, league, LAUNCH_DAYS],
    )


def capture(con, league: str, item_ids: list[str]) -> int:
    """Reduce a finished league's fortnight into item_day_history, replacing what was
    captured for it before. The aggregate runs on the site's database itself
    (`db.pushdown`), so a hosted capture doesn't copy the league's hours out. Returns
    the rows written."""
    site = db.pushdown(con)
    df = league_days(site, league, item_ids)
    start = db.scalar(site, "SELECT start_at FROM league WHERE name = ?", [league])
    rows = [
        (league, start, r["item_id"], r["day"], r["chaos"], r["divine"], r["chaos_volume"])
        + (r["hours"], r["absret"], r["day_hours"])
        for r in (df.sort("item_id", "day").iter_rows(named=True) if df.height else [])
    ]
    db.execute(site, f"DELETE FROM {HISTORY} WHERE league = ?", [league])
    marks = ", ".join("%s" if db.is_postgres(con) else "?" for _ in COLUMNS)
    sql = f"INSERT INTO {HISTORY} ({', '.join(COLUMNS)}) VALUES ({marks})"
    if db.is_postgres(con):
        with con.cursor() as cur:
            cur.executemany(sql, rows)
    elif rows:
        con.executemany(sql, rows)
    return len(rows)


def captured_leagues(con) -> list[str]:
    """Leagues in item_day_history, newest first."""
    q = f"SELECT league, max(league_start) AS s FROM {HISTORY} GROUP BY league ORDER BY s DESC"
    return [r[0] for r in db.rows(con, q)]


def refresh(con, settings: Settings, live: str | None = None) -> list[str]:
    """Capture every league with a complete fortnight that isn't captured yet (the live
    league only once its fortnight is over), as `launch_picks.refresh` does for the
    Launch history. The checks run on the site's database (`db.pushdown`) and cost a
    few small queries a pass; a capture happens about once a league. Returns the
    leagues captured."""
    site = db.pushdown(con)
    captured = set(captured_leagues(site))
    todo = [
        league
        for league in launch_picks.complete_leagues(site)
        if league not in captured
        and not (league == live and not launch_picks._fortnight_over(site, league))
    ]
    if not todo:
        return []
    items = basket_items(site, settings)
    for league in todo:
        capture(con, league, items)
    return todo


def history(con, leagues: list[str] | None = None) -> pl.DataFrame:
    """The captured rows (all leagues, or the given ones), for the Farming services."""
    if leagues == []:
        return pl.DataFrame()
    where, params = "", []
    if leagues:
        where = f"WHERE league IN ({', '.join('?' for _ in leagues)})"
        params = list(leagues)
    return db.frame(con, f"SELECT * FROM {HISTORY} {where} ORDER BY league, item_id, day", params)
