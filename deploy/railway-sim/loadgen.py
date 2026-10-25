"""Simulated visitors for the Railway simulation, behaving the way the built site does.

A "user" is a daily active visitor: about VISITS_PER_DAY visits a day at random times
(weighted toward European and American evenings, UTC), each viewing a few pages and
leaving the tab open a while. Each visitor's browser mirrors web/src:
- index.html is revalidated each visit (ETag → 304); assets are fetched once, then
  either revalidated each visit (no cache header: the "before" case) or not at all
  (hashed and immutable: `immutable_assets`);
- the query cache is saved between visits for 6 hours (lib/persist.ts), current data
  version only;
- /api/status is checked only when a new hour is due (lib/schedule.ts, ported below);
- a page's data is fetched only when the data version changed since it was cached.

Every visit price-checks a few items (the user: "a few times every session", likely
different items each time): the Price check list, then ITEMS_PER_VISIT items on
average (at least one), picked from the movers or the most traded, so most item views
are a response no one else asked for this hour.

Time runs on the simulation's clock: `seconds_per_hour` real seconds per simulated
hour (60 compresses a day into 24 minutes). Every response is counted: bytes on the
wire (plus HEADER_BYTES for headers and TLS framing) are what Railway would bill as
egress."""

import asyncio
import random
import re
import statistics
import time
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

MIN = 60.0
HOUR = 3600.0
VISITS_PER_DAY = 3.0
PAGES_PER_VISIT = 3.0
ITEMS_PER_VISIT = 3.0  # Price check items opened per visit (mean; at least one)
MOVER_SHARE = 0.4  # of those, opened from the movers; the rest by how much they trade
VISIT_MINUTES = 15.0
CACHE_HOURS = 6.0
HEADER_BYTES = 400  # response headers + TLS framing, per response
# Hour-of-day weights (UTC): quiet nights, busy European and American evenings.
HOUR_WEIGHTS = [2, 1, 1, 1, 1, 1, 2, 3, 3, 3, 3, 3, 4, 4, 4, 5, 6, 7, 8, 8, 8, 7, 5, 3]
# The site's pages after the landing page (web/src/App.tsx). Loops and cards are
# sections of the landing page now (/arbitrage and /cards redirect there), so they read
# its one cached recap; Conversions and About are static.
OTHER_PAGES = {
    "loops": 0.2,
    "cards": 0.15,
    "launch": 0.2,
    "backtest": 0.05,
    "conversions": 0.1,
    "about": 0.05,
}

# --- lib/schedule.ts, in seconds ----------------------------------------------------
PUBLISH_DELAY = 8 * MIN
MIN_CHECK = 2 * MIN
IDLE_CHECK = 30 * MIN


def _overdue_every(late_by: float) -> float:
    if late_by < 15 * MIN:
        return 3 * MIN
    if late_by < HOUR:
        return 5 * MIN
    return 10 * MIN


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def next_expected(status: dict) -> float | None:
    due = [
        _ts(lg["latest_hour"]) + 2 * HOUR + PUBLISH_DELAY
        for lg in status["leagues"]
        if lg.get("latest_hour")
    ]
    if status.get("upcoming"):
        due.append(_ts(status["upcoming"]["first_data_at"]))
    return min(due) if due else None


def next_check_in(status: dict, fetched_at: float, now: float, jitter: float = 0.0) -> float:
    """Seconds until the next status check (lib/schedule.ts nextCheckIn)."""
    skew = _ts(status["now"]) - fetched_at
    server_now = now + skew
    expected = next_expected(status)
    if expected is None:
        at = fetched_at + IDLE_CHECK
    elif server_now < expected:
        at = expected - skew + jitter
    else:
        at = fetched_at + _overdue_every(server_now - expected)
    return max(at, fetched_at + MIN_CHECK) - now


# --- The visitors ----------------------------------------------------------------------


@dataclass
class Clock:
    """Simulated time: `seconds_per_hour` real seconds per simulated hour."""

    sim_start: float  # unix seconds
    seconds_per_hour: float
    real_start: float = field(default_factory=time.monotonic)

    @property
    def scale(self) -> float:
        return HOUR / self.seconds_per_hour  # simulated seconds per real second

    def now(self) -> float:
        return self.sim_start + (time.monotonic() - self.real_start) * self.scale

    async def sleep_until(self, sim_t: float) -> None:
        delay = (sim_t - self.now()) / self.scale
        if delay > 0:
            await asyncio.sleep(delay)


@dataclass
class Browser:
    """One visitor's browser: what it has cached, kept between visits."""

    jitter: float
    index_etag: str | None = None
    asset_etags: dict = field(default_factory=dict)
    status: dict | None = None
    status_at: float = 0.0  # sim time it was fetched
    data: dict = field(default_factory=dict)  # endpoint → data version cached
    saved_at: float = 0.0
    rng: random.Random = field(default_factory=random.Random)
    # Price check: the list's items (id, units an hour) and movers, from its response.
    items: list = field(default_factory=list)
    movers: list = field(default_factory=list)
    current: tuple[str, str] | None = (
        None  # (kind, URL) the open page shows: refetched on a new version
    )


