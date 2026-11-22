from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
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
    cors_origins: list[str] = [
        "http://localhost:5173",
        "https://suit-woad.vercel.app",
    ]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    max_request_bytes: int = Field(default=1_048_576, ge=16_384, le=10_485_760)

    @field_validator("cors_origins")
    @classmethod
    def reject_wildcard_cors(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError("Wildcard CORS origins are not allowed")
        return value

    def validate_runtime_security(self) -> None:
        if self.env == "production" and (
            len(self.jwt_secret) < 32 or "development-only" in self.jwt_secret
        ):
            raise RuntimeError("Production requires a random SUIT_JWT_SECRET of at least 32 chars")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_runtime_security()
    return settings

