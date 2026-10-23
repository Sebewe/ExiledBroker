"""GGG's public Currency Exchange history: one page per hour, across all leagues.

`GET <base>/<unix hour>` returns that hour's markets and `next_change_id = hour + 3600`.
The current (unfinished) hour returns no markets and points back at itself. A
timestamp before the history starts silently returns the first page instead, so
every page is checked against the hour we asked for.

Pages never change, so each is fetched once and kept gzipped, either on disk under
data/raw/ggg/currency_exchange/<hour>.json.gz (local: the whole history; files are
written to a temporary path and renamed, so a page on disk is always complete) or in
the site database's `exchange_page` table (`EB_EXCHANGE_PAGES=database`, the hosted
pipeline: only the live window's pages, see `prune_pages`).
"""

import gzip
import hashlib
import json
import os
from collections import OrderedDict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from exiledbroker.config import Settings
from exiledbroker.ingest.files import tmp_path_for
from exiledbroker.ingest.http import PoliteClient
from exiledbroker.normalize.leagues import league_id
from exiledbroker.storage import db

HOUR = 3600
GAME = "poe1"
# The exchange (and its history) started with Settlers.
HISTORY_START = datetime(2024, 7, 26, 20, tzinfo=UTC)
# How long after a league's first dump date we look for its first exchange hour.
LAUNCH_SEARCH_HOURS = 72


class EndOfStream(Exception):
    """The requested hour hasn't finished yet."""


def to_ts(dt: datetime) -> int:
    return int(dt.timestamp()) // HOUR * HOUR


def from_ts(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, UTC)


def page_path(settings: Settings, ts: int) -> Path:
    return settings.exchange_raw_dir / f"{ts}.json.gz"


def _in_db(settings: Settings) -> bool:
    return settings.exchange_pages == "database"


# Pages this process wrote to or read from the database, gzipped, by their MD5: a
# pass reads back the pages it just fetched, which would otherwise cross the network
# again. A read asks the database for the stored page's MD5 (computed there), so only
# the exact page the database holds is served from memory. Oldest out first.
_bodies: OrderedDict[str, bytes] = OrderedDict()
BODIES_MAX_BYTES = 32_000_000


def _remember(body: bytes) -> None:
    _bodies[hashlib.md5(body).hexdigest()] = body
    while sum(map(len, _bodies.values())) > BODIES_MAX_BYTES and len(_bodies) > 1:
        _bodies.popitem(last=False)


def has_page(settings: Settings, ts: int) -> bool:
    if _in_db(settings):
        with db.site_session(settings, read_only=False) as con:
            return bool(db.rows(con, "SELECT 1 FROM exchange_page WHERE hour = ?", [ts]))
    return page_path(settings, ts).exists()


def read_page(settings: Settings, ts: int) -> dict | None:
    if _in_db(settings):
        with db.site_session(settings, read_only=False) as con:
            digest = db.rows(con, "SELECT md5(body) FROM exchange_page WHERE hour = ?", [ts])
            if not digest:
                return None
            body = _bodies.get(digest[0][0])
            if body is None:
                body = bytes(db.scalar(con, "SELECT body FROM exchange_page WHERE hour = ?", [ts]))
                _remember(body)
        return json.loads(gzip.decompress(body))
    path = page_path(settings, ts)
    if not path.exists():
        return None
    with gzip.open(path, "rt") as f:
        return json.load(f)


def write_page(settings: Settings, ts: int, page: dict) -> None:
    if _in_db(settings):
        body = gzip.compress(json.dumps(page).encode())
        with db.site_session(settings, read_only=False) as con:
            db.execute(
                con,
                "INSERT INTO exchange_page (hour, body) VALUES (?, ?) ON CONFLICT (hour) DO NOTHING",
                [ts, body],
            )
        _remember(body)
        return
    path = page_path(settings, ts)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_path_for(path)
    with gzip.open(tmp, "wt") as f:
        json.dump(page, f)
    os.replace(tmp, path)


def page_count(settings: Settings) -> int:
    if _in_db(settings):
        with db.site_session(settings, read_only=False) as con:
            return db.scalar(con, "SELECT count(*) FROM exchange_page")
    d = settings.exchange_raw_dir
    return sum(1 for _ in d.glob("*.json.gz")) if d.exists() else 0


