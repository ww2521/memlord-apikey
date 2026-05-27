from pathlib import Path
from typing import Literal

from pydantic import EmailStr, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEMLORD_", env_file=".env", extra="ignore")

    db_url: str = "postgresql+asyncpg://postgres:postgres@localhost/memlord"
    db_echo: bool = False

    model_dir: Path = Path("src/memlord/onnx")
    host: str = "0.0.0.0"
    port: int = 8000
    base_url: str = "http://localhost:8000"
    rrf_k: int = 60
    default_limit: int = 10
    sim_threshold: float = Field(0.25, ge=0.0, le=1.0)
    dedup_threshold: float = Field(0.85, ge=0.0, le=1.0)
    oauth_jwt_secret: str = "memlord-dev-secret-please-change"
    stdio_user_id: int | None = Field(None, description="use for stdio mode")

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: EmailStr | None = None
    smtp_tls: bool = True

    azure_sso_enabled: bool = False
    azure_client_id: str | None = None
    azure_client_secret: str | None = None
    azure_tenant_id: str | None = None
    azure_redirect_uri: str | None = None
    azure_scope: str = "openid profile email"
    azure_login_button_text: str = "Sign in with Azure AD"
    azure_allowed_email_domains: list[str] | None = None

    @field_validator("azure_allowed_email_domains", mode="before")
    @classmethod
    def _parse_domains(cls, v):
        if isinstance(v, str):
            return [d.strip() for d in v.split(",") if d.strip()]
        return v

    azure_auto_register: bool = True

    local_password_login_enabled: bool = True
    local_registration_enabled: bool = True

    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"


settings = Settings()
