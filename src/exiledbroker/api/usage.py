"""Usage counts without cookies: how many people visit, how many come back, and which
pages and features they use (docs/usage.md).

Nothing is stored in the visitor's browser, so there's nothing to consent to under the
ePrivacy rules (no cookie banner). The page sends a beacon naming the page or feature
(`POST /api/hit?e=page:/launch`), from a fixed list (EVENTS). The server derives a
visitor id: a truncated HMAC-SHA256 of the IP and User-Agent under a random salt that
lives for one period (a calendar month by default, `EB_USAGE_PERIOD`). The IP and the
User-Agent are never stored. When a period ends, its totals go into `usage_period` and
its salt and visitor rows are deleted: the counts that remain can't be tied to anyone.
Visitors who send Do-Not-Track or Global Privacy Control, and bots, aren't counted.

Counts collect in memory and are written every FLUSH_EVERY seconds, as a few upserts
(`flush`): a visit costs the database nothing at the moment it happens. With no
`EB_DATABASE_URL` (local DuckDB, which the API opens read-only) they stay in memory."""

import hashlib
import hmac
import logging
import re
import secrets
import threading
from collections import Counter
from collections.abc import Callable
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from exiledbroker.storage import db

log = logging.getLogger("uvicorn.error")

Period = Literal["day", "week", "month"]
FLUSH_EVERY = 300.0  # seconds between writes of the collected counts
MAX_PER_DAY = 50  # views of one event a visitor can add in a day (a reload loop, a script)
MAX_SEEN = 50_000  # (event, visitor) pairs held for the day: bounds memory under a flood
LOAD_RETRY = 60.0  # seconds before trying the database again after it failed

# The pages (the frontend's routes) and the features worth knowing are used. Anything
# else is ignored, so the tables stay a few rows a day whatever is sent.
PAGES = ["/", "/launch", "/price-check", "/conversions", "/backtest", "/about", "/not-found"]
FEATURES = [
    "league",  # switched league
    "theme",  # switched Dusk / Parchment
    "recap-show-all",  # Market recap: showed a whole list
    "recap-pin",  # Market recap: pinned a look-back
    "launch-pick",  # Launch: opened a pick's details
    "price-check-item",  # Price check: looked an item up
    "price-check-range",  # Price check: changed the chart's range
    "price-check-stack",  # Price check: priced a stack
]
SITE = "site"  # every page view, also counted on its own: the site's visitors
EVENTS = frozenset([*(f"page:{p}" for p in PAGES), *(f"feature:{f}" for f in FEATURES)])

BOTS = re.compile(
    r"bot|crawl|spider|slurp|preview|headless|lighthouse|python|curl|wget|httpx|go-http|java/",
    re.IGNORECASE,
)


def period_of(day: date, period: Period) -> str:
    if period == "month":
        return f"{day:%Y-%m}"
    if period == "week":
        year, week, _ = day.isocalendar()
        return f"{year}-W{week:02d}"
    return day.isoformat()


def opted_out(headers) -> bool:
    """Do-Not-Track or Global Privacy Control."""
    return headers.get("dnt") == "1" or headers.get("sec-gpc") == "1"


def client_ip(request) -> str:
    """The visitor's address: the Cloudflare Worker passes it on as x-eb-client-ip
    (deploy/cloudflare/), else Cloudflare's own header or the first X-Forwarded-For.
    Used only for the hash."""
    h = request.headers
    forwarded = h.get("x-forwarded-for", "").split(",")[0].strip()
    return (
        h.get("x-eb-client-ip")
        or h.get("cf-connecting-ip")
        or forwarded
        or (request.client.host if request.client else "")
    )


@contextmanager
def _transaction(con):
    if db.is_postgres(con):
        with con.transaction():
            yield
        return
    con.execute("BEGIN")
    try:
        yield
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