def prune_pages(settings: Settings, keep: list[int]) -> int:
    """Delete stored pages outside `keep` (the live window's hours), so the database
    holds only what a rebuild would re-read. Pages on disk are never pruned: locally
    they're the history. Returns the number deleted."""
    if not _in_db(settings) or not keep:
        return 0
    # The window is one or two runs of hours (the launch days, then the latest ones).
    runs: list[list[int]] = []
    for ts in sorted(keep):
        if runs and ts == runs[-1][1] + HOUR:
            runs[-1][1] = ts
        else:
            runs.append([ts, ts])
    inside = " OR ".join("hour BETWEEN ? AND ?" for _ in runs)
    with db.site_session(settings, read_only=False) as con:
        before = db.scalar(con, "SELECT count(*) FROM exchange_page")
        db.execute(
            con, f"DELETE FROM exchange_page WHERE NOT ({inside})", [t for r in runs for t in r]
        )
        return before - db.scalar(con, "SELECT count(*) FROM exchange_page")


def fetch_page(client: PoliteClient, settings: Settings, ts: int) -> dict:
    """Return the page for hour `ts`, from disk if we already have it."""
    cached = read_page(settings, ts)
    if cached is not None:
        return cached
    page = client.get_json(f"{settings.exchange_base_url}/{ts}")
    nxt = page.get("next_change_id")
    if nxt == ts:
        raise EndOfStream(ts)
    if nxt != ts + HOUR:
        raise ValueError(f"exchange returned next_change_id={nxt} for hour {ts}")
    write_page(settings, ts, page)
    return page


def league_in_page(page: dict, league_name: str) -> bool:
    return any(m["league"] == league_name for m in page.get("markets", ()))


@dataclass
class Window:
    league_name: str
    launched_at: datetime
    end: datetime  # exclusive
    start: datetime | None = None  # defaults to the launch; later for a live window
    # A live window also keeps the league's first days, so launch analysis still works.
    keep_launch_days: float = 0

    @property
    def hours(self) -> list[int]:
        end = to_ts(self.end)
        hours = set(range(to_ts(self.start or self.launched_at), end, HOUR))
        if self.keep_launch_days:
            launch = to_ts(self.launched_at)
            hours |= set(
                range(launch, min(end, launch + int(self.keep_launch_days * 24) * HOUR), HOUR)
            )
        return sorted(hours)


@dataclass
class SyncResult:
    window: Window | None
    fetched: int
    cached: int
    reached_end: bool


def sync_league(
    client: PoliteClient,
    settings: Settings,
    league_name: str,
    first_dump_date: date,
    days: int,
    progress: Callable[[int, int, int], None] | None = None,
) -> SyncResult:
    """Fetch the first `days` days of hourly pages for a league. Safe to interrupt."""
    fetched = cached = 0

    def get(ts: int) -> dict:
        nonlocal fetched, cached
        if has_page(settings, ts):
            cached += 1
        else:
            fetched += 1
        return fetch_page(client, settings, ts)

    # 1. Find the launch hour: the first hour the league trades on the exchange.
    search_from = max(
        datetime.combine(first_dump_date, datetime.min.time(), UTC) - timedelta(hours=12),
        HISTORY_START,
    )
    launched_at = None
    start_ts = to_ts(search_from)
    try:
        for ts in range(start_ts, start_ts + LAUNCH_SEARCH_HOURS * HOUR, HOUR):
            if league_in_page(get(ts), league_name):
                launched_at = from_ts(ts)
                break
    except EndOfStream:
        return SyncResult(None, fetched, cached, reached_end=True)
    if launched_at is None:
        raise LookupError(f"{league_name} not found on the exchange near {first_dump_date}")

    # 2. Fetch every hour of the window.
    window = Window(league_name, launched_at, launched_at + timedelta(days=days))
    hours = window.hours
    try:
        for i, ts in enumerate(hours, 1):
            get(ts)
            if progress:
                progress(i, len(hours), fetched)
    except EndOfStream:
        window.end = from_ts(ts)
        return SyncResult(window, fetched, cached, reached_end=True)
    return SyncResult(window, fetched, cached, reached_end=False)


def market_rows(settings: Settings, league_name: str, hours: list[int]) -> Iterator[dict]:
    """The league's markets in the given hours (pages on disk), one dict per market."""
    lid = league_id(GAME, league_name)
    for ts in hours:
        page = read_page(settings, ts)
        if page is None:
            continue
        hour = from_ts(ts).replace(tzinfo=None)
        for m in page["markets"]:
            if m["league"] != league_name:
                continue
            a, b = m["market_pair"]
            row = {"league_id": lid, "hour": hour, "market_id": m["market_id"], "a": a, "b": b}
            for field in (
                "volume_traded",
                "lowest_stock",
                "highest_stock",
                "lowest_ratio",
                "highest_ratio",
            ):
                values = m.get(field) or {}
                row[f"{field}_a"] = values.get(a)
                row[f"{field}_b"] = values.get(b)
            yield row


