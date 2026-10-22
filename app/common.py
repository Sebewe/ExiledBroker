"""Cached data loaders and formatting shared by the demo pages."""

import polars as pl
import streamlit as st

from exiledbroker.config import get_settings
from exiledbroker.services import market, overview
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
