"""`eb preview build`: the pre-launch preview's snapshot (docs/preview.md), built from
pages already on disk, with no request to anyone.

A past league is replayed into a throwaway DuckDB beside the research database: the
live loader (`ingest.live.sync_live`) runs as the worker would have at the end of each
chosen day (`now = launch + day × 24 h`), with a client that refuses every request, so
every page must come from disk (`currency_exchange.fetch_page`). After each day the
site's services answer as the API would have then, and their answers are stored, one
document per key (preview/snapshot.py). A last load to NEXT_DAYS gives the reveal's
documents: each item's series to then, and whether each recap trade kept paying.

What the services read besides the league's hours is copied from the research
database, rewound: the reference data (names, core pool, card tiers: today's), and
the Launch history and Price check's paths without the replayed league or any later
one (the picks and the medians are rebuilt from the rest), so the preview never knows
what happened next. The fitted constants (Price check's band, the sell helper's) stay
as fitted: they're a few numbers across every league, not the league's own prices.

The snapshot then replaces `preview_snapshot` in the research database, in one
transaction; `eb site seed` copies it to the site."""

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
from pydantic import TypeAdapter

from exiledbroker.api import models as m
from exiledbroker.api.deps import records
from exiledbroker.config import Settings
from exiledbroker.ingest.http import PoliteClient
from exiledbroker.ingest.live import sync_live
from exiledbroker.preview import snapshot
from exiledbroker.services import (
    cross_market,
    divination,
    launch_picks,
    live,
    missed,
    price_check,
    price_paths,
)
from exiledbroker.services.missed import BUFFER
from exiledbroker.storage import db

HOURLY = "ggg-exchange-hourly"
NEXT_HOURS = 24  # recap-next: the hours after the chosen day that are judged
STILL_FROM = 18  # still paid: paid in any of hours 19-24 after
# Copied from the research database into the replay (its own league's rows are loaded).
REFERENCE = ["reference_data"]
REWOUND = {  # rows of the replayed league, or a later one, are left out
    "launch_history": "league_start",
    "price_path_league": "league_start",
}
KEPT = ["price_path_constant", "sell_helper_report"]


class OfflineError(RuntimeError):
    """The build asked for something that isn't stored (a page not on disk)."""


class OfflineClient(PoliteClient):
    """A client that makes no request. Reference checks answer "not modified" (the
    copy stored in the replay stands); anything else, an exchange page that isn't on
    disk above all, raises."""

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.refused: list[str] = []

    def get_if_changed(self, url: str, etag=None, last_modified=None) -> None:
        return None

    def _get(self, url: str, headers=None):
        self.refused.append(url)
        hour = url.rsplit("/", 1)[-1]
        what = f"the exchange page for hour {hour}" if hour.isdigit() else url
        raise OfflineError(f"{what} isn't on disk (the build makes no requests)")

    def stream(self, url: str, headers):
        self._get(url)


@dataclass
class BuildResult:
    league: str
    version: str
    documents: int
    bytes: int  # stored (gzipped)
    items: int  # Price check items with a reveal series
    seconds: float
    requests: int = 0
    skipped: list[str] = field(default_factory=list)  # items with no series at the end

    def __str__(self) -> str:
        skipped = f"; {len(self.skipped)} item(s) had no series at the end" if self.skipped else ""
        return (
            f"Preview of {self.league}: {self.documents:,} documents, "
            f"{self.bytes / 1024:,.0f} kB gzipped, {self.items} items, {self.requests} requests, "
            f"{self.seconds:,.0f} s{skipped}. Version {self.version}."
        )


def _doc(key: str, out: Any) -> Any:
    """A service's answer as the API sends it: checked against the key's model, JSON."""
    rows = records(out) if isinstance(out, pl.DataFrame) else out
    return snapshot.decode(snapshot.encode(key, rows))


def _iso(at: datetime) -> str:
    return f"{at:%Y-%m-%dT%H:%M:%S}Z"


def _target(con, league: str) -> datetime:
    rows = db.rows(con, "SELECT launched_at FROM league WHERE name = ?", [league])
    if not rows:
        raise LookupError(f"{league} isn't in the local database")
    if rows[0][0] is None:
        raise LookupError(f"{league} has no launch hour (load it with `eb exchange sync`)")
    return rows[0][0].replace(tzinfo=None)


def _columns(con, table: str) -> list[str]:
    return [r[0] for r in db.rows(con, f"DESCRIBE {table}")]


