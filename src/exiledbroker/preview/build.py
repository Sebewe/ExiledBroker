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

from exiledbroker.analysis import backtest as bt
from exiledbroker.analysis import flips
from exiledbroker.api import models as m
from exiledbroker.api.deps import records
from exiledbroker.config import Settings
from exiledbroker.ingest.http import PoliteClient
from exiledbroker.ingest.live import sync_live
from exiledbroker.preview import snapshot
from exiledbroker.services import (
    launch_picks,
    live,
    missed,
    price_check,
    price_paths,
)
from exiledbroker.storage import db

NEXT_HOURS = 24  # recap-next: the hours after the chosen day that are judged
STILL_FROM = 18  # still paid: paid in any of hours 19-24 after
FILL = "touch"  # a fill: some trade went past the order (the recap's chances count so)
FLIP_HOLD = 24  # hours a flip stays listed before it's dumped (the Backtest's: 72)
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


def _outcome(kind, item_id, direction, orders: dict, hours: list[datetime]) -> dict:
    """One trade's next hours from its orders (`orders`: pricing hour -> (filled, pnl in
    Chaos, or None while the sale isn't known)), an hour with no order as None."""
    filled, pnl, paid = [], [], []
    for at in hours:
        f, v = orders.get(at, (None, None))
        filled.append(f)
        pnl.append(v if f else None)
        paid.append(None if f is None or (f and v is None) else bool(f and v > 0))
    return {
        "kind": kind,
        "item_id": item_id,
        "direction": direction,
        "paid": paid,
        "paid_hours": sum(1 for p in paid if p),
        "traded_hours": sum(1 for p in paid if p is not None),
        "next_hour_paid": paid[0] if paid else None,
        "still_paid": any(paid[STILL_FROM:]) if len(hours) >= NEXT_HOURS else None,
        "filled": filled,
        "pnl": pnl,
        "orders": sum(1 for f in filled if f is not None),
        "fills": sum(1 for f in filled if f),
        "profit": sum(v for v in pnl if v is not None),
    }


def _orders(t: pl.DataFrame, keys: list[str], unknown: pl.Expr) -> dict:
    """The orders the backtest placed (`t`, one row per order), by (`keys`..., hour):
    (filled, pnl in Chaos or None where `unknown`)."""
    t = t.with_columns(chaos=pl.when(unknown).then(None).otherwise(pl.col("pnl") * pl.col("rate")))
    return {
        (*(r[k] for k in keys), r["observed_at"]): (bool(r["filled"]), r["chaos"])
        for r in t.iter_rows(named=True)
    }


def _loop_orders(con, league: str, items: list[str], since, until, last_hour) -> dict:
    cross = bt._cross_hours(con, league, items, since)
    hours = cross.filter(pl.col("observed_at") < until).select("observed_at", "item_id")
    sig = pl.concat([hours.with_columns(direction=pl.lit(d)) for d in missed.DIRECTIONS])
    t = bt.loop_order_fills(
        cross, bt._rate(con, league, since), sig, "limit_both", FILL, *missed.LOOP_ORDER, True
    )
    sale_open = pl.col("observed_at") + 2 * bt.H + bt.SELL_WITHIN > last_hour
    unknown = pl.col("filled") & pl.col("sell_at").is_null() & sale_open
    return _orders(t, ["item_id", "direction"], unknown)


def _card_orders(con, league: str, cards: list[str], since, until, last_hour) -> dict:
    marks = ", ".join("?" for _ in cards)
    rewards = db.rows(
        con,
        f"SELECT DISTINCT reward_item_id FROM divination_card "
        f"WHERE item_id IN ({marks}) AND reward_item_id IS NOT NULL",
        cards,
    )
    prices = bt._prices(con, league, [*cards, *(r[0] for r in rewards)], since)
    sig = prices.filter(pl.col("item_id").is_in(cards), pl.col("observed_at") < until)
    t = bt.card_order_fills(
        con,
        prices,
        bt._rate(con, league, since),
        sig,
        "limit_both",
        FILL,
        *missed.CARD_ORDER,
        True,
    )
    sale_open = pl.col("observed_at") + 2 * bt.H + bt.SELL_WITHIN > last_hour
    unknown = pl.col("filled") & pl.col("sell_at").is_null() & sale_open
    return _orders(t, ["item_id"], unknown)


def _flip_orders(con, league: str, items: list[str], since, until, last_hour) -> dict:
    px = flips.chaos_prices(con, league).filter(
        pl.col("item_id").is_in(items), pl.col("observed_at") > since
    )
    sig = flips.candidates(px).filter(pl.col("observed_at") < until)
    rate = bt._rate(con, league, since)
    t = flips.hold(px, rate, sig, FILL, **bt.FLIP, whole_lots=True, max_hold=FLIP_HOLD)
    sale_open = pl.col("observed_at") + (1 + FLIP_HOLD) * bt.H > last_hour
    t = t.with_columns(filled=pl.lit(True), pnl="profit")
    out = _orders(t, ["item_id"], pl.col("dumped") & sale_open)
    for r in sig.iter_rows(named=True):  # placed, not bought: the next hour didn't reach it
        out.setdefault((r["item_id"], r["observed_at"]), (False, None))
    return out


def recap_next(con, league: str, windows: list[dict], last_hour: datetime) -> dict | None:
    """Did each of a day's recap trades (`windows`: its d{day}/missed) keep paying,
    hour by hour, over the next NEXT_HOURS (as far as `last_hour`, the replay's last)?
    Each hour, the recap's own order for it is priced from the hour before (the first
    is the very order the recap showed) and filled by the Backtest's rules
    (analysis/backtest.py: loops and cards as the Market recap orders them, flips listed
    and cut for FLIP_HOLD hours), counting a fill the optimistic way (FILL). It's placed
    when the recap would call it ok: a loop or a set that still pays from the bid at
    that hour's worst prices, an item still liquid and volatile enough to flip; other
    hours have none. Random-reward cards aren't replayed (the Backtest can't price
    them), so they're left out. None for a recap with no look-backs."""
    if not windows:
        return None
    cutoff = _hour(windows[0]["latest_hour"])
    known = max(0, min(NEXT_HOURS, int((last_hour - cutoff).total_seconds() // 3600)))
    keys: dict[tuple, None] = {}
    for w in windows:
        keys |= {("loop", x["item_id"], x["direction"]): None for x in w["loops"]}
        keys |= {("card", x["item_id"], None): None for x in w["cards"] if not x["worst_roll"]}
        keys |= {("flip", x["item_id"], None): None for x in w["flips"]}
    # Orders are priced from these hours and placed in the hour after each.
    hours = [cutoff + k * bt.H for k in range(known)]
    since, until = cutoff - bt.H, cutoff + known * bt.H
    orders: dict[str, dict] = {"loop": {}, "card": {}, "flip": {}}
    find = {"loop": _loop_orders, "card": _card_orders, "flip": _flip_orders}
    for kind in orders:
        items = sorted({i for k, i, _ in keys if k == kind})
        if items and known:
            orders[kind] = find[kind](con, league, items, since, until, last_hour)
    trades = []
    for kind, item_id, direction in keys:
        key = (item_id, direction) if kind == "loop" else (item_id,)
        mine = {at: orders[kind].get((*key, at)) for at in hours}
        mine = {at: o for at, o in mine.items() if o is not None}
        trades.append(_outcome(kind, item_id, direction, mine, hours))
    return {"latest_hour": windows[0]["latest_hour"], "hours": known, "trades": trades}


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
