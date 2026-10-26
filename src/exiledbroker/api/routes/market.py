"""Launch market: what to buy in a league's first days (the Launch market page), and the
Backtest page's report."""

from fastapi import APIRouter, Request, Response

from exiledbroker.api import deps
from exiledbroker.api.deps import View
from exiledbroker.api.models import BacktestReport, LaunchWindow
from exiledbroker.services import backtest, launch_picks

router = APIRouter(tags=["market"])


def launch_picks_view() -> View:
    return View("launch_picks", (), launch_picks.launch_board, LaunchWindow)


def backtest_view() -> View:
    return View("backtest", (), backtest.report, BacktestReport, stamp=backtest.built_at)


@router.get("/launch/picks", response_model=list[LaunchWindow])
def picks(request: Request, v: deps.Version = None) -> Response:
    """What to buy in each early-league window, ranked from past leagues (empty until
    `eb launch picks` has been run on the research database and seeded)."""
    return deps.respond(request, launch_picks_view())


@router.get("/backtest", response_model=list[BacktestReport])
def backtest_report(request: Request, v: deps.Version = None) -> Response:
    """Would following the site's tools have paid? The backtest's report (one item; empty
    until `eb backtest run` has been run on the research database and seeded)."""
    return deps.respond(request, backtest_view())
