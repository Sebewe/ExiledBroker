"""`eb perf report`: measure the site's API on the local data, and keep a dated history.

Local only (it isn't part of the site). Each report measures:
- what every endpoint the site's pages call reads from the database on a cold call
  (cache empty): queries, rows, bytes, time, response size, and which functions read
  the most;
- what is stored: rows per table, overall and for the leagues that would be hosted
  (the running ones), and the database file size;
- what the live worker has cost lately (ingest_run).

Reports are saved to `data/perf/<date>.json` and compared with the previous one, so a
change that makes an endpoint read much more shows up. The same measurements are
asserted as budgets on the replay fixture in tests/test_performance.py."""

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from exiledbroker.config import Settings
from exiledbroker.storage import db

# What each page of the site calls, with its default settings ({league}: the newest).
ENDPOINTS = {
    "status": "/api/status",
    "market recap": "/api/missed/{league}",
    "launch picks": "/api/launch/picks",
    "backtest": "/api/backtest",
    "price check": "/api/price-check/{league}",
    # The list's first mover (else its first item): what a visitor most likely opens.
    "price check item": "/api/price-check/{league}/{item}",
}
TABLES = ["price_observation", "cross_market_hour", "exchange_hour_loaded", "item"]
# Reads that grew more than this since the previous report are flagged.
GROWTH_FLAG = 1.25


def _summary(meter: db.Meter, wall_ms: float, response_bytes: int) -> dict:
    top = sorted(meter.by_caller().values(), key=lambda q: -q.bytes)[:5]
    return {
        "queries": len(meter.queries),
        "rows": meter.rows,
        "bytes": meter.bytes,
        "response_bytes": response_bytes,
        "query_ms": round(meter.ms, 1),
        "wall_ms": round(wall_ms, 1),
        "top": [
            {"caller": q.caller, "rows": q.rows, "bytes": q.bytes, "ms": round(q.ms, 1)}
            for q in top
        ],
    }


def _first_item(client, league: str) -> str | None:
    """The Price check list's first mover, else its first item (None without a list)."""
    r = client.get(f"/api/price-check/{league}")
    if r.status_code != 200:
        return None
    doc = r.json()
    ids = doc.get("movers") or [x["item_id"] for x in doc.get("items", [])]
    return ids[0] if ids else None


def measure_pages() -> dict[str, dict]:
    """A cold call (empty cache) of each endpoint the site's pages use."""
    from fastapi.testclient import TestClient

    from exiledbroker.api import app as app_module
    from exiledbroker.api import deps

    client = TestClient(app_module.create_app())
    deps.reset()
    leagues = client.get("/api/status").json().get("leagues", [])
    league = leagues[0]["name"] if leagues else "none"
    item = _first_item(client, league)
    out = {}
    for name, path in ENDPOINTS.items():
        if "{item}" in path and item is None:
            continue  # no league traded yet, or no Price check list
        deps.reset()
        started = time.perf_counter()
        with db.metered() as meter:
            r = client.get(
                path.format(league=league, item=item), headers={"Accept-Encoding": "identity"}
            )
        out[name] = _summary(meter, (time.perf_counter() - started) * 1000, len(r.content))
        if r.status_code != 200:
            out[name]["error"] = [f"{r.status_code}: {r.text[:200]}"]
    return out


def measure_storage(settings: Settings) -> dict:
    """Rows per table: all of them, and the newest league's (what would be hosted)."""
    from exiledbroker.services.live import live_leagues

    with db.session(settings.db_path, read_only=True) as con:
        leagues = live_leagues(con)
        hosted = leagues["name"][0] if leagues.height else None
        tables = {}
        for table in TABLES:
            total = db.scalar(con, f"SELECT count(*) FROM {table}")
            if table == "item":
                # A hosted database gets only the items its league's rows refer to (the
                # exchange loader inserts no others); local dumps add every past unique.
                mine = db.scalar(
                    con,
                    """
                    SELECT count(*) FROM item WHERE id IN (
                        SELECT item_id FROM price_observation
                        WHERE league_id = (SELECT id FROM league WHERE name = ?)
                        UNION SELECT item_id FROM cross_market_hour
                        WHERE league_id = (SELECT id FROM league WHERE name = ?))
                    """,
                    [hosted, hosted],
                )
                tables[table] = {"rows": total, "hosted_rows": mine}
                continue
            mine = db.scalar(
                con,
                f"SELECT count(*) FROM {table} "
                "WHERE league_id = (SELECT id FROM league WHERE name = ?)",
                [hosted],
            )
            tables[table] = {"rows": total, "hosted_rows": mine}
    return {"db_bytes": settings.db_path.stat().st_size, "hosted_league": hosted, "tables": tables}


