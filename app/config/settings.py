from typing import List
import json
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


import os
from pathlib import Path

_ENV_FILE = Path(__file__).parent.parent.parent / ".env"  # backend/.env


class Settings(BaseSettings):
    # ── Application ───────────────────────────────────────────────────────────
    app_name: str = "HSE Safety Compliance Intelligence API"
    app_env: str = "local"
    debug: bool = False                # env: DEBUG
    api_v1_prefix: str = "/api/v1"
    app_version: str = "1.0.0"        # internal constant, not in .env

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "mysql+pymysql://root:@localhost:3306/hse_db"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    
    # Optional components to build URL if DATABASE_URL is not provided
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "hse_db"

    @property
    def effective_database_url(self) -> str:
        if self.database_url and "hse_db" not in self.database_url:
            return self.database_url
        import urllib.parse
        safe_password = urllib.parse.quote_plus(self.db_password)
        return f"mysql+pymysql://{self.db_user}:{safe_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    # ── Auth / JWT ────────────────────────────────────────────────────────────
    jwt_issuer: str = "hse-platform"
    jwt_audience: str = "hse-users"
    jwt_secret: str = "hse-local-dev-secret-change-in-production"  # env: JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60    # env: ACCESS_TOKEN_EXPIRE_MINUTES
    frontend_base_url: str = "http://localhost:5173"  # env: FRONTEND_BASE_URL

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Accepts either JSON array: ["url1","url2"] or comma-separated: url1,url2
    allowed_origins: str = '["http://localhost:3000","http://localhost:5173"]'

    # ── Email backend ─────────────────────────────────────────────────────────
    # auto → SendGrid if SENDGRID_API_KEY is set, otherwise SMTP
    email_backend: str = "auto"

    # ── SendGrid ──────────────────────────────────────────────────────────────
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "noreply@hse-platform.com"
    sendgrid_from_name: str = "HSE Platform"

    # ── SMTP ─────────────────────────────────────────────────────────────────
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_user: str = ""           # env: SMTP_USER
    smtp_password: str = ""
    smtp_from_email: str = ""     # env: SMTP_FROM_EMAIL
    smtp_from_name: str = ""      # env: SMTP_FROM_NAME

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = "DEBUG"
    log_dir: str = "logs"
    log_max_bytes: int = 10_485_760
    log_backup_count: int = 5

    # ── Azure Storage ─────────────────────────────────────────────────────────
    azure_storage_account: str = ""
    azure_storage_container: str = "evidence"
    azure_key_vault_url: str = ""

    # ── Anthropic / Claude ───────────────────────────────────────────────────
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # Connection used to run LLM-generated SQL (app/services/sql_agent.py). Point
    # this at a SELECT-only MySQL user — see docs/sql_agent_readonly_user.sql. It
    # is the guardrail that still holds if query validation is ever bypassed.
    # Falls back to database_url when empty, with a startup warning.
    sql_agent_database_url: str = ""

    # ── Azure OpenAI (alternative AI provider) ────────────────────────────────
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4o"
    azure_openai_api_version: str = "2025-01-01-preview"
    azure_openai_embeddings_deployment: str = "text-embedding-3-small"

    # ── Azure AI Search ───────────────────────────────────────────────────────
    azure_search_endpoint: str = ""
    azure_search_api_key: str = ""
    azure_search_index: str = "hse-knowledge"

    # ── Backward-compat properties (existing code keeps working unchanged) ────

    @property
    def app_debug(self) -> bool:
        return self.debug

    @property
    def jwt_secret_key(self) -> str:
        return self.jwt_secret

    @property
    def jwt_access_token_expire_minutes(self) -> int:
        return self.access_token_expire_minutes

    @property
    def frontend_url(self) -> str:
        return self.frontend_base_url

    @property
    def cors_origins(self) -> List[str]:
        raw = self.allowed_origins.strip()
        if raw.startswith("["):
            try:
                return json.loads(raw)
            except Exception:
                pass
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def smtp_username(self) -> str:
        return self.smtp_user

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    return s


# Force re-read on import so .env changes take effect immediately
get_settings.cache_clear()
