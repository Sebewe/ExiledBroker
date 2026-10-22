"""The running league: what is paying right now (the Live market page)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response

from exiledbroker.api import deps
from exiledbroker.api.deps import View
from exiledbroker.api.models import CardFlip, LiveLeague, Loop, Status
from exiledbroker.services import live

router = APIRouter(tags=["live"])
Direction = Literal["chaos_first", "divine_first"]
Unit = Literal["chaos", "divine"]


def leagues_view() -> View:
    return View("status_leagues", (), live.live_leagues, LiveLeague)


def loops_view(
    league: str,
    direction: Direction = "chaos_first",
    buffer: float = 0.02,
    lookback: int = 6,
    min_price: float = 1.0,
    weights: str | None = None,
) -> View:
    w = deps.parse_weights(weights, live.LOOP_WEIGHTS)
    return View(
        "loops",
        (league, direction, buffer, lookback, min_price, tuple(sorted(w.items()))),
        lambda con: live.live_loops(con, league, direction, buffer, lookback, min_price, w),
        Loop,
    )


def card_flips_view(
    league: str, lookback: int = 6, unit: Unit = "chaos", weights: str | None = None
) -> View:
    w = deps.parse_weights(weights, live.CARD_WEIGHTS)
    return View(
        "card_flips",
        (league, lookback, unit, tuple(sorted(w.items()))),
        lambda con: live.live_card_flips(con, league, lookback, unit, w),
        CardFlip,
    )


@router.get("/status", response_model=Status)
def status() -> dict:
    """Leagues on the exchange, newest data first, and the data version. Cheap: poll
    this, and refetch everything else when `data_version` changes."""
    leagues = deps.payload(leagues_view()).rows
    return {"now": deps.now_utc(), "data_version": deps.data_version(), "leagues": leagues}


@router.get("/live/{league}/loops", response_model=list[Loop])
def loops(
    request: Request,
    league: str,
    direction: Direction = "chaos_first",
    buffer: Annotated[float, Query(ge=0, le=0.5)] = 0.02,
    lookback: Annotated[int, Query(ge=1, le=48)] = 6,
    min_price: Annotated[float, Query(ge=0)] = 1.0,
    weights: str | None = None,
) -> Response:
    """Chaos/Divine loops that paid in the latest hours, best score first."""
    deps.require_league(league)
    return deps.respond(
        request, loops_view(league, direction, buffer, lookback, min_price, weights)
    )


@router.get("/live/{league}/card-flips", response_model=list[CardFlip])
def card_flips(
    request: Request,
    league: str,
    lookback: Annotated[int, Query(ge=1, le=48)] = 6,
    unit: Unit = "chaos",
    weights: str | None = None,
) -> Response:
    """Card turn-ins that paid in the latest hours, best score first."""
    deps.require_league(league)
    return deps.respond(request, card_flips_view(league, lookback, unit, weights))
