import sys
from contextlib import contextmanager
from typing import Annotated

import typer
import uvicorn

from exiledbroker.config import get_settings
from exiledbroker.ingest import poe_ninja_dumps as dumps_mod
from exiledbroker.ingest.http import PoliteClient, is_complete, part_path_for
from exiledbroker.normalize.leagues import LEAGUE_KINDS
from exiledbroker.storage import db
from exiledbroker.storage import dumps as dump_store

app = typer.Typer(help="ExiledBroker: PoE league-start market speculation.", no_args_is_help=True)
dumps_app = typer.Typer(help="poe.ninja historical economy dumps.", no_args_is_help=True)
app.add_typer(dumps_app, name="dumps")


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
            n = dump_store.upsert_leagues(con, index)
            views = dump_store.refresh_views(con, settings.dumps_processed_dir)
        typer.echo(f"Loaded {n} leagues into the calendar; views: {', '.join(views) or 'none'}")
