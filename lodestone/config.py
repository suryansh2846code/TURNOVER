"""Central configuration, loaded from environment / .env with local defaults."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


def _default_home() -> Path:
    """Where the brain lives. macOS-native by default, like Turnstone."""
    override = os.environ.get("LODESTONE_HOME")
    if override:
        return Path(override).expanduser()
    if os.name == "posix" and Path.home().joinpath("Library").exists():
        return Path.home() / "Library" / "Lodestone"
    # Linux / Windows / headless fallback
    return Path.home() / ".lodestone"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LODESTONE_", env_file=".env", extra="ignore"
    )

    home: Path = Field(default_factory=_default_home)

    # embeddings
    embedding_provider: str = "hash"  # hash | local | openai | gemini
    embedding_model: str | None = None

    # LLM backend for agents (bring your own model)
    model_provider: str = "mock"  # subscription | anthropic | openai | openrouter | ollama | mock
    model_name: str | None = None

    # max files a single connector sync will ingest (guardrail; raise for big corpora)
    max_files: int = 2000

    # continuous background sync: re-index ready connectors on a timer
    sync_enabled: bool = True
    sync_interval_minutes: int = 30

    # Bounded-by-default sync: recent window + on-demand fetch for the tail.
    gmail_recent_days: int = 90       # default bounded window
    gmail_recent_max: int = 600       # cap for the bounded window
    gmail_max: int = 3000             # cap when full_history (escape hatch)
    drive_max: int = 500

    # server
    host: str = "127.0.0.1"
    port: int = 8787

    # raw keys (read outside the prefix, so declared explicitly)
    @property
    def openai_api_key(self) -> str | None:
        return os.environ.get("OPENAI_API_KEY")

    @property
    def gemini_api_key(self) -> str | None:
        return os.environ.get("GEMINI_API_KEY")

    @property
    def notion_token(self) -> str | None:
        return os.environ.get("NOTION_TOKEN")

    @property
    def google_client_secrets(self) -> Path | None:
        # 1) explicit override
        raw = os.environ.get("GOOGLE_CLIENT_SECRETS")
        if raw and Path(raw).expanduser().exists():
            return Path(raw).expanduser()
        # 2) a client the user dropped in their Lodestone home
        user = self.home / "google_client_secret.json"
        if user.exists():
            return user
        # 3) a client BUNDLED with the app → end users just "Sign in with Google",
        #    no Cloud Console setup. (Developer ships one at build time.)
        bundled = Path(__file__).resolve().parent / "data" / "google_client.json"
        if bundled.exists():
            return bundled
        return None

    @property
    def db_path(self) -> Path:
        return self.home / "lodestone.db"

    def ensure_home(self) -> Path:
        self.home.mkdir(parents=True, exist_ok=True)
        return self.home


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_home()
    return s
