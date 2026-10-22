import httpx
import pytest

from exiledbroker.config import Settings
from exiledbroker.ingest.http import PoliteClient, download, is_complete, part_path_for

PAYLOAD = bytes(range(256)) * 400  # 100 KB
URL = "https://example.test/file.zip"


class RangeServer:
    """Mock server supporting Range/If-Range, optionally dropping the first response."""

    def __init__(self, payload=PAYLOAD, last_modified="Tue, 10 Jun 2025 17:24:42 GMT"):
        self.payload = payload
        self.last_modified = last_modified
        self.drop_after: int | None = None
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        start = 0
        rng = request.headers.get("Range")
        if rng and request.headers.get("If-Range") == self.last_modified:
            start = int(rng.removeprefix("bytes=").rstrip("-"))
        body = self.payload[start:]
        headers = {"Last-Modified": self.last_modified, "Content-Length": str(len(body))}
        stream = body
        if self.drop_after is not None:
            cut, self.drop_after = self.drop_after, None
            stream = DroppingStream(body, cut)
        return httpx.Response(206 if start else 200, headers=headers, stream=_as_stream(stream))


class DroppingStream(httpx.SyncByteStream):
    def __init__(self, body: bytes, cut: int):
        self.body, self.cut = body, cut

    def __iter__(self):
        yield self.body[: self.cut]
        raise httpx.ReadError("connection dropped")


def _as_stream(body):
    return body if isinstance(body, httpx.SyncByteStream) else httpx.ByteStream(body)


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, request_min_interval=0, http_retries=2)


def make_client(settings, server):
    client = PoliteClient(settings, transport=httpx.MockTransport(server.handler))
    client.backoff = lambda *a, **k: None
    return client


def test_download_completes_and_marks(settings, tmp_path):
    server = RangeServer()
    dest = tmp_path / "f.zip"
    with make_client(settings, server) as client:
        result = download(client, URL, dest)
    assert not result.skipped and dest.read_bytes() == PAYLOAD and is_complete(dest)
    assert not part_path_for(dest).exists()


def test_completed_download_is_not_refetched(settings, tmp_path):
    server = RangeServer()
    dest = tmp_path / "f.zip"
    with make_client(settings, server) as client:
        download(client, URL, dest)
        assert download(client, URL, dest).skipped
    assert len(server.requests) == 1


def test_dropped_connection_resumes_with_range(settings, tmp_path):
    server = RangeServer()
    server.drop_after = 30_000
    dest = tmp_path / "f.zip"
    with make_client(settings, server) as client:
        result = download(client, URL, dest)
    assert dest.read_bytes() == PAYLOAD
    assert result.resumed_from == 30_000
    assert server.requests[1].headers["Range"] == "bytes=30000-"


def test_resume_across_processes(settings, tmp_path):
    """A partial left by an interrupted run is continued by the next run."""
    server = RangeServer()
    server.drop_after = 50_000
    dest = tmp_path / "f.zip"
    no_retry = Settings(data_dir=tmp_path, request_min_interval=0, http_retries=0)
    with make_client(no_retry, server) as client, pytest.raises(httpx.ReadError):
        download(client, URL, dest)
    assert part_path_for(dest).stat().st_size == 50_000

    with make_client(settings, server) as client:
        result = download(client, URL, dest)
    assert result.resumed_from == 50_000 and dest.read_bytes() == PAYLOAD


def test_changed_upstream_file_restarts_from_zero(settings, tmp_path):
    server = RangeServer()
    server.drop_after = 50_000
    dest = tmp_path / "f.zip"
    no_retry = Settings(data_dir=tmp_path, request_min_interval=0, http_retries=0)
    with make_client(no_retry, server) as client, pytest.raises(httpx.ReadError):
        download(client, URL, dest)

    server.payload = b"new version" * 1000
    server.last_modified = "Wed, 11 Jun 2025 00:00:00 GMT"
    with make_client(settings, server) as client:
        result = download(client, URL, dest)
    assert result.resumed_from == 0 and dest.read_bytes() == server.payload


def test_failed_verification_discards_partial(settings, tmp_path):
    server = RangeServer()
    dest = tmp_path / "f.zip"

    def reject(path):
        raise ValueError("bad file")

    with make_client(settings, server) as client, pytest.raises(ValueError):
        download(client, URL, dest, verify=reject)
    assert not dest.exists() and not part_path_for(dest).exists()
