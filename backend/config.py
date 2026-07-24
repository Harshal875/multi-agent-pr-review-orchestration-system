"""Application settings, loaded from backend/.env via pydantic-settings.

Foundational and dependency-free (imports nothing from other backend modules),
so any module may import `settings` without creating a cycle."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    # Data spine + queue
    tiger_database_url: str
    redis_url: str = "redis://localhost:6379"

    # Embeddings — Voyage AI voyage-code-3 @ 256 dims (Phase 6/14)
    voyage_api_key: str = ""
    # Reasoning — Claude/Anthropic (Phase 5/8)
    anthropic_api_key: str = ""
    # Unused (OpenAI account had no quota; embeddings moved to Voyage)
    openai_api_key: str = ""

    # GitHub App
    github_app_id: str = ""
    github_webhook_secret: str = ""
    github_private_key_path: str = ""

    # Policy knobs (ADR-000 / ROADMAP §7)
    daily_budget_usd: float = 5.00
    confidence_threshold: float = 0.75


settings = Settings()
