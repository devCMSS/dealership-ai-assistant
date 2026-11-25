"""Runtime settings, read once from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Demo mode: seeds a fictional inventory, enables demo admin credentials and
    # uses the offline assistant when no Anthropic credentials are configured.
    demo_mode: bool = field(default_factory=lambda: _bool("DEMO_MODE", True))

    secret_key: str = field(default_factory=lambda: os.environ.get("SECRET_KEY", ""))
    database_path: Path = field(
        default_factory=lambda: Path(os.environ.get("DATABASE_PATH", BASE_DIR / "data" / "dealership.db"))
    )
    uploads_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("UPLOADS_DIR", BASE_DIR / "data" / "uploads"))
    )
    max_upload_bytes: int = 5 * 1024 * 1024

    admin_user: str = field(default_factory=lambda: os.environ.get("ADMIN_USER", "admin"))
    # Format: scrypt$<salt hex>$<hash hex>. Generate with: python -m app.security hash
    admin_password_hash: str = field(default_factory=lambda: os.environ.get("ADMIN_PASSWORD_HASH", ""))

    # Assistant
    assistant_provider: str = field(default_factory=lambda: os.environ.get("ASSISTANT_PROVIDER", "auto"))
    assistant_model: str = field(default_factory=lambda: os.environ.get("ASSISTANT_MODEL", "claude-opus-5-5"))
    history_limit: int = 16

    # Cookies are Secure unless explicitly running over plain HTTP locally.
    https_only: bool = field(default_factory=lambda: _bool("HTTPS_ONLY", False))

    dealership_name: str = "Crestline Motors"


DEMO_ADMIN_PASSWORD = "crestline-demo"


def get_settings() -> Settings:
    settings = Settings()
    if not settings.secret_key:
        if settings.demo_mode:
            # Demo only: a per-process random key (sessions reset on restart).
            object.__setattr__(settings, "secret_key", os.urandom(32).hex())
        else:
            raise RuntimeError("SECRET_KEY is required when DEMO_MODE is off.")
    if not settings.demo_mode and not settings.admin_password_hash:
        raise RuntimeError("ADMIN_PASSWORD_HASH is required when DEMO_MODE is off.")
    return settings
