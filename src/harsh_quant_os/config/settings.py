"""Typed, environment-driven configuration.

The configuration layer is intentionally the only place that reads
environment variables. Everything else receives an explicit ``Settings``
instance, which keeps the code testable and avoids hidden global state.

Safety note
-----------
``LIVE_TRADING_ENABLED`` is rejected at load time. Enabling live trading is
not a configuration change: it requires Phase 16 completion plus an explicit
human approval record. See ``SECURITY.md`` and ``docs/security/broker-security.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Self

from pydantic import Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from harsh_quant_os.version import PROJECT_NAME, PROJECT_SLUG

_PLACEHOLDER_PREFIXES = ("replace-", "changeme", "your-", "todo")


class SettingsError(ValueError):
    """Raised when the environment contains an unsafe or invalid value."""


class Settings(BaseSettings):
    """Application settings loaded from environment variables and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        validate_assignment=True,
    )

    # --- application -------------------------------------------------
    app_name: str = PROJECT_SLUG
    app_env: str = Field(default="development", pattern="^(development|test|staging|production)$")
    app_version: str = "0.1.0-alpha"
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    log_dir: Path = Path("logs")

    # --- api ---------------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    api_base_url: str = "http://127.0.0.1:8000"
    api_allowed_origins: str = "http://localhost:3000"

    # --- web ---------------------------------------------------------
    web_host: str = "127.0.0.1"
    web_port: int = Field(default=3000, ge=1, le=65535)

    # --- authentication ----------------------------------------------
    auth_secret_key: str = "replace-with-at-least-32-random-characters"
    auth_token_expiry_minutes: int = Field(default=60, ge=1, le=1440)

    # --- database -----------------------------------------------------
    database_url: str = "postgresql+asyncpg://harsh_quant_os:replace-with-a-local-dev-password@127.0.0.1:5432/harsh_quant_os"
    database_host: str = "127.0.0.1"
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = "harsh_quant_os"
    database_user: str = "harsh_quant_os"
    database_password: str = "replace-with-a-local-dev-password"
    redis_enabled: bool = False

    # --- local agent --------------------------------------------------
    local_agent_enabled: bool = False
    local_agent_host: str = "127.0.0.1"
    local_agent_port: int = Field(default=8100, ge=1, le=65535)
    local_agent_token: str = "replace-with-a-long-random-local-agent-token"
    local_agent_max_concurrent_jobs: int = Field(default=1, ge=1, le=8)
    local_agent_job_timeout_seconds: int = Field(default=3600, ge=1)

    # --- ai (provider agnostic, optional) -----------------------------
    ai_provider: str = ""
    ai_api_key: str = ""
    ai_local_enabled: bool = False
    ai_max_tokens: int = Field(default=2048, ge=1, le=128_000)

    # --- trading safety ----------------------------------------------
    live_trading_enabled: bool = False
    paper_trading_enabled: bool = False
    broker_provider: str = ""
    broker_api_key: str = ""
    broker_account_id: str = ""
    paper_capital_currency: str = "INR"
    paper_capital_amount: float = Field(default=1000.0, gt=0)

    # --- risk defaults -------------------------------------------------
    risk_max_position_notional: float = Field(default=100_000.0, gt=0)
    risk_max_daily_loss: float = Field(default=5_000.0, gt=0)
    risk_max_open_positions: int = Field(default=5, ge=1)
    risk_drawdown_kill_switch_percent: float = Field(default=10.0, gt=0, le=100)

    # --- cloud / sync --------------------------------------------------
    cloud_sync_enabled: bool = False

    # ---------------------------------------------------------------
    # validators
    # ---------------------------------------------------------------
    @model_validator(mode="after")
    def _enforce_safety_invariants(self) -> Self:
        """Configuration-level safety gates.

        1. Live trading can never be switched on through configuration.
        2. Placeholder secrets are rejected outside local development/test.
        """
        if self.live_trading_enabled:
            raise SettingsError(
                "LIVE_TRADING_ENABLED must remain false. Live trading is not a "
                "configuration flag; it requires Phase 16 completion plus an "
                "explicit human approval record. See SECURITY.md."
            )
        if self.app_env in {"staging", "production"}:
            unresolved = self.missing_secrets()
            if unresolved:
                raise SettingsError(
                    f"Placeholder secrets in {self.app_env}: {', '.join(unresolved)}. "
                    "Copy .env.example to .env and set real values."
                )
        return self

    def is_placeholder(self, field_name: str) -> bool:
        """Return ``True`` when a secret still holds its template value."""
        value = getattr(self, field_name)
        if not isinstance(value, str):
            raise TypeError(f"{field_name} is not a string setting")
        return value.lower().startswith(_PLACEHOLDER_PREFIXES)

    # ---------------------------------------------------------------
    # derived helpers
    # ---------------------------------------------------------------
    @classmethod
    def load(cls, **kwargs: Any) -> Self:
        """Construct settings and translate validation failures.

        Configuration errors are raised as :class:`SettingsError` so that
        application start-up has exactly one exception type to handle.
        """
        try:
            return cls(**kwargs)
        except ValidationError as exc:
            raise SettingsError(str(exc)) from exc

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_allowed_origins.split(",") if origin.strip()]

    @property
    def project_name(self) -> str:
        return PROJECT_NAME

    def missing_secrets(self) -> list[str]:
        """Names of secrets that still contain template placeholders."""
        return [
            name
            for name in ("auth_secret_key", "database_password", "local_agent_token")
            if self.is_placeholder(name)
        ]

    def with_live_trading_approved(self) -> Self:
        """Reserved for Phase 16.

        Deliberately absent from Phase 0: there is no code path in this
        repository that can turn live trading on.
        """
        raise SettingsError(
            "Live trading cannot be enabled by configuration. "
            "See docs/ROADMAP.md phase 16 and SECURITY.md."
        )
