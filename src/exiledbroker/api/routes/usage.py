"""Usage counts (api/usage.py): the pages' beacon and the owner's stats. The beacon
takes one event from a fixed list and never reads the database; the stats answer only
with the admin token (EB_ADMIN_TOKEN)."""

import hmac
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response

from exiledbroker.api import deps
from exiledbroker.api import usage as counting

router = APIRouter(tags=["usage"])


@router.post("/hit", status_code=204)
def hit(
    request: Request,
    e: Annotated[str, Query(max_length=40, description="A page (`page:/launch`) or feature.")],
) -> Response:
    """Count a page view or a feature's use. No cookies, nothing stored in the browser;
    Do-Not-Track and Global Privacy Control are honoured. Always 204."""
    counter = getattr(request.app.state, "usage", None)
    if counter is not None and not counting.opted_out(request.headers):
        counter.record(e, counting.client_ip(request), request.headers.get("user-agent", ""))
    return Response(status_code=204)


@router.get("/stats")
def stats(request: Request, authorization: Annotated[str | None, Header()] = None) -> dict:
    """Visitors, returning visitors and each page's and feature's use, for the site's
    owner (`Authorization: Bearer <EB_ADMIN_TOKEN>`; without the setting, 404)."""
    expected = deps.settings().admin_token
    given = (authorization or "").removeprefix("Bearer ").strip()
    counter = getattr(request.app.state, "usage", None)
    if not expected or counter is None or not hmac.compare_digest(given, expected):
        raise HTTPException(404, "not found")
    return counter.stats()
