"""`eb preview build`: the pre-launch preview's snapshot (docs/preview.md), built from
pages already on disk, with no request to anyone.

A past league is replayed into a throwaway DuckDB beside the research database: the
live loader (`ingest.live.sync_live`) runs as the worker would have at the end of each
chosen day (`now = launch + day × 24 h`), with a client that refuses every request, so
every page must come from disk (`currency_exchange.fetch_page`). After each day the
site's services answer as the API would have then, and their answers are stored, one
document per key (preview/snapshot.py). A last load to NEXT_DAYS gives the reveal's
documents: each item's series to then. The trading game's hours (`game/{n}`) are loaded
one at a time from the first day's end, each with its recap and the orders it'd take.

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

FILL = "touch"  # a fill: some trade went past the order (the recap's chances count so)
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
    league_row = json.loads(TypeAdapter(m.LiveLeague).dump_json(m.LiveLeague(**row)))
    key = snapshot.day_key(day, "price-check")
    index = docs[key] = _doc(key, price_check.index(con, league, settings))
    for item_id, entry in _entries(index).items():
        key = snapshot.day_key(day, "price-check", item_id)
        docs[key] = _doc(key, price_check.item(con, league, item_id, entry))
    key = snapshot.day_key(day, "launch-picks")
    docs[key] = _doc(key, launch_picks.launch_board(con))
    return docs, league_row


def _hour(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=None)


def _orders(
    t: pl.DataFrame,
    keys: list[str],
    unknown: pl.Expr,
    spent: pl.Expr,
    settle: pl.Expr,
    lot: pl.Expr,
    hold: pl.Expr,
    units: pl.Expr | str,
) -> dict:
    """The orders the backtest placed (`t`, one row per order), by (`keys`..., hour):
    (filled, pnl in Chaos or None where `unknown`, what the fill spent in Chaos, the
    hour it sold or None, the smallest whole purchase the order makes in Chaos, the
    item held while it sells and how many one purchase holds, and whether its sale never
    filled: the Backtest gave up and counted it lost, where the game holds it)."""
    t = t.with_columns(
        chaos=pl.when(unknown).then(None).otherwise(pl.col("pnl") * pl.col("rate")),
        spent_=pl.when(pl.col("filled")).then(spent).otherwise(None),
        settle_=pl.when(pl.col("filled") & unknown.not_()).then(settle).otherwise(None),
        lot_=lot,
        hold_=hold,
        units_=units,
        unsold_=pl.col("filled") & pl.col("sell_at").is_null() & unknown.not_(),
    )
    return {
        (*(r[k] for k in keys), r["observed_at"]): (
            bool(r["filled"]),
            r["chaos"],
            r["spent_"],
            r["settle_"],
            r["lot_"],
            r["hold_"],
            r["units_"],
            bool(r["unsold_"]),
        )
        for r in t.iter_rows(named=True)
    }


def _settled() -> pl.Expr:
    """The hour an order's sale settled: when it sold, or for one that never did (lost
    whole), when the Backtest gave up waiting."""
    return pl.coalesce(pl.col("sell_at"), pl.col("observed_at") + 2 * bt.H + bt.SELL_WITHIN)


def _loop_orders(con, league: str, items: list[str], since, until, last_hour) -> dict:
    cross = bt._cross_hours(con, league, items, since)
    hours = cross.filter(pl.col("observed_at") < until).select("observed_at", "item_id")
    sig = pl.concat([hours.with_columns(direction=pl.lit(d)) for d in missed.DIRECTIONS])
    t = bt.loop_order_fills(
        cross, bt._rate(con, league, since), sig, "limit_both", FILL, *missed.LOOP_ORDER, True
    )
    sale_open = pl.col("observed_at") + 2 * bt.H + bt.SELL_WITHIN > last_hour
    unknown = pl.col("filled") & pl.col("sell_at").is_null() & sale_open
    # Chaos first spends `buy` Chaos an item; Divines first, `buy` Divines at the hour's rate.
    each = pl.when(pl.col("direction") == "chaos_first").then(pl.col("buy"))
    each = each.otherwise(pl.col("buy") * pl.col("rate"))
    # It buys whole lots of what one sale takes (1 Divine for 8 items: 8 at a time).
    lot = pl.col("sell_lot") * each
    k = pl.col("k") * each
    return _orders(
        t, ["item_id", "direction"], unknown, k, _settled(), lot, pl.col("item_id"), "sell_lot"
    )


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
    spent = pl.col("k") * pl.col("n") * pl.col("buy")
    # Whole sets, as many as one sale of the reward takes.
    sets = (pl.col("sell_lot") / pl.col("q")).ceil().clip(lower_bound=1)
    lot = sets * pl.col("n") * pl.col("buy")
    held = sets * pl.col("q")  # the rewards a purchase turns into
    return _orders(t, ["item_id"], unknown, spent, _settled(), lot, pl.col("reward_id"), held)


def _chaos_hours(con, league: str, items: list[str], since) -> pl.DataFrame | None:
    """`items`' hourly Chaos-market prices (low, average, high, items traded) from `since`."""
    if not items:
        return None
    marks = ", ".join("?" for _ in items)
    return db.frame(
        con,
        f"""
        SELECT item_id, observed_at, chaos_low AS lo, chaos_price AS p, chaos_high AS hi,
               chaos_volume AS units
        FROM cross_market_hour
        WHERE league_id = (SELECT id FROM league WHERE name = ?) AND chaos_price > 0
          AND observed_at >= ? AND item_id IN ({marks})
        """,
        [league, since, *items],
    )


