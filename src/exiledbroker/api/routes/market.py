"""Launch market: tracked items over a league's first 14 days (the Launch market page),
and the league calendar (the Data / about page)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from exiledbroker.api import deps
from exiledbroker.api.models import CalendarLeague, Group, HourlyLeague, MarketHour, MarketItem
from exiledbroker.normalize.tracked import GROUPS
from exiledbroker.services import market, overview

router = APIRouter(tags=["market"])
Con = Annotated[object, Depends(deps.connection)]
Unit = Literal["chaos", "divine"]


@router.get("/market/leagues", response_model=list[HourlyLeague])
def leagues(con: Con) -> list[dict]:
    """Leagues with hourly data, newest first."""
    return deps.cached(con, "market_leagues", (), lambda: deps.records(market.hourly_leagues(con)))


@router.get("/market/groups", response_model=list[Group])
def groups(con: Con) -> list[dict]:
    """Price-mapping groups (currency, essences, scarabs, cards) and their item counts."""
    return deps.cached(con, "groups", (), lambda: deps.records(market.tracked_groups(con)))


@router.get("/market/{league}/summary", response_model=list[MarketItem])
def summary(
    con: Con, league: str, group: Annotated[list[str], Query()], unit: Unit = "chaos"
) -> list[dict]:
    """Launch-window summary per tracked item of the chosen groups."""
    deps.league_id(con, league)
    known = {g.id for g in GROUPS}  # fixed by code: valid before any item is loaded
    if unknown := sorted(set(group) - known):
        raise HTTPException(404, f"unknown group(s): {', '.join(unknown)}")
    args = (league, tuple(sorted(group)), unit)
    return deps.cached(
        con, "summary", args, lambda: deps.records(market.summary(con, league, group, unit))
    )


@router.get("/market/{league}/hourly", response_model=list[MarketHour])
def hourly(
    con: Con,
    league: str,
    item_id: Annotated[list[str], Query(max_length=20)],
    unit: Unit = "chaos",
) -> list[dict]:
    """Hourly prices of up to 20 items, for the chart."""
    deps.league_id(con, league)
    args = (league, tuple(sorted(item_id)), unit)
    return deps.cached(
        con, "hourly", args, lambda: deps.records(market.hourly(con, league, item_id, unit))
    )


@router.get("/leagues", response_model=list[CalendarLeague])
def calendar(con: Con) -> list[dict]:
    """Challenge leagues and how much price data each has."""
    return deps.cached(con, "calendar", (), lambda: deps.records(overview.league_calendar(con)))
