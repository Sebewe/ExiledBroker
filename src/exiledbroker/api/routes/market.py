"""Launch market: what to buy in a league's first days (the Launch market page), tracked
items over a league's first 14 days, and the league calendar."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response

from exiledbroker.api import deps
from exiledbroker.api.deps import View
from exiledbroker.api.models import (
    BacktestReport,
    CalendarLeague,
    Group,
    HourlyLeague,
    LaunchWindow,
    MarketHour,
    MarketItem,
)
from exiledbroker.normalize.tracked import GROUPS
from exiledbroker.services import backtest, launch_picks, market, overview

router = APIRouter(tags=["market"])
Unit = Literal["chaos", "divine"]


def market_leagues_view() -> View:
    return View("market_leagues", (), market.hourly_leagues, HourlyLeague)


def groups_view() -> View:
    return View("groups", (), market.tracked_groups, Group)


def launch_picks_view() -> View:
    return View("launch_picks", (), launch_picks.launch_board, LaunchWindow)


def backtest_view() -> View:
    return View("backtest", (), backtest.report, BacktestReport)


def summary_view(league: str, group: list[str], unit: Unit = "chaos") -> View:
    groups = sorted(group)
    return View(
        "summary",
        (league, tuple(groups), unit),
        lambda con: market.summary(con, league, groups, unit),
        MarketItem,
    )


@router.get("/market/leagues", response_model=list[HourlyLeague])
def leagues(request: Request) -> Response:
    """Leagues with hourly data, newest first."""
    return deps.respond(request, market_leagues_view())


@router.get("/market/groups", response_model=list[Group])
def groups(request: Request) -> Response:
    """Price-mapping groups (currency, essences, scarabs, cards) and their item counts."""
    return deps.respond(request, groups_view())


@router.get("/launch/picks", response_model=list[LaunchWindow])
def picks(request: Request) -> Response:
    """What to buy in each early-league window, ranked from past leagues (empty until
    `eb launch picks` has been run on the research database and seeded)."""
    return deps.respond(request, launch_picks_view())


@router.get("/backtest", response_model=list[BacktestReport])
def backtest_report(request: Request) -> Response:
    """Would following the site's tools have paid? The backtest's report (one item; empty
    until `eb backtest run` has been run on the research database and seeded)."""
    return deps.respond(request, backtest_view())


@router.get("/market/{league}/summary", response_model=list[MarketItem])
def summary(
    request: Request, league: str, group: Annotated[list[str], Query()], unit: Unit = "chaos"
) -> Response:
    """Launch-window summary per tracked item of the chosen groups."""
    deps.require_league(league)
    known = {g.id for g in GROUPS}  # fixed by code: valid before any item is loaded
    if unknown := sorted(set(group) - known):
        raise HTTPException(404, f"unknown group(s): {', '.join(unknown)}")
    return deps.respond(request, summary_view(league, group, unit))


@router.get("/market/{league}/hourly", response_model=list[MarketHour])
def hourly(
    request: Request,
    league: str,
    item_id: Annotated[list[str], Query(max_length=20)],
    unit: Unit = "chaos",
) -> Response:
    """Hourly launch-window prices of up to 20 items, for the chart."""
    deps.require_league(league)
    ids = sorted(item_id)
    view = View(
        "hourly",
        (league, tuple(ids), unit),
        lambda con: market.hourly(con, league, ids, unit),
        MarketHour,
    )
    return deps.respond(request, view)


@router.get("/leagues", response_model=list[CalendarLeague])
def calendar(request: Request) -> Response:
    """Challenge leagues and how much price data each has."""
    return deps.respond(request, View("calendar", (), overview.league_calendar, CalendarLeague))
