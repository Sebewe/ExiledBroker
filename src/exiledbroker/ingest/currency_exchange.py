"""GGG's public Currency Exchange history: one page per hour, across all leagues.

`GET <base>/<unix hour>` returns that hour's markets and `next_change_id = hour + 3600`.
The current (unfinished) hour returns no markets and points back at itself. A
timestamp before the history starts silently returns the first page instead, so
every page is checked against the hour we asked for.

Pages never change, so each is fetched once and kept gzipped under
data/raw/ggg/currency_exchange/<hour>.json.gz. Files are written to a temporary
path and renamed, so a page on disk is always complete.
"""

import gzip
import json
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from exiledbroker.config import Settings
from exiledbroker.ingest.files import read_json, tmp_path_for, write_json_atomic
from exiledbroker.ingest.http import PoliteClient
from exiledbroker.normalize.leagues import league_id, slugify

HOUR = 3600
GAME = "poe1"
# Bump when the Parquet layout changes so existing files are rebuilt.
EXTRACT_VERSION = 1
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


def read_page(settings: Settings, ts: int) -> dict | None:
    path = page_path(settings, ts)
    if not path.exists():
        return None
    with gzip.open(path, "rt") as f:
        return json.load(f)


def write_page(settings: Settings, ts: int, page: dict) -> None:
    path = page_path(settings, ts)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_path_for(path)
    with gzip.open(tmp, "wt") as f:
        json.dump(page, f)
    os.replace(tmp, path)


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

    @property
    def hours(self) -> range:
        return range(to_ts(self.start or self.launched_at), to_ts(self.end), HOUR)


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
        if page_path(settings, ts).exists():
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


def processed_path(settings: Settings, league_name: str) -> Path:
    return settings.exchange_processed_dir / f"{slugify(league_name)}.parquet"


def sidecar_path(settings: Settings, league_name: str) -> Path:
    path = processed_path(settings, league_name)
    return path.with_name(path.name + ".meta.json")


def _market_rows(settings: Settings, window: Window) -> Iterator[dict]:
    lid = league_id(GAME, window.league_name)
    for ts in window.hours:
        page = read_page(settings, ts)
        if page is None:
            continue
        hour = from_ts(ts).replace(tzinfo=None)
        for m in page["markets"]:
            if m["league"] != window.league_name:
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


def extract_league(settings: Settings, window: Window) -> bool:
    """Flatten the league's markets into one Parquet file. Returns False if up to date."""
    present = [ts for ts in window.hours if page_path(settings, ts).exists()]
    fingerprint = {
        "extract_version": EXTRACT_VERSION,
        "league": window.league_name,
        "launched_at": window.launched_at.isoformat(),
        "hours": len(present),
        "first": present[0] if present else None,
        "last": present[-1] if present else None,
    }
    out = processed_path(settings, window.league_name)
    if out.exists() and read_json(sidecar_path(settings, window.league_name)) == fingerprint:
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_path_for(out)
    try:
        df = pl.DataFrame(list(_market_rows(settings, window)), infer_schema_length=None)
        df.write_parquet(tmp)
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
    write_json_atomic(sidecar_path(settings, window.league_name), fingerprint)
    return True


def extracted_window(settings: Settings, league_name: str) -> Window | None:
    meta = read_json(sidecar_path(settings, league_name))
    if not meta or not meta.get("hours"):
        return None
    return Window(
        league_name,
        datetime.fromisoformat(meta["launched_at"]),
        from_ts(meta["last"] + HOUR),
        start=from_ts(meta["first"]),
    )


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
) -> SyncResult:
    """Fetch the latest published hours of a running league: from `lookback_hours` ago
    (or the launch, if later) up to the hour being traded now. Run it every hour: only
    the newly published hours are fetched."""
    end_ts = current_hour(now)
    start_ts = max(to_ts(launched_at), end_ts - lookback_hours * HOUR)
    window = Window(league_name, launched_at, from_ts(end_ts), start=from_ts(start_ts))
    fetched = cached = 0
    hours = window.hours
    try:
        for i, ts in enumerate(hours, 1):
            if page_path(settings, ts).exists():
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
