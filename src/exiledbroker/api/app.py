from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from exiledbroker import __version__
from exiledbroker.config import get_settings
from exiledbroker.services import overview, prices
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

    @app.get("/api/leagues")
    def get_leagues() -> list[dict]:
        with db.session(read_only=True) as con:
            return overview.league_calendar(con).to_dicts()

    @app.get("/api/leagues/{league}/items/{item}/curve")
    def get_item_curve(league: str, item: str, max_day: int = 30) -> list[dict]:
        with db.session(read_only=True) as con:
            if league not in overview.leagues_with_prices(con):
                raise HTTPException(404, f"no price data for league {league!r}")
            return prices.item_curve(con, league, item, max_day).to_dicts()

    return app


app = create_app()
