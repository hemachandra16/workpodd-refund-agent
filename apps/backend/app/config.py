"""Centralised, validated settings loaded from environment.

All secrets live here and never reach the client. Values fall back to the
``.env.example`` defaults so the app boots in dev without a key (the agent
simply degrades to a deterministic-only mode when GROQ_API_KEY is absent).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Groq ---
    groq_api_key: str = ""
    groq_llm_model: str = "llama-3.3-70b-versatile"
    groq_stt_model: str = "whisper-large-v3-turbo"
    groq_tts_model: str = "canopylabs/orpheus-v1-english"
    groq_tts_voice: str = "troy"

    # --- Server ---
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    environment: Literal["development", "production", "test"] = "development"
    frontend_origin: str = "http://localhost:3000"

    # --- DB ---
    database_url: str = "sqlite:///./data/workpodd.db"

    # --- Admin auth ---
    admin_session_secret: str = "dev-insecure-change-me"
    admin_username: str = "admin"
    admin_password_hash: str = ""  # bcrypt hash; empty = login disabled in dev

    # --- Rate limits ---
    rate_limit_chat: str = "30/minute"
    rate_limit_voice: str = "20/minute"
    rate_limit_admin: str = "120/minute"

    # --- Safety ---
    max_message_chars: int = 1000
    max_agent_steps: int = 8

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def groq_available(self) -> bool:
        return bool(self.groq_api_key) and not self.groq_api_key.startswith("gsk_your")

    @field_validator("admin_session_secret")
    @classmethod
    def _warn_weak_secret(cls, v: str) -> str:
        if v in {"dev-insecure-change-me", "change_me_to_a_long_random_string"}:
            # Allowed in dev; the app will refuse to boot in production with it.
            pass
        return v

    def production_safety_check(self) -> None:
        """Hard-fail in production if secrets are not properly set."""
        if not self.is_production:
            return
        problems: list[str] = []
        if self.admin_session_secret in {"dev-insecure-change-me", "change_me_to_a_long_random_string"}:
            problems.append("ADMIN_SESSION_SECRET is a placeholder")
        if not self.groq_available:
            problems.append("GROQ_API_KEY missing/placeholder")
        if not self.admin_password_hash or not self.admin_password_hash.startswith("$2"):
            problems.append("ADMIN_PASSWORD_HASH missing/malformed")
        if problems:
            raise RuntimeError("Refusing to boot in production: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
