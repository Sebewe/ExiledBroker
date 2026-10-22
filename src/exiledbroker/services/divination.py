"""Divination card turn-ins: is a full set worth more as cards or as its reward?

For every followed card whose reward trades on the exchange (currency, or another
card), and every hour in which both the card and its reward traded:

    set cost     = stack_size x card price
    reward value = reward_quantity x reward price
    margin       = reward value - set cost

A positive margin means buying a set of cards, turning it in and selling the reward
was profitable at that hour's prices (before trade friction). Unique-item rewards
need the expected value of the reward (it can roll differently), which comes later.

SQL here must stay Postgres-compatible: Supabase will serve the same queries.
"""

import duckdb
import polars as pl

from exiledbroker.normalize.exchange_loader import SOURCE as HOURLY
from exiledbroker.services.market import UNIT_COLUMN
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
}


def _unit(unit: str) -> str:
    if unit not in UNIT_COLUMN:
        raise ValueError(f"unit must be one of {', '.join(UNIT_COLUMN)}")
    return UNIT_COLUMN[unit]


def followed_cards(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Every followed card: tier, set size and reward."""
    return db.frame(
        con,
        """
        SELECT item_id, name, filter_tier, stack_size, reward_kind, reward_name,
               reward_quantity, reward_item_id, reward_fixed, reward_text
        FROM divination_card WHERE followed
        ORDER BY filter_tier, name
        """,
    )


def hourly_turn_ins(
    con: duckdb.DuckDBPyConnection,
    league: str,
    card_ids: list[str] | None = None,
    unit: str = "chaos",
) -> pl.DataFrame:
    """Set cost vs reward value for each hour both the card and its reward traded."""
    col = _unit(unit)
    where, params = "", [league, HOURLY]
    if card_ids is not None:
        if not card_ids:
            return pl.DataFrame(schema=HOURLY_SCHEMA)
        where = f"AND d.item_id IN ({', '.join('?' for _ in card_ids)})"
        params += card_ids
    return db.frame(
        con,
        f"""
        SELECT c.observed_at, c.day_offset, d.name AS card,
               c.{col} AS card_price, r.{col} AS reward_price,
               d.stack_size * c.{col} AS set_cost,
               d.reward_quantity * r.{col} AS reward_value,
               d.reward_quantity * r.{col} - d.stack_size * c.{col} AS margin,
               c.volume AS card_volume
        FROM divination_card d
        JOIN price_observation c ON c.item_id = d.item_id
        JOIN league l ON l.id = c.league_id
        JOIN price_observation r ON r.item_id = d.reward_item_id
             AND r.league_id = c.league_id AND r.observed_at = c.observed_at
             AND r.source = c.source
        WHERE d.followed AND d.reward_item_id IS NOT NULL
          AND l.name = ? AND c.source = ? {where}
        ORDER BY c.observed_at
        """,
        params,
    )


def turn_in_summary(
    con: duckdb.DuckDBPyConnection, league: str, unit: str = "chaos"
) -> pl.DataFrame:
    """One row per card with an exchange-priced reward, best average margin first."""
    cards = followed_cards(con).filter(pl.col("reward_item_id").is_not_null())
    hourly = hourly_turn_ins(con, league, unit=unit).drop_nulls("margin")
    stats = hourly.group_by("card").agg(
        pl.len().alias("hours"),
        (pl.col("margin") > 0).mean().alias("profitable_share"),
        pl.col("margin").mean().alias("avg_margin"),
        pl.col("margin").max().alias("best_margin"),
        # Total margin over total set cost: averaging per-hour percentages blows up
        # when a set costs next to nothing.
        (pl.col("margin").sum() / pl.col("set_cost").sum()).alias("avg_margin_pct"),
        pl.col("set_cost").mean().alias("avg_set_cost"),
        pl.col("reward_value").mean().alias("avg_reward_value"),
        pl.col("card_volume").sum().alias("cards_traded"),
    )
    return (
        cards.join(stats, left_on="name", right_on="card", how="left")
        .with_columns(hours=pl.col("hours").fill_null(0))
        .sort("avg_margin", descending=True, nulls_last=True)
    )
