from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from exiledbroker import __version__


def _default_data_dir() -> Path:
    """The repo's gitignored data/ folder when running from a checkout, else ./data."""
    repo_root = Path(__file__).resolve().parents[2]
    if (repo_root / "pyproject.toml").exists():
        return repo_root / "data"
    return Path("data")


class Settings(BaseSettings):
    """Runtime settings, overridable via EB_* environment variables or a .env file."""

    model_config = SettingsConfigDict(env_prefix="EB_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default_factory=_default_data_dir)
    db_filename: str = "exiledbroker.duckdb"
    # Only PoE1 for now; every league row still carries its game.
    default_game: str = "poe1"
    # Origins allowed to call the API from a browser (the future public frontend).
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Outbound HTTP. poe.ninja asks for a descriptive User-Agent with a contact.
    user_agent: str = f"ExiledBroker/{__version__} (+https://github.com/Sebewe/ExiledBroker)"
    request_min_interval: float = 1.0  # seconds between requests to the same client
    http_timeout: float = 60.0
    http_retries: int = 5
    poe_ninja_base_url: str = "https://poe.ninja"

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


def get_settings() -> Settings:
    return Settings()
