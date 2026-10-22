"""Load hourly currency-exchange markets into item / price_observation / tracked_item.

For each hour and item X, every market pairing X with Chaos or Divine contributes:
  volume       = units of X traded
  chaos_volume = Chaos traded, or Divine traded x that hour's Divine rate
  chaos_value  = sum(chaos_volume) / sum(volume)   (volume-weighted price)
  chaos_low/high = the market's lowest/highest traded ratio, in chaos
The Divine rate is the Chaos/Divine market's volume-weighted price, carried forward
through hours with no Divine trades. Hours with no trades for X have no row.

Like the dump loader, each league loads in one transaction and is skipped when its
inputs are unchanged.
"""

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

import duckdb

from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest.files import read_json
from exiledbroker.ingest.item_names import BaseItem
from exiledbroker.normalize.mappings import refresh_mappings
from exiledbroker.normalize.tracked import (
    CHAOS_METADATA,
    DIVINE_METADATA,
    GROUPS,
    currency_item_id,
)
from exiledbroker.storage import db

SOURCE = "ggg-exchange-hourly"
LOADER_VERSION = 2
CATEGORY_BY_CLASS = {"StackableCurrency": "currency", "MapFragment": "fragment"}


@dataclass
class LoadResult:
    league_id: str
    skipped: bool
    items: int = 0
    rows: int = 0


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


def _stage_prices(con: duckdb.DuckDBPyConnection, parquet: str, lid: str) -> None:
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE stage_price AS
        WITH m AS (SELECT * FROM read_parquet('{parquet}')),
        -- Each market as two legs: X priced in the other currency (the reference).
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
        traded AS (SELECT * FROM legs WHERE x_vol > 0 AND ref_vol > 0),
        hours AS (SELECT DISTINCT hour FROM m),
        divine AS (
            SELECT h.hour,
                   last_value(d.rate IGNORE NULLS) OVER (ORDER BY h.hour) AS rate
            FROM hours h
            LEFT JOIN (
                SELECT hour, ref_vol / x_vol AS rate FROM traded
                WHERE x = '{DIVINE_METADATA}' AND ref = '{CHAOS_METADATA}'
            ) d ON d.hour = h.hour
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


def fingerprint(settings: Settings, league_name: str) -> str:
    meta = read_json(cx.sidecar_path(settings, league_name))
    if meta is None:
        raise FileNotFoundError(f"{league_name} has no extracted exchange data")
    return json.dumps({"loader_version": LOADER_VERSION, "extract": meta}, sort_keys=True)


def load_league(
    con: duckdb.DuckDBPyConnection,
    settings: Settings,
    window: cx.Window,
    names: dict[str, BaseItem],
    force: bool = False,
) -> LoadResult:
    lid = cx.league_id(cx.GAME, window.league_name)
    fp = fingerprint(settings, window.league_name)
    q = "SELECT fingerprint FROM ingest_load WHERE league_id = ? AND source = ?"
    previous = db.rows(con, q, [lid, SOURCE])
    if previous and previous[0][0] == fp and not force:
        return LoadResult(lid, skipped=True)

    parquet = cx.processed_path(settings, window.league_name).resolve().as_posix()
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(
            "UPDATE league SET launched_at = ? WHERE id = ?",
            [window.launched_at.replace(tzinfo=None), lid],
        )
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
        con.execute(
            """
            INSERT INTO item (id, game, canonical_name, category, metadata_id)
            SELECT DISTINCT n.item_id, 'poe1', n.name, n.category, n.metadata_id
            FROM stage_names n WHERE n.item_id IN (SELECT item_id FROM stage_price)
            ON CONFLICT (id) DO UPDATE SET metadata_id = excluded.metadata_id
            """
        )
        con.execute(
            "DELETE FROM price_observation WHERE league_id = ? AND source = ?", [lid, SOURCE]
        )
        con.execute(
            """
            INSERT INTO price_observation (item_id, league_id, observed_at, day_offset,
                chaos_value, divine_value, source, volume, chaos_volume, chaos_low, chaos_high)
            SELECT * FROM stage_price
            """
        )
        refresh_mappings(con, settings)
        items = db.scalar(con, "SELECT count(DISTINCT item_id) FROM stage_price")
        rows = db.scalar(con, "SELECT count(*) FROM stage_price")
        con.execute(
            """
            INSERT INTO ingest_load (league_id, source, fingerprint, item_count, row_count,
                                     loaded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (league_id, source) DO UPDATE SET fingerprint = excluded.fingerprint,
                item_count = excluded.item_count, row_count = excluded.row_count,
                loaded_at = excluded.loaded_at
            """,
            [lid, SOURCE, fp, items, rows, datetime.now(UTC).replace(tzinfo=None)],
        )
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.execute("DROP TABLE IF EXISTS stage_names")
        con.execute("DROP TABLE IF EXISTS stage_price")
    return LoadResult(lid, skipped=False, items=items, rows=rows)