@dataclass
class Stats:
    requests: dict = field(default_factory=lambda: defaultdict(int))
    bytes: dict = field(default_factory=lambda: defaultdict(int))
    latency: dict = field(default_factory=lambda: defaultdict(list))
    errors: dict = field(default_factory=lambda: defaultdict(int))
    visits: int = 0

    def add(self, kind: str, response: httpx.Response | None, ms: float) -> None:
        self.requests[kind] += 1
        if response is None or response.status_code >= 500 or response.status_code in (404, 422):
            self.errors[kind] += 1
            return
        self.bytes[kind] += response.num_bytes_downloaded + HEADER_BYTES
        self.latency[kind].append(ms)

    def summary(self) -> dict:
        def pct(values, p):
            return (
                round(statistics.quantiles(values, n=100)[p - 1], 1)
                if len(values) >= 2
                else (values[0] if values else None)
            )

        all_ms = [v for vs in self.latency.values() for v in vs]
        return {
            "visits": self.visits,
            "requests": dict(self.requests),
            "bytes": dict(self.bytes),
            "errors": dict(self.errors),
            "total_requests": sum(self.requests.values()),
            "total_bytes": sum(self.bytes.values()),
            "p50_ms": pct(all_ms, 50),
            "p95_ms": pct(all_ms, 95),
            "p95_ms_by_kind": {k: pct(v, 95) for k, v in self.latency.items()},
        }


class Site:
    """The requests the built frontend makes, by page."""

    def __init__(self, client: httpx.AsyncClient, stats: Stats, immutable_assets: bool):
        self.client, self.stats, self.immutable = client, stats, immutable_assets
        self.assets: list[str] | None = None

    async def get(self, kind: str, url: str, headers: dict | None = None) -> httpx.Response | None:
        started = time.perf_counter()
        try:
            r = await self.client.get(url, headers=headers or {})
        except httpx.HTTPError:
            r = None
        self.stats.add(kind, r, (time.perf_counter() - started) * 1000)
        return r

    async def _discover_assets(self, html: str) -> None:
        """The files a first visit loads: the script, the stylesheet and the fonts the
        stylesheet uses for Latin text (what a browser actually downloads)."""
        files = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
        css = [f for f in files if f.endswith(".css")]
        fonts: list[str] = []
        for c in css:
            r = await self.client.get(c)
            fonts += [
                "/assets/" + f
                for f in re.findall(r"url\(\.?/?(?:assets/)?([^)]+\.woff2)\)", r.text)
                if re.search(r"-latin-(400|500|600)-normal", f)
            ]
        self.assets = files + sorted(set(fonts))

    async def open(self, b: Browser) -> None:
        """Loading the app: index.html, then its assets."""
        r = await self.get("index", "/", {"If-None-Match": b.index_etag} if b.index_etag else None)
        if r is not None and r.status_code == 200:
            b.index_etag = r.headers.get("etag")
            if self.assets is None:
                await self._discover_assets(r.text)
        for a in self.assets or []:
            if a in b.asset_etags and self.immutable:
                continue  # cached for a year
            headers = {"If-None-Match": b.asset_etags[a]} if b.asset_etags.get(a) else None
            r = await self.get("asset", a, headers)
            if r is not None and r.status_code == 200:
                b.asset_etags[a] = r.headers.get("etag") or ""

    async def status(self, b: Browser, now: float) -> None:
        r = await self.get("status", "/api/status")
        if r is not None and r.status_code == 200:
            status = r.json()
            status["now"] = datetime.fromtimestamp(now, UTC).isoformat()  # the simulated clock
            b.status, b.status_at = status, now

    def endpoint(self, page: str, b: Browser) -> tuple[str, str] | None:
        """The request a page makes with its default controls (src/api/queries.ts)."""
        if not b.status:
            return None
        live = [lg["name"] for lg in b.status["leagues"] if lg.get("latest_hour")]
        if page == "launch":
            return "launch", "/api/launch/picks"
        if page == "backtest":
            return "backtest", "/api/backtest"
        if page in ("missed", "loops", "cards") and live:
            return "missed", f"/api/missed/{live[0]}"
        if page == "price_check" and live:
            return "price_check", f"/api/price-check/{live[0]}"
        if page == "item" and live:
            item = self.pick(b)
            if item:
                return "item", f"/api/price-check/{live[0]}/{urllib.parse.quote(item, safe='')}"
        return None  # a static page, or no league yet

    @staticmethod
    def pick(b: Browser) -> str | None:
        """An item to price-check: a mover, or one of the items weighted by how much it
        trades (people look up what they hold, which is mostly what trades)."""
        if b.movers and b.rng.random() < MOVER_SHARE:
            return b.rng.choice(b.movers)
        traded = [(i, v) for i, v in b.items if v]
        if not traded:
            return b.rng.choice(b.movers) if b.movers else None
        ids, volume = zip(*traded, strict=True)
        return b.rng.choices(ids, weights=[v**0.5 for v in volume])[0]

    async def view(self, page: str, b: Browser) -> None:
        ep = self.endpoint(page, b)
        if ep is None or not b.status:
            return
        await self.fetch(*ep, b)

    async def fetch(self, kind: str, url: str, b: Browser) -> None:
        b.current = (kind, url)
        version = b.status.get("data_version") if b.status else None
        if b.data.get(url) == version:
            return  # cached for this data version
        r = await self.get(kind, url)
        if r is not None and r.status_code == 200:
            b.data[url] = version
            if kind == "price_check":
                doc = r.json()
                b.items = [(x["item_id"], x.get("volume_h")) for x in doc.get("items", [])]
                b.movers = list(doc.get("movers", []))


