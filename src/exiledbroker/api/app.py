"""The site's JSON API. It only reads, through `services/`, from the site's database
(Postgres at EB_DATABASE_URL, or the local DuckDB file). Tables are computed once per
data version and served as cached bytes (api/deps.py), the defaults precomputed in the
background (api/warm.py). The built frontend (web/dist), when present, is served too."""

import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse

from exiledbroker import __version__
from exiledbroker.api.routes import live, market, trading
from exiledbroker.config import get_settings


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
    api = APIRouter(prefix="/api")

    @api.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "game": settings.default_game}

    for routes in (live, trading, market):
        api.include_router(routes.router)
    app.include_router(api)

    if (web_dist / "index.html").exists():
        # The single-page app: real files as they are, any other path gets index.html
        # (client-side routes). /api/* never falls through to it.
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path == "api" or path.startswith("api/"):
                raise HTTPException(404, "not found")
            file = (web_dist / path).resolve()
            if path and file.is_file() and file.is_relative_to(web_dist.resolve()):
                return FileResponse(file)
            return FileResponse(web_dist / "index.html")

    return app


app = create_app()