def measure_worker(settings: Settings, days: int = 7) -> dict | None:
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    with db.session(settings.db_path, read_only=True) as con:
        exists = db.scalar(
            con,
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'ingest_run'",
        )
        if not exists:  # no live update since the table was added
            return None
        rows = db.rows(
            con,
            """
            SELECT count(*), count(*) FILTER (WHERE state = 'failed'),
                avg(requests), avg(bytes_received), avg(seconds), avg(rows_added),
                max(seconds), max(bytes_received)
            FROM ingest_run WHERE started_at >= ?
            """,
            [since],
        )[0]
    if not rows[0]:
        return None
    keys = ["runs", "failed", "avg_requests", "avg_bytes", "avg_seconds", "avg_rows_added"]
    keys += ["max_seconds", "max_bytes"]
    return {"days": days} | {
        k: round(v, 2) if isinstance(v, float) else v for k, v in zip(keys, rows, strict=True)
    }


def report(settings: Settings) -> dict:
    return {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "pages": measure_pages(),
        "storage": measure_storage(settings),
        "worker": measure_worker(settings),
    }


def perf_dir(settings: Settings) -> Path:
    return settings.data_dir / "perf"


def previous(settings: Settings) -> dict | None:
    files = sorted(perf_dir(settings).glob("*.json"))
    return json.loads(files[-1].read_text()) if files else None


def save(settings: Settings, rep: dict) -> Path:
    d = perf_dir(settings)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{rep['at'][:19].replace(':', '')}.json"  # several a day are kept
    path.write_text(json.dumps(rep, indent=2))
    return path


def flags(rep: dict, prev: dict | None) -> list[str]:
    """Pages whose reads grew noticeably since the previous report, and failures."""
    out = []
    for page, now in rep["pages"].items():
        if "error" in now:
            out.append(f"{page}: page raised {now['error']}")
        before = (prev or {}).get("pages", {}).get(page)
        for key in ("rows", "bytes"):
            if before and before[key] and now[key] > before[key] * GROWTH_FLAG:
                out.append(f"{page}: {key} {before[key]:,} → {now[key]:,}")
    worker = rep.get("worker")
    if worker and worker["failed"]:
        out.append(f"worker: {worker['failed']} of {worker['runs']} updates failed")
    return out


def render(rep: dict, prev: dict | None) -> str:
    def size(n: float) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:,.0f} {unit}"
            n /= 1024
        return f"{n:,.1f} TB"

    lines = [f"Performance report {rep['at']}", "", "Endpoint reads (cold call, empty cache):"]
    for page, m in rep["pages"].items():
        lines.append(
            f"  {page:<20} {m['queries']:>3} queries {m['rows']:>9,} rows "
            f"{size(m['bytes']):>9} read, {size(m.get('response_bytes', 0)):>9} sent, "
            f"{m['wall_ms']:>6,.0f} ms"
        )
        biggest = m["top"][0] if m["top"] else None
        if biggest and biggest["bytes"] > 0.5 * m["bytes"] and m["bytes"] > 100_000:
            lines.append(f"  {'':<26} mostly {biggest['caller']}")
    s = rep["storage"]
    lines += ["", f"Storage: {size(s['db_bytes'])} on disk; hosted league {s['hosted_league']}"]
    for table, t in s["tables"].items():
        lines.append(f"  {table:<22} {t['rows']:>12,} rows  ({t['hosted_rows']:,} hosted)")
    w = rep["worker"]
    lines += [""]
    if w:
        lines.append(
            f"Live worker, last {w['days']} days: {w['runs']} updates ({w['failed']} failed); "
            f"per update {w['avg_requests']} requests, {size(w['avg_bytes'] or 0)}, "
            f"{w['avg_seconds']} s, {w['avg_rows_added']} rows added "
            f"(max {w['max_seconds']} s, {size(w['max_bytes'] or 0)})"
        )
    else:
        lines.append("Live worker: no recorded updates in the last 7 days.")
    found = flags(rep, prev)
    lines += ["", "Flags:" if found else "No flags."]
    lines += [f"  - {f}" for f in found]
    return "\n".join(lines)
