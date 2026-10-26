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
   rebuilds the picks (`launch_picks.refresh`), and adds its paths to Price check's
   (`price_paths.refresh`);
4. once the live league has data, drops any other league's rows (a league switch;
   what was built from them, the Launch history, stays);
5. with EB_BACKUP_URL set, syncs the site's database to the off-site backup
   (`storage/backup.py`: uploads the changes, reads back tens of kB);
6. with EB_HEALTHCHECK_URL set, pings the dead-man's switch (`ingest/healthcheck.py`):
   `/start` first, then success, or `/fail` when the pass raised, the backup failed or
   the feed looks stopped (`stale_feed`).

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
from exiledbroker.ingest.healthcheck import Healthcheck
from exiledbroker.ingest.http import PoliteClient
from exiledbroker.ingest.live import LiveStatus, sync_live
from exiledbroker.services import launch_picks, price_paths
from exiledbroker.services.live import live_leagues, traded, upcoming_league
from exiledbroker.storage import backup as backup_mod
from exiledbroker.storage import db, site

LEAGUES_MAX_AGE = timedelta(hours=1)  # a new league must be picked up within the hour
# The alert fires when the followed league's latest hour ended this long ago. The site's
# banner warns at 75 minutes (web/src/lib/freshness.ts) because a visitor wants to know at
# once; an alert should mean a real outage. A pass runs at :06 and sees the hour that ended
# at :00 unless GGG is late, so 3 hours is two or more passes in a row that loaded nothing,
# while a single late hour or a single failed pass (that one pings /fail itself) stays quiet.
STALE_ALERT_AFTER = timedelta(hours=3)


class NotSeeded(RuntimeError):
    """The site's database has no history: seed it from the local copy instead of
    fetching everything from GGG."""


@dataclass
class PipelineResult:
    league: str
    live: LiveStatus
    picks_from: list[str] | None = None  # the picks were rebuilt from these leagues
    paths_from: str | None = None  # Price check's paths gained this league
    dropped: list[str] = field(default_factory=list)
    backup: backup_mod.SyncResult | None = None  # with EB_BACKUP_URL
    backup_error: str | None = None  # the backup failed; the pass didn't
    stale: str | None = None  # the feed looks stopped (`stale_feed`)
    ping_errors: list[str] = field(default_factory=list)  # pings that didn't get through

    def __str__(self) -> str:
        parts = [str(self.live)]
        if self.picks_from:
            parts.append(f"Launch picks rebuilt from {', '.join(self.picks_from)}.")
        if self.paths_from:
            parts.append(f"Price check's paths now include {self.paths_from}.")
        if self.dropped:
            parts.append(f"Dropped {', '.join(self.dropped)} from the site.")
        if self.backup is not None:
            parts.append(str(self.backup))
        if self.backup_error:
            parts.append(f"Backup failed ({self.backup_error}); the next pass catches up.")
        if self.ping_errors:
            parts.append(f"Healthcheck not reached ({'; '.join(self.ping_errors)}).")
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
    # Only with a name and a time: a date alone (GGG hasn't announced the hour yet) would
    # start searching for the league's first hour on a guess.
    start = settings.next_league_start_at
    if settings.next_league and start and now >= start:
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
    start = settings.next_league_start_at
    if settings.next_league == league and start:
        return max(start - timedelta(days=1), cx.HISTORY_START)
    return cx.HISTORY_START


def _seeded(settings: Settings) -> bool:
    with db.site_writer(settings) as con:
        return bool(db.rows(db.pushdown(con), f"SELECT 1 FROM {launch_picks.HISTORY} LIMIT 1"))


def stale_feed(settings: Settings, league: str, now: datetime) -> str | None:
    """Why the followed league's feed looks stopped, else None. The site's definition
    (web/src/lib/freshness.ts, Freshness.tsx): the latest loaded hour ended too long ago,
    unless a next league is announced and has no trades yet, when the old league has
    simply ended (`upcoming_league`). A league with no trades yet is waiting, not stale."""
    with db.site_writer(settings) as con:
        leagues = live_leagues(db.pushdown(con))
    row = next((r for r in leagues.iter_rows(named=True) if r["name"] == league), None)
    if row is None or row["latest_hour"] is None:
        return None
    if upcoming_league(settings, traded(leagues)):
        return None
    latest = row["latest_hour"]
    latest = latest if latest.tzinfo else latest.replace(tzinfo=UTC)
    age = now - (latest + timedelta(hours=1))  # the hour's trades ended here
    if age <= STALE_ALERT_AFTER:
        return None
    hours = age.total_seconds() / 3600
    return f"{league}: the feed looks stopped, the latest loaded hour ended {hours:.1f} h ago."


def run(
    client: PoliteClient,
    settings: Settings,
    league: str | None = None,
    now: datetime | None = None,
    lookback_hours: int = 14 * 24,
    healthcheck: Healthcheck | None = None,
) -> PipelineResult:
    """One hourly pass. `now` replays a moment (tests, the Railway simulation). Then,
    with EB_BACKUP_URL set, the site's database is synced to the off-site backup: a
    failed backup is reported, never raised (the site is fine; the next pass catches
    the backup up).

    With EB_HEALTHCHECK_URL (or a `healthcheck`) the pass pings a dead-man's switch:
    /start, then success, or /fail with the reason when the pass raised (and it still
    raises), the backup failed, or the feed looks stopped. A ping that doesn't get
    through is noted on the result and never fails or slows the pass."""
    settings = hosted(settings)
    own = healthcheck is None
    check = Healthcheck.from_settings(settings) if healthcheck is None else healthcheck
    try:
        check.start()
        try:
            result = _pass(client, settings, league, now, lookback_hours)
        except Exception as e:
            check.fail(f"The pass raised {type(e).__name__}: {e}")
            raise
        if settings.backup_url:
            try:
                result.backup = backup_mod.back_up(settings)
            except Exception as e:  # noqa: BLE001 (any failure: network, the backup's database)
                result.backup_error = f"{type(e).__name__}: {e}"
        if check:
            problems = []
            if result.backup_error:
                problems.append(f"Backup failed: {result.backup_error}")
            try:
                result.stale = stale_feed(settings, result.league, now or datetime.now(UTC))
            except Exception as e:  # noqa: BLE001 (a broken check is itself worth hearing)
                result.stale = f"The stale-feed check failed: {type(e).__name__}: {e}"
            if result.stale:
                problems.append(result.stale)
            summary = str(result)
            if problems:
                check.fail("\n".join(problems) + "\n\n" + summary)
            else:
                check.success(summary)
            result.ping_errors = list(check.errors)
        return result
    finally:
        if own:
            check.close()


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
        result.paths_from = price_paths.refresh(con, name, settings)
        result.dropped = site.drop_leagues(con, name)
    return result
