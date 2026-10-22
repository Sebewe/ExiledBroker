import sys
import time
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

import httpx
import typer
import uvicorn

from exiledbroker.config import get_settings
from exiledbroker.ingest import core_pool, item_names
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest import live as live_mod
from exiledbroker.ingest import poe_ninja_dumps as dumps_mod
from exiledbroker.ingest.http import PoliteClient, is_complete, part_path_for
from exiledbroker.normalize import dump_loader, exchange_loader, mappings
from exiledbroker.normalize.leagues import CHALLENGE, LEAGUE_KINDS
from exiledbroker.storage import db
from exiledbroker.storage import dumps as dump_store

app = typer.Typer(help="ExiledBroker: PoE league-start market speculation.", no_args_is_help=True)
dumps_app = typer.Typer(help="poe.ninja historical economy dumps.", no_args_is_help=True)
exchange_app = typer.Typer(
    help="GGG currency exchange: hourly history since Settlers.", no_args_is_help=True
)
app.add_typer(dumps_app, name="dumps")
app.add_typer(exchange_app, name="exchange")


@contextmanager
def resumable():
    """Turn Ctrl-C into a clean exit; every step is safe to re-run."""
    try:
        yield
    except KeyboardInterrupt:
        typer.echo("\nInterrupted. Progress so far is kept; re-run the same command to resume.")
        sys.exit(130)


@app.command("init-db")
def init_db() -> None:
    """Create the DuckDB file and apply the schema."""
    path = get_settings().db_path
    with db.session() as con:
        db.init_schema(con)
    typer.echo(f"Initialised database at {path}")


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: bool = typer.Option(False, help="Auto-reload on code changes (dev only)."),
) -> None:
    """Run the API locally."""
    uvicorn.run("exiledbroker.api.app:app", host=host, port=port, reload=reload)


def _local_state(settings, dump) -> str:
    if dumps_mod.is_extracted(settings, dump):
        return "extracted"
    zp = dumps_mod.zip_path(settings, dump)
    if is_complete(zp):
        return "downloaded"
    part = part_path_for(zp)
    if part.exists():
        return f"partial ({part.stat().st_size / 1e6:.1f} MB)"
    return "-"


def _select(index, leagues: list[str], kind: str, since: int | None):
    if leagues:
        by_name = {d.league_name.lower(): d for d in index}
        missing = [n for n in leagues if n.lower() not in by_name]
        if missing:
            raise typer.BadParameter(f"unknown league(s): {', '.join(missing)}")
        return [by_name[n.lower()] for n in leagues]
    return [
        d
        for d in index
        if (kind == "all" or d.kind == kind) and (since is None or d.min_date.year >= since)
    ]


def _calendar_leagues(index, selected):
    """Challenge leagues, plus anything explicitly selected. Event and Ruthless leagues
    are left out by default: few players, and markets unlike a normal league."""
    names = {d.league_name for d in selected}
    return [d for d in index if d.kind == CHALLENGE or d.league_name in names]


def _progress_printer(label: str):
    last = {"pct": -10}

    def show(done: int, total: int | None) -> None:
        if not total:
            return
        pct = int(done * 100 / total)
        if pct >= last["pct"] + 10 or done == total:
            last["pct"] = pct
            typer.echo(f"  {label}: {pct:3d}% of {total / 1e6:.1f} MB")

    return show


@dumps_app.command("list")
def dumps_list(
    offline: bool = typer.Option(False, help="Use the cached listing instead of fetching it."),
) -> None:
    """Show available league dumps and what is already stored locally."""
    settings = get_settings()
    with resumable():
        if offline:
            index = dumps_mod.cached_index(settings)
            if index is None:
                raise typer.BadParameter("no cached listing yet; run without --offline")
        else:
            with PoliteClient(settings) as client:
                index = dumps_mod.fetch_index(client, settings)
    typer.echo(f"{'league':<22} {'kind':<10} {'start':<11} {'end':<11} local")
    for d in index:
        state = _local_state(settings, d)
        typer.echo(
            f"{d.league_name:<22} {d.kind:<10} {d.min_date!s:<11} {d.max_date!s:<11} {state}"
        )


