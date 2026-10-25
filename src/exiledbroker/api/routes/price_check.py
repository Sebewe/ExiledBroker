"""The Price check page (docs/price-check.md): one league's search list and movers,
and one item at a time. Both are cached views, computed once per data version. The
item is bounded: only the items the league's list holds (the core pool's exchange
items it has traded), so no visitor can make it read anything else."""

from fastapi import APIRouter, HTTPException, Request, Response

from exiledbroker.api import deps
from exiledbroker.api.deps import View
from exiledbroker.api.models import PriceCheckIndex, PriceCheckItem
from exiledbroker.services import price_check

router = APIRouter(tags=["price check"])


def index_view(league: str) -> View:
    return View(
        "price_check",
        (league,),
        lambda con: price_check.index(con, league),
        PriceCheckIndex,
        one=True,
    )


def listed(league: str) -> dict[str, dict]:
    """The league's list, by item id (from the cached index view)."""
    doc = deps.payload(index_view(league)).rows[0]
    return {x.item_id: x.model_dump() for x in doc.items}


def item_view(league: str, item_id: str, entry: dict) -> View:
    return View(
        "price_check_item",
        (league, item_id),
        lambda con: price_check.item(con, league, item_id, entry),
        PriceCheckItem,
        one=True,
    )


def movers_views(league: str) -> list[View]:
    """The movers' item views: what a visitor most likely opens (api/warm.py)."""
    doc = deps.payload(index_view(league)).rows[0]
    entries = listed(league)
    return [item_view(league, i, entries[i]) for i in doc.movers if i in entries]


@router.get("/price-check/{league}", response_model=PriceCheckIndex)
def price_check_index(request: Request, league: str) -> Response:
    """The search list (every core-pool exchange item the league has traded: price now,
    units an hour, 24-hour verdict and move in Divines) and the movers: the strongest
    24-hour calls in the launch fortnight, else the biggest 24-hour moves."""
    deps.require_league(league)
    return deps.respond(request, index_view(league))


@router.get("/price-check/{league}/{item_id}", response_model=PriceCheckItem)
def price_check_item(request: Request, league: str, item_id: str) -> Response:
    """One item: its hourly series over the hosted window, the outlook for the next 24
    hours and 3 days (judged in Divines), the stack seller's inputs, its launch premium
    and the best-hour inputs. 404 for an item the league's list doesn't hold."""
    deps.require_league(league)
    entry = listed(league).get(item_id)
    if entry is None:
        raise HTTPException(404, f"{item_id!r} isn't a core-pool exchange item {league} has traded")
    return deps.respond(request, item_view(league, item_id, entry))
