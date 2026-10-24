"""The Farming page: which mechanics to farm, the launch outlook and the sell helper's
inputs for one league (docs/farming.md), precomputed once per loaded hour like the
Market recap. It takes no other arguments: a typed stack size stays in the browser."""

from fastapi import APIRouter, Request, Response

from exiledbroker.api import deps
from exiledbroker.api.deps import View
from exiledbroker.api.models import Farming
from exiledbroker.services import farming

router = APIRouter(tags=["farming"])


def farming_view(league: str) -> View:
    return View("farming", (league,), lambda con: farming.farming(con, league), Farming, one=True)


@router.get("/farming/{league}", response_model=Farming)
def farming_page(request: Request, league: str) -> Response:
    """Mechanics ranked on their trend against past leagues' usual path, the launch
    outlook and Easy to sell; the basket items' recent trading in each market; the hour
    of day and stack-impact constants. Before the league's first trades, the outlook
    only. Prices in Chaos (Divines for the Divine market): convert with `/api/status`."""
    deps.require_league(league)
    return deps.respond(request, farming_view(league))