@dumps_app.command("sync")
def dumps_sync(
    league: Annotated[
        list[str] | None, typer.Option("--league", "-l", help="League name; repeatable.")
    ] = None,
    kind: str = typer.Option(
        "challenge", help=f"Which leagues to sync: {', '.join(LEAGUE_KINDS)} or all."
    ),
    since: int | None = typer.Option(None, help="Only leagues starting in or after this year."),
    hardcore: bool = typer.Option(False, help="Also keep each league's hardcore twin."),
    offline: bool = typer.Option(False, help="Skip downloading; only extract and load."),
) -> None:
    """Download, extract and load league dumps. Interrupt any time and re-run to resume."""
    if kind not in (*LEAGUE_KINDS, "all"):
        raise typer.BadParameter(f"kind must be one of {', '.join(LEAGUE_KINDS)} or all")
    settings = get_settings()

    with resumable(), PoliteClient(settings) as client:
        index = dumps_mod.cached_index(settings) if offline else None
        if index is None:
            index = dumps_mod.fetch_index(client, settings)
        selected = _select(index, league or [], kind, since)
        typer.echo(f"{len(selected)} league(s) selected.")

        for i, dump in enumerate(selected, 1):
            prefix = f"[{i}/{len(selected)}] {dump.league_name}"
            zp = dumps_mod.zip_path(settings, dump)
            if not is_complete(zp):
                if offline:
                    typer.echo(f"{prefix}: not downloaded, skipping (offline)")
                    continue
                result = dumps_mod.download_dump(
                    client, settings, dump, progress=_progress_printer(dump.zip_name)
                )
                note = (
                    f" (resumed at {result.resumed_from / 1e6:.1f} MB)"
                    if result.resumed_from
                    else ""
                )
                typer.echo(f"{prefix}: downloaded{note}")
            written = dumps_mod.extract_dump(settings, dump, include_hardcore=hardcore)
            typer.echo(f"{prefix}: {'extracted' if written else 'already extracted'}")

        with db.session() as con:
            db.init_schema(con)
            n = dump_store.upsert_leagues(con, _calendar_leagues(index, selected))
            views = dump_store.refresh_views(con, settings.dumps_processed_dir)
        typer.echo(f"Loaded {n} leagues into the calendar; views: {', '.join(views) or 'none'}")


@dumps_app.command("load")
def dumps_load(
    league: Annotated[
        list[str] | None, typer.Option("--league", "-l", help="League name; repeatable.")
    ] = None,
    kind: str = typer.Option(CHALLENGE, help=f"Filter by kind: {', '.join(LEAGUE_KINDS)} or all."),
    force: bool = typer.Option(False, help="Reload even if the inputs are unchanged."),
) -> None:
    """Process extracted dumps into the item and price_observation tables.

    Each league loads in one transaction, so an interrupt leaves it fully loaded or
    untouched. Leagues already loaded from the same files are skipped.
    """
    settings = get_settings()
    index = dumps_mod.cached_index(settings)
    if index is None:
        raise typer.BadParameter("no dump listing yet; run `eb dumps list` or `eb dumps sync`")
    selected = [
        d for d in _select(index, league or [], kind, None) if dumps_mod.is_extracted(settings, d)
    ]
    if not selected:
        typer.echo("Nothing extracted to load. Run `eb dumps sync` first.")
        raise typer.Exit(1)

    with resumable(), db.session() as con:
        db.init_schema(con)
        dump_store.upsert_leagues(con, _calendar_leagues(index, selected))
        for i, dump in enumerate(selected, 1):
            prefix = f"[{i}/{len(selected)}] {dump.league_name} ({dump.kind})"
            result = dump_loader.load_league(con, settings, dump, force=force)
            if result.skipped:
                typer.echo(f"{prefix}: already loaded")
            else:
                typer.echo(f"{prefix}: {result.items:,} items, {result.rows:,} price rows")


