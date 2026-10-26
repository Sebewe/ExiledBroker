"""After a deploy: does the site answer what its pages ask for? (`eb site smoke <url>`)

Walks what a visitor's browser fetches: the pages (every client-side route gets the app's
index.html), the built files index.html names, the social preview image, and every API
endpoint the pages request, for the newest league, plus the answers that must stay
closed (unknown routes, a previous deploy's chunk, the owner's stats). While the
pre-launch preview is on (/api/status's `preview`, docs/preview.md) it also fetches the
snapshot's documents for the default day, as the pages do. About 30 requests to our own
site (about 45 with the preview), nothing upstream. `run` takes any `get(path, headers)` returning an
httpx-style response, so the tests run it on FastAPI's TestClient.

`edge=True` (the Cloudflare-fronted domain) also checks that a table asked for twice is
an edge cache hit. `origin_check` (the *.up.railway.app address) checks that the origin
refuses requests without Cloudflare's key and still answers Railway's health check."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# The client-side routes the menu links to (web/src/App.tsx); each must get index.html.
PAGES = (
    "/",
    "/price-check",
    "/launch",
    "/research",
    "/research/method",
    "/research/backtest",
    "/research/conversions",
    "/research/about",
    "/no-such-page",  # the app's own Not found page, still index.html
)
STATIC = ("/og.png", "/favicon.svg", "/robots.txt")
# The site's banner calls the feed late after this (web/src/lib/freshness.ts).
STALE_AFTER = timedelta(minutes=75)


@dataclass
class Check:
    name: str
    ok: bool | None  # None: a warning, not a failure
    detail: str = ""

    def __str__(self) -> str:
        mark = {True: "ok  ", False: "FAIL", None: "warn"}[self.ok]
        return f"{mark}  {self.name}" + (f": {self.detail}" if self.detail else "")


Get = Callable[..., object]


def _check(results: list[Check], name: str, ok: bool, detail: str = "") -> bool:
    results.append(Check(name, ok, "" if ok else detail))
    return ok


def _is_app(r) -> bool:
    return r.headers.get("x-eb-origin") == "app"


def run(
    get: Get,
    *,
    edge: bool = False,
    origin_check: Get | None = None,
    now: datetime | None = None,
) -> list[Check]:
    out: list[Check] = []
    now = now or datetime.now(UTC)

    r = get("/api/health")
    _check(out, "/api/health", r.status_code == 200 and _is_app(r), f"{r.status_code}")

    # The pages, and the files the page loads.
    index = get("/")
    html = index.text if index.status_code == 200 else ""
    _check(
        out,
        "/ is the app",
        'id="root"' in html and "content-security-policy" in index.headers,
        f"{index.status_code}, no app root or no CSP",
    )
    for path in PAGES[1:]:
        r = get(path)
        _check(out, path, r.status_code == 200 and r.text == html, f"{r.status_code}")
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
    _check(out, "index.html names its built files", bool(assets), "none found")
    for path in assets:
        r = get(path)
        _check(
            out,
            path,
            r.status_code == 200 and "immutable" in r.headers.get("cache-control", ""),
            f"{r.status_code} {r.headers.get('cache-control')}",
        )
    r = get("/assets/smoke-missing-0000.js")
    _check(out, "a missing built file is 404", r.status_code == 404, f"{r.status_code}")
    for path in STATIC:
        r = get(path)
        _check(out, path, r.status_code == 200 and r.text != html, f"{r.status_code}")

    # The API, as the pages call it.
    r = get("/api/status")
    if not _check(out, "/api/status", r.status_code == 200, f"{r.status_code}: {r.text[:200]}"):
        return out
    status = r.json()
    version, leagues = status.get("data_version"), status.get("leagues") or []
    v = f"?v={version}" if version else ""
    for path in ("/api/launch/picks", "/api/backtest"):
        _table(out, get, path + v, edge)
    if not leagues:
        out.append(Check("leagues", None, "none loaded yet: the league endpoints weren't checked"))
    else:
        league = leagues[0]
        name = league["name"]
        latest = league.get("latest_hour")
        if latest is None:
            out.append(Check(f"{name} freshness", None, "no trades loaded yet"))
        else:
            ended = datetime.fromisoformat(latest)
            ended = (ended if ended.tzinfo else ended.replace(tzinfo=UTC)) + timedelta(hours=1)
            late = now - ended > STALE_AFTER and not status.get("upcoming")
            out.append(
                Check(
                    f"{name} freshness",
                    None if late else True,
                    f"latest hour ended {(now - ended).total_seconds() / 3600:.1f} h ago",
                )
            )
        _table(out, get, f"/api/missed/{name}{v}", edge)
        index_r = _table(out, get, f"/api/price-check/{name}{v}", edge)
        items = (index_r.json().get("items") or []) if index_r is not None else []
        if items:
            _table(out, get, f"/api/price-check/{name}/{items[0]['item_id']}{v}", edge)
        r = get("/api/missed/No Such League")
        _check(out, "an unknown league is 404", r.status_code == 404, f"{r.status_code}")

    preview = status.get("preview")
    if preview:
        _preview(out, get, preview, edge)
    elif status.get("upcoming"):
        out.append(
            Check(
                "preview",
                None,
                "a next league is announced but the preview is off "
                "(no snapshot seeded, or EB_PREVIEW=off)",
            )
        )

    r = get("/api/no-such-endpoint")
    _check(out, "an unknown endpoint is 404", r.status_code == 404, f"{r.status_code}")
    r = get("/api/stats")
    _check(out, "/api/stats is closed", r.status_code in (401, 404), f"{r.status_code}")
    r = get("/api/admin/overview")
    _check(out, "/api/admin is closed", r.status_code in (401, 404), f"{r.status_code}")
    if edge:
        r = get("/api/health")
        _check(
            out,
            "/api/health is never cached",
            "no-store" in r.headers.get("cache-control", ""),
            r.headers.get("cache-control", ""),
        )

    if origin_check is not None:
        r = origin_check("/api/status")
        _check(
            out, "origin refuses requests without the key", r.status_code == 403, f"{r.status_code}"
        )
        r = origin_check("/api/health")
        _check(
            out, "origin answers Railway's health check", r.status_code == 200, f"{r.status_code}"
        )
    return out


def _preview(out: list[Check], get: Get, preview: dict, edge: bool):
    """The preview's documents for its default day, as the pages ask for them (under the
    snapshot's version, so a day in the browser and at the edge), and a key it lacks."""
    version, day = preview.get("version"), preview.get("default_day")
    v = f"?v={version}"
    r = _table(out, get, f"/api/preview/manifest{v}", edge)
    if r is None:
        return
    _check(
        out,
        "the preview's manifest is /api/status's",
        r.json().get("version") == version,
        f"{r.json().get('version')} != {version}",
    )
    cache = r.headers.get("cache-control", "")
    _check(out, "the preview's documents are cached a day", "max-age=86400" in cache, cache)
    days = [d.get("day") for d in preview.get("days") or []]
    _check(out, "the preview's default day is one of its days", day in days, f"{day} {days}")
    for what in ("missed", "launch-picks", "recap-next"):
        _table(out, get, f"/api/preview/d{day}/{what}{v}", edge)
    index_r = _table(out, get, f"/api/preview/d{day}/price-check{v}", edge)
    items = (index_r.json().get("items") or []) if index_r is not None else []
    if not items:
        out.append(Check("preview items", None, f"day {day}'s Price check lists no items"))
    else:
        item = items[0]["item_id"]
        _table(out, get, f"/api/preview/d{day}/price-check/{item}{v}", edge)
        _table(out, get, f"/api/preview/next/price-check/{item}{v}", edge)
    r = get(f"/api/preview/d{day}/no-such-key")
    _check(out, "an unknown preview key is 404", r.status_code == 404, f"{r.status_code}")


def _table(out: list[Check], get: Get, path: str, edge: bool):
    """A cached table: 200 with an ETag, 304 when asked again with it, and on the edge a
    cache hit the second time. Returns the first response (None when it failed)."""
    r = get(path)
    if not _check(out, path, r.status_code == 200, f"{r.status_code}: {r.text[:200]}"):
        return None
    etag = r.headers.get("etag")
    if _check(out, f"{path} has an ETag", bool(etag), "none"):
        again = get(path, headers={"If-None-Match": etag})
        _check(out, f"{path} revalidates (304)", again.status_code == 304, f"{again.status_code}")
    if edge:
        hit = get(path).headers.get("cf-cache-status", "")
        _check(out, f"{path} is an edge cache hit", hit == "HIT", hit or "no cf-cache-status")
    return r
