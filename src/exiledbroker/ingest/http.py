import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import httpx

from exiledbroker.config import Settings
from exiledbroker.ingest.files import read_json, write_json_atomic

RETRYABLE_STATUS = {429, 500, 502, 503, 504}

ProgressFn = Callable[[int, int | None], None]


class PoliteClient:
    """httpx client that spaces out requests and retries transient failures."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self._client = httpx.Client(
            headers={"User-Agent": settings.user_agent},
            timeout=settings.http_timeout,
            follow_redirects=True,
            transport=transport,
        )
        self._last_request = 0.0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self._client.close()

    def throttle(self) -> None:
        wait = self._last_request + self.settings.request_min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def backoff(self, attempt: int, response: httpx.Response | None = None) -> None:
        delay = min(2**attempt, 60)
        if response is not None and (retry_after := response.headers.get("Retry-After")):
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass
        time.sleep(delay)

    def get_json(self, url: str) -> object:
        return self._get(url).json()

    def get_text(self, url: str) -> str:
        return self._get(url).text

    def _get(self, url: str) -> httpx.Response:
        for attempt in range(self.settings.http_retries + 1):
            self.throttle()
            try:
                r = self._client.get(url)
            except httpx.TransportError:
                if attempt == self.settings.http_retries:
                    raise
                self.backoff(attempt)
                continue
            if r.status_code in RETRYABLE_STATUS and attempt < self.settings.http_retries:
                self.backoff(attempt, r)
                continue
            r.raise_for_status()
            return r
        raise RuntimeError("unreachable")

    def stream(self, url: str, headers: dict[str, str]):
        self.throttle()
        return self._client.stream("GET", url, headers=headers)


@dataclass
class DownloadResult:
    path: Path
    skipped: bool  # True when the file was already complete locally
    resumed_from: int = 0


def meta_path_for(dest: Path) -> Path:
    return dest.with_name(dest.name + ".meta.json")


def part_path_for(dest: Path) -> Path:
    return dest.with_name(dest.name + ".part")


def is_complete(dest: Path) -> bool:
    return dest.exists() and meta_path_for(dest).exists()


def download(
    client: PoliteClient,
    url: str,
    dest: Path,
    *,
    verify: Callable[[Path], None] | None = None,
    progress: ProgressFn | None = None,
) -> DownloadResult:
    """Download url to dest, resuming a previous partial download if there is one.

    Bytes go to `<dest>.part`; the validator (ETag / Last-Modified) of the response
    that started it goes to `<dest>.part.json`, and resumes send it as If-Range so the
    server restarts from zero if the file changed upstream. On success the part file
    is verified, renamed to dest, and `<dest>.meta.json` is written last as the marker.
    """
    if is_complete(dest):
        return DownloadResult(dest, skipped=True)

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = part_path_for(dest)
    part_meta_path = part.with_name(part.name + ".json")
    resumed_from = 0

    for attempt in range(client.settings.http_retries + 1):
        part_meta = read_json(part_meta_path) or {}
        offset = part.stat().st_size if part.exists() else 0
        validator = part_meta.get("etag") or part_meta.get("last_modified")
        headers = {"Accept-Encoding": "identity"}
        if offset and validator:
            headers["Range"] = f"bytes={offset}-"
            headers["If-Range"] = validator
        else:
            offset = 0

        try:
            with client.stream(url, headers) as r:
                if r.status_code == 416:
                    # Our partial is not a prefix the server recognises; start over.
                    part.unlink(missing_ok=True)
                    continue
                if r.status_code in RETRYABLE_STATUS and attempt < client.settings.http_retries:
                    client.backoff(attempt, r)
                    continue
                r.raise_for_status()

                if r.status_code == 206:
                    mode = "ab"
                    resumed_from = offset
                else:
                    mode, offset = "wb", 0
                    part_meta = {
                        "url": url,
                        "etag": r.headers.get("ETag"),
                        "last_modified": r.headers.get("Last-Modified"),
                    }
                    write_json_atomic(part_meta_path, part_meta)

                length = r.headers.get("Content-Length")
                total = offset + int(length) if length is not None else None
                part_meta["size"] = total
                written = offset
                with open(part, mode) as f:
                    # Write chunks as they arrive, so a dropped connection loses nothing.
                    for chunk in r.iter_raw():
                        f.write(chunk)
                        written += len(chunk)
                        if progress:
                            progress(written, total)
                    f.flush()
                    os.fsync(f.fileno())
        except httpx.TransportError:
            # Connection dropped mid-stream; keep the bytes we have and resume.
            if attempt == client.settings.http_retries:
                raise
            client.backoff(attempt)
            continue

        size = part.stat().st_size
        if total is not None and size != total:
            if attempt == client.settings.http_retries:
                raise OSError(f"incomplete download of {url}: {size} of {total} bytes")
            continue

        if verify:
            try:
                verify(part)
            except Exception:
                part.unlink(missing_ok=True)
                part_meta_path.unlink(missing_ok=True)
                raise
        os.replace(part, dest)
        write_json_atomic(
            meta_path_for(dest),
            {
                "url": url,
                "size": size,
                "etag": part_meta.get("etag"),
                "last_modified": part_meta.get("last_modified"),
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )
        part_meta_path.unlink(missing_ok=True)
        return DownloadResult(dest, skipped=False, resumed_from=resumed_from)

    raise OSError(f"gave up downloading {url}")
