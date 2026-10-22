from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from exiledbroker import __version__
from exiledbroker.config import get_settings
from exiledbroker.services import overview
from exiledbroker.storage import db


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="ExiledBroker", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "game": settings.default_game}

    @app.get("/api/overview")
    def get_overview() -> dict[str, int]:
        with db.session(read_only=True) as con:
            return overview.table_counts(con)

    return app


app = create_app()
