"""Keeping the API cheap to abuse: only Cloudflare may reach the origin, and one visitor
can't make it compute more than a reasonable share.

The site sits behind Cloudflare (deploy/cloudflare/), which caches the tables at the
edge and rate-limits per visitor. Railway's own *.up.railway.app address is public,
though, and a script pointed at it would skip both. With `EB_ORIGIN_KEY` set, a
Cloudflare transform rule adds that key to every request it forwards, and `RequireEdgeKey`
answers 403 to anything without it (docs/go-live.md). Behind that check the visitor's
address (Cloudflare's CF-Connecting-IP, passed on by the Worker) can be trusted, so
`PerClientLimit` caps each one's /api requests a minute. Both are plain ASGI and answer before any route runs: a
rejected request costs no database query and no thread."""

import hmac
import json
import threading
import time

KEY_HEADER = b"x-eb-origin-key"
# The visitor's address: the Worker copies Cloudflare's CF-Connecting-IP into its own
# header (deploy/cloudflare/handler.mjs), since a Worker's request to another host may
# not carry Cloudflare's. Requests that skip the Worker (assets) still have Cloudflare's.
CLIENT_HEADERS = (b"x-eb-client-ip", b"cf-connecting-ip")
# Railway's health check calls the origin directly, without the key.
OPEN_PATHS = frozenset({"/api/health"})
WINDOW = 60.0  # seconds
MAX_CLIENTS = 50_000  # addresses tracked in one window; a flood of new ones resets it


def _header(scope, name: bytes) -> bytes | None:
    for k, v in scope.get("headers", []):
        if k.lower() == name:
            return v
    return None


async def _reject(send, status: int, detail: str, extra: list | None = None) -> None:
    body = json.dumps({"detail": detail}).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        (b"cache-control", b"no-store"),
        *(extra or []),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def _is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


class RequireEdgeKey:
    """403 for requests that didn't come through Cloudflare (no or wrong
    X-EB-Origin-Key), when a key is configured. /api/health stays open."""

    def __init__(self, app, key: str | None):
        self.app = app
        self.key = key.encode() if key else None

    async def __call__(self, scope, receive, send):
        if (
            self.key is None
            or scope["type"] != "http"
            or scope["path"] in OPEN_PATHS
            or hmac.compare_digest(_header(scope, KEY_HEADER) or b"", self.key)
        ):
            return await self.app(scope, receive, send)
        await _reject(send, 403, "forbidden")


class PerClientLimit:
    """At most `limit` /api requests a minute per visitor (fixed one-minute windows),
    then 429 with Retry-After. Keyed on the visitor's address (CLIENT_HEADERS), so only
    use it behind `RequireEdgeKey`; a request without one isn't counted."""

    def __init__(self, app, limit: int):
        self.app = app
        self.limit = limit
        self._lock = threading.Lock()
        self._window = 0
        self._counts: dict[bytes, int] = {}

    def allow(self, client: bytes, now: float | None = None) -> bool:
        window = int((time.time() if now is None else now) // WINDOW)
        with self._lock:
            if window != self._window or len(self._counts) >= MAX_CLIENTS:
                self._window, self._counts = window, {}
            n = self._counts.get(client, 0) + 1
            self._counts[client] = n
            return n <= self.limit

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and _is_api(scope["path"]) and scope["path"] not in OPEN_PATHS:
            client = next(filter(None, (_header(scope, h) for h in CLIENT_HEADERS)), None)
            if client is not None and not self.allow(client):
                retry = str(int(WINDOW - time.time() % WINDOW) + 1).encode()
                return await _reject(
                    send, 429, "too many requests, slow down", [(b"retry-after", retry)]
                )
        await self.app(scope, receive, send)
