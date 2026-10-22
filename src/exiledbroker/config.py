from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, overridable via EB_* environment variables or a .env file."""

    model_config = SettingsConfigDict(env_prefix="EB_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    db_filename: str = "exiledbroker.duckdb"
    # Only PoE1 for now; every league row still carries its game.
    default_game: str = "poe1"
    # Origins allowed to call the API from a browser (the future public frontend).
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_filename

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"


def get_settings() -> Settings:
    return Settings()
