# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Application configuration for FlexMapping.

All runtime settings are read from environment variables or a .env file.

Two deliberate conventions apply to the defaults below:

* Secrets (session key, admin password, LLM key) default to an obvious
  placeholder that starts with "CHANGE_ME". These are NOT safe values; they
  exist so that a misconfiguration is visible rather than silent. When
  ENVIRONMENT is "production", startup aborts while a placeholder is still in
  place -- see check_production_readiness().
* Behaviour switches (debug output, API docs, CORS) default to the SAFE
  option, not the convenient one. Development overrides belong in .env or in
  docker-compose.dev.yml, where they are visible.
"""
from functools import lru_cache
from pathlib import Path
from typing import Annotated, List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Marker prefix for values that must be replaced before production use.
PLACEHOLDER_PREFIX = "CHANGE_ME"


def find_env_file() -> str:
    """
    Locate a .env file in the usual places.

    The application is started from the repository root during development and
    from /app inside the container, so both are checked.
    """
    possible_paths = [
        Path(".env"),                # current working directory
        Path("../.env"),             # one level up
        Path("app/.env"),            # started from the repository root
        Path("/app/.env"),           # inside the Docker container
    ]

    for path in possible_paths:
        if path.exists():
            return str(path)

    return ".env"


class Settings(BaseSettings):
    """Application settings."""

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://flexmap:flexmap@localhost:5432/flexmap",
        alias="DATABASE_URL",
        description="Async connection string used by the API and the worker.",
    )
    database_url_sync: str = Field(
        default="postgresql://flexmap:flexmap@localhost:5432/flexmap",
        alias="DATABASE_URL_SYNC",
        description="Sync connection string used by Alembic and the health check.",
    )

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    redis_key_prefix: str = Field(
        default="flexmap",
        alias="REDIS_KEY_PREFIX",
        description="Prefix for all Redis keys, so several instances can share one server.",
    )

    # ------------------------------------------------------------------
    # LLM backend
    # ------------------------------------------------------------------
    llm_base_url: str = Field(default="http://localhost:8001/v1", alias="LLM_BASE_URL")
    llm_api_key: str = Field(
        default=f"{PLACEHOLDER_PREFIX}_llm_api_key",
        alias="LLM_API_KEY",
    )
    llm_model: str = Field(default="current-best", alias="LLM_MODEL")
    llm_timeout: int = Field(default=30, alias="LLM_TIMEOUT")
    llm_max_tokens: int = Field(default=500, alias="LLM_MAX_TOKENS")
    llm_temperature: float = Field(default=0.1, alias="LLM_TEMPERATURE")
    llm_requests_per_minute: int = Field(
        default=30,
        alias="LLM_REQUESTS_PER_MINUTE",
        description="Maximum LLM requests per minute (0 = unlimited).",
    )
    llm_request_delay: float = Field(
        default=2.0,
        alias="LLM_REQUEST_DELAY",
        description="Minimum seconds between LLM requests, per worker.",
    )

    # ------------------------------------------------------------------
    # Worker pool
    # ------------------------------------------------------------------
    num_workers: int = Field(default=3, alias="NUM_WORKERS")
    max_concurrent_llm: int = Field(default=5, alias="MAX_CONCURRENT_LLM")

    # ------------------------------------------------------------------
    # Crawler
    # ------------------------------------------------------------------
    crawler_user_agent: str = Field(default="FlexMapping-Bot/1.0", alias="CRAWLER_USER_AGENT")
    crawler_timeout: int = Field(default=30, alias="CRAWLER_TIMEOUT")
    crawler_max_markdown_size: int = Field(default=200000, alias="CRAWLER_MAX_MARKDOWN_SIZE")
    crawler_default_rate_limit: float = Field(default=1.0, alias="CRAWLER_DEFAULT_RATE_LIMIT")
    crawler_multi_page_enabled: bool = Field(default=True, alias="CRAWLER_MULTI_PAGE_ENABLED")
    crawler_max_pages: int = Field(default=5, alias="CRAWLER_MAX_PAGES")
    crawler_verify_ssl: bool = Field(
        default=True,
        alias="CRAWLER_VERIFY_SSL",
        description="Verify TLS certificates (set false only for self-signed hosts).",
    )
    crawler_respect_robots: bool = Field(
        default=True,
        alias="CRAWLER_RESPECT_ROBOTS",
        description="Honour robots.txt (set false only for sites you operate yourself).",
    )

    # ------------------------------------------------------------------
    # Robustness
    # ------------------------------------------------------------------
    circuit_breaker_failure_threshold: int = Field(default=10, alias="CIRCUIT_BREAKER_FAILURE_THRESHOLD")
    circuit_breaker_timeout: int = Field(default=300, alias="CIRCUIT_BREAKER_TIMEOUT")
    retry_max_attempts: int = Field(default=3, alias="RETRY_MAX_ATTEMPTS")
    retry_backoff_base: float = Field(default=2.0, alias="RETRY_BACKOFF_BASE")

    # ------------------------------------------------------------------
    # HTTP API
    # ------------------------------------------------------------------
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    api_reload: bool = Field(default=False, alias="API_RELOAD")
    docs_enabled: bool = Field(
        default=False,
        alias="DOCS_ENABLED",
        description="Expose /docs and /redoc. These list every endpoint, so they are off by default.",
    )
    # NoDecode keeps pydantic-settings from JSON-decoding the value before it
    # reaches the validator below. Without it, a comma-separated list in a .env
    # file aborts startup with a JSON parse error instead of being split.
    cors_allow_origins: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:8000", "http://127.0.0.1:8000"],
        alias="CORS_ALLOW_ORIGINS",
        description="Comma-separated list of origins allowed to send credentialed requests.",
    )

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    session_secret: str = Field(
        default=f"{PLACEHOLDER_PREFIX}_session_secret_at_least_32_characters_long",
        alias="SESSION_SECRET",
        description="Signing key for the session cookie. Rotating it logs everyone out.",
    )
    session_max_age: int = Field(
        default=60 * 60 * 12,
        alias="SESSION_MAX_AGE",
        description="Session lifetime in seconds.",
    )
    session_cookie_secure: bool = Field(
        default=False,
        alias="SESSION_COOKIE_SECURE",
        description="Send the session cookie only over HTTPS. Enable behind a TLS proxy.",
    )
    bootstrap_admin_username: str = Field(
        default="admin",
        alias="BOOTSTRAP_ADMIN_USERNAME",
        description="Username of the administrator created on first start, if no user exists.",
    )
    bootstrap_admin_password: str = Field(
        default=f"{PLACEHOLDER_PREFIX}_admin_password",
        alias="BOOTSTRAP_ADMIN_PASSWORD",
        description="Password of that administrator. Change it after the first login.",
    )
    login_failure_delay: float = Field(
        default=1.0,
        alias="LOGIN_FAILURE_DELAY",
        description="Seconds to wait after a failed login. Slows down password guessing.",
    )

    # ------------------------------------------------------------------
    # Static site generation
    # ------------------------------------------------------------------
    public_site_dir: str = Field(
        default="./public",
        alias="PUBLIC_SITE_DIR",
        description=(
            "Target directory for the generated site. Its contents are DELETED on every "
            "generation run, so it must not be shared with anything else."
        ),
    )
    static_site_base_url: str = Field(
        default="http://localhost:8000",
        alias="STATIC_SITE_BASE_URL",
        description="Absolute base URL used in the sitemap and in canonical links.",
    )
    public_site_url_prefix: str = Field(
        default="",
        alias="PUBLIC_SITE_URL_PREFIX",
        description=(
            "Path the generated site is served under. Empty when a web server or "
            "CDN serves it at the root. Set to /public to view it through the "
            "application itself, which serves the same directory under that path."
        ),
    )

    # ------------------------------------------------------------------
    # Category configuration
    # ------------------------------------------------------------------
    config_dir: Optional[str] = Field(
        default=None,
        alias="FLEXMAP_CONFIG_DIR",
        description="Directory holding the category YAML files. Defaults to app/config.",
    )

    # ------------------------------------------------------------------
    # Logging and environment
    # ------------------------------------------------------------------
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    debug: bool = Field(
        default=False,
        alias="DEBUG",
        description="Echo SQL and return exception text to HTTP clients. Never enable in production.",
    )

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def split_origins(cls, value):
        """Accept a comma-separated string so the value can come from a single env var."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    model_config = SettingsConfigDict(
        env_file=find_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Startup guards
    # ------------------------------------------------------------------
    def placeholder_settings(self) -> List[str]:
        """Return the names of secrets that still hold their placeholder value."""
        candidates = {
            "SESSION_SECRET": self.session_secret,
            "BOOTSTRAP_ADMIN_PASSWORD": self.bootstrap_admin_password,
            "LLM_API_KEY": self.llm_api_key,
        }
        return [name for name, value in candidates.items() if value.startswith(PLACEHOLDER_PREFIX)]

    def is_production(self) -> bool:
        return self.environment.strip().lower() in {"production", "prod"}

    def check_production_readiness(self) -> None:
        """
        Abort startup if the instance claims to be production but still carries
        development defaults.

        This is deliberately a hard failure. A warning in the log is not enough:
        the failure mode it prevents -- a publicly reachable instance with a
        known session key and a known admin password -- is silent.
        """
        if not self.is_production():
            return

        problems = [f"{name} is still set to its placeholder value" for name in self.placeholder_settings()]
        if self.debug:
            problems.append("DEBUG is enabled, which returns internal error text to HTTP clients")
        if self.docs_enabled:
            problems.append("DOCS_ENABLED exposes the full endpoint catalogue without authentication")

        if problems:
            raise RuntimeError(
                "Refusing to start with ENVIRONMENT=production:\n  - "
                + "\n  - ".join(problems)
                + "\nSet these in your .env file, or set ENVIRONMENT=development."
            )


@lru_cache()
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
