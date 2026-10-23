"""The running league: what the latest published hours offered (the Missed
opportunities page), plus the loop and card tables behind it."""

from datetime import UTC, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response

from exiledbroker.api import deps
from exiledbroker.api.deps import View
from exiledbroker.api.models import CardFlip, LiveLeague, Loop, MissedWindow, Status
from exiledbroker.config import get_settings
from exiledbroker.services import live, missed

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


def missed_view(league: str) -> View:
    return View("missed", (league,), lambda con: missed.missed(con, league), MissedWindow)


# GGG publishes an hour a few minutes after it ends; the worker loads it ~6 minutes past.
FIRST_DATA_DELAY = timedelta(minutes=10)


def upcoming(leagues: list) -> dict | None:
    """The announced next league (settings), until it has trades loaded: when it starts
    and roughly when its first hour shows up here (the end of its first clock hour,
    plus the publishing delay)."""
    settings = get_settings()
    name, start = settings.next_league, settings.next_league_start
    if not name or not start:
        return None
    if any(lg.name == name and lg.latest_hour for lg in leagues):
        return None
    start = start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC)
    first_hour_end = start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return {"name": name, "start_at": start, "first_data_at": first_hour_end + FIRST_DATA_DELAY}


# Browsers check the status only when a new hour is due (web/src/lib/schedule.ts); this
# is the backstop if one asks more often: it gets its own copy for a minute.
STATUS_CACHE = "public, max-age=60"


@router.get("/status", response_model=Status)
def status(response: Response) -> dict:
    """Leagues on the exchange, newest data first, the data version, and the announced
    next league until it has trades. Cheap: poll this, and refetch everything else when
    `data_version` changes."""
    leagues = deps.payload(leagues_view()).rows
    response.headers["Cache-Control"] = STATUS_CACHE
    return {
        "now": deps.now_utc(),
        "data_version": deps.data_version(),
        "leagues": leagues,
        "upcoming": upcoming(leagues),
    }


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


@router.get("/missed/{league}", response_model=list[MissedWindow])
def missed_opportunities(request: Request, league: str) -> Response:
    """What the latest 1, 2 and 3 published hours offered: key movers, volatile items
    and the loops and card turn-ins that left the most on the table. All three
    look-backs at once (a few KB), computed once per loaded hour."""
    deps.require_league(league)
    return deps.respond(request, missed_view(league))
