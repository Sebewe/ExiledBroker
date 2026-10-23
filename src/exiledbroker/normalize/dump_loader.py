"""Load poe.ninja dump Parquet into the general tables (item, price_observation).

Everything is done in SQL over the Parquet files, inside one transaction per league:
items are upserted, the league's previous rows from this source are replaced, and
an ingest_load row records what was loaded. Interrupting rolls the whole league
back; re-running with unchanged inputs is skipped.

Only softcore rows, and only currency and uniques, are loaded. The SQL keeps to what DuckDB and Postgres share so
the same row shapes can be copied to the site's Postgres.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import duckdb

from exiledbroker.config import Settings
from exiledbroker.ingest.files import read_json
from exiledbroker.ingest.poe_ninja_dumps import GAME, DumpInfo, parquet_path
from exiledbroker.normalize.mappings import refresh_mappings
from exiledbroker.storage import db

SOURCE = "poe.ninja-dump"
# Bump when the row mapping changes so loaded leagues are rebuilt.
LOADER_VERSION = 3

SLUG = "trim(regexp_replace(lower({col}), '[^a-z0-9]+', '-', 'g'), '-')"
CONFIDENCE_RANK = "CASE {col} WHEN 'High' THEN 3 WHEN 'Medium' THEN 2 WHEN 'Low' THEN 1 END"
# '1-4 links' is stored as 4, meaning "four or fewer".
LINKS = "CASE links WHEN '6 links' THEN 6 WHEN '5 links' THEN 5 WHEN '1-4 links' THEN 4 END"
# For now we keep currency and uniques only. Item-file types that are really
# currency are keyed by name, like the currency file and the hourly exchange.
CURRENCY_LIKE_TYPES = (
    "DivinationCard",
    "Scarab",
    "Essence",
    "Fossil",
    "Resonator",
    "Oil",
    "DeliriumOrb",
    "Omen",
    "Tattoo",
)
CURRENCY_LIKE = "(" + ", ".join(f"'{t}'" for t in CURRENCY_LIKE_TYPES) + ")"


@dataclass
class LoadResult:
    league_id: str
    skipped: bool
    items: int = 0
    rows: int = 0


def fingerprint(settings: Settings, dump: DumpInfo) -> str:
    parts = {"loader_version": LOADER_VERSION}
    for kind in ("items", "currency"):
        path = parquet_path(settings, dump, kind)
        meta = read_json(path.with_name(path.name + ".meta.json"))
        if not path.exists() or meta is None:
            raise FileNotFoundError(f"{path} is missing; run `eb dumps sync` first")
        parts[kind] = meta
    return json.dumps(parts, sort_keys=True)


def _stage(con: duckdb.DuckDBPyConnection, settings: Settings, dump: DumpInfo) -> None:
    """Build temp tables of this league's items and prices from its Parquet files."""
    items_pq = parquet_path(settings, dump, "items").resolve().as_posix()
    currency_pq = parquet_path(settings, dump, "currency").resolve().as_posix()

    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE stage_item_rows AS
        SELECT *,
               CASE WHEN type IN {CURRENCY_LIKE} THEN 'currency:' || {SLUG.format(col="name")}
                    ELSE 'ninja:' || ninja_id END AS item_id
        FROM read_parquet('{items_pq}')
        -- Nameless rows (e.g. 15 Sanctum relics in the Ancestor dump) can't be identified.
        WHERE NOT hardcore AND chaos_value > 0 AND name IS NOT NULL
          AND (type LIKE 'Unique%' OR type IN {CURRENCY_LIKE})
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE stage_currency AS
        WITH c AS (SELECT * FROM read_parquet('{currency_pq}') WHERE NOT hardcore AND value > 0
                   AND get IS NOT NULL AND pay IS NOT NULL),
        ask AS (
            SELECT get AS name, date, value AS chaos_ask, confidence AS ask_conf
            FROM c WHERE pay = 'Chaos Orb' AND get <> 'Chaos Orb'
        ),
        bid AS (
            SELECT pay AS name, date, 1 / value AS chaos_bid, confidence AS bid_conf
            FROM c WHERE get = 'Chaos Orb' AND pay <> 'Chaos Orb'
        )
        SELECT coalesce(ask.name, bid.name) AS name, coalesce(ask.date, bid.date) AS date,
               chaos_ask, chaos_bid,
               CASE WHEN chaos_ask IS NOT NULL AND chaos_bid IS NOT NULL
                    THEN (chaos_ask + chaos_bid) / 2 ELSE coalesce(chaos_ask, chaos_bid)
               END AS chaos_value,
               -- The less confident side wins: a price is only as good as its weaker quote.
               CASE WHEN ask_conf IS NULL THEN bid_conf WHEN bid_conf IS NULL THEN ask_conf
                    WHEN {CONFIDENCE_RANK.format(col="ask_conf")}
                         <= {CONFIDENCE_RANK.format(col="bid_conf")} THEN ask_conf
                    ELSE bid_conf END AS confidence
        FROM ask FULL OUTER JOIN bid ON ask.name = bid.name AND ask.date = bid.date
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE stage_item AS
        WITH candidates AS (
            SELECT 'currency:' || {SLUG.format(col="name")} AS id, name, 'currency' AS category,
                   NULL AS base_type, NULL AS variant, NULL::INTEGER AS links,
                   NULL::BIGINT AS ninja_id, 0 AS pref, NULL::DATE AS date
            FROM stage_currency
            UNION ALL
            SELECT item_id, name,
                   CASE WHEN type IN {CURRENCY_LIKE} THEN lower(type) ELSE type END,
                   CASE WHEN type LIKE 'Unique%' THEN base_type END,
                   CASE WHEN type LIKE 'Unique%' THEN variant END,
                   {LINKS},
                   CASE WHEN type LIKE 'Unique%' THEN ninja_id END,
                   1, date
            FROM stage_item_rows
        )
        SELECT DISTINCT ON (id)
            id, '{GAME}' AS game, name AS canonical_name, category, base_type, variant, links,
            ninja_id
        FROM candidates
        ORDER BY id, pref, date DESC NULLS LAST
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE stage_price AS
        WITH divine AS (
            SELECT date, chaos_value AS rate FROM stage_currency WHERE name = 'Divine Orb'
        ),
        rows AS (
            SELECT 'currency:' || {SLUG.format(col="name")} AS item_id, date, chaos_value,
                   chaos_ask, chaos_bid, confidence, 0 AS pref
            FROM stage_currency
            UNION ALL
            SELECT item_id, date, chaos_value,
                   NULL::DOUBLE PRECISION, NULL::DOUBLE PRECISION, confidence,
                   4 - {CONFIDENCE_RANK.format(col="confidence")}
            FROM stage_item_rows
        ),
        -- One row per item and day: the currency file wins, then the most confident row.
        best AS (
            SELECT DISTINCT ON (item_id, date) * FROM rows ORDER BY item_id, date, pref
        )
        SELECT r.item_id, l.id AS league_id, CAST(r.date AS TIMESTAMP) AS observed_at,
               CAST(datediff('day', CAST(l.start_at AS DATE), r.date) AS DOUBLE PRECISION)
                   AS day_offset,
               r.chaos_value, r.chaos_value / d.rate AS divine_value,
               '{SOURCE}' AS source, r.confidence, r.chaos_ask, r.chaos_bid
        FROM best r
        JOIN league l ON l.id = '{dump.league_id}'
        LEFT JOIN divine d ON d.date = r.date
        """
    )


def load_league(
    con: duckdb.DuckDBPyConnection, settings: Settings, dump: DumpInfo, force: bool = False
) -> LoadResult:
    fp = fingerprint(settings, dump)
    q = "SELECT fingerprint FROM ingest_load WHERE league_id = ? AND source = ?"
    previous = db.rows(con, q, [dump.league_id, SOURCE])
    if previous and previous[0][0] == fp and not force:
        return LoadResult(dump.league_id, skipped=True)

    con.execute("BEGIN TRANSACTION")
    try:
        _stage(con, settings, dump)
        con.execute(
            """
            INSERT INTO item (id, game, canonical_name, category, base_type, variant, links,
                              ninja_id)
            SELECT * FROM stage_item
            ON CONFLICT (id) DO NOTHING
            """
        )
        refresh_mappings(con, settings)
        con.execute(
            "DELETE FROM price_observation WHERE league_id = ? AND source = ?",
            [dump.league_id, SOURCE],
        )
        con.execute(
            """
            INSERT INTO price_observation (item_id, league_id, observed_at, day_offset,
                chaos_value, divine_value, source, confidence, chaos_ask, chaos_bid)
            SELECT * FROM stage_price
            """
        )
        items = db.scalar(con, "SELECT count(*) FROM stage_item")
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
            [dump.league_id, SOURCE, fp, items, rows, datetime.now(UTC).replace(tzinfo=None)],
        )
        con.execute("COMMIT")
    except BaseException:
        # Includes KeyboardInterrupt: the league is either fully loaded or untouched.
        con.execute("ROLLBACK")
        raise
    finally:
        for t in ("stage_item_rows", "stage_currency", "stage_item", "stage_price"):
            con.execute(f"DROP TABLE IF EXISTS {t}")
    return LoadResult(dump.league_id, skipped=False, items=items, rows=rows)