class Usage:
    """The counter. `connect` opens a writable connection to the site's database, or is
    None to keep everything in memory (local development, tests of the counting)."""

    def __init__(
        self,
        connect: Callable[[], AbstractContextManager] | None = None,
        period: Period = "month",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.connect, self.period, self.clock = connect, period, clock
        self._lock = threading.Lock()
        self._salt: tuple[str, bytes] | None = None  # (period, salt)
        self._day: date | None = None
        self._seen: dict[tuple[str, str], int] = {}  # today's (event, visitor) -> views
        self._loaded_day: date | None = None  # the day whose seen pairs came from the db
        self._failed_at: datetime | None = None
        self._views: Counter = Counter()  # (day, event) -> views not yet written
        self._visitors: Counter = Counter()  # (day, event) -> new visitors not yet written
        self._new: list[tuple[date, str, str]] = []  # (day, event, visitor) not yet written
        self._schema_ready = False

    # -- counting ---------------------------------------------------------------------

    def record(self, event: str, ip: str, user_agent: str) -> bool:
        """Count one page view or feature use; False when it isn't counted."""
        if event not in EVENTS or not user_agent or BOTS.search(user_agent):
            return False
        now = self.clock()
        day = now.date()
        with self._lock:
            if not self._ready(day, now):
                return False
            salt = self._salt[1]
            visitor = hmac.new(salt, f"{ip}\n{user_agent}".encode(), hashlib.sha256)
            visitor = visitor.hexdigest()[:16]
            counted = self._count(day, event, visitor)
            if counted and event.startswith("page:"):
                self._count(day, SITE, visitor)
            return counted

    def _count(self, day: date, event: str, visitor: str) -> bool:
        n = self._seen.get((event, visitor), 0)
        if n >= MAX_PER_DAY or (n == 0 and len(self._seen) >= MAX_SEEN):
            return False
        self._seen[(event, visitor)] = n + 1
        self._views[(day, event)] += 1
        if n == 0:
            self._visitors[(day, event)] += 1
            self._new.append((day, event, visitor))
        return True

    def _ready(self, day: date, now: datetime) -> bool:
        """This period's salt and today's seen pairs are in hand (read from the
        database once, after a start or a new day)."""
        period = period_of(day, self.period)
        if self._day != day:
            self._day, self._seen = day, {}
        have_salt = self._salt is not None and self._salt[0] == period
        if have_salt and (self.connect is None or self._loaded_day == day):
            return True
        if self.connect is None:
            self._salt = (period, secrets.token_bytes(32))
            return True
        if self._failed_at and now - self._failed_at < timedelta(seconds=LOAD_RETRY):
            return False
        try:
            with self.connect() as con:
                self._ensure_schema(con)
                salt = self._salt[1] if have_salt else self._load_salt(con, period)
                seen = db.rows(con, "SELECT event, visitor FROM usage_seen WHERE day = ?", [day])
        except Exception:
            log.exception("usage counts: reading the day's state failed")
            self._failed_at = now
            return False
        self._failed_at = None
        self._salt, self._loaded_day = (period, salt), day
        for event, visitor in seen:
            self._seen.setdefault((event, visitor), 1)
        return True

    def _ensure_schema(self, con) -> None:
        if not self._schema_ready:
            db.init_schema(con)
            self._schema_ready = True

    @staticmethod
    def _load_salt(con, period: str) -> bytes:
        """This period's salt: the stored one, or a new one stored now (so a restart
        hashes visitors the same way)."""
        db.execute(
            con,
            "INSERT INTO usage_salt (period, salt) VALUES (?, ?) ON CONFLICT DO NOTHING",
            [period, secrets.token_hex(32)],
        )
        return bytes.fromhex(
            db.scalar(con, "SELECT salt FROM usage_salt WHERE period = ?", [period])
        )

    # -- writing ----------------------------------------------------------------------

    def flush(self) -> int:
        """Write what's been counted since the last flush; returns how many events. A
        failed write keeps the counts for the next one."""
        if self.connect is None:
            return 0
        with self._lock:
            views, visitors, new = self._views, self._visitors, self._new
            self._views, self._visitors, self._new = Counter(), Counter(), []
        today = self.clock().date()
        try:
            with self.connect() as con:
                self._ensure_schema(con)
                with _transaction(con):
                    # The counts first: the last visitors of a period that just ended
                    # are in its totals.
                    self._write(con, views, visitors, new, today)
                    self._close_periods(con, period_of(today, self.period))
        except Exception:
            with self._lock:
                self._views.update(views)
                self._visitors.update(visitors)
                self._new = new + self._new
            raise
        return sum(views.values())

    def _close_periods(self, con, current: str) -> None:
        """A finished period: its totals kept, its salt and visitors deleted."""
        for (period,) in db.rows(con, "SELECT period FROM usage_salt WHERE period <> ?", [current]):
            db.execute(
                con,
                "INSERT INTO usage_period (period, visitors, returned) "
                "SELECT ?, count(*), count(*) FILTER (WHERE days > 1) FROM usage_visitor "
                "WHERE period = ? ON CONFLICT (period) DO NOTHING",
                [period, period],
            )
            db.execute(con, "DELETE FROM usage_visitor WHERE period = ?", [period])
            db.execute(con, "DELETE FROM usage_salt WHERE period = ?", [period])

    def _write(self, con, views: Counter, visitors: Counter, new: list, today: date) -> None:
        db.execute(con, "DELETE FROM usage_seen WHERE day < ?", [today])
        for (day, event), n in sorted(views.items()):
            db.execute(
                con,
                "INSERT INTO usage_daily (day, event, views, visitors) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (day, event) DO UPDATE SET "
                "views = usage_daily.views + excluded.views, "
                "visitors = usage_daily.visitors + excluded.visitors",
                [day, event, n, visitors.get((day, event), 0)],
            )
        for day, event, visitor in new:
            if day == today:
                db.execute(
                    con,
                    "INSERT INTO usage_seen (day, event, visitor) VALUES (?, ?, ?) "
                    "ON CONFLICT DO NOTHING",
                    [day, event, visitor],
                )
            if event == SITE:  # a visitor's first page of the day: one more day seen
                db.execute(
                    con,
                    "INSERT INTO usage_visitor (period, visitor, last_day, days) "
                    "VALUES (?, ?, ?, 1) ON CONFLICT (period, visitor) DO UPDATE SET "
                    "days = usage_visitor.days + CASE WHEN usage_visitor.last_day < "
                    "excluded.last_day THEN 1 ELSE 0 END, "
                    "last_day = greatest(usage_visitor.last_day, excluded.last_day)",
                    [period_of(day, self.period), visitor, day],
                )

    def run_forever(self, stop: threading.Event, every: float = FLUSH_EVERY) -> None:
        """Background loop: flush every `every` seconds, and once more on the way out."""
        while not stop.wait(every):
            self._flush_logged()
        self._flush_logged()

    def _flush_logged(self) -> None:
        try:
            self.flush()
        except Exception:  # never let the counter take the web process down
            log.exception("writing usage counts failed")

    # -- reading ----------------------------------------------------------------------

    def stats(self, days: int = 30) -> dict:
        """The counts so far (written ones plus those still in memory)."""
        if self.connect is None:
            return self._memory_stats()
        self.flush()
        today = self.clock().date()
        with self.connect() as con:
            return read_stats(con, today, period_of(today, self.period), days)

    def _memory_stats(self) -> dict:
        with self._lock:
            events = {}
            for (_, event), n in self._views.items():
                e = events.setdefault(event, {"event": event, "views": 0, "visitors": 0})
                e["views"] += n
            for (_, event), n in self._visitors.items():
                events[event]["visitors"] += n
        site = events.pop(SITE, {"views": 0, "visitors": 0})
        return {
            "stored": False,
            "total": {"views": site["views"], "visitor_days": site["visitors"]},
            "periods": [],
            "days": [],
            "events": sorted(events.values(), key=lambda e: (-e["views"], e["event"])),
        }


def read_stats(con, today: date, current: str, days: int = 30) -> dict:
    """Totals, each period's visitors and returning visitors, the last `days` days and
    each page's and feature's use (all time, and `_recent`: the last `days` days). A
    few small aggregates."""
    since = today - timedelta(days=days - 1)
    total = db.rows(
        con,
        "SELECT coalesce(sum(views), 0), coalesce(sum(visitors), 0), min(day) "
        "FROM usage_daily WHERE event = ?",
        [SITE],
    )[0]
    periods = [
        {"period": p, "visitors": v, "returning": r, "finished": True}
        for p, v, r in db.rows(con, "SELECT period, visitors, returned FROM usage_period")
    ]
    v, r = db.rows(
        con,
        "SELECT count(*), count(*) FILTER (WHERE days > 1) FROM usage_visitor WHERE period = ?",
        [current],
    )[0]
    periods.append({"period": current, "visitors": v, "returning": r, "finished": False})
    daily = db.rows(
        con,
        "SELECT day, views, visitors FROM usage_daily WHERE event = ? AND day >= ?",
        [SITE, since],
    )
    events = db.rows(
        con,
        "SELECT event, sum(views), sum(visitors), "
        "coalesce(sum(views) FILTER (WHERE day >= ?), 0), "
        "coalesce(sum(visitors) FILTER (WHERE day >= ?), 0) "
        "FROM usage_daily WHERE event <> ? GROUP BY event",
        [since, since, SITE],
    )
    return {
        "stored": True,
        "total": {"views": int(total[0]), "visitor_days": int(total[1]), "since": total[2]},
        "periods": sorted(periods, key=lambda p: p["period"]),
        "days": [{"day": d, "views": int(n), "visitors": int(u)} for d, n, u in sorted(daily)],
        "events": sorted(
            (
                {
                    "event": e,
                    "views": int(n),
                    "visitors": int(u),
                    "views_recent": int(n30),
                    "visitors_recent": int(u30),
                }
                for e, n, u, n30, u30 in events
            ),
            key=lambda e: (-e["views"], e["event"]),
        ),
    }
