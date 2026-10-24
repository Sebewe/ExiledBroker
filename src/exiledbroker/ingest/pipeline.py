"""The hosted data pipeline: one hourly pass, then exit (`eb pipeline run`, a Railway
cron job a few minutes past every hour).

The server keeps only what the site reads, in its Postgres database (EB_DATABASE_URL):
the live league's rows, the live window's raw pages (`exchange_page`, so a loader
rebuild re-reads them instead of fetching again), and the Launch history the picks
are ranked from. No DuckDB file and no disk: the loader runs on an in-memory DuckDB
with Postgres attached (`db.site_writer`). Each pass:

1. picks the league: the announced next league once it has started (settings), else
   the one already followed (`pick_league`: never Standard or an event in the days
   between leagues);
2. loads the newly published hours (`live.sync_live`, which records the run and
   prunes pages that left the window);
3. once the live league's launch fortnight is over, adds it to the Launch history and
   rebuilds the picks (`launch_picks.refresh`), and reduces it into the Farming page's
   history (`item_history.refresh`: a row per basket item and day, ~2 MB a league;
   the baskets come from config/mechanics.toml, in the image);
4. once the live league has data, drops any other league's rows (a league switch;
   what was built from them, the Launch history and the Farming history, stays);
5. with EB_BACKUP_URL set, syncs the site's database to the off-site backup
   (`storage/backup.py`: uploads the changes, reads back tens of kB).

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
from exiledbroker.normalize import mechanics
from exiledbroker.services import item_history, launch_picks
from exiledbroker.services.live import live_leagues
from exiledbroker.storage import backup as backup_mod
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
    farming_from: list[str] = field(default_factory=list)  # captured into item_day_history
    no_baskets: str | None = None  # the mechanics file is missing: nothing to capture
    dropped: list[str] = field(default_factory=list)
    backup: backup_mod.SyncResult | None = None  # with EB_BACKUP_URL
    backup_error: str | None = None  # the backup failed; the pass didn't

    def __str__(self) -> str:
        parts = [str(self.live)]
        if self.picks_from:
            parts.append(f"Launch picks rebuilt from {', '.join(self.picks_from)}.")
        if self.farming_from:
            parts.append(f"Farming history captured for {', '.join(self.farming_from)}.")
        if self.no_baskets:
            parts.append(f"No mechanics at {self.no_baskets}: the Farming history waits.")
        if self.dropped:
            parts.append(f"Dropped {', '.join(self.dropped)} from the site.")
        if self.backup is not None:
            parts.append(str(self.backup))
        if self.backup_error:
            parts.append(f"Backup failed ({self.backup_error}); the next pass catches up.")
        return " ".join(parts)


def hosted(settings: Settings) -> Settings:
    """The pipeline's settings: pages are kept in the site's database. (Without
    EB_DATABASE_URL that's the local DuckDB file, as in the tests; an unseeded
    database is refused either way.)"""
    return settings.model_copy(update={"exchange_pages": "database"})


def challenge_like(name: str) -> bool:
    """Could `name` be a challenge league? Rules out the permanent leagues and the
    variants poe.ninja lists next to a challenge league (Hardcore, Ruthless, SSF) and
    private leagues. Event leagues can't be told apart by name, which is why
    poe.ninja's list is only a fallback (see `pick_league`)."""
    lowered = name.lower()
    return not (
        lowered in ("standard", "hardcore", "ruthless", "hardcore ruthless")
        or lowered.startswith(("hardcore ", "hc ", "ruthless ", "ssf ", "solo self-found"))
        or "(pl" in lowered
    )


def pick_league(client: PoliteClient, settings: Settings, now: datetime) -> str:
    """The league to follow this pass.

    1. The announced next league (EB_NEXT_LEAGUE / _START), once it has started.
    2. Else the league the site already follows (the newest in the database), even
       after it has stopped trading: an old league ends days before the next one
       launches, and in between only Standard and event leagues trade. It's never
       swapped for whatever poe.ninja lists first in that gap.
    3. Else (a database with no league yet) poe.ninja's first challenge-like league,
       from the copy checked within the hour."""
    start = settings.next_league_start
    if settings.next_league and start:
        start = start if start.tzinfo else start.replace(tzinfo=UTC)
        if now >= start:
            return settings.next_league
    with db.site_writer(settings) as con:
        followed = live_leagues(db.pushdown(con))  # its subqueries scan, through DuckDB
        if followed.height:
            return followed["name"][0]
        url = f"{settings.poe_ninja_base_url}/poe1/api/economy/leagues"
        leagues = reference.fetch_if_changed(
            con, client, core_pool.LEAGUES_KEY, url, json.loads, LEAGUES_MAX_AGE
        ).value
    names = [lg["id"] for lg in leagues if challenge_like(lg["id"])]
    if not names:
        raise LookupError("poe.ninja lists no challenge league; set EB_NEXT_LEAGUE")
    return names[0]


def launch_search_from(settings: Settings, league: str) -> datetime:
    """Where the search for a league's first hour starts: a day before its announced
    start (a dozen pages fewer than searching from 2024), else the exchange's start."""
    start = settings.next_league_start
    if settings.next_league == league and start:
        start = start if start.tzinfo else start.replace(tzinfo=UTC)
        return max(start - timedelta(days=1), cx.HISTORY_START)
    return cx.HISTORY_START


def _seeded(settings: Settings) -> bool:
    with db.site_writer(settings) as con:
        return bool(db.rows(db.pushdown(con), f"SELECT 1 FROM {launch_picks.HISTORY} LIMIT 1"))


def run(
    client: PoliteClient,
    settings: Settings,
    league: str | None = None,
    now: datetime | None = None,
    lookback_hours: int = 14 * 24,
) -> PipelineResult:
    """One hourly pass. `now` replays a moment (tests, the Railway simulation). Then,
    with EB_BACKUP_URL set, the site's database is synced to the off-site backup: a
    failed backup is reported, never raised (the site is fine; the next pass catches
    the backup up)."""
    settings = hosted(settings)
    result = _pass(client, settings, league, now, lookback_hours)
    if settings.backup_url:
        try:
            result.backup = backup_mod.back_up(settings)
        except Exception as e:  # noqa: BLE001 (any failure: network, the backup's database)
            result.backup_error = f"{type(e).__name__}: {e}"
    return result


def _pass(
    client: PoliteClient,
    settings: Settings,
    league: str | None,
    now: datetime | None,
    lookback_hours: int,
) -> PipelineResult:
    if not _seeded(settings):
        raise NotSeeded(
            "The site's database has no Launch history, so it hasn't been seeded. Seed it "
            "from the local copy (`eb site seed --hosted`) rather than fetching it all from GGG."
        )
    moment = now or datetime.now(UTC)
    name = league or pick_league(client, settings, moment)
    earliest = launch_search_from(settings, name)
    status = sync_live(client, settings, name, lookback_hours, now=now, earliest=earliest)
    result = PipelineResult(name, status)
    if status.state not in ("updated", "unchanged"):
        return result  # e.g. the announced league has no trades yet: keep the old one
    with db.site_writer(settings) as con:
        result.picks_from = launch_picks.refresh(con, live=name)
        # Before a league switch drops the old league's hours: a finished league not
        # captured yet (a few small queries a pass; a capture about once a league).
        if mechanics.load_mechanics(settings):
            result.farming_from = item_history.refresh(con, settings, live=name)
        else:  # without baskets it would "capture" leagues as empty, every pass
            result.no_baskets = str(settings.mechanics_file)
        result.dropped = site.drop_leagues(con, name)
    return result
