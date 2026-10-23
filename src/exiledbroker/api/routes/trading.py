"""Trading tools across a league's whole loaded window: cross-market loops (the
Arbitrage trading page) and card turn-ins (the Card turn-ins page)."""

from datetime import timedelta
from typing import Annotated, Literal

import polars as pl
from fastapi import APIRouter, Query, Request, Response

from exiledbroker.analysis import launch_patterns as lp
from exiledbroker.api import deps
from exiledbroker.api.deps import View
from exiledbroker.api.models import ArbitrageItem, CrossMarketHour, TurnIn, TurnInHour
from exiledbroker.services import cross_market, divination, live

router = APIRouter(tags=["trading"])
Direction = Literal["chaos_first", "divine_first"]
Unit = Literal["chaos", "divine"]
# Charts show the latest few days by default: the whole loaded window is weeks, with a
# gap between a live league's launch fortnight and its latest days.
CHART_HOURS = 72
MAX_CHART_HOURS = 28 * 24


def arbitrage_view(
    leagues: list[str],
    direction: Direction = "chaos_first",
    buffer: float = 0.02,
    min_hours: int = 24,
    min_price: float = 1.0,
    half_life: float = 2.0,
    weights: str | None = None,
) -> View:
    w = deps.parse_weights(weights, cross_market.DEFAULT_WEIGHTS)

    def compute(con) -> pl.DataFrame:
        per = cross_market.summarize(con, leagues, direction, buffer, min_hours)
        summary = cross_market.across_leagues(per, leagues, lp.recency_weights(leagues, half_life))
        if summary.is_empty():
            return summary
        return cross_market.score(summary.filter(pl.col("chaos_price") >= min_price), w)

    args = (
        tuple(leagues),
        direction,
        buffer,
        min_hours,
        min_price,
        half_life,
        tuple(sorted(w.items())),
    )
    return View("arbitrage", args, compute, ArbitrageItem)


def _latest_hours(con, league: str, hours: int):
    """`since` for a league's latest `hours` hours (None: nothing traded yet)."""
    latest = live.latest_hour(con, league)
    return None if latest is None else latest - timedelta(hours=hours)


def arbitrage_hourly_view(
    item_id: str, leagues: list[str], direction: Direction, hours: int
) -> View:
    def compute(con) -> pl.DataFrame:
        frames = []
        for league in leagues:  # each league's own latest hours
            since = _latest_hours(con, league, hours)
            if since is not None:
                frames.append(
                    cross_market.hourly(
                        con, [league], [item_id], direction, since=since, chaos_only_hours=True
                    )
                )
        return pl.concat(frames) if frames else pl.DataFrame(schema=cross_market.HOURLY_SCHEMA)

    return View(
        "arbitrage_hourly", (item_id, tuple(leagues), direction, hours), compute, CrossMarketHour
    )


def cards_view(
    league: str, unit: Unit = "chaos", prefer_cheaper_sets: bool = True, weights: str | None = None
) -> View:
    w = deps.parse_weights(weights, divination.DEFAULT_WEIGHTS)

    def compute(con) -> pl.DataFrame:
        summary = divination.turn_in_summary(con, league, unit)
        return divination.score_turn_ins(summary, w, prefer_cheaper_sets)

    args = (league, unit, prefer_cheaper_sets, tuple(sorted(w.items())))
    return View("cards", args, compute, TurnIn)


def card_hourly_view(league: str, card_id: str, unit: Unit, hours: int) -> View:
    def compute(con) -> pl.DataFrame:
        since = _latest_hours(con, league, hours)
        if since is None:
            return pl.DataFrame(schema=divination.HOURLY_SCHEMA)
        return divination.hourly_turn_ins(con, league, [card_id], unit, since=since)

    return View("card_hourly", (league, card_id, unit, hours), compute, TurnInHour)


@router.get("/arbitrage", response_model=list[ArbitrageItem])
def arbitrage(
    request: Request,
    league: Annotated[list[str] | None, Query()] = None,
    direction: Direction = "chaos_first",
    buffer: Annotated[float, Query(ge=0, le=0.5)] = 0.02,
    min_hours: Annotated[int, Query(ge=1, le=1000)] = 24,
    min_price: Annotated[float, Query(ge=0)] = 1.0,
    half_life: Annotated[float, Query(gt=0, le=20)] = 2.0,
    weights: str | None = None,
) -> Response:
    """Loops scored across leagues (default: every league with hourly data), newest
    league weighted most. Repeat `league` to choose."""
    if league is None:
        for con in deps.connection():
            league = lp.hourly_league_names(con)
    for name in league:
        deps.require_league(name)
    return deps.respond(
        request, arbitrage_view(league, direction, buffer, min_hours, min_price, half_life, weights)
    )


@router.get("/arbitrage/hourly", response_model=list[CrossMarketHour])
def arbitrage_hourly(
    request: Request,
    item_id: str,
    league: Annotated[list[str], Query()],
    direction: Direction = "chaos_first",
    hours: Annotated[int, Query(ge=1, le=MAX_CHART_HOURS)] = CHART_HOURS,
) -> Response:
    """One item's latest `hours` hours, for its chart: every hour it traded against
    Chaos, with the Divine side null in hours it didn't also trade against Divine."""
    for name in league:
        deps.require_league(name)
    return deps.respond(request, arbitrage_hourly_view(item_id, league, direction, hours))


@router.get("/cards/{league}", response_model=list[TurnIn])
def cards(
    request: Request,
    league: str,
    unit: Unit = "chaos",
    prefer_cheaper_sets: bool = True,
    weights: str | None = None,
) -> Response:
    """Every followed card with a priced reward and at least one traded hour, scored."""
    deps.require_league(league)
    return deps.respond(request, cards_view(league, unit, prefer_cheaper_sets, weights))


@router.get("/cards/{league}/{card_id}/hourly", response_model=list[TurnInHour])
def card_hourly(
    request: Request,
    league: str,
    card_id: str,
    unit: Unit = "chaos",
    hours: Annotated[int, Query(ge=1, le=MAX_CHART_HOURS)] = CHART_HOURS,
) -> Response:
    """One card's set cost against its reward over its latest `hours` hours."""
    deps.require_league(league)
    return deps.respond(request, card_hourly_view(league, card_id, unit, hours))
