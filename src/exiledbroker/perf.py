"""`eb perf report`: measure the local database and demo, and keep a dated history.

Local only (it isn't part of the site). Each report measures:
- what every page (and analysis tool) reads from the database on a cold view: queries,
  rows, bytes, time, and which functions read the most;
- what is stored: rows per table, overall and for the leagues that would be hosted
  (the running ones), and the database file size;
- what the live worker has cost lately (ingest_run).

Reports are saved to `data/perf/<date>.json` and compared with the previous one, so a
change that makes a page read much more shows up. The same page measurements are
asserted as budgets on the replay fixture in tests/test_performance.py."""

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from exiledbroker.config import Settings
from exiledbroker.storage import db

APP = Path(__file__).resolve().parents[2] / "app" / "dashboard.py"
PAGES = ["live", "market", "cards", "arbitrage", "analysis", "data"]
ANALYSIS_TOOLS = ["Unique moves", "Launch curves", "Group timing", "Card turn-ins"]
TABLES = ["price_observation", "cross_market_hour", "exchange_hour_loaded", "item"]
# Reads that grew more than this since the previous report are flagged.
GROWTH_FLAG = 1.25


def _summary(meter: db.Meter, wall_ms: float) -> dict:
    top = sorted(meter.by_caller().values(), key=lambda q: -q.bytes)[:5]
    return {
        "queries": len(meter.queries),
        "rows": meter.rows,
        "bytes": meter.bytes,
        "query_ms": round(meter.ms, 1),
        "wall_ms": round(wall_ms, 1),
        "top": [
            {"caller": q.caller, "rows": q.rows, "bytes": q.bytes, "ms": round(q.ms, 1)}
            for q in top
        ],
    }


def measure_pages() -> dict[str, dict]:
    """Cold views of every page and analysis tool, through Streamlit's AppTest."""
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    out = {}
    for page in PAGES:
        at = AppTest.from_file(str(APP), default_timeout=300).run()
        st.cache_data.clear()
        started = time.perf_counter()
        with db.metered() as meter:
            at.switch_page(f"app_pages/{page}.py").run()
        out[page] = _summary(meter, (time.perf_counter() - started) * 1000)
        if at.exception:
            out[page]["error"] = [e.message for e in at.exception]
        if page == "analysis" and at.get("button_group"):
            for tool in ANALYSIS_TOOLS:
                st.cache_data.clear()
                started = time.perf_counter()
                with db.metered() as meter:
                    at.get("button_group")[0].set_value(tool).run()
                out[f"analysis: {tool}"] = _summary(meter, (time.perf_counter() - started) * 1000)
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

    lines = [f"Performance report {rep['at']}", "", "Page reads (cold view):"]
    for page, m in rep["pages"].items():
        lines.append(
            f"  {page:<26} {m['queries']:>3} queries {m['rows']:>9,} rows "
            f"{size(m['bytes']):>9}  {m['query_ms']:>7,.0f} ms in queries, "
            f"{m['wall_ms']:>7,.0f} ms total"
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
