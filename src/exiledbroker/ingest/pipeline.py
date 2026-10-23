"""The hosted data pipeline: one hourly pass, then exit (`eb pipeline run`, a Railway
cron job a few minutes past every hour).

The server keeps only what the site reads, in its Postgres database (EB_DATABASE_URL):
the live league's rows, the live window's raw pages (`exchange_page`, so a loader
rebuild re-reads them instead of fetching again), and the Launch history the picks
are ranked from. No DuckDB file and no disk: the loader runs on an in-memory DuckDB
with Postgres attached (`db.site_writer`). Each pass:

1. picks the league: the announced next league once it has started (settings),
   else poe.ninja's current one, checked at most hourly with a conditional request;
2. loads the newly published hours (`live.sync_live`, which records the run and
   prunes pages that left the window);
3. once the live league's launch fortnight is over, adds it to the Launch history and
   rebuilds the picks (`launch_picks.refresh`);
4. once the live league has data, drops any other league's rows (a league switch).

The database must be seeded first (`eb site seed --hosted`, from the local copy), so
the server never fetches from GGG what we already have: a pass then fetches only the
hours since the seed, or since the last pass after downtime.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from exiledbroker.config import Settings
from exiledbroker.ingest import core_pool, reference
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest.http import PoliteClient
from exiledbroker.ingest.live import LiveStatus, sync_live
from exiledbroker.services import launch_picks
from exiledbroker.storage import db, site

LEAGUES_MAX_AGE = timedelta(hours=1)  # a new league must be picked up within the hour


class NotSeeded(RuntimeError):
    """The site's database has no history: seed it from the local copy instead of
    fetching everything from GGG."""


@dataclass
class PipelineResult:
    league: str
    live: LiveStatus
    picks_from: list[str] | None = None  # the picks were rebuilt from these leagues
    dropped: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        parts = [str(self.live)]
        if self.picks_from:
            parts.append(f"Launch picks rebuilt from {', '.join(self.picks_from)}.")
        if self.dropped:
            parts.append(f"Dropped {', '.join(self.dropped)} from the site.")
        return " ".join(parts)


def hosted(settings: Settings) -> Settings:
    """The pipeline's settings: pages are kept in the site's database. (Without
    EB_DATABASE_URL that's the local DuckDB file, as in the tests; an unseeded
    database is refused either way.)"""
    return settings.model_copy(update={"exchange_pages": "database"})


def pick_league(client: PoliteClient, settings: Settings, now: datetime) -> str:
    """The announced next league once it has started, else poe.ninja's current
    challenge league (its first listed), from the copy checked within the hour."""
    start = settings.next_league_start
    if settings.next_league and start:
        start = start if start.tzinfo else start.replace(tzinfo=UTC)
        if now >= start:
            return settings.next_league
    url = f"{settings.poe_ninja_base_url}/poe1/api/economy/leagues"
    with db.site_writer(settings) as con:
        leagues = reference.fetch_if_changed(
            con, client, core_pool.LEAGUES_KEY, url, json.loads, LEAGUES_MAX_AGE
        ).value
    return leagues[0]["id"]


def _seeded(settings: Settings) -> bool:
    with db.site_writer(settings) as con:
        return db.scalar(con, f"SELECT count(*) FROM {launch_picks.HISTORY}") > 0


def run(
    client: PoliteClient,
    settings: Settings,
    league: str | None = None,
    now: datetime | None = None,
    lookback_hours: int = 14 * 24,
) -> PipelineResult:
    """One hourly pass. `now` replays a moment (tests, the Railway simulation)."""
    settings = hosted(settings)
    if not _seeded(settings):
        raise NotSeeded(
            "The site's database has no Launch history, so it hasn't been seeded. Seed it "
            "from the local copy (`eb site seed --hosted`) rather than fetching it all from GGG."
        )
    moment = now or datetime.now(UTC)
    name = league or pick_league(client, settings, moment)
    status = sync_live(client, settings, name, lookback_hours, now=now, earliest=cx.HISTORY_START)
    result = PipelineResult(name, status)
    if status.state not in ("updated", "unchanged"):
        return result  # e.g. the announced league has no trades yet: keep the old one
    with db.site_writer(settings) as con:
        result.picks_from = launch_picks.refresh(con, live=name)
        result.dropped = site.drop_leagues(con, name)
    return result