def plan_visits(
    users: int, sim_start: float, sim_hours: float, rng: random.Random
) -> list[tuple[int, float, float, list[str]]]:
    """(user, start, open seconds, pages) for every visit in the window, sim time."""
    visits = []
    days = sim_hours / 24
    for u in range(users):
        n = _poisson(rng, VISITS_PER_DAY * days)
        for _ in range(n):
            # A time inside the window, weighted by the hour of day.
            for _attempt in range(50):
                t = sim_start + rng.random() * sim_hours * HOUR
                hour = datetime.fromtimestamp(t, UTC).hour
                if rng.random() < HOUR_WEIGHTS[hour % 24] / max(HOUR_WEIGHTS):
                    break
            open_s = min(max(rng.expovariate(1 / (VISIT_MINUTES * MIN)), 2 * MIN), 60 * MIN)
            items = ["item"] * max(_poisson(rng, ITEMS_PER_VISIT), 1)
            others = rng.choices(
                list(OTHER_PAGES),
                weights=list(OTHER_PAGES.values()),
                k=_poisson(rng, PAGES_PER_VISIT - 1),
            )
            pages = ["missed", "price_check", *items[:8], *others[:4]]
            visits.append((u, t, open_s, pages))
    return sorted(visits, key=lambda v: v[1])


def _poisson(rng: random.Random, mean: float) -> int:
    # Knuth: fine for small means.
    limit, k, p = pow(2.718281828459045, -mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


async def visit(
    site: Site,
    clock: Clock,
    b: Browser,
    start: float,
    open_s: float,
    pages: list[str],
    stats: Stats,
) -> None:
    await clock.sleep_until(start)
    stats.visits += 1
    now = clock.now()
    if now - b.saved_at > CACHE_HOURS * HOUR:
        b.status, b.data = None, {}  # the saved cache expired
    await site.open(b)
    if b.status is None or next_check_in(b.status, b.status_at, now, b.jitter) <= 0:
        await site.status(b, now)
    end = start + open_s
    step = open_s / max(len(pages), 1)
    for i, page in enumerate(pages):
        await clock.sleep_until(start + i * step)
        await site.view(page, b)
    # The tab stays open: status checks when due; a new version refetches the page.
    while b.status is not None:
        due = b.status_at + next_check_in(b.status, b.status_at, clock.now(), b.jitter)
        if due >= end:
            break
        await clock.sleep_until(due)
        before = b.status.get("data_version")
        await site.status(b, clock.now())
        if b.status and b.status.get("data_version") != before and b.current:
            await site.fetch(*b.current, b)
    b.saved_at = clock.now()


async def run(
    base_url: str,
    users: int,
    sim_start: datetime,
    sim_hours: float,
    seconds_per_hour: float,
    immutable_assets: bool = False,
    seed: int = 1,
    spike_minutes: float | None = None,
    real_start: float | None = None,
) -> dict:
    """Run the visitors; returns the request summary. `spike_minutes`: instead of a
    day, every user arrives (cold) within that many minutes of the start."""
    rng = random.Random(seed)
    clock = Clock(sim_start.timestamp(), seconds_per_hour, real_start or time.monotonic())
    stats = Stats()
    if spike_minutes is not None:
        plan = [
            (
                u,
                clock.sim_start + rng.random() * spike_minutes * MIN,
                VISIT_MINUTES * MIN,
                ["missed"],
            )
            for u in range(users)
        ]
    else:
        plan = plan_visits(users, clock.sim_start, sim_hours, rng)
    browsers = [
        Browser(jitter=rng.random() * 90, rng=random.Random(rng.random())) for _ in range(users)
    ]
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=100)
    async with httpx.AsyncClient(
        base_url=base_url, timeout=30, limits=limits, headers={"Accept-Encoding": "gzip"}
    ) as client:
        site = Site(client, stats, immutable_assets)
        # One visitor's visits run in order (a browser), visitors in parallel.
        by_user: dict[int, list] = defaultdict(list)
        for u, t, open_s, pages in plan:
            by_user[u].append((t, open_s, pages))

        async def user(u: int) -> None:
            for t, open_s, pages in by_user[u]:
                await visit(site, clock, browsers[u], t, open_s, pages, stats)

        await asyncio.gather(*(user(u) for u in by_user))
    out = stats.summary()
    out["users"] = users
    out["sim_hours"] = sim_hours
    out["real_seconds"] = round(time.monotonic() - clock.real_start, 1)
    out["requests_per_user_day"] = (
        round(out["total_requests"] / users / max(sim_hours / 24, 1e-9), 2)
        if spike_minutes is None
        else None
    )
    return out
