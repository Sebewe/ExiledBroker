"""Cached data loaders and formatting shared by the demo pages."""

import polars as pl
import streamlit as st

from exiledbroker.analysis import launch_patterns as lp
from exiledbroker.config import get_settings
from exiledbroker.services import cross_market, divination, live, market, overview
from exiledbroker.storage import db

UNIT_SUFFIX = {"chaos": "c", "divine": "div"}


def database_ready() -> bool:
    return get_settings().db_path.exists()


@st.cache_data(ttl="10m", show_spinner=False)
def hourly_leagues() -> pl.DataFrame:
    with db.session(read_only=True) as con:
        return market.hourly_leagues(con)


@st.cache_data(ttl="10m", show_spinner=False)
def summary(league: str, groups: tuple[str, ...], unit: str) -> pl.DataFrame:
    with db.session(read_only=True) as con:
        return market.summary(con, league, list(groups), unit)


@st.cache_data(ttl="10m", show_spinner=False, max_entries=64)
def hourly(league: str, item_ids: tuple[str, ...], unit: str) -> pl.DataFrame:
    with db.session(read_only=True) as con:
        return market.hourly(con, league, list(item_ids), unit)


@st.cache_data(ttl="10m", show_spinner=False)
def turn_ins(league: str, unit: str) -> pl.DataFrame:
    with db.session(read_only=True) as con:
        return divination.turn_in_summary(con, league, unit)


@st.cache_data(ttl="10m", show_spinner=False, max_entries=64)
def card_turn_in_hourly(league: str, card_id: str, unit: str) -> pl.DataFrame:
    with db.session(read_only=True) as con:
        return divination.hourly_turn_ins(con, league, [card_id], unit)


@st.cache_data(ttl="10m", show_spinner=False)
def followed_cards() -> pl.DataFrame:
    with db.session(read_only=True) as con:
        return divination.followed_cards(con)


# --- Analysis --------------------------------------------------------------------


@st.cache_data(ttl="10m", show_spinner=False)
def analysis_leagues() -> dict[str, list[str]]:
    """Challenge leagues with hourly and with daily data, newest first."""
    with db.session(read_only=True) as con:
        return {
            "hourly": lp.hourly_league_names(con),
            "daily": lp.daily_league_names(con),
        }


@st.cache_data(ttl="10m", show_spinner=False)
def tracked_items() -> pl.DataFrame:
    with db.session(read_only=True) as con:
        return db.frame(
            con,
            """
            SELECT t.item_id, i.canonical_name AS name, t.group_id, t.group_label, t.sort_order
            FROM tracked_item t JOIN item i ON i.id = t.item_id
            ORDER BY t.sort_order, i.canonical_name
            """,
        )


@st.cache_data(ttl="10m", show_spinner="Comparing uniques across leagues…")
def unique_moves(leagues: tuple[str, ...], base_day: int, end_day: int, high_only: bool):
    with db.session(read_only=True) as con:
        moves = lp.unique_moves(
            con,
            since=None,
            base_day=base_day,
            end_day=end_day,
            confidence="High" if high_only else None,
        )
    return moves.filter(pl.col("league").is_in(list(leagues)))


@st.cache_data(ttl="10m", show_spinner=False, max_entries=64)
def launch_curves(item_ids: tuple[str, ...], leagues: tuple[str, ...], unit: str, bucket: int):
    with db.session(read_only=True) as con:
        return lp.launch_curves(con, list(item_ids), list(leagues), unit, bucket)


@st.cache_data(ttl="10m", show_spinner="Building group curves…", max_entries=32)
def group_curves(group_id: str, leagues: tuple[str, ...], unit: str, bucket: int):
    with db.session(read_only=True) as con:
        return lp.group_curves(con, group_id, list(leagues), unit, bucket)


@st.cache_data(ttl="10m", show_spinner="Comparing turn-ins across leagues…")
def turn_ins_across(leagues: tuple[str, ...], half_life: float) -> pl.DataFrame:
    with db.session(read_only=True) as con:
        return lp.turn_ins_across_leagues(
            con, list(leagues), lp.recency_weights(list(leagues), half_life)
        )


@st.cache_data(ttl="10m", show_spinner="Pricing loops through both markets…", max_entries=64)
def cross_market_per_league(
    leagues: tuple[str, ...], direction: str, buffer: float, min_hours: int
) -> pl.DataFrame:
    with db.session(read_only=True) as con:
        return cross_market.summarize(con, list(leagues), direction, buffer, min_hours)


@st.cache_data(ttl="10m", show_spinner=False, max_entries=64)
def cross_market_item(leagues: tuple[str, ...], item_id: str, direction: str) -> pl.DataFrame:
    with db.session(read_only=True) as con:
        return cross_market.hourly(con, list(leagues), [item_id], direction)


# --- Live -------------------------------------------------------------------------
# The watcher adds one hour of data per hour. Only the cheap league list is re-read
# every minute; the heavy results are cached by the league's latest loaded hour, so
# they're re-queried once per new hour, not once per minute (cost issue #1).


@st.cache_data(ttl="1m", show_spinner=False)
def live_leagues() -> pl.DataFrame:
    with db.session(read_only=True) as con:
        return live.live_leagues(con)


@st.cache_data(ttl="6h", show_spinner=False, max_entries=64)
def live_loops(
    league: str, latest_hour, direction: str, buffer: float, lookback: int, min_price: float
) -> pl.DataFrame:
    """`latest_hour` is part of the cache key: a new hour means a fresh query."""
    with db.session(read_only=True) as con:
        return live.live_loops(con, league, direction, buffer, lookback, min_price)


@st.cache_data(ttl="6h", show_spinner=False, max_entries=64)
def live_cards(league: str, latest_hour, lookback: int, unit: str) -> pl.DataFrame:
    """`latest_hour` is part of the cache key: a new hour means a fresh query."""
    with db.session(read_only=True) as con:
        return live.live_card_flips(con, league, lookback, unit)


@st.cache_data(ttl="10m", show_spinner=False)
def calendar() -> pl.DataFrame:
    with db.session(read_only=True) as con:
        return overview.league_calendar(con)


@st.cache_data(ttl="10m", show_spinner=False)
def loads() -> pl.DataFrame:
    with db.session(read_only=True) as con:
        return db.frame(
            con,
            """
            SELECT l.name AS league, il.source, il.item_count, il.row_count, il.loaded_at
            FROM ingest_load il JOIN league l ON l.id = il.league_id
            ORDER BY l.start_at DESC, il.source
            """,
        )


def fmt_price(value: float | None, unit: str) -> str:
    if value is None:
        return "–"
    if value >= 1000:
        text = f"{value:,.0f}"
    elif value >= 10:
        text = f"{value:,.1f}"
    elif value >= 1:
        text = f"{value:.2f}"
    else:
        text = f"{value:.3g}"
    return f"{text} {UNIT_SUFFIX[unit]}"


def price_format(unit: str) -> str:
    return "%.2f" if unit == "chaos" else "%.4f"
