"""The admin page's API (/admin; docs/admin.md): the site's usage counts and the
pipeline's health, for the site's owner only. There is no user system: one long token
from EB_ADMIN_TOKEN, sent as `Authorization: Bearer <token>`. Unset, every admin route
answers 404, as if it didn't exist. Responses are never cached (`no-store`), by the
browser or Cloudflare. A wrong token is refused before the database is touched, so
guessing costs the server nothing but the request."""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response

from exiledbroker.api import deps
from exiledbroker.api.models import AdminOverview
from exiledbroker.services import pipeline_health
from exiledbroker.storage import db

NO_STORE = "no-store, private"


def require_admin(authorization: Annotated[str | None, Header()] = None) -> None:
    """Every admin route depends on this."""
    token = deps.settings().admin_token
    if token is None:
        raise HTTPException(404, "not found")
    scheme, _, given = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        given.strip().encode(), token.get_secret_value().encode()
    ):
        raise HTTPException(401, "admin token required", {"WWW-Authenticate": "Bearer"})


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _has(con, table: str) -> bool:
    return bool(
        db.scalar(
            con, "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]
        )
    )


@router.get("/overview", response_model=AdminOverview)
def overview(response: Response) -> dict:
    """The pipeline's health per league. Read from the database on every request: only
    the admin calls it, and it's a few small aggregates."""
    response.headers["Cache-Control"] = NO_STORE
    settings = deps.settings()
    now = deps.now_utc()
    pipeline, version = [], None
    if settings.database_url or settings.db_path.exists():
        with db.site_session(settings) as con:
            if _has(con, "ingest_run"):
                pipeline = deps.records(pipeline_health.summary(con, now.replace(tzinfo=None)))
            if _has(con, "ingest_load"):
                version = deps.data_version()
    return {"now": now, "data_version": version, "pipeline": pipeline}
