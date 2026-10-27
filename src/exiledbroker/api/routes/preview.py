"""The pre-launch preview (docs/preview.md): the site rewound to a past league's early
days, from the snapshot `eb preview build` writes (preview/snapshot.py). One bounded
route: it sends a stored document as it is, and answers 404 for any key the snapshot
doesn't hold, so no visitor can make it compute anything. /api/status says whether the
preview is on (`status_preview`), which turns it off by itself once the announced
league's first trades are loaded."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi import Path as PathParam

from exiledbroker.api import deps
from exiledbroker.api.cache import previews, results
from exiledbroker.api.deps import Payload
from exiledbroker.api.models import (
    LaunchWindow,
    MissedWindow,
    PreviewGameHour,
    PreviewItemNext,
    PreviewManifest,
    PreviewRecapNext,
    PriceCheckIndex,
    PriceCheckItem,
)
from exiledbroker.preview import snapshot

router = APIRouter(tags=["preview"])

# A document never changes under its URL's `v` (the snapshot's version): browsers and
# Cloudflare's edge keep it a day. Any other `v` gets the tables' short revalidation.
PREVIEW_CACHE_CONTROL = "public, max-age=86400"

# What /api/preview/{key} can send, by key (preview/snapshot.py): typed for the frontend.
PreviewDocument = (
    PreviewManifest
    | PreviewRecapNext
    | PreviewItemNext
    | PreviewGameHour
    | PriceCheckIndex
    | PriceCheckItem
    | list[MissedWindow]
    | list[LaunchWindow]
)


@dataclass(frozen=True)
class Index:
    keys: frozenset[str]
    manifest: PreviewManifest | None


def index() -> Index:
    """The snapshot's keys and manifest: read once per data version (an hour), so a
    request for a key it doesn't hold costs no query."""

    def build() -> Index:
        for con in deps.connection():
            keys = snapshot.keys(con)
            doc = snapshot.read(con, snapshot.MANIFEST) if snapshot.MANIFEST in keys else None
        manifest = PreviewManifest.model_validate(doc) if doc else None
        return Index(frozenset(keys), manifest)

    return results.get_or_compute(("preview_index", (), deps.data_version()), build)


def status_preview(upcoming: dict | None) -> PreviewManifest | None:
    """The manifest while the preview is on: EB_PREVIEW "on", or "auto" (the default)
    while a next league is announced and has no trades yet."""
    mode = deps.settings().preview
    if mode == "off" or (mode == "auto" and upcoming is None):
        return None
    return index().manifest


Key = Annotated[
    str,
    PathParam(
        max_length=snapshot.MAX_KEY,
        description="`manifest`, `d{day}/missed`, `d{day}/price-check`, "
        "`d{day}/price-check/{item_id}`, `d{day}/launch-picks`, `d{day}/recap-next` or "
        "`next/price-check/{item_id}`; 404 unless the snapshot holds it.",
    ),
]


@router.get("/preview/{key:path}", response_model=PreviewDocument)
def preview_document(request: Request, key: Key, v: deps.Version = None) -> Response:
    """One document of the pre-launch preview's snapshot, as built: the pages' data on
    one of the preview's days, or what happened next. Send the manifest's `version` as
    `v`; such a response is cached for a day."""
    found = index()
    if key not in found.keys or snapshot.model_for(key) is None:
        raise HTTPException(404, f"the preview has no {key!r}")
    version = found.manifest.version if found.manifest else ""

    def load() -> Payload:
        for con in deps.connection():
            body = snapshot.body(con, key)
        if body is None:  # rebuilt since the index was read
            raise HTTPException(404, f"the preview has no {key!r}")
        return Payload([], None, body, deps.etag_of(body))

    p = previews.get_or_compute((key, version), load)
    current = bool(version) and v == version
    return deps.send(request, p, PREVIEW_CACHE_CONTROL if current else deps.CACHE_CONTROL)
