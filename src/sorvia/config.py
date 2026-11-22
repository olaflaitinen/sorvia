"""Runtime configuration, read from environment variables prefixed with SORVIA_."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SORVIA_", env_file=".env", extra="ignore")

    # Database connections. Three identities, three privilege levels.
    admin_dsn: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/sorvia",
        description="Schema owner. Migrations, seeding, applying index recommendations.",
    )
    app_dsn: str = Field(
        default="postgresql://sorvia_api:sorvia_api@localhost:5432/sorvia",
        description="API service (member of sorvia_app).",
    )
    reader_dsn: str = Field(
        default="postgresql://sorvia_nl:sorvia_nl@localhost:5432/sorvia",
        description="Executes generated SQL (member of sorvia_reader).",
    )
    pool_min_size: int = 1
    pool_max_size: int = 10

    migrations_dir: Path = REPO_ROOT / "db" / "migrations"

    # Authentication.
    jwt_secret: SecretStr = SecretStr("change-me-in-production-please-32-bytes-minimum")
    jwt_ttl_minutes: int = 60
    environment: Literal["development", "test", "production"] = "development"

    # Personal data protection (pgcrypto).
    fin_key: SecretStr = SecretStr("dev-only-fin-key")

    # Language model.
    llm_provider: Literal["openai", "static"] = "static"
    llm_model: str = ""
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    llm_timeout_s: float = 60.0
    llm_max_tokens: int = 1024
    static_sql_path: Path | None = REPO_ROOT / "benchmark" / "data" / "az_text2sql_v1.jsonl"

    # Embeddings for schema retrieval.
    embedding_provider: Literal["hashing", "openai"] = "hashing"
    embedding_model: str = "hashing-ngram-512"
    embedding_dim: int = 512
    embedding_base_url: str | None = None
    embedding_api_key: SecretStr | None = None

    # NL to SQL pipeline.
    strategy: Literal["full_schema", "retrieval", "retrieval_fewshot"] = "retrieval_fewshot"
    retrieval_top_k: int = 6
    repair_attempts: int = 1

    # Guardrails.
    max_rows: int = 500
    max_joins: int = 12
    max_sql_length: int = 8000
    statement_timeout_ms: int = 5000
    max_plan_cost: float = 5.0e6

    # API.
    rate_limit_per_minute: int = 30
    cors_origins: list[str] = Field(default_factory=list)

    def validate_for_production(self) -> None:
        """Refuse to start in production with development secrets."""
        if self.environment != "production":
            return
        secret = self.jwt_secret.get_secret_value()
        if len(secret) < 32 or secret.startswith("change-me"):
            raise RuntimeError("SORVIA_JWT_SECRET must be a random value of at least 32 characters")
        if self.fin_key.get_secret_value().startswith("dev-only"):
            raise RuntimeError("SORVIA_FIN_KEY must be set in production")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
