"""A stand-in for GGG's exchange API and poe.ninja, for the Railway simulation.

The simulated pipeline talks only to this (its network has no route out), so the
simulation never sends a request to the real servers. It serves:
- exchange pages from the pages already on disk (mounted read-only at PAGES), with
  GGG's rules: an hour at or after the simulated "now" is still being traded (its
  `next_change_id` is itself, the end of the stream);
- poe.ninja's leagues list and the reference sources (RePoE, the loot filter): a
  conditional request answers 304 Not Modified, as the real ones do when nothing
  changed; an unconditional one gets the stored copy (REFERENCE, exported by seed).

Every request is counted by kind: what the hosted pipeline would have cost GGG and
poe.ninja. Control: POST /_sim/now?ts=<unix> sets the clock, GET /_sim/stats reads
the counts."""

import gzip
import json
import os
from collections import Counter
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response

PAGES = Path(os.environ.get("SIM_PAGES", "/pages"))
# The league switch replay crosses days no page was recorded for (between leagues,
# where only Standard and events trade): those hours are served as finished, empty
# pages instead of 404s, so "the league isn't trading" is answered the real way.
REFERENCE = Path(os.environ.get("SIM_REFERENCE", "/sim-cache/reference.json"))
HOUR = 3600

app = FastAPI(title="ExiledBroker upstream stand-in")
state: dict = {"now": None}
counts: Counter = Counter()
log: list[dict] = []


def _reference() -> dict:
    return json.loads(REFERENCE.read_text()) if REFERENCE.exists() else {}


def _conditional(request: Request) -> bool:
    return "if-none-match" in request.headers or "if-modified-since" in request.headers


def _count(kind: str, **extra) -> None:
    counts[kind] += 1
    log.append({"kind": kind, **extra})
    del log[:-5000]  # keep the recent ones


@app.post("/_sim/now")
def set_now(ts: int, missing_empty: bool = False) -> dict:
    state["now"], state["missing_empty"] = ts, missing_empty
    return {"now": ts}


@app.get("/_sim/stats")
def stats() -> dict:
    return {"now": state["now"], "counts": dict(counts), "recent": log[-50:]}


@app.post("/_sim/reset")
def reset() -> dict:
    counts.clear()
    log.clear()
    return {"ok": True}


@app.get("/api/currency-exchange/{ts}")
def exchange_page(ts: int) -> Response:
    if ts % HOUR:
        raise HTTPException(400, "not an hour")
    now = state["now"]
    if now is None or ts >= now - now % HOUR:
        _count("exchange_unfinished", ts=ts)
        body = {"next_change_id": ts, "markets": []}
        return Response(json.dumps(body), media_type="application/json")
    path = PAGES / f"{ts}.json.gz"
    if not path.exists() and state.get("missing_empty"):
        _count("exchange_empty", ts=ts)
        body = {"next_change_id": ts + HOUR, "markets": []}
        return Response(json.dumps(body), media_type="application/json")
    if not path.exists():
        _count("exchange_missing", ts=ts)
        raise HTTPException(404, f"no recorded page for {ts}")
    _count("exchange_page", ts=ts)
    return Response(gzip.decompress(path.read_bytes()), media_type="application/json")


@app.get("/ninja/poe1/api/economy/leagues")
def leagues(request: Request) -> Response:
    if _conditional(request):
        _count("ninja_304", path="leagues")
        return Response(status_code=304)
    _count("ninja_200", path="leagues")
    return Response(json.dumps(_reference()["poe_ninja/leagues"]), media_type="application/json")


@app.get("/ninja/poe1/api/economy/exchange/current/overview")
def overview(request: Request, league: str, type: str) -> Response:
    if _conditional(request):
        _count("ninja_304", path=f"overview {type}")
        return Response(status_code=304)
    _count("ninja_200", path=f"overview {type}")
    names = _reference()[f"core_pool/type/{type}"]["names"]
    return Response(
        json.dumps({"items": [{"name": n} for n in names]}), media_type="application/json"
    )


@app.get("/repoe/base_items.min.json")
def repoe(request: Request) -> Response:
    if _conditional(request):
        _count("reference_304", path="repoe")
        return Response(status_code=304)
    _count("reference_200", path="repoe")
    return Response(json.dumps(_reference()["repoe/base_items"]), media_type="application/json")


@app.get("/filter/{name}")
def loot_filter(request: Request, name: str) -> Response:
    if _conditional(request):
        _count("reference_304", path="filter")
        return Response(status_code=304)
    # The raw filter isn't kept (only the tiers parsed from it): this shouldn't happen
    # with a seeded volume, so it's counted and refused rather than faked.
    _count("reference_missing", path="filter")
    raise HTTPException(404, "the raw loot filter isn't stored")
