"""The running league: what is paying right now (the Live market page)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from exiledbroker.api import deps
from exiledbroker.api.models import CardFlip, Loop, Status
from exiledbroker.services import live

router = APIRouter(tags=["live"])
Con = Annotated[object, Depends(deps.connection)]
Direction = Literal["chaos_first", "divine_first"]
Unit = Literal["chaos", "divine"]


@router.get("/status", response_model=Status)
def status(con: Con) -> dict:
    """Leagues on the exchange, newest data first, and the data version. Cheap: poll
    this, and refetch everything else when `data_version` changes."""
    leagues = deps.cached(con, "status", (), lambda: deps.records(live.live_leagues(con)))
    return {"now": deps.now_utc(), "data_version": deps.data_version(con), "leagues": leagues}


@router.get("/live/{league}/loops", response_model=list[Loop])
def loops(
    con: Con,
    league: str,
    direction: Direction = "chaos_first",
    buffer: Annotated[float, Query(ge=0, le=0.5)] = 0.02,
    lookback: Annotated[int, Query(ge=1, le=48)] = 6,
    min_price: Annotated[float, Query(ge=0)] = 1.0,
    weights: str | None = None,
) -> list[dict]:
    """Chaos/Divine loops that paid in the latest hours, best score first."""
    deps.league_id(con, league)
    w = deps.parse_weights(weights, live.LOOP_WEIGHTS)
    args = (league, direction, buffer, lookback, min_price, tuple(sorted(w.items())))
    return deps.cached(
        con,
        "loops",
        args,
        lambda: deps.records(
            live.live_loops(con, league, direction, buffer, lookback, min_price, w)
        ),
    )


@router.get("/live/{league}/card-flips", response_model=list[CardFlip])
def card_flips(
    con: Con,
    league: str,
    lookback: Annotated[int, Query(ge=1, le=48)] = 6,
    unit: Unit = "chaos",
    weights: str | None = None,
) -> list[dict]:
    """Card turn-ins that paid in the latest hours, best score first."""
    deps.league_id(con, league)
    w = deps.parse_weights(weights, live.CARD_WEIGHTS)
    args = (league, lookback, unit, tuple(sorted(w.items())))
    return deps.cached(
        con,
        "card_flips",
        args,
        lambda: deps.records(live.live_card_flips(con, league, lookback, unit, w)),
    )
