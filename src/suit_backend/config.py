from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SUIT_",
        case_sensitive=False,
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    app_name: str = "SUIT API"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./suit.db"
    jwt_secret: str = "development-only-change-this-secret-key"
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_minutes: int = Field(default=30, ge=5, le=1440)
    bootstrap_enabled: bool = False
    bootstrap_token: SecretStr | None = None
    cors_origins: list[str] = [
        "http://localhost:5173",
        "https://suit-woad.vercel.app",
    ]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    max_request_bytes: int = Field(default=1_048_576, ge=16_384, le=10_485_760)
    rate_limit_enabled: bool = True
    cleanup_interval_seconds: int = Field(default=300, ge=30, le=86_400)

    @field_validator("cors_origins")
    @classmethod
    def reject_wildcard_cors(cls, value: list[str]) -> list[str]:
        if "*" in value or any(origin.endswith("*") for origin in value):
            raise ValueError("Wildcard CORS origins are not allowed")
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def reject_wildcard_hosts(cls, value: list[str]) -> list[str]:
        if "*" in value or any(host.startswith("*") for host in value):
            raise ValueError("Wildcard hosts are not allowed")
        return value

    def validate_runtime_security(self) -> None:
        if self.env != "production":
            return
        errors: list[str] = []
        if len(self.jwt_secret) < 32 or "development-only" in self.jwt_secret:
            errors.append("SUIT_JWT_SECRET must be a random value of at least 32 characters")
        if self.access_token_minutes > 30:
            errors.append("SUIT_ACCESS_TOKEN_MINUTES must be 30 or less")
        if not self.database_url.startswith("postgresql+"):
            errors.append("SUIT_DATABASE_URL must use PostgreSQL in production")
        if any(not origin.startswith("https://") for origin in self.cors_origins):
            errors.append("All production CORS origins must use HTTPS")
        if any(host in {"localhost", "127.0.0.1", "testserver"} for host in self.allowed_hosts):
            errors.append("Production allowed hosts must not contain local development hosts")
        if self.bootstrap_enabled:
            token = self.bootstrap_token.get_secret_value() if self.bootstrap_token else ""
            if len(token) < 32:
                errors.append("Enabled production bootstrap requires a 32+ character token")
            if token and token == self.jwt_secret:
                errors.append("Bootstrap token and JWT secret must be different")
        if errors:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_runtime_security()
    return settings

