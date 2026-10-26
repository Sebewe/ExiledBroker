"""The running league: its status and what the latest published hours offered (the
Market recap). The hosted API serves only what the site's pages request, all of it
precomputed once per hour (api/warm.py): no endpoint takes free-form arguments, so
no visitor can make it read the database again (docs/decisions.md)."""

from fastapi import APIRouter, Request, Response

from exiledbroker.api import deps
from exiledbroker.api.deps import View
from exiledbroker.api.models import LiveLeague, MissedWindow, Status
from exiledbroker.api.routes import preview
from exiledbroker.services import live, missed

router = APIRouter(tags=["live"])


def leagues_view() -> View:
    return View("status_leagues", (), live.live_leagues, LiveLeague)


def missed_view(league: str) -> View:
    return View("missed", (league,), lambda con: missed.missed(con, league), MissedWindow)


def upcoming(leagues: list) -> dict | None:
    """The announced next league until it has trades loaded (`live.upcoming_league`)."""
    return live.upcoming_league(deps.settings(), live.traded(leagues))


# Browsers check the status only when a new hour is due (web/src/lib/schedule.ts); this
# is the backstop if one asks more often: it gets its own copy for a minute.
STATUS_CACHE = "public, max-age=60"


@router.get("/status", response_model=Status)
def status(response: Response) -> dict:
    """Leagues on the exchange, newest data first, the data version, the announced next
    league until it has trades, and the pre-launch preview while it's on. Cheap: poll
    this, and refetch everything else when `data_version` changes."""
    leagues = deps.payload(leagues_view()).rows
    announced = upcoming(leagues)
    response.headers["Cache-Control"] = STATUS_CACHE
    return {
        "now": deps.now_utc(),
        "data_version": deps.public_version(),
        "leagues": leagues,
        "upcoming": announced,
        "preview": preview.status_preview(announced),
    }


@router.get("/missed/{league}", response_model=list[MissedWindow])
def missed_opportunities(request: Request, league: str, v: deps.Version = None) -> Response:
    """What the latest 1, 2 and 3 published hours offered: key movers, volatile items
    and the loops and card turn-ins that left the most on the table. All three
    look-backs at once (a few KB), computed once per loaded hour."""
    deps.require_league(league)
    return deps.respond(request, missed_view(league))
