import typer
import uvicorn

from exiledbroker.config import get_settings
from exiledbroker.storage import db

app = typer.Typer(help="ExiledBroker: PoE league-start market speculation.", no_args_is_help=True)


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
