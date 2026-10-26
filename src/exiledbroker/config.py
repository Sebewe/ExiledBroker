from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from exiledbroker import __version__


def _repo_root() -> Path | None:
    root = Path(__file__).resolve().parents[2]
    return root if (root / "pyproject.toml").exists() else None


def _default_data_dir() -> Path:
    """The repo's gitignored data/ folder when running from a checkout, else ./data."""
    root = _repo_root()
    return root / "data" if root else Path("data")


def _default_web_dist() -> Path:
    root = _repo_root()
    return root / "web" / "dist" if root else Path("web/dist")


def _default_core_pool() -> Path:
    root = _repo_root()
    return root / "config" / "core_pool.toml" if root else Path("config/core_pool.toml")


def _default_mechanics() -> Path:
    root = _repo_root()
    return root / "config" / "mechanics.toml" if root else Path("config/mechanics.toml")


class Settings(BaseSettings):
    """Runtime settings, overridable via EB_* environment variables or a .env file."""

    model_config = SettingsConfigDict(env_prefix="EB_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default_factory=_default_data_dir)
    # Manual include/exclude lists for the core drop pool (committed, edit by hand).
    core_pool_file: Path = Field(default_factory=_default_core_pool)
    # What each league mechanic drops: core-pool lists, labels (committed, edit by hand).
    mechanics_file: Path = Field(default_factory=_default_mechanics)
    db_filename: str = "exiledbroker.duckdb"
    # The site's database (Railway's Postgres when hosted, the compose `db` service
    # locally). Unset: the site reads the local DuckDB file instead.
    database_url: str | None = None
    # The off-site backup (Supabase, docs/supabase.md): each hosted pipeline pass syncs
    # the site's database to it; read back only to restore. Unset: no backup.
    backup_url: str | None = None
    # A dead-man's-switch ping (healthchecks.io or similar, docs/go-live.md): each hosted
    # pipeline pass pings <url>/start, then <url> or <url>/fail. Unset: no pings.
    healthcheck_url: str | None = None
    # The built frontend the API serves (`npm run build` in web/). Not there: API only.
    web_dist: Path = Field(default_factory=_default_web_dist)
    # Where raw exchange pages are kept: files under data/raw (local, the whole history)
    # or the site's database (hosted: the live window only, see ingest/pipeline.py).
    exchange_pages: Literal["disk", "database"] = "disk"
    # Precompute the pages' default tables in the background whenever new data loads.
    api_warm: bool = True
    # Only PoE1 for now; every league row still carries its game.
    default_game: str = "poe1"
    # The next league, as GGG announced it (name and launch time, UTC), for the landing
    # page's countdown to its first published hour. Unset: no countdown.
    next_league: str | None = None
    next_league_start: datetime | None = None
    # Origins allowed to call the API from a browser (the future public frontend).
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    # The API's docs (/docs, /redoc, /openapi.json). Handy locally; off in the image
    # (Dockerfile), so the hosted site doesn't hand out a map of itself.
    api_docs: bool = True
    # A shared secret Cloudflare adds to every request it sends to the origin, as the
    # X-EB-Origin-Key header (a transform rule, docs/go-live.md). Set: requests without
    # it get 403, so nobody can skip Cloudflare's cache and limits by calling the
    # *.up.railway.app address directly (api/guard.py). Unset: no check (local, tests).
    origin_key: str | None = None
    # Requests a minute one visitor (by address, api/guard.py) may make to /api
    # before getting 429. Applied only with `origin_key`, the only case where that
    # header can be trusted. Counts what reaches the origin, so edge cache hits are free.
    api_rate_limit: int = 120

    # Outbound HTTP. poe.ninja asks for a descriptive User-Agent with a contact.
    user_agent: str = f"ExiledBroker/{__version__} (+https://github.com/Sebewe/ExiledBroker)"
    request_min_interval: float = 1.0  # seconds between requests to the same client
    http_timeout: float = 60.0
    http_retries: int = 5
    poe_ninja_base_url: str = "https://poe.ninja"
    exchange_base_url: str = "https://web.poecdn.com/api/currency-exchange"
    # NeverSink's loot filter (the one FilterBlade serves) decides which divination
    # cards we follow: only cards the filter shows at this strictness.
    loot_filter_url: str = (
        "https://raw.githubusercontent.com/NeverSinkDev/NeverSink-Filter/master/"
        "NeverSink%27s%20filter%20-%20{strictness}.filter"
    )
    loot_filter_strictness: str = "2-SEMI-STRICT"
    repoe_base_items_url: str = "https://repoe-fork.github.io/base_items.min.json"

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_filename

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def dumps_raw_dir(self) -> Path:
        return self.raw_dir / "poe_ninja" / "dumps"

    @property
    def dumps_processed_dir(self) -> Path:
        return self.processed_dir / "poe_ninja" / "dumps"

    @property
    def exchange_raw_dir(self) -> Path:
        return self.raw_dir / "ggg" / "currency_exchange"

    @property
    def exchange_processed_dir(self) -> Path:
        return self.processed_dir / "ggg" / "currency_exchange"

    @property
    def repoe_raw_dir(self) -> Path:
        return self.raw_dir / "repoe"


def get_settings() -> Settings:
    return Settings()
