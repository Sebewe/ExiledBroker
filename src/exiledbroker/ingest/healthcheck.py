"""A dead-man's-switch ping for the hosted pipeline (healthchecks.io or any service
with the same URLs): `<url>/start` when a pass begins, `<url>` when it succeeded,
`<url>/fail` when it didn't, each with a short plain-text body. The service emails when
a ping says fail or when no ping arrives within its period plus grace, which also
catches a cron that never ran (Railway stopped by its usage limit, a broken deploy).

This is the user's own monitoring service, not GGG or poe.ninja, so it doesn't go
through `PoliteClient` (no 1 s spacing or long backoff), but it must never break or slow
a pass: a few seconds' timeout, one retry, every error swallowed and logged. The URL is
a secret (anyone with it can ping the check), so errors never repeat it.
"""

import logging
from types import TracebackType
from typing import Self

import httpx

from exiledbroker.config import Settings

log = logging.getLogger(__name__)

TIMEOUT = 5.0  # seconds; a pass doesn't wait on its monitor
ATTEMPTS = 2  # one retry
BODY_MAX = 4000  # characters kept of a ping's body (healthchecks.io keeps 100 kB)


class Healthcheck:
    """Pings one check's URL. Falsy when no URL is set, and then makes no request.
    `errors` collects what failed to send, for the pass's result line."""

    def __init__(
        self,
        url: str | None,
        user_agent: str = "",
        transport: httpx.BaseTransport | None = None,
    ):
        self.url = url.rstrip("/") if url else None
        self.errors: list[str] = []
        self._client = (
            httpx.Client(
                headers={"User-Agent": user_agent} if user_agent else {},
                timeout=TIMEOUT,
                follow_redirects=True,
                transport=transport,
            )
            if self.url
            else None
        )

    @classmethod
    def from_settings(
        cls, settings: Settings, transport: httpx.BaseTransport | None = None
    ) -> Self:
        return cls(settings.healthcheck_url, settings.user_agent, transport)

    def __bool__(self) -> bool:
        return self.url is not None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def start(self) -> None:
        """The pass began (healthchecks.io then shows how long it ran, and a pass that
        starts and never reports fails after the grace period)."""
        self._ping("/start", "")

    def success(self, body: str = "") -> None:
        self._ping("", body)

    def fail(self, body: str = "") -> None:
        self._ping("/fail", body)

    def _ping(self, suffix: str, body: str) -> None:
        if self._client is None or self.url is None:
            return
        error = ""
        for _ in range(ATTEMPTS):
            try:
                response = self._client.post(
                    self.url + suffix, content=body[:BODY_MAX].encode("utf-8", "replace")
                )
                response.raise_for_status()
                return
            except httpx.HTTPStatusError as e:
                error = f"HTTP {e.response.status_code}"
            except Exception as e:  # noqa: BLE001 (any failure: DNS, timeout, a closed socket)
                error = type(e).__name__  # not str(e): httpx errors can name the URL
        what = suffix.lstrip("/") or "success"
        log.warning("Healthcheck %s ping failed: %s", what, error)
        self.errors.append(f"{what} ping: {error}")