def _prepare(research: Settings, replay: Settings, league: str, launched: datetime) -> None:
    """The replay's database: the schema, the league registered with its launch, and
    the research tables the services read, rewound to before the league."""
    with db.session(replay.db_path) as con:
        db.init_schema(con)
        con.execute(f"ATTACH '{research.db_path}' AS research (READ_ONLY)")
        try:
            found = {
                r[0]
                for r in db.rows(
                    con,
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_catalog = 'research'",
                )
            }
            cols = _columns(con, "league")
            names = ", ".join(cols)
            con.execute(
                f"INSERT INTO league ({names}) SELECT {names} FROM research.league WHERE name = ?",
                [league],
            )
            con.execute(
                "UPDATE league SET exchange_tracked = TRUE, launched_at = ? WHERE name = ?",
                [launched, league],
            )
            for table in [*REFERENCE, *REWOUND, *KEPT]:
                if table not in found:
                    continue  # an older local copy: never built
                names = ", ".join(_columns(con, table))
                where, params = "", []
                if table in REWOUND:
                    where = f"WHERE league <> ? AND {REWOUND[table]} < ?"
                    params = [league, launched]
                con.execute(
                    f"INSERT INTO {table} ({names}) SELECT {names} FROM research.{table} {where}",
                    params,
                )
        finally:
            con.execute("DETACH research")
        if not db.scalar(con, "SELECT count(*) FROM reference_data"):
            raise LookupError("no reference data in the local database (run `eb live sync` once)")


def _load(client, replay: Settings, league: str, launched: datetime, hours: int) -> datetime:
    """Load the league as the worker had it `hours` after launch; its last hour."""
    end = launched.replace(tzinfo=UTC) + timedelta(hours=hours)
    status = sync_live(client, replay, league, now=end + timedelta(minutes=10))
    want = end - timedelta(hours=1)
    if status.latest_hour != want:
        raise OfflineError(
            f"{league} at {hours} h: latest hour {status.latest_hour}, expected {want} "
            f"({status.state})"
        )
    return want.replace(tzinfo=None)


def _rebuild_history(con) -> None:
    """The picks and Price check's medians, from the rewound history only."""
    launch_picks.build(con)
    price_paths.rebuild(con)


def _entries(index: dict) -> dict[str, dict]:
    """Price check's items by id, as the item route hands them to the service."""
    checked = TypeAdapter(m.PriceCheckIndex).validate_python(index)
    return {x.item_id: x.model_dump() for x in checked.items}


def _day(con, settings: Settings, league: str, day: int) -> tuple[dict, dict]:
    """The site on `day`: its documents, and the league as /api/status listed it."""
    docs: dict[str, Any] = {}
    row = next(r for r in records(live.live_leagues(con)) if r["name"] == league)
    docs[snapshot.day_key(day, "missed")] = _doc(
        snapshot.day_key(day, "missed"), missed.missed(con, league)
    )
    key = snapshot.day_key(day, "price-check")
    index = docs[key] = _doc(key, price_check.index(con, league, settings))
    for item_id, entry in _entries(index).items():
        key = snapshot.day_key(day, "price-check", item_id)
        docs[key] = _doc(key, price_check.item(con, league, item_id, entry))
    key = snapshot.day_key(day, "launch-picks")
    docs[key] = _doc(key, launch_picks.launch_board(con))
    league_row = json.loads(TypeAdapter(m.LiveLeague).dump_json(m.LiveLeague(**row)))
    return docs, league_row


def _hour(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=None)


def _outcome(kind, item_id, paid_by_hour: dict, cutoff: datetime, known: int, direction=None):
    paid = [paid_by_hour.get(cutoff + timedelta(hours=k)) for k in range(1, known + 1)]
    return {
        "kind": kind,
        "item_id": item_id,
        "direction": direction,
        "paid": paid,
        "paid_hours": sum(1 for p in paid if p),
        "traded_hours": sum(1 for p in paid if p is not None),
        "next_hour_paid": paid[0] if paid else None,
        "still_paid": any(paid[STILL_FROM:]) if known >= NEXT_HOURS else None,
    }


