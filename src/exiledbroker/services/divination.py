"""Divination card turn-ins: is a full set worth more as cards or as its reward?

For every followed card whose reward trades on the exchange (currency, or another
card), and every hour in which both the card and its reward traded:

    set cost     = stack_size x card price
    reward value = reward_quantity x reward price
    margin       = reward value - set cost

A positive margin means buying a set of cards, turning it in and selling the reward
was profitable at that hour's prices (before trade friction). A random currency reward
("10x Delirium Orb") is valued at its floor, the cheapest item it can roll
(`hourly_floor_turn_ins`, docs/findings.md 12). Unique-item rewards are out of scope.

SQL here must stay Postgres-compatible: the hosted site's Postgres serves the same queries.
"""

from datetime import datetime

import duckdb
import polars as pl

from exiledbroker.normalize.exchange_loader import SOURCE as HOURLY
from exiledbroker.services.market import UNIT_COLUMN
from exiledbroker.services.scoring import rank_score
from exiledbroker.storage import db

HOURLY_SCHEMA = {
    "observed_at": pl.Datetime,
    "day_offset": pl.Float64,
    "card": pl.String,
    "card_price": pl.Float64,
    "reward_price": pl.Float64,
    "set_cost": pl.Float64,
    "reward_value": pl.Float64,
    "margin": pl.Float64,
    "card_volume": pl.Float64,
    "card_low": pl.Float64,  # the hour's lowest and highest trades, in Chaos
    "card_high": pl.Float64,
    "reward_low": pl.Float64,
}


def _unit(unit: str) -> str:
    if unit not in UNIT_COLUMN:
        raise ValueError(f"unit must be one of {', '.join(UNIT_COLUMN)}")
    return UNIT_COLUMN[unit]


CARD_COLUMNS = (
    "item_id, name, filter_tier, stack_size, reward_kind, reward_name, "
    "reward_quantity, reward_item_id, reward_fixed, reward_text"
)


def followed_cards(con: duckdb.DuckDBPyConnection, names: list[str] | None = None) -> pl.DataFrame:
    """Every followed card (or just the named ones): tier, set size and reward."""
    where, params = "", []
    if names is not None:
        if not names:
            names = [""]
        where = f"AND name IN ({', '.join('?' for _ in names)})"
        params = list(names)
    cards = db.frame(
        con,
        f"SELECT {CARD_COLUMNS} FROM divination_card WHERE followed {where}",
        params,
    )
    # Sorted here, not in SQL: Postgres orders text by locale, DuckDB bytewise.
    return cards.sort("filter_tier", "name", nulls_last=True)


def hourly_turn_ins(
    con: duckdb.DuckDBPyConnection,
    league: str,
    card_ids: list[str] | None = None,
    unit: str = "chaos",
    since: datetime | None = None,
) -> pl.DataFrame:
    """Set cost vs reward value for each hour both the card and its reward traded.

    `since` (exclusive) limits it to recent hours in SQL, for the live view."""
    col = _unit(unit)
    where, params = "", [league, HOURLY]
    if card_ids is not None:
        if not card_ids:
            return pl.DataFrame(schema=HOURLY_SCHEMA)
        where = f"AND d.item_id IN ({', '.join('?' for _ in card_ids)})"
        params += card_ids
    if since is not None:
        where += " AND c.observed_at > ?"
        params.append(since)
    out = db.frame(
        con,
        f"""
        SELECT c.observed_at, c.day_offset, d.name AS card,
               c.{col} AS card_price, r.{col} AS reward_price,
               d.stack_size * c.{col} AS set_cost,
               d.reward_quantity * r.{col} AS reward_value,
               d.reward_quantity * r.{col} - d.stack_size * c.{col} AS margin,
               c.volume AS card_volume, c.chaos_low AS card_low, c.chaos_high AS card_high,
               r.chaos_low AS reward_low
        FROM divination_card d
        JOIN price_observation c ON c.item_id = d.item_id
        JOIN price_observation r ON r.item_id = d.reward_item_id
             AND r.league_id = c.league_id AND r.observed_at = c.observed_at
             AND r.source = c.source
        WHERE d.followed AND d.reward_item_id IS NOT NULL
          AND c.league_id = (SELECT id FROM league WHERE name = ?) AND c.source = ? {where}
        """,
        params,
    )
    # Sorted here, not in SQL: Postgres orders text by locale, DuckDB bytewise.
    return out.sort("observed_at", "card")


# A random reward's hour counts only when this share of its pool traded that hour, so a
# missing cheap item can't lift the floor (as in analysis/card_ev.MIN_COVERAGE).
FLOOR_COVERAGE = 0.8