def _parse_start(value: str | None):
    if value is None:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError as e:
        raise typer.BadParameter("--start must look like 2026-11-20") from e


def _exchange_leagues(settings, client, leagues: list[str], start: date | None):
    """Leagues to sync. A league not in the dumps (the current or upcoming one) needs
    --start the first time; after that its row in the database remembers it."""
    index = dumps_mod.cached_index(settings) or dumps_mod.fetch_index(client, settings)
    if not leagues:
        history_start = cx.HISTORY_START.date()
        eligible = [d for d in index if d.kind == CHALLENGE and d.max_date >= history_start]
        return index, eligible

    by_name = {d.league_name.lower(): d for d in index}
    known = {}
    if settings.db_path.exists():
        with db.session(read_only=True) as con:
            q = "SELECT name, CAST(start_at AS DATE) FROM league"
            known = {name.lower(): (name, d) for name, d in db.rows(con, q)}
    selected = []
    for name in leagues:
        if name.lower() in by_name:
            selected.append(by_name[name.lower()])
            continue
        stored_name, stored_start = known.get(name.lower(), (name, None))
        first_day = start or stored_start
        if first_day is None:
            raise typer.BadParameter(
                f"{name!r} has no poe.ninja dump yet. For a current or upcoming league, "
                "pass its launch date once: --start YYYY-MM-DD"
            )
        selected.append(dumps_mod.DumpInfo(stored_name, "", first_day, None, CHALLENGE))
    return index, selected


def _report_pool(pool) -> None:
    sizes = ", ".join(f"{g} {len(n)}" for g, n in sorted(pool.listed.items()))
    sizes = sizes.replace("divination", "divination cards shown by the loot filter")
    included = sum(len(n) for n in pool.include.values())
    extra = f"; {len(pool.exclude)} excluded, {included} included by config/core_pool.toml"
    typer.echo(f"Core pool from poe.ninja ({pool.league}): {sizes}{extra}")


@exchange_app.command("sync")
def exchange_sync(
    league: Annotated[
        list[str] | None,
        typer.Option(
            "--league",
            "-l",
            help="League name; repeatable. Default: every challenge league since Settlers.",
        ),
    ] = None,
    days: int = typer.Option(14, help="Days after launch to fetch."),
    start: str | None = typer.Option(
        None,
        help="Launch date (YYYY-MM-DD) for a league with no poe.ninja dump yet, i.e. the "
        "current or upcoming league. Only needed the first time.",
    ),
    force: bool = typer.Option(False, help="Rebuild the league's rows even if unchanged."),
    refresh: bool = typer.Option(
        False, help="Re-fetch the core pool and loot-filter tiers now (normally daily)."
    ),
) -> None:
    """Fetch hourly exchange history, then process it into the database.

    One request per hour of history, spaced politely. Interrupt any time (Ctrl-C) and
    re-run the same command: finished hours are never fetched again. For a live league,
    each re-run adds the hours published since the last one.
    """
    settings = get_settings()
    with resumable(), PoliteClient(settings) as client:
        index, selected = _exchange_leagues(settings, client, league or [], _parse_start(start))
        # Reference data lives in the database and is refreshed on a schedule
        # (RePoE weekly, the core pool and card tiers daily), or now with --refresh.
        with db.session() as con:
            db.init_schema(con)
            item_names.ensure_base_items(client, settings, con)
            names = item_names.load_base_items(con)
            pool = (
                core_pool.refresh_pool(client, con, settings)
                if refresh
                else core_pool.refresh_pool_if_stale(client, con, settings)
            )
        _report_pool(pool)
        typer.echo(f"{len(selected)} league(s), first {days} days each.")

        for i, dump in enumerate(selected, 1):
            prefix = f"[{i}/{len(selected)}] {dump.league_name}"
            last = {"day": -1}

            def progress(done: int, total: int, fetched: int, prefix=prefix, last=last) -> None:
                day = done // 24
                if day != last["day"] or done == total:
                    last["day"] = day
                    typer.echo(f"  {prefix}: hour {done}/{total} ({fetched} fetched)")

            # Register the league first, so the demo can show it while it has no data yet.
            with db.session() as con:
                db.init_schema(con)
                dump_store.upsert_leagues(con, _calendar_leagues(index, [dump]))
                con.execute(
                    "UPDATE league SET exchange_tracked = TRUE WHERE id = ?", [dump.league_id]
                )

            result = cx.sync_league(
                client, settings, dump.league_name, dump.min_date, days, progress
            )
            if result.window is None:
                typer.echo(
                    f"{prefix}: no trades published yet (GGG publishes each hour after it "
                    "ends). Re-run later to pick them up."
                )
                continue
            w = result.window
            note = (
                " (league still running; stopped at the current hour)" if result.reached_end else ""
            )
            typer.echo(
                f"{prefix}: launched {w.launched_at:%Y-%m-%d %H:%M} UTC, "
                f"{result.fetched} hour(s) fetched, {result.cached} already on disk{note}"
            )
            with db.session() as con:
                loaded = exchange_loader.load_league(con, settings, w, names, force=force)
                # The pool can change without the league's inputs changing.
                mappings.refresh_mappings(con, settings)
            typer.echo(f"{prefix}: {_load_summary(loaded)}")


