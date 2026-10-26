"""The site's JSON API. It only reads, through `services/`, from the site's database
(Postgres at EB_DATABASE_URL, or the local DuckDB file). Tables are computed once per
data version and served as cached bytes (api/deps.py), the defaults precomputed in the
background (api/warm.py). The built frontend (web/dist), when present, is served too."""

import mimetypes
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse

from exiledbroker import __version__
from exiledbroker.api.routes import live, market, price_check
from exiledbroker.config import get_settings

ORIGIN_HEADER = b"x-eb-origin"


class MarkOrigin:
    """Stamps `X-EB-Origin: app` on every response this app sends (API, static files,
    errors, 304s). Cloudflare's fallback Worker (deploy/cloudflare/) uses it to tell the
    app's own 503/404/422 answers from Railway's edge errors: a 5xx without it means the
    origin is down. Plain ASGI, so bodies are streamed untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_marked(message):
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), (ORIGIN_HEADER, b"app")]
            await send(message)

        await self.app(scope, receive, send_marked)


class ApiNoStoreByDefault:
    """`Cache-Control: no-store` on every /api response that doesn't set its own: errors
    (503 no data yet, 404, 422) and /api/health. Cloudflare's Worker caches what the
    origin's Cache-Control allows (deploy/cloudflare/), and a response without one would
    get Cloudflare's default edge TTL (2 hours for a 200, minutes for a 404). The tables
    and the status set their own (api/deps.py, routes/live.py)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not (
            scope["path"] == "/api" or scope["path"].startswith("/api/")
        ):
            return await self.app(scope, receive, send)

        async def send_defaulted(message):
            if message["type"] == "http.response.start":
                headers = message.get("headers", [])
                if not any(k.lower() == b"cache-control" for k, _ in headers):
                    message["headers"] = [*headers, (b"cache-control", b"no-store")]
            await send(message)

        await self.app(scope, receive, send_defaulted)


def create_app(web_dist: Path | None = None) -> FastAPI:
    settings = get_settings()
    web_dist = web_dist or settings.web_dist

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Precompute the pages' default tables whenever new data is loaded (api/warm.py).
        stop = threading.Event()
        if settings.api_warm:
            from exiledbroker.api import warm

            threading.Thread(target=warm.run_forever, args=(stop,), daemon=True).start()
        yield
        stop.set()

    app = FastAPI(title="ExiledBroker", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    # Tables arrive pre-gzipped from the cache (api/deps.py); this covers the rest.
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(ApiNoStoreByDefault)
    app.add_middleware(MarkOrigin)  # outermost, so it covers every response
    api = APIRouter(prefix="/api")

    @api.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "game": settings.default_game}

    for routes in (live, market, price_check):
        api.include_router(routes.router)
    app.include_router(api)

    if (web_dist / "index.html").exists():
        # The single-page app: real files as they are, any other path gets index.html
        # (client-side routes). /api/* never falls through to it.
        # Built files under assets/ have a content hash in their name, so browsers keep
        # them for a year; index.html (which names them) is revalidated on every visit.
        # The Dockerfile gzips the build once: the .gz is sent when the browser takes it.
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str, request: Request):
            if path == "api" or path.startswith("api/"):
                raise HTTPException(404, "not found")
            file = (web_dist / path).resolve()
            if not (path and file.is_file() and file.is_relative_to(web_dist.resolve())):
                file = web_dist / "index.html"
            immutable = file.parent.name == "assets" and file.parent.parent == web_dist.resolve()
            headers = {
                "Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache"
            }
            gz = file.with_name(file.name + ".gz")
            if "gzip" in request.headers.get("accept-encoding", "") and gz.is_file():
                media_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                headers |= {"Content-Encoding": "gzip", "Vary": "Accept-Encoding"}
                return FileResponse(gz, media_type=media_type, headers=headers)
            return FileResponse(file, headers=headers)

    return app


app = create_app()