MARKET_SCHEMA = {
    "league_id": pl.String,
    "hour": pl.Datetime,
    "market_id": pl.String,
    "a": pl.String,
    "b": pl.String,
    **{
        f"{field}_{side}": pl.Int64
        for field in (
            "volume_traded",
            "lowest_stock",
            "highest_stock",
            "lowest_ratio",
            "highest_ratio",
        )
        for side in ("a", "b")
    },
}


def write_markets(settings: Settings, league_name: str, hours: list[int], out: Path) -> int:
    """Write the league's markets for `hours` to a Parquet file; returns the row count.

    Only the hours being loaded are read, so an hourly live update reads one page."""
    out.parent.mkdir(parents=True, exist_ok=True)
    df = pl.DataFrame(
        list(market_rows(settings, league_name, hours)),
        schema=MARKET_SCHEMA,
        strict=False,
    )
    tmp = tmp_path_for(out)
    df.write_parquet(tmp)
    os.replace(tmp, out)
    return df.height


# --- Live ----------------------------------------------------------------------------


def current_hour(now: datetime | None = None) -> int:
    """The hour being traded now; it's published once it ends."""
    return to_ts(now or datetime.now(UTC))


def latest_published_hour(
    client: PoliteClient, settings: Settings, now: datetime | None = None
) -> int | None:
    """The newest finished hour GGG has published: usually the previous hour, or the one
    before during the few minutes after an hour ends."""
    current = current_hour(now)
    for ts in (current - HOUR, current - 2 * HOUR):
        try:
            fetch_page(client, settings, ts)
            return ts
        except EndOfStream:
            continue
    return None


def find_launch(
    client: PoliteClient,
    settings: Settings,
    league_name: str,
    now: datetime | None = None,
    earliest: datetime = HISTORY_START,
) -> datetime | None:
    """First hour a league appears on the exchange, by binary search over history.

    A league is absent before its launch and present every hour after, so this needs
    about a dozen pages (each cached) to search two years. None if it hasn't launched
    or nothing has been published for it yet."""
    lo = to_ts(earliest)
    last = latest_published_hour(client, settings, now)
    if (
        last is None
        or last < lo
        or not league_in_page(fetch_page(client, settings, last), league_name)
    ):
        return None
    # The answer is in [lo, hi] and the league is present at hi. Halve until they meet.
    hi = last
    while lo < hi:
        mid = lo + (hi - lo) // HOUR // 2 * HOUR  # always < hi, so the range shrinks
        if league_in_page(fetch_page(client, settings, mid), league_name):
            hi = mid
        else:
            lo = mid + HOUR
    return from_ts(lo)


def sync_recent(
    client: PoliteClient,
    settings: Settings,
    league_name: str,
    launched_at: datetime,
    lookback_hours: int = 14 * 24,
    now: datetime | None = None,
    progress: Callable[[int, int, int], None] | None = None,
    keep_launch_days: float = 14,
    only: Callable[[list[int]], list[int]] | None = None,
) -> SyncResult:
    """Fetch the latest published hours of a running league: from `lookback_hours` ago
    (or the launch, if later) up to the hour being traded now, plus its first
    `keep_launch_days` days. Run it every hour: only newly published hours are fetched.

    `only` narrows which of the window's hours to fetch (e.g. those not loaded yet);
    by default every hour whose page isn't on disk is fetched."""
    end_ts = current_hour(now)
    start_ts = max(to_ts(launched_at), end_ts - lookback_hours * HOUR)
    window = Window(
        league_name,
        launched_at,
        from_ts(end_ts),
        start=from_ts(start_ts),
        keep_launch_days=keep_launch_days,
    )
    fetched = cached = 0
    hours = only(window.hours) if only else window.hours
    try:
        for i, ts in enumerate(hours, 1):
            if has_page(settings, ts):
                cached += 1
            else:
                fetched += 1
            fetch_page(client, settings, ts)
            if progress:
                progress(i, len(hours), fetched)
    except EndOfStream:
        # The last hour isn't published yet (GGG adds a few minutes' delay).
        window.end = from_ts(ts)
        return SyncResult(window, fetched, cached, reached_end=True)
    return SyncResult(window, fetched, cached, reached_end=False)