def _load_summary(loaded) -> str:
    if loaded.skipped:
        return "already loaded"
    how = "rebuilt" if loaded.rebuilt else "updated"
    return (
        f"{how}: +{loaded.hours_added} hour(s), -{loaded.hours_removed} hour(s), "
        f"+{loaded.rows_added:,} rows; {loaded.items:,} items, {loaded.rows:,} hourly rows"
    )


@exchange_app.command("status")
def exchange_status() -> None:
    """Show how much hourly history is on disk and loaded, per league."""
    settings = get_settings()
    pages = len(list(settings.exchange_raw_dir.glob("*.json.gz")))
    typer.echo(f"{pages:,} hourly pages on disk in {settings.exchange_raw_dir}")
    if not settings.db_path.exists():
        return
    with db.session(read_only=True) as con:
        rows = db.rows(
            con,
            """
            SELECT l.name, min(h.hour), max(h.hour), count(*), il.row_count, il.loaded_at
            FROM exchange_hour_loaded h
            JOIN league l ON l.id = h.league_id
            LEFT JOIN ingest_load il ON il.league_id = h.league_id AND il.source = ?
            GROUP BY l.name, il.row_count, il.loaded_at, l.start_at
            ORDER BY l.start_at
            """,
            [exchange_loader.SOURCE],
        )
    for name, first, last, hours, n, at in rows:
        typer.echo(
            f"{name:<14} {first:%Y-%m-%d %H:%M} → {last:%Y-%m-%d %H:%M}  {hours:>4} hours, "
            f"{n or 0:,} rows (loaded {at:%Y-%m-%d %H:%M})"
        )


live_app = typer.Typer(
    help="Live market: keep the current league's latest exchange hours loaded.",
    no_args_is_help=True,
)
app.add_typer(live_app, name="live")


def _live_once(
    client, settings, league: str | None, lookback_hours: int, force: bool = False
) -> str:
    name = league or live_mod.current_league(client, settings)
    return str(live_mod.sync_live(client, settings, name, lookback_hours, force=force))


