"""Load hourly currency-exchange markets into item / price_observation / tracked_item.

For each hour and item X, every market pairing X with Chaos or Divine contributes:
  volume       = units of X traded
  chaos_volume = Chaos traded, or Divine traded x that hour's Divine rate
  chaos_value  = sum(chaos_volume) / sum(volume)   (volume-weighted price)
  chaos_low/high = the market's lowest/highest traded ratio, in chaos
The Divine rate is the Chaos/Divine market's volume-weighted price, carried forward
through hours with no Divine trades. Hours with no trades for X have no row.

Loads are incremental. `exchange_hour_loaded` records which hours a league has, and
each load only inserts hours that are new and deletes hours that left the window,
in one transaction. Nothing else is rewritten, so an hourly live update touches
one hour's rows. The Divine rate for new hours is carried forward from the rows
already in the database. A full rebuild happens only when LOADER_VERSION changes
or with `force`.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

import duckdb

from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest.item_names import BaseItem
from exiledbroker.normalize.mappings import refresh_mappings
from exiledbroker.normalize.tracked import (
    CHAOS_METADATA,
    DIVINE,
    DIVINE_METADATA,
    GROUPS,
    currency_item_id,
)
from exiledbroker.storage import db

SOURCE = "ggg-exchange-hourly"
LOADER_VERSION = 4
CATEGORY_BY_CLASS = {"StackableCurrency": "currency", "MapFragment": "fragment"}


@dataclass
class LoadResult:
    league_id: str
    skipped: bool  # nothing to add or remove
    items: int = 0  # items with rows for the league, after the load
    rows: int = 0  # price rows for the league, after the load
    hours_added: int = 0
    hours_removed: int = 0
    rows_added: int = 0
    rebuilt: bool = False


def _category(name: str, item_class: str) -> str:
    for group in GROUPS:
        if group.id in ("essence", "scarab") and group.rule(name):
            return group.id
    return CATEGORY_BY_CLASS.get(item_class, item_class.lower() or "unknown")


def resolve_names(metadata_ids: list[str], names: dict[str, BaseItem]) -> list[tuple]:
    """(metadata_id, item_id, name, category) for each id.

    RePoE gives some different items the same name (an old and a new id, or a
    mislabelled variant), so an ambiguous name never merges items: each id becomes
    its own item, labelled with its metadata name.
    """
    counts = Counter(b.name for b in names.values())
    rows = []
    for mid in metadata_ids:
        segment = mid.rsplit("/", 1)[-1]
        base = names.get(mid) or BaseItem(mid, segment, "")
        name = base.name
        if counts[name] > 1:
            name = f"{name} ({segment})"
        rows.append((mid, currency_item_id(name), name, _category(base.name, base.item_class)))
    return rows


def _stage_names(con: duckdb.DuckDBPyConnection, metadata_ids: list[str], names) -> None:
    con.execute(
        "CREATE OR REPLACE TEMP TABLE stage_names "
        "(metadata_id VARCHAR, item_id VARCHAR, name VARCHAR, category VARCHAR)"
    )
    rows = resolve_names(metadata_ids, names)
    if rows:
        con.executemany("INSERT INTO stage_names VALUES (?, ?, ?, ?)", rows)


def _legs_sql(parquet: str) -> str:
    """CTEs `m` (the league's markets), `legs` and `traded`: each market as two legs,
    X priced in the other currency (the reference), keeping legs with trades."""
    return f"""
        m AS (SELECT * FROM read_parquet('{parquet}')),
        legs AS (
            SELECT hour, b AS x, a AS ref, volume_traded_b AS x_vol, volume_traded_a AS ref_vol,
                   lowest_ratio_a AS lo_ref, lowest_ratio_b AS lo_x,
                   highest_ratio_a AS hi_ref, highest_ratio_b AS hi_x
            FROM m WHERE a IN ('{CHAOS_METADATA}', '{DIVINE_METADATA}')
            UNION ALL
            SELECT hour, a, b, volume_traded_a, volume_traded_b,
                   lowest_ratio_b, lowest_ratio_a, highest_ratio_b, highest_ratio_a
            FROM m WHERE b IN ('{CHAOS_METADATA}', '{DIVINE_METADATA}')
        ),
        traded AS (SELECT * FROM legs WHERE x_vol > 0 AND ref_vol > 0)"""


def _stage_cross(con: duckdb.DuckDBPyConnection, parquet: str, lid: str) -> None:
    """Item-hours traded against both Chaos and Divine, with that hour's Divine rate.

    Unlike the hourly prices, the rate isn't carried forward: a loop through both
    markets needs the Divine/Chaos trade to happen in the same hour."""
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE stage_cross AS
        WITH {_legs_sql(parquet)},
        p AS (
            SELECT hour, x, ref, x_vol, ref_vol / x_vol AS price,
                   least(lo_ref / nullif(lo_x, 0), hi_ref / nullif(hi_x, 0)) AS lo,
                   greatest(lo_ref / nullif(lo_x, 0), hi_ref / nullif(hi_x, 0)) AS hi
            FROM traded
        ),
        c AS (SELECT * FROM p WHERE ref = '{CHAOS_METADATA}' AND x <> '{DIVINE_METADATA}'),
        d AS (SELECT * FROM p WHERE ref = '{DIVINE_METADATA}' AND x <> '{CHAOS_METADATA}'),
        r AS (SELECT * FROM p WHERE x = '{DIVINE_METADATA}' AND ref = '{CHAOS_METADATA}')
        SELECT '{lid}' AS league_id, n.item_id, c.hour AS observed_at,
               date_diff('second', l.launched_at, c.hour) / 86400.0 AS day_offset,
               c.price, c.x_vol, c.lo, c.hi,
               d.price, d.x_vol, d.lo, d.hi,
               r.price, r.lo, r.hi
        FROM c
        JOIN d ON d.hour = c.hour AND d.x = c.x
        JOIN r ON r.hour = c.hour
        JOIN stage_names n ON n.metadata_id = c.x
        JOIN league l ON l.id = '{lid}'
        """
    )


