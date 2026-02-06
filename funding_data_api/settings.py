from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from quantshark_shared.settings import DBSettings


class CORSSettings(BaseSettings):
    """CORS middleware configuration.

    All fields are Optional - None means use middleware default.
    Use to_middleware_kwargs() to pass only explicitly set values.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_prefix="FDA_CORS_",
        extra="ignore",
    )

    allow_origins: list[str] | Literal["*"] | None = None
    allow_origin_regex: str | None = None
    allow_methods: list[str] | Literal["*"] | None = None
    allow_headers: list[str] | Literal["*"] | None = None
    allow_credentials: bool | None = None
    allow_private_network: bool | None = None
    expose_headers: list[str] | None = None
    max_age: int | None = None

    def to_middleware_kwargs(self) -> dict[str, object]:
        """Returns only explicitly set parameters (filters None)."""
        return {k: v for k, v in self.model_dump().items() if v is not None}


class FDADBSettings(DBSettings):
    """Funding Data API DB settings with service-specific kwargs."""

    engine_kwargs: dict[str, Any] | None = Field(default=None, alias="FDA_ENGINE_KWARGS")
    session_kwargs: dict[str, Any] | None = Field(default=None, alias="FDA_SESSION_KWARGS")


class Settings(BaseModel):
    """Funding Data API configuration."""

    cors: CORSSettings
    db: FDADBSettings


settings = Settings(cors=CORSSettings(), db=FDADBSettings())
