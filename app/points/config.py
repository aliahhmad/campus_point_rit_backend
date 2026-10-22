"""Load only POINTS_ settings from the shared development environment."""

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from collections.abc import Callable


class PointsSettings(BaseSettings):
    """Database credentials belonging to the Points Service."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_prefix="POINTS_",
        extra="ignore",
    )

    db_user: str = "campuspoint_points"
    db_password: SecretStr
    db_address: str = "localhost"
    db_port: int = 5434
    db_name: str = "campuspoint_points"
    service_token: SecretStr = SecretStr("")
    campus_api_url: str = "http://localhost:8001"


@lru_cache
def get_settings() -> PointsSettings:
    """Cache the Points Service settings for this process."""
    # Required settings are supplied by the environment at runtime.
    settings_factory = cast("Callable[..., PointsSettings]", PointsSettings)
    return settings_factory()