def recap_next(con, league: str, windows: list[dict], last_hour: datetime) -> dict | None:
    """Did each of a day's recap trades (`windows`: its d{day}/missed) keep paying,
    hour by hour, over the next NEXT_HOURS (as far as `last_hour`, the replay's last)?
    Each hour is judged by the recap's own test. None for a recap with no look-backs."""
    if not windows:
        return None
    cutoff = _hour(windows[0]["latest_hour"])
    known = max(0, min(NEXT_HOURS, int((last_hour - cutoff).total_seconds() // 3600)))
    trades: dict[tuple, dict] = {}
    for w in windows:
        for loop in w["loops"]:
            key = ("loop", loop["item_id"], loop["direction"])
            if key in trades:
                continue
            hours = cross_market.hourly(
                con, [league], [loop["item_id"]], direction=loop["direction"], since=cutoff
            )
            by_hour = {r["observed_at"]: r["edge"] > BUFFER for r in hours.iter_rows(named=True)}
            trades[key] = _outcome(
                "loop", loop["item_id"], by_hour, cutoff, known, loop["direction"]
            )
        for card in w["cards"]:
            key = ("card", card["item_id"], None)
            if key in trades:
                continue
            hours = divination.hourly_turn_ins(con, league, [card["item_id"]], since=cutoff)
            hours = hours.drop_nulls("margin") if hours.height else hours
            by_hour = {r["observed_at"]: r["margin"] > 0 for r in hours.iter_rows(named=True)}
            trades[key] = _outcome("card", card["item_id"], by_hour, cutoff, known)
        for flip in w["flips"]:
            key = ("flip", flip["item_id"], None)
            if key in trades:
                continue
            hours = db.frame(
                con,
                "SELECT observed_at, chaos_low, chaos_high FROM price_observation "
                "WHERE league_id = (SELECT id FROM league WHERE name = ?) AND source = ? "
                "AND item_id = ? AND observed_at > ? AND chaos_low IS NOT NULL",
                [league, HOURLY, flip["item_id"], cutoff],
            )
            by_hour = {
                r["observed_at"]: r["chaos_low"] <= flip["bid"] and r["chaos_high"] >= flip["ask"]
                for r in hours.iter_rows(named=True)
            }
            trades[key] = _outcome("flip", flip["item_id"], by_hour, cutoff, known)
    return {
        "latest_hour": windows[0]["latest_hour"],
        "hours": known,
        "trades": list(trades.values()),
    }


def build(
    settings: Settings,
    league: str,
    days: tuple[int, ...] = snapshot.DAYS,
    default_day: int = snapshot.DEFAULT_DAY,
    next_day: int = snapshot.NEXT_DAYS,
    day_hours: int = 24,
    progress: Callable[[str], None] = lambda _: None,
) -> BuildResult:
    """Replay `league` from pages on disk and replace the research database's snapshot.
    `day_hours` is 24 except in tests (the recorded replay is 30 hours long)."""
    days = tuple(sorted(set(days)))
    if not days or days[0] < 1:
        raise ValueError("days are launch days, from 1")
    if default_day not in days:
        raise ValueError(f"the default day ({default_day}) must be one of the days")
    if next_day < days[-1]:
        raise ValueError(f"the reveal's last day ({next_day}) is before day {days[-1]}")
    clock = time.perf_counter()
    research = settings.model_copy(update={"database_url": None, "exchange_pages": "disk"})
    with db.session(research.db_path, read_only=True) as con:
        launched = _target(con, league)
    replay = research.model_copy(update={"db_filename": "preview-build.duckdb"})
    for path in (replay.db_path, replay.db_path.with_name(replay.db_path.name + ".wal")):
        path.unlink(missing_ok=True)
    docs: dict[str, Any] = {}
    manifest_days, recaps, items = [], {}, set()
    with OfflineClient(replay) as client:
        try:
            _prepare(research, replay, league, launched)
            for i, day in enumerate(days):
                last = _load(client, replay, league, launched, day * day_hours)
                with db.session(replay.db_path) as con:
                    if i == 0:  # the loader has named the items the picks list
                        _rebuild_history(con)
                    day_docs, row = _day(con, research, league, day)
                docs.update(day_docs)
                manifest_days.append({"day": day, "league": row})
                recaps[day] = day_docs[snapshot.day_key(day, "missed")]
                items |= set(_entries(day_docs[snapshot.day_key(day, "price-check")]))
                progress(f"day {day}: to {last:%Y-%m-%d %H:00} UTC, {len(day_docs)} documents")
            last = _load(client, replay, league, launched, next_day * day_hours)
            skipped = []
            with db.session(replay.db_path, read_only=True) as con:
                entries = _entries(price_check.index(con, league, research))
                for item_id in sorted(items):
                    if item_id not in entries:
                        skipped.append(item_id)
                        continue
                    doc = price_check.item(con, league, item_id, entries[item_id])
                    key = snapshot.next_key(item_id)
                    docs[key] = _doc(
                        key, {k: doc[k] for k in ("item_id", "name", "unit", "series")}
                    )
                for day, windows in recaps.items():
                    if (doc := recap_next(con, league, windows, last)) is not None:
                        key = snapshot.day_key(day, "recap-next")
                        docs[key] = _doc(key, doc)
            progress(f"day {next_day} (the reveal): to {last:%Y-%m-%d %H:00} UTC")
            requests = client.requests
        finally:
            for path in (replay.db_path, replay.db_path.with_name(replay.db_path.name + ".wal")):
                path.unlink(missing_ok=True)

    built_at = datetime.now(UTC)
    digest = hashlib.sha1()
    for key in sorted(docs):
        digest.update(key.encode() + snapshot.encode(key, docs[key]))
    version = f"{built_at:%Y%m%d%H%M%S}-{digest.hexdigest()[:8]}"
    docs[snapshot.MANIFEST] = {
        "league": league,
        "launched_at": _iso(launched),
        "days": manifest_days,
        "default_day": default_day,
        "next_until": _iso(last),
        "built_at": built_at,
        "version": version,
    }
    with db.session(research.db_path) as con:
        db.init_schema(con)
        con.execute("BEGIN TRANSACTION")
        try:
            snapshot.clear(con)
            snapshot.put(con, docs, built_at)
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        size = db.scalar(con, f"SELECT sum(octet_length(body)) FROM {snapshot.TABLE}")
    return BuildResult(
        league,
        version,
        len(docs),
        int(size or 0),
        len(items) - len(skipped),
        time.perf_counter() - clock,
        requests,
        skipped,
    )