@live_app.command("sync")
def live_sync(
    league: str | None = typer.Option(
        None, "--league", "-l", help="Default: poe.ninja's current challenge league."
    ),
    lookback_hours: int = typer.Option(
        14 * 24, help="Keep this many recent hours loaded (or everything since launch)."
    ),
    force: bool = typer.Option(
        False,
        help="Rebuild the league's rows (e.g. after the core pool gains items). Reuses pages "
        "on disk; any missing page is fetched, so don't use it on a wiped disk.",
    ),
) -> None:
    """Load the latest published exchange hours of a running league, once."""
    settings = get_settings()
    with resumable(), PoliteClient(settings) as client:
        typer.echo(_live_once(client, settings, league, lookback_hours, force))


@live_app.command("watch")
def live_watch(
    league: str | None = typer.Option(
        None, "--league", "-l", help="Default: poe.ninja's current challenge league."
    ),
    lookback_hours: int = typer.Option(
        14 * 24, help="Keep this many recent hours loaded (or everything since launch)."
    ),
    delay_minutes: int = typer.Option(
        6, help="Minutes after each hour to fetch it (GGG publishes with a short delay)."
    ),
) -> None:
    """Keep a running league's latest hours loaded: update now, then shortly after every
    hour. Ctrl-C to stop; re-running picks up where it left off."""
    settings = get_settings()
    with resumable(), PoliteClient(settings) as client:
        while True:
            try:
                # Reference data (names, core pool) refreshes itself when stale.
                status = _live_once(client, settings, league, lookback_hours)
            except (httpx.HTTPError, OSError, ValueError, LookupError) as e:
                status = f"update failed ({e}); retrying next hour"
            now = datetime.now(UTC)
            next_run = now.replace(minute=0, second=0, microsecond=0) + timedelta(
                hours=1, minutes=delay_minutes
            )
            typer.echo(f"{now:%H:%M} UTC  {status}  Next update ~{next_run:%H:%M} UTC.")
            time.sleep(max(60.0, (next_run - datetime.now(UTC)).total_seconds()))


perf_app = typer.Typer(help="Local performance measurements (not part of the site).")
app.add_typer(perf_app, name="perf")


@perf_app.command("report")
def perf_report(
    save: bool = typer.Option(True, help="Keep the report in data/perf/ for comparison."),
) -> None:
    """Measure what each page reads, what is stored and what the live worker costs,
    and flag what grew since the previous report."""
    from exiledbroker import perf

    settings = get_settings()
    if not settings.db_path.exists():
        typer.echo("No database yet.")
        raise typer.Exit(1)
    prev = perf.previous(settings)
    rep = perf.report(settings)
    typer.echo(perf.render(rep, prev))
    if save:
        typer.echo(f"\nSaved {perf.save(settings, rep)}")


site_app = typer.Typer(
    help="The site's database (Postgres at EB_DATABASE_URL): what the hosted site reads.",
    no_args_is_help=True,
)
app.add_typer(site_app, name="site")


@site_app.command("seed")
def site_seed(
    league: Annotated[
        list[str] | None,
        typer.Option("--league", "-l", help="Repeatable. Default: the newest exchange league."),
    ] = None,
) -> None:
    """Copy leagues' site rows from the local DuckDB into Postgres (development only).
    Replaces those leagues' rows there; other leagues are left alone."""
    import psycopg

    from exiledbroker.services.live import live_leagues
    from exiledbroker.storage import site

    settings = get_settings()
    if not settings.database_url:
        typer.echo("Set EB_DATABASE_URL (see .env.example) to the site's Postgres database.")
        raise typer.Exit(1)
    with db.session(read_only=True) as duck:
        names = league or live_leagues(duck)["name"].head(1).to_list()
        if not names:
            typer.echo("No exchange league in the local database.")
            raise typer.Exit(1)
        with psycopg.connect(settings.database_url, autocommit=True) as pg:
            result = site.seed(duck, pg, names)
    rows = ", ".join(f"{t} {n:,}" for t, n in result.rows.items())
    typer.echo(f"Seeded {', '.join(result.leagues)}: {rows}")
