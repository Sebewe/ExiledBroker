"""Live mode: keep a running league's latest published exchange hours loaded.

One update (`sync_live`) finds the league's launch hour if it isn't known yet,
fetches the hours published since the last update (within `lookback_hours`), and
reloads the league. `eb live watch` runs it shortly after every hour.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

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


def _page_count(settings: Settings) -> int:
    d = settings.exchange_raw_dir
    return sum(1 for _ in d.glob("*.json.gz")) if d.exists() else 0


def current_league(client: PoliteClient, settings: Settings) -> str:
    """poe.ninja's current challenge league (its first listed league)."""
    leagues = client.get_json(f"{settings.poe_ninja_base_url}/poe1/api/economy/leagues")
    return leagues[0]["id"]


def _known_launch(settings: Settings, league_id: str) -> datetime | None:
    if not settings.db_path.exists():
        return None
    with db.session(read_only=True) as con:
        rows = db.rows(con, "SELECT launched_at FROM league WHERE id = ?", [league_id])
    return rows[0][0].replace(tzinfo=UTC) if rows and rows[0][0] else None


def _register(settings: Settings, name: str, launched_at: datetime) -> None:
    info = dumps_mod.DumpInfo(name, "", launched_at.date(), None, CHALLENGE)
    with db.session() as con:
        db.init_schema(con)
        dump_store.upsert_leagues(con, [info])
        con.execute(
            "UPDATE league SET launched_at = ?, exchange_tracked = TRUE WHERE id = ?",
            [launched_at.replace(tzinfo=None), info.league_id],
        )


def sync_live(
    client: PoliteClient,
    settings: Settings,
    league: str,
    lookback_hours: int = 14 * 24,
    now: datetime | None = None,
    earliest: datetime = cx.HISTORY_START,
) -> LiveStatus:
    """One live update for a running league. Safe to interrupt and to repeat."""
    lid = dumps_mod.league_id(cx.GAME, league)
    pages_before = _page_count(settings)
    # Only running leagues: an ended league has no recent hours, and loading an empty
    # window would replace its history.
    last = cx.latest_published_hour(client, settings, now)
    if last is None or not cx.league_in_page(cx.fetch_page(client, settings, last), league):
        return LiveStatus(league, "not_running")
    # Reference data from the database, refreshed only when stale (RePoE weekly, the
    # core pool and card tiers daily), so a fresh container doesn't re-download it.
    with db.session() as con:
        db.init_schema(con)
        item_names.ensure_base_items(client, settings, con)
        names = item_names.load_base_items(con)
        refresh_pool_if_stale(client, con, settings)
    launched_at = _known_launch(settings, lid)
    if launched_at is None:
        launched_at = cx.find_launch(client, settings, league, now=now, earliest=earliest)
        if launched_at is None:
            return LiveStatus(league, "not_running")
        _register(settings, league, launched_at)
    # Fetch only the hours the database doesn't have yet (all of them on a rebuild),
    # so a worker whose disk is wiped between runs makes one request per new hour.
    with db.session(read_only=True) as con:
        rebuild = exchange_loader.needs_rebuild(con, lid)
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
    with db.session() as con:
        db.init_schema(con)
        con.execute("UPDATE league SET exchange_tracked = TRUE WHERE id = ?", [lid])
        loaded = exchange_loader.load_league(con, settings, result.window, names)
    return LiveStatus(
        league,
        "unchanged" if loaded.skipped else "updated",
        latest_hour=cx.from_ts(hours[-1]),
        # Count every page this update added (the launch search and the latest-hour
        # check fetch pages too, so the sync alone would undercount).
        fetched=_page_count(settings) - pages_before,
        rows=loaded.rows,
        hours_added=loaded.hours_added,
        hours_removed=loaded.hours_removed,
        rows_added=loaded.rows_added,
    )
