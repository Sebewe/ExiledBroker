"""Live mode: keep a running league's latest published exchange hours loaded.

One update (`sync_live`) finds the league's launch hour if it isn't known yet,
fetches the hours published since the last update (within `lookback_hours`), and
reloads the league. `eb live watch` runs it shortly after every hour.
"""

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest import item_names
from exiledbroker.ingest import poe_ninja_dumps as dumps_mod
from exiledbroker.ingest.core_pool import refresh_pool_if_stale
from exiledbroker.ingest.http import PoliteClient
from exiledbroker.normalize import exchange_loader
from exiledbroker.normalize.leagues import CHALLENGE
from exiledbroker.storage import db
from exiledbroker.storage import dumps as dump_store


@dataclass
class LiveStatus:
    league: str
    state: str  # "updated" | "unchanged" | "not_running" | "no_hours"
    latest_hour: datetime | None = None
    fetched: int = 0
    rows: int = 0  # the league's hourly rows after the update
    hours_added: int = 0
    hours_removed: int = 0
    rows_added: int = 0

    def __str__(self) -> str:
        if self.state == "not_running":
            return (
                f"{self.league}: not trading in the latest published hour, so it isn't "
                "running (or hasn't launched). For an ended league use `eb exchange sync`."
            )
        if self.state == "no_hours":
            return f"{self.league}: no published hours in the window yet."
        latest = f"{self.latest_hour:%Y-%m-%d %H:00} UTC" if self.latest_hour else "–"
        loaded = (
            "unchanged"
            if self.state == "unchanged"
            else f"+{self.hours_added} hour(s), -{self.hours_removed} hour(s), "
            f"+{self.rows_added:,} rows ({self.rows:,} hourly rows in total)"
        )
        return (
            f"{self.league}: latest published hour {latest}; "
            f"{self.fetched} new hour(s) fetched; {loaded}."
        )


def current_league(client: PoliteClient, settings: Settings) -> str:
    """poe.ninja's current challenge league (its first listed league)."""
    leagues = client.get_json(f"{settings.poe_ninja_base_url}/poe1/api/economy/leagues")
    return leagues[0]["id"]


def _stored_names(con) -> dict:
    try:
        return item_names.load_base_items(con)
    except LookupError:  # a new database: RePoE isn't stored yet
        return {}


def _unknown_ids(page: dict, league: str, names: dict) -> set[str]:
    """Items the league trades in `page` that RePoE doesn't name (yet)."""
    traded = {x for m in page["markets"] if m["league"] == league for x in m["market_pair"]}
    return traded - set(names) if names else set()


def _known_launch(settings: Settings, league_id: str) -> datetime | None:
    with db.site_writer(settings) as con:
        rows = db.rows(con, "SELECT launched_at FROM league WHERE id = ?", [league_id])
    return rows[0][0].replace(tzinfo=UTC) if rows and rows[0][0] else None


def _register(settings: Settings, name: str, launched_at: datetime) -> None:
    info = dumps_mod.DumpInfo(name, "", launched_at.date(), None, CHALLENGE)
    with db.site_writer(settings) as con:
        dump_store.upsert_leagues(con, [info])
        con.execute(
            "UPDATE league SET launched_at = ?, exchange_tracked = TRUE WHERE id = ?",
            [launched_at.replace(tzinfo=None), info.league_id],
        )


RUN_HISTORY = timedelta(days=90)


def _record_run(
    settings: Settings,
    lid: str,
    started_at: datetime,
    seconds: float,
    status: LiveStatus | None,
    requests: int,
    bytes_received: int,
    not_modified: int,
    error: str | None = None,
) -> None:
    """Write the update's ingest_run row, and drop rows older than RUN_HISTORY."""
    s = status
    with db.site_writer(settings) as con:
        con.execute(
            "INSERT INTO ingest_run VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT DO NOTHING",
            [
                lid,
                started_at,
                seconds,
                s.state if s else "failed",
                s.latest_hour.replace(tzinfo=None) if s and s.latest_hour else None,
                s.fetched if s else None,
                requests,
                bytes_received,
                not_modified,
                s.hours_added if s else None,
                s.hours_removed if s else None,
                s.rows_added if s else None,
                s.rows if s else None,
                error,
            ],
        )
        con.execute("DELETE FROM ingest_run WHERE started_at < ?", [started_at - RUN_HISTORY])


