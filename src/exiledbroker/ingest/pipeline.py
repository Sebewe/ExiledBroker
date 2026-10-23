"""The hosted data pipeline: one hourly pass, then exit (`eb pipeline run`, a Railway
cron job a few minutes past every hour).

The pipeline owns the research database: a DuckDB file on its volume with the whole
history and the raw GGG pages, so nothing it already has is ever fetched again, even
on a rebuild. Each pass:

1. picks the league: the announced next league once it has started (settings),
   else poe.ninja's current one, checked at most hourly with a conditional request;
2. loads the newly published hours (`live.sync_live`, which records the run);
3. rebuilds the launch picks when a league's launch fortnight has just completed;
4. publishes what changed to the site's Postgres (`site.publish`), in one transaction.

A pass with nothing new writes nothing, so visitors' caches stay valid.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from exiledbroker.config import Settings
from exiledbroker.ingest import core_pool, reference
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest.http import PoliteClient
from exiledbroker.ingest.live import LiveStatus, sync_live
from exiledbroker.services import launch_picks
from exiledbroker.storage import db, site

LEAGUES_MAX_AGE = timedelta(hours=1)  # a new league must be picked up within the hour


class EmptyVolume(RuntimeError):
    """The pipeline's database has no history: seed the volume instead of fetching it."""


@dataclass
class PipelineResult:
    league: str
    live: LiveStatus
    picks_rebuilt: bool
    published: site.PublishResult | None

    def __str__(self) -> str:
        parts = [str(self.live)]
        if self.picks_rebuilt:
            parts.append("Launch picks rebuilt.")
        if self.published is None:
            parts.append("Not published (no EB_PUBLISH_URL).")
        elif self.published.changed:
            p = self.published
            parts.append(
                f"Published: +{p.hours_added} / -{p.hours_removed} hour(s)"
                + (", picks" if p.picks else "")
                + "."
            )
        else:
            parts.append("Nothing new to publish.")
        return " ".join(parts)


def pick_league(client: PoliteClient, settings: Settings, now: datetime) -> str:
    """The announced next league once it has started, else poe.ninja's current
    challenge league (its first listed), from the copy checked within the hour."""
    start = settings.next_league_start
    if settings.next_league and start:
        start = start if start.tzinfo else start.replace(tzinfo=UTC)
        if now >= start:
            return settings.next_league
    url = f"{settings.poe_ninja_base_url}/poe1/api/economy/leagues"
    with db.session(settings.db_path) as con:
        db.init_schema(con)
        leagues = reference.fetch_if_changed(
            con, client, core_pool.LEAGUES_KEY, url, json.loads, LEAGUES_MAX_AGE
        ).value
    return leagues[0]["id"]


def _has_history(settings: Settings) -> bool:
    if not settings.db_path.exists():
        return False
    with db.session(settings.db_path, read_only=True) as con:
        has = db.scalar(
            con,
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'exchange_hour_loaded'",
        )
        return bool(has) and db.scalar(con, "SELECT count(*) FROM exchange_hour_loaded") > 0


def _picks_stale(settings: Settings) -> list[str] | None:
    """The reference leagues if the stored picks were built from others (a league's
    fortnight completed since), else None."""
    with db.session(settings.db_path) as con:
        leagues = launch_picks.complete_leagues(con)[: launch_picks.REFERENCE_LEAGUES]
        built = db.rows(con, "SELECT leagues FROM launch_window LIMIT 1")
    if not leagues:
        return None
    return leagues if not built or built[0][0] != ",".join(leagues) else None


def run(
    client: PoliteClient,
    settings: Settings,
    league: str | None = None,
    now: datetime | None = None,
    lookback_hours: int = 14 * 24,
) -> PipelineResult:
    """One hourly pass. `now` replays a moment (tests, the Railway simulation)."""
    if settings.database_url:
        raise ValueError(
            "The pipeline writes its own DuckDB; set EB_PUBLISH_URL (not EB_DATABASE_URL) "
            "to the site's Postgres."
        )
    if not _has_history(settings):
        raise EmptyVolume(
            f"No history in {settings.db_path}. Seed the volume with the research database "
            "and raw pages (deploy/railway-sim/seed.sh) rather than fetching it all from GGG."
        )
    moment = now or datetime.now(UTC)
    name = league or pick_league(client, settings, moment)
    status = sync_live(client, settings, name, lookback_hours, now=now, earliest=cx.HISTORY_START)
    rebuilt = False
    if (refs := _picks_stale(settings)) is not None:
        with db.session(settings.db_path) as con:
            launch_picks.build(con, refs)
        rebuilt = True
    published = None
    if settings.publish_url and status.state in ("updated", "unchanged"):
        import psycopg

        with (
            db.session(settings.db_path, read_only=True) as duck,
            psycopg.connect(settings.publish_url, autocommit=True) as pg,
        ):
            published = site.publish(duck, pg, name)
    return PipelineResult(name, status, rebuilt, published)