def _stage_prices(con: duckdb.DuckDBPyConnection, parquet: str, lid: str) -> None:
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE stage_price AS
        WITH {_legs_sql(parquet)},
        hours AS (SELECT DISTINCT hour FROM m),
        -- Divine rates known so far: this batch's, plus those already loaded (the
        -- Divine's own hourly price) from hours outside the batch.
        known_rates AS (
            SELECT hour, ref_vol / x_vol AS rate FROM traded
            WHERE x = '{DIVINE_METADATA}' AND ref = '{CHAOS_METADATA}'
            UNION ALL
            SELECT observed_at, chaos_value FROM price_observation
            WHERE league_id = '{lid}' AND source = '{SOURCE}'
              AND item_id = '{currency_item_id(DIVINE)}'
              AND observed_at NOT IN (SELECT hour FROM hours)
        ),
        -- Each hour uses the latest rate at or before it (carried forward).
        divine AS (
            SELECT h.hour, k.rate FROM hours h ASOF LEFT JOIN known_rates k ON h.hour >= k.hour
        ),
        priced AS (
            SELECT t.hour, t.x, t.x_vol,
                   CASE WHEN t.ref = '{CHAOS_METADATA}' THEN 1 ELSE dv.rate END AS to_chaos,
                   t.ref_vol, t.lo_ref / nullif(t.lo_x, 0) AS r1,
                   t.hi_ref / nullif(t.hi_x, 0) AS r2
            FROM traded t JOIN divine dv ON dv.hour = t.hour
        ),
        agg AS (
            SELECT hour, x,
                   sum(x_vol) AS volume,
                   sum(ref_vol * to_chaos) AS chaos_volume,
                   min(least(r1, r2) * to_chaos) AS chaos_low,
                   max(greatest(r1, r2) * to_chaos) AS chaos_high
            FROM priced WHERE to_chaos IS NOT NULL
            GROUP BY hour, x
        )
        SELECT n.item_id, '{lid}' AS league_id, a.hour AS observed_at,
               date_diff('second', l.launched_at, a.hour) / 86400.0 AS day_offset,
               CASE WHEN a.x = '{CHAOS_METADATA}' THEN 1.0
                    ELSE a.chaos_volume / a.volume END AS chaos_value,
               CASE WHEN a.x = '{CHAOS_METADATA}' THEN 1.0 / dv.rate
                    ELSE a.chaos_volume / a.volume / dv.rate END AS divine_value,
               '{SOURCE}' AS source,
               a.volume, a.chaos_volume,
               CASE WHEN a.x = '{CHAOS_METADATA}' THEN 1.0 ELSE a.chaos_low END AS chaos_low,
               CASE WHEN a.x = '{CHAOS_METADATA}' THEN 1.0 ELSE a.chaos_high END AS chaos_high
        FROM agg a
        JOIN stage_names n ON n.metadata_id = a.x
        JOIN divine dv ON dv.hour = a.hour
        JOIN league l ON l.id = '{lid}'
        """
    )


def _hours_table(con: duckdb.DuckDBPyConnection, name: str, hours: list[int]) -> None:
    con.execute(f"CREATE OR REPLACE TEMP TABLE {name} (hour TIMESTAMP)")
    if hours:
        con.executemany(
            f"INSERT INTO {name} VALUES (?)",
            [(cx.from_ts(h).replace(tzinfo=None),) for h in hours],
        )


def _loaded_hours(con: duckdb.DuckDBPyConnection, lid: str) -> set[int]:
    rows = db.rows(con, "SELECT hour FROM exchange_hour_loaded WHERE league_id = ?", [lid])
    return {cx.to_ts(r[0].replace(tzinfo=UTC)) for r in rows}


def load_league(
    con: duckdb.DuckDBPyConnection,
    settings: Settings,
    window: cx.Window,
    names: dict[str, BaseItem],
    force: bool = False,
) -> LoadResult:
    """Bring a league's hourly rows in line with `window`, touching only what changed:
    hours with pages on disk that aren't loaded yet are added, loaded hours outside
    the window are removed."""
    lid = cx.league_id(cx.GAME, window.league_name)
    version = f"loader_version={LOADER_VERSION}"
    q = "SELECT fingerprint FROM ingest_load WHERE league_id = ? AND source = ?"
    previous = db.rows(con, q, [lid, SOURCE])
    rebuild = force or not previous or previous[0][0] != version

    wanted = set(window.hours)
    loaded = set() if rebuild else _loaded_hours(con, lid)
    add = sorted(h for h in wanted - loaded if cx.page_path(settings, h).exists())
    remove = sorted(loaded - wanted)
    if not (add or remove or rebuild):
        return LoadResult(lid, skipped=True)

    batch = settings.data_dir / "tmp" / f"{lid}-load.parquet"
    markets = cx.write_markets(settings, window.league_name, add, batch) if add else 0
    parquet = batch.resolve().as_posix()
    rows_added = 0
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(
            "UPDATE league SET launched_at = ? WHERE id = ?",
            [window.launched_at.replace(tzinfo=None), lid],
        )
        if rebuild:
            for table in ("price_observation", "cross_market_hour", "exchange_hour_loaded"):
                extra = " AND source = ?" if table == "price_observation" else ""
                params = [lid, SOURCE] if extra else [lid]
                con.execute(f"DELETE FROM {table} WHERE league_id = ?{extra}", params)
        # Only the hours leaving the window, and (to make a retry safe) the new ones.
        _hours_table(con, "touched_hours", remove + add)
        con.execute(
            "DELETE FROM price_observation WHERE league_id = ? AND source = ? "
            "AND observed_at IN (SELECT hour FROM touched_hours)",
            [lid, SOURCE],
        )
        con.execute(
            "DELETE FROM cross_market_hour WHERE league_id = ? "
            "AND observed_at IN (SELECT hour FROM touched_hours)",
            [lid],
        )
        con.execute(
            "DELETE FROM exchange_hour_loaded WHERE league_id = ? "
            "AND hour IN (SELECT hour FROM touched_hours)",
            [lid],
        )
        if markets:
            metadata_ids = [
                r[0]
                for r in db.rows(
                    con,
                    f"SELECT DISTINCT a FROM read_parquet('{parquet}') "
                    f"UNION SELECT DISTINCT b FROM read_parquet('{parquet}')",
                )
            ]
            _stage_names(con, metadata_ids, names)
            _stage_prices(con, parquet, lid)
            _stage_cross(con, parquet, lid)
            con.execute(
                """
                INSERT INTO item (id, game, canonical_name, category, metadata_id)
                SELECT DISTINCT n.item_id, 'poe1', n.name, n.category, n.metadata_id
                FROM stage_names n WHERE n.item_id IN (SELECT item_id FROM stage_price)
                ON CONFLICT (id) DO UPDATE SET metadata_id = excluded.metadata_id
                """
            )
            con.execute(
                """
                INSERT INTO price_observation (item_id, league_id, observed_at, day_offset,
                    chaos_value, divine_value, source, volume, chaos_volume, chaos_low,
                    chaos_high)
                SELECT * FROM stage_price
                """
            )
            con.execute("INSERT INTO cross_market_hour SELECT * FROM stage_cross")
            rows_added = db.scalar(con, "SELECT count(*) FROM stage_price")
        _hours_table(con, "added_hours", add)
        con.execute("INSERT INTO exchange_hour_loaded SELECT ?, hour FROM added_hours", [lid])
        refresh_mappings(con, settings)
        items, rows = db.rows(
            con,
            "SELECT count(DISTINCT item_id), count(*) FROM price_observation "
            "WHERE league_id = ? AND source = ?",
            [lid, SOURCE],
        )[0]
        con.execute(
            """
            INSERT INTO ingest_load (league_id, source, fingerprint, item_count, row_count,
                                     loaded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (league_id, source) DO UPDATE SET fingerprint = excluded.fingerprint,
                item_count = excluded.item_count, row_count = excluded.row_count,
                loaded_at = excluded.loaded_at
            """,
            [lid, SOURCE, version, items, rows, datetime.now(UTC).replace(tzinfo=None)],
        )
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        for t in ("stage_names", "stage_price", "stage_cross", "touched_hours", "added_hours"):
            con.execute(f"DROP TABLE IF EXISTS {t}")
        batch.unlink(missing_ok=True)
    return LoadResult(
        lid,
        skipped=False,
        items=items,
        rows=rows,
        hours_added=len(add),
        hours_removed=len(remove),
        rows_added=rows_added,
        rebuilt=rebuild,
    )
