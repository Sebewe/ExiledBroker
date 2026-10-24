"""Compute the pages' default tables as soon as new data is loaded, so every visitor
(the first one after an hourly update included) is served cached bytes.

`default_views` must match what the frontend asks for with its default controls;
tests/test_api.py checks that a default page load is a cache hit after `warm()`."""

import logging
import threading

from fastapi import HTTPException

from exiledbroker.api import deps
from exiledbroker.api.deps import View
from exiledbroker.api.routes.farming import farming_view
from exiledbroker.api.routes.live import leagues_view, missed_view
from exiledbroker.api.routes.market import backtest_view, launch_picks_view

log = logging.getLogger("uvicorn.error")  # shown in the server log (Railway's logs)
CHECK_EVERY = 30.0  # seconds between data-version checks


def default_views() -> list[View]:
    leagues = deps.payload(leagues_view()).rows  # newest first, as the pages list them
    trading = [lg.name for lg in leagues if lg.latest_hour]
    views = [deps.LEAGUE_NAMES, launch_picks_view(), backtest_view()]
    views += [missed_view(league) for league in trading]
    views += [farming_view(league) for league in trading]
    return views


def warm() -> int:
    """Compute every default view for the current data version; returns how many."""
    views = default_views()
    for view in views:
        deps.payload(view)
    return len(views)


def run_forever(stop: threading.Event, every: float = CHECK_EVERY) -> None:
    """Background loop: warm once per new data version."""
    warmed = None
    while not stop.is_set():
        try:
            version = deps.data_version(force=True)
            if version and version != warmed:
                log.info("warmed %d views for data version %s", warm(), version)
                warmed = version
        except HTTPException:
            pass  # no data loaded yet
        except Exception:  # never let the warmer take the web process down
            log.exception("warming the API cache failed")
        stop.wait(every)
