"""Configuration from environment variables (12-factor). No secrets have defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class ConfigError(RuntimeError):
    pass


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return default if raw is None else int(raw)


@dataclass(frozen=True)
class Settings:
    environment: str
    database_url: str
    jwt_secret: str
    blob_dir: str
    trust_store_path: str
    cors_origins: tuple[str, ...]
    access_token_ttl_s: int = 900
    command_ttl_s: int = 86400
    offline_after_s: int = 30
    password_iterations: int = 600_000
    allow_self_approval: bool = False
    frontend_dist: str | None = None
    max_firmware_bytes: int = 16 * 1024 * 1024
    extra: dict = field(default_factory=dict)

    @staticmethod
    def from_env() -> "Settings":
        env = os.environ.get("AUTOLINK_ENV", "development")
        secret = os.environ.get("AUTOLINK_JWT_SECRET", "")
        if len(secret) < 32:
            raise ConfigError("AUTOLINK_JWT_SECRET must be set to >= 32 random characters")
        trust = os.environ.get("AUTOLINK_TRUST_STORE", "")
        if not trust:
            raise ConfigError("AUTOLINK_TRUST_STORE must point to the firmware trust-store JSON")
        origins = tuple(o.strip() for o in os.environ.get("AUTOLINK_CORS_ORIGINS", "").split(",") if o.strip())
        if "*" in origins:
            raise ConfigError("wildcard CORS origin is not allowed")
        return Settings(
            environment=env,
            database_url=os.environ.get("AUTOLINK_DATABASE_URL", "sqlite:///" + str(BACKEND_ROOT / "autolink.db")),
            jwt_secret=secret,
            blob_dir=os.environ.get("AUTOLINK_BLOB_DIR", str(BACKEND_ROOT / "blobs")),
            trust_store_path=trust,
            cors_origins=origins,
            access_token_ttl_s=_int("AUTOLINK_ACCESS_TOKEN_TTL_S", 900),
            command_ttl_s=_int("AUTOLINK_COMMAND_TTL_S", 86400),
            offline_after_s=_int("AUTOLINK_OFFLINE_AFTER_S", 30),
            password_iterations=_int("AUTOLINK_PASSWORD_ITERATIONS", 600_000),
            allow_self_approval=os.environ.get("AUTOLINK_ALLOW_SELF_APPROVAL", "false").lower() == "true",
            frontend_dist=os.environ.get("AUTOLINK_FRONTEND_DIST") or None,
        )