def game_hours(con, league: str, games: dict[int, dict], last_hour: datetime) -> dict:
    """The trading game's hours (lib/game.ts): `games` (hours since launch -> the
    league's latest hour, its Divine rate and its Market recap then), each given what a
    player could trade then. Loops and cards: the recap's own order that hour, filled by
    the Backtest's rules, with what it spent, made and when it
    sold (null where the sale isn't known by `last_hour`), or `unsold` where it never did
    (the player holds `units` of `hold` a purchase and sells them). Flips, and what an
    unsold order holds, are played in the browser from the hour's Chaos prices (low,
    average, high, items traded), since a player holds them as long as they like."""
    if not games:
        return {}
    first = min(_hour(g["latest_hour"]) for g in games.values())
    end = max(_hour(g["latest_hour"]) for g in games.values()) + bt.H
    keys = {"loop": set(), "card": set()}
    flipped: set[str] = set()
    for g in games.values():
        for w in g["recap"]:
            keys["loop"] |= {x["item_id"] for x in w["loops"]}
            keys["card"] |= {x["item_id"] for x in w["cards"] if not x["worst_roll"]}
            flipped |= {x["item_id"] for x in w["flips"]}
    find = {"loop": _loop_orders, "card": _card_orders}
    orders = {
        k: find[k](con, league, sorted(v), first - bt.H, end, last_hour) if v else {}
        for k, v in keys.items()
    }

    # What an order whose sale never filled leaves the player holding, priced each hour:
    # a loop's item from its Chaos market (the hourly price rows keep only price-mapping
    # items), a card's reward as the Backtest sells it.
    def held(kind: str) -> list[str]:
        return sorted({v[5] for v in orders[kind].values() if v[7] and v[5]} - flipped)

    prices: dict[datetime, dict] = {}
    cards = held("card")
    for px in (
        _chaos_hours(con, league, held("loop"), first),
        bt._prices(con, league, cards, first) if cards else None,
    ):
        for r in px.iter_rows(named=True) if px is not None else ():
            hour = prices.setdefault(r["observed_at"], {})
            hour.setdefault(r["item_id"], [r["lo"], r["p"], r["hi"], r["units"]])
    if flipped:
        px = flips.chaos_prices(con, league).filter(
            pl.col("item_id").is_in(sorted(flipped)), pl.col("observed_at") >= first
        )
        for r in px.iter_rows(named=True):
            hour = prices.setdefault(r["observed_at"], {})
            hour[r["item_id"]] = [r["lo"], r["p"], r["hi"], r["units"]]
    out = {}
    for n, g in games.items():
        at = _hour(g["latest_hour"])
        mine = []
        seen: set[tuple] = set()
        for w in g["recap"]:
            rows = [("loop", x["item_id"], x["direction"]) for x in w["loops"]]
            rows += [("card", x["item_id"], None) for x in w["cards"] if not x["worst_roll"]]
            for kind, item_id, direction in rows:
                if (kind, item_id, direction) in seen:
                    continue
                seen.add((kind, item_id, direction))
                key = (item_id, direction, at) if kind == "loop" else (item_id, at)
                f, v, spent, settle, lot, hold, units, unsold = orders[kind].get(key, (None,) * 8)
                mine.append(
                    {
                        "kind": kind,
                        "item_id": item_id,
                        "direction": direction,
                        "filled": f,
                        "spent": spent if f else None,
                        "pnl": v if f else None,
                        "settle_at": _iso(settle) if f and settle is not None else None,
                        "lot": lot if f is not None and lot and lot > 0 else None,
                        "hold": hold if f else None,
                        "units": units if f else None,
                        "unsold": bool(unsold) if f else None,
                    }
                )
        out[n] = {**g, "orders": mine, "prices": prices.get(at, {})}
    return out


def build(
    settings: Settings,
    league: str,
    days: tuple[int, ...] = snapshot.DAYS,
    default_day: int = snapshot.DEFAULT_DAY,
    next_day: int = snapshot.NEXT_DAYS,
    day_hours: int = 24,
    game: bool = True,
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
    manifest_days, items, games = [], set(), {}
    # The trading game plays hour by hour from the first day to the reveal's last.
    played = {d * day_hours: d for d in days}
    if game:
        played |= {
            n: None for n in range(days[0] * day_hours, next_day * day_hours) if n not in played
        }
    with OfflineClient(replay) as client:
        try:
            _prepare(research, replay, league, launched)
            for i, n in enumerate(sorted(played)):
                last = _load(client, replay, league, launched, n)
                day = played[n]
                with db.session(replay.db_path) as con:
                    if i == 0:  # the loader has named the items the picks list
                        _rebuild_history(con)
                    if day is not None:
                        day_docs, row = _day(con, research, league, day)
                        docs.update(day_docs)
                        manifest_days.append({"day": day, "league": row})
                        recap = day_docs[snapshot.day_key(day, "missed")]
                        items |= set(_entries(day_docs[snapshot.day_key(day, "price-check")]))
                        progress(
                            f"day {day}: to {last:%Y-%m-%d %H:00} UTC, {len(day_docs)} documents"
                        )
                    else:
                        recap = _doc(snapshot.day_key(1, "missed"), missed.missed(con, league))
                        row = next(
                            r for r in records(live.live_leagues(con)) if r["name"] == league
                        )
                    if game and n < next_day * day_hours:
                        games[n] = {
                            "latest_hour": _iso(last),
                            "divine_chaos": row["divine_chaos"],
                            "recap": recap,
                        }
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
                for n, doc in game_hours(con, league, games, last).items():
                    key = snapshot.game_key(n)
                    docs[key] = _doc(key, doc)
            if games:
                progress(f"the trading game: {len(games)} hours")
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
        "game": {"first": min(games), "last": max(games)} if games else None,
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
