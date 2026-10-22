"""Trading tools across a league's whole loaded window: cross-market loops (the
Arbitrage trading page) and card turn-ins (the Card turn-ins page)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from exiledbroker.analysis import launch_patterns as lp
from exiledbroker.api import deps
from exiledbroker.api.models import ArbitrageItem, CrossMarketHour, TurnIn, TurnInHour
from exiledbroker.services import cross_market, divination

router = APIRouter(tags=["trading"])
Con = Annotated[object, Depends(deps.connection)]
Direction = Literal["chaos_first", "divine_first"]
Unit = Literal["chaos", "divine"]


@router.get("/arbitrage", response_model=list[ArbitrageItem])
def arbitrage(
    con: Con,
    league: Annotated[list[str] | None, Query()] = None,
    direction: Direction = "chaos_first",
    buffer: Annotated[float, Query(ge=0, le=0.5)] = 0.02,
    min_hours: Annotated[int, Query(ge=1, le=1000)] = 24,
    min_price: Annotated[float, Query(ge=0)] = 1.0,
    half_life: Annotated[float, Query(gt=0, le=20)] = 2.0,
    weights: str | None = None,
) -> list[dict]:
    """Loops scored across leagues (default: every league with hourly data), newest
    league weighted most. Repeat `league` to choose."""
    leagues = league or lp.hourly_league_names(con)
    for name in leagues:
        deps.league_id(con, name)
    w = deps.parse_weights(weights, cross_market.DEFAULT_WEIGHTS)
    args = (
        tuple(leagues),
        direction,
        buffer,
        min_hours,
        min_price,
        half_life,
        tuple(sorted(w.items())),
    )

    def compute() -> list[dict]:
        per = cross_market.summarize(con, leagues, direction, buffer, min_hours)
        summary = cross_market.across_leagues(per, leagues, lp.recency_weights(leagues, half_life))
        if summary.is_empty():
            return []
        summary = summary.filter(summary["chaos_price"] >= min_price)
        return deps.records(cross_market.score(summary, w))

    return deps.cached(con, "arbitrage", args, compute)


@router.get("/arbitrage/hourly", response_model=list[CrossMarketHour])
def arbitrage_hourly(
    con: Con,
    item_id: str,
    league: Annotated[list[str], Query()],
    direction: Direction = "chaos_first",
) -> list[dict]:
    """One item's hours in both markets, for its chart."""
    for name in league:
        deps.league_id(con, name)
    args = (item_id, tuple(league), direction)
    return deps.cached(
        con,
        "arbitrage_hourly",
        args,
        lambda: deps.records(cross_market.hourly(con, league, [item_id], direction)),
    )


@router.get("/cards/{league}", response_model=list[TurnIn])
def cards(
    con: Con,
    league: str,
    unit: Unit = "chaos",
    prefer_cheaper_sets: bool = True,
    weights: str | None = None,
) -> list[dict]:
    """Every followed card with a priced reward and at least one traded hour, scored."""
    deps.league_id(con, league)
    w = deps.parse_weights(weights, divination.DEFAULT_WEIGHTS)
    args = (league, unit, prefer_cheaper_sets, tuple(sorted(w.items())))

    def compute() -> list[dict]:
        summary = divination.turn_in_summary(con, league, unit)
        return deps.records(divination.score_turn_ins(summary, w, prefer_cheaper_sets))

    return deps.cached(con, "cards", args, compute)


@router.get("/cards/{league}/{card_id}/hourly", response_model=list[TurnInHour])
def card_hourly(con: Con, league: str, card_id: str, unit: Unit = "chaos") -> list[dict]:
    """One card's set cost against its reward, hour by hour."""
    deps.league_id(con, league)
    return deps.cached(
        con,
        "card_hourly",
        (league, card_id, unit),
        lambda: deps.records(divination.hourly_turn_ins(con, league, [card_id], unit)),
    )