def sync_live(
    client: PoliteClient,
    settings: Settings,
    league: str,
    lookback_hours: int = 14 * 24,
    now: datetime | None = None,
    earliest: datetime = cx.HISTORY_START,
    force: bool = False,
) -> LiveStatus:
    """One live update for a running league. Safe to interrupt and to repeat.
    Each update, failed or not, is recorded in ingest_run.

    `force` rebuilds the league's rows from the window's pages, e.g. after the core pool
    gains items. Pages on disk are reused; missing ones are fetched, so on a wiped disk
    (the hosted worker) it re-fetches the whole window."""
    lid = dumps_mod.league_id(cx.GAME, league)
    started_at = datetime.now(UTC).replace(tzinfo=None)
    clock = time.perf_counter()
    before = (client.requests, client.bytes_received, client.not_modified)
    status, error = None, None
    try:
        status = _sync_live(client, settings, league, lookback_hours, now, earliest, force)
        return status
    except BaseException as e:  # Ctrl-C too: the run is recorded as failed
        error = f"{type(e).__name__}: {e}"[:500]
        raise
    finally:
        try:
            _record_run(
                settings,
                lid,
                started_at,
                time.perf_counter() - clock,
                status,
                client.requests - before[0],
                client.bytes_received - before[1],
                client.not_modified - before[2],
                error,
            )
        except Exception:
            if error is None:
                raise  # otherwise keep the update's own error, not the recording's


def _sync_live(
    client: PoliteClient,
    settings: Settings,
    league: str,
    lookback_hours: int,
    now: datetime | None,
    earliest: datetime,
    force: bool = False,
) -> LiveStatus:
    lid = dumps_mod.league_id(cx.GAME, league)
    pages_before = cx.page_count(settings)
    # Only running leagues: an ended league has no recent hours, and loading an empty
    # window would replace its history.
    last = cx.latest_published_hour(client, settings, now)
    latest = cx.fetch_page(client, settings, last) if last is not None else None
    if latest is None or not cx.league_in_page(latest, league):
        return LiveStatus(league, "not_running")
    # Reference data from the database, refreshed only when stale (RePoE weekly, the
    # core pool and card tiers daily), so a fresh container doesn't re-download it.
    # New league items can trade before RePoE knows them (a league's own currency, new
    # cards): until it does they're checked daily, not weekly, and once their names
    # arrive the league is rebuilt from its stored pages (no requests), so an item
    # never splits into a placeholder and its real name.
    with db.site_writer(settings) as con:
        known = _stored_names(con)
        unknown = _unknown_ids(latest, league, known)
        max_age = item_names.UNKNOWN_MAX_AGE if unknown else item_names.MAX_AGE
        state = item_names.ensure_base_items(client, settings, con, max_age)
        names = item_names.load_base_items(con)
        renamed = state == "downloaded" and exchange_loader.renamed_items(con, names)
        refresh_pool_if_stale(client, con, settings, league=league)
    force = force or bool(renamed)
    launched_at = _known_launch(settings, lid)
    if launched_at is None:
        launched_at = cx.find_launch(client, settings, league, now=now, earliest=earliest)
        if launched_at is None:
            return LiveStatus(league, "not_running")
        _register(settings, league, launched_at)
    # Fetch only the hours the database doesn't have yet (all of them on a rebuild),
    # so a worker whose disk is wiped between runs makes one request per new hour.
    with db.site_writer(settings) as con:
        rebuild = exchange_loader.needs_rebuild(con, lid, force)
        loaded = set() if rebuild else exchange_loader.loaded_hours(con, lid)
    result = cx.sync_recent(
        client,
        settings,
        league,
        launched_at,
        lookback_hours,
        now=now,
        only=lambda hours: [h for h in hours if h not in loaded],
    )
    hours = list(result.window.hours)
    if not hours:
        return LiveStatus(league, "no_hours")
    with db.site_writer(settings) as con:
        con.execute("UPDATE league SET exchange_tracked = TRUE WHERE id = ?", [lid])
        loaded = exchange_loader.load_league(con, settings, result.window, names, force=force)
        if renamed:  # their placeholders no longer stand for anything
            for item_id in renamed:
                con.execute("UPDATE item SET metadata_id = NULL WHERE id = ?", [item_id])
    fetched = cx.page_count(settings) - pages_before
    # Pages kept in the database: only the window's (a rebuild re-reads them).
    cx.prune_pages(settings, hours)
    return LiveStatus(
        league,
        "unchanged" if loaded.skipped else "updated",
        latest_hour=cx.from_ts(hours[-1]),
        # Count every page this update added (the launch search and the latest-hour
        # check fetch pages too, so the sync alone would undercount).
        fetched=fetched,
        rows=loaded.rows,
        hours_added=loaded.hours_added,
        hours_removed=loaded.hours_removed,
        rows_added=loaded.rows_added,
    )