def hourly_floor_turn_ins(
    con: duckdb.DuckDBPyConnection, league: str, since: datetime
) -> pl.DataFrame:
    """`hourly_turn_ins` (in Chaos, with `reward_high`) for followed cards whose reward is
    random, valued at its floor: each hour, the cheapest Chaos-market price among the
    items `card_reward_pool` says it can roll (`reward_low` / `reward_high`: the lowest
    low and the lowest high among them, so whatever rolls).

    The pool is what traded since `since` (exclusive): items absent from the league
    never count, and an hour needs FLOOR_COVERAGE of that pool traded. Aggregated in
    SQL: one row per card and hour back."""
    out = db.frame(
        con,
        """
        WITH h AS (
            SELECT p.reward_name, x.item_id, x.observed_at, x.chaos_price,
                   x.chaos_low, x.chaos_high
            FROM cross_market_hour x
            JOIN card_reward_pool p ON p.item_id = x.item_id
            WHERE x.league_id = (SELECT id FROM league WHERE name = ?)
              AND x.observed_at > ? AND x.chaos_price > 0
        ),
        size AS (
            SELECT reward_name, count(DISTINCT item_id) AS pool_size FROM h GROUP BY reward_name
        ),
        f AS (
            SELECT h.reward_name, h.observed_at, min(h.chaos_price) AS floor,
                   min(h.chaos_low) AS floor_low, min(h.chaos_high) AS floor_high
            FROM h JOIN size s ON s.reward_name = h.reward_name
            GROUP BY h.reward_name, h.observed_at, s.pool_size
            HAVING count(*) >= ? * s.pool_size
        )
        SELECT c.observed_at, c.day_offset, d.name AS card,
               c.chaos_value AS card_price, f.floor AS reward_price,
               d.stack_size * c.chaos_value AS set_cost,
               d.reward_quantity * f.floor AS reward_value,
               d.reward_quantity * f.floor - d.stack_size * c.chaos_value AS margin,
               c.volume AS card_volume, c.chaos_low AS card_low, c.chaos_high AS card_high,
               f.floor_low AS reward_low, f.floor_high AS reward_high
        FROM divination_card d
        JOIN price_observation c ON c.item_id = d.item_id
        JOIN f ON f.reward_name = d.reward_name AND f.observed_at = c.observed_at
        WHERE d.followed AND d.reward_fixed = false AND d.stack_size IS NOT NULL
          AND c.league_id = (SELECT id FROM league WHERE name = ?) AND c.source = ?
          AND c.observed_at > ? AND c.chaos_value > 0
        """,
        [league, since, FLOOR_COVERAGE, league, HOURLY, since],
    ).cast({**HOURLY_SCHEMA, "reward_high": pl.Float64})  # typed even when empty
    # Sorted here, not in SQL: Postgres orders text by locale, DuckDB bytewise.
    return out.sort("observed_at", "card")


def turn_in_summary(
    con: duckdb.DuckDBPyConnection, league: str, unit: str = "chaos"
) -> pl.DataFrame:
    """One row per card with an exchange-priced reward, best typical margin first.

    set_cost, reward_value, margin and margin_pct are medians over the hours both the
    card and its reward traded: thin card markets have junk hours (one card sold at
    100x its price) that would dominate an average. Aggregated in the database, so it
    returns one row per card instead of every card-hour (cost issue #5)."""
    col = _unit(unit)
    out = db.frame(
        con,
        f"""
        WITH t AS (
            SELECT d.item_id, c.volume AS card_volume,
                   d.stack_size * c.{col} AS set_cost,
                   d.reward_quantity * r.{col} AS reward_value,
                   d.reward_quantity * r.{col} - d.stack_size * c.{col} AS margin
            FROM divination_card d
            JOIN price_observation c ON c.item_id = d.item_id
            JOIN price_observation r ON r.item_id = d.reward_item_id
                 AND r.league_id = c.league_id AND r.observed_at = c.observed_at
                 AND r.source = c.source
            WHERE d.followed AND d.reward_item_id IS NOT NULL
              AND c.league_id = (SELECT id FROM league WHERE name = ?) AND c.source = ?
              AND c.{col} IS NOT NULL AND r.{col} IS NOT NULL
        ),
        s AS (
            SELECT item_id,
                   count(*) AS hours,
                   avg(CASE WHEN margin > 0 THEN 1.0 ELSE 0.0 END) AS profitable_share,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY margin) AS margin,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY margin / nullif(set_cost, 0))
                       AS margin_pct,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY set_cost) AS set_cost,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY reward_value) AS reward_value,
                   sum(card_volume) AS cards_traded
            FROM t GROUP BY item_id
        )
        -- Every card with an exchange-priced reward, traded or not, in one query.
        SELECT {", ".join(f"d.{c}" for c in CARD_COLUMNS.split(", "))},
               coalesce(s.hours, 0) AS hours, s.profitable_share, s.margin, s.margin_pct,
               s.set_cost, s.reward_value, s.cards_traded
        FROM divination_card d LEFT JOIN s ON s.item_id = d.item_id
        WHERE d.followed AND d.reward_item_id IS NOT NULL
        """,
        [league, HOURLY],
    )
    return out.with_columns(
        hours=pl.col("hours").cast(pl.UInt32),
        cards_traded=pl.col("cards_traded").cast(pl.Float64),
        # Full sets' worth of cards traded: how quickly a set can be bought.
        sets_traded=pl.col("cards_traded").cast(pl.Float64) / pl.col("stack_size"),
    ).sort(["margin", "filter_tier", "name"], descending=[True, False, False], nulls_last=True)


# --- Scoring -------------------------------------------------------------------------

# factor -> (column, higher is better)
SCORE_FACTORS = {
    "margin": ("margin_pct", True),
    "investment": ("set_cost", False),  # direction can be flipped
    "profitable_hours": ("profitable_share", True),
    "volume": ("sets_traded", True),
}
DEFAULT_WEIGHTS = {"margin": 4.0, "investment": 2.0, "profitable_hours": 3.0, "volume": 3.0}


def score_turn_ins(
    summary: pl.DataFrame,
    weights: dict[str, float] | None = None,
    prefer_cheaper_sets: bool = True,
) -> pl.DataFrame:
    """Add a 0–1 `score` (and a `<factor>_rank` per factor) to a turn-in summary.

    See services/scoring.py. By default a cheaper set ranks better (less capital,
    quicker to fill); set `prefer_cheaper_sets=False` to favour bigger sets instead.
    """
    factors = dict(SCORE_FACTORS)
    factors["investment"] = ("set_cost", not prefer_cheaper_sets)
    return rank_score(summary.filter(pl.col("hours") > 0), factors, weights or DEFAULT_WEIGHTS)
