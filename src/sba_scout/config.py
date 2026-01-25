"""
Configuration management for SBA Scout.

Uses pydantic-settings for environment variable support and type validation.
Rating weights can be modified via config file or environment variables.
"""

from pathlib import Path
from typing import Self

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RatingWeights(BaseModel):
    """
    Configurable weights for calculating composite batter ratings.

    These weights determine how each stat component contributes to the
    overall vL (vs Left-handed pitchers) and vR (vs Right-handed pitchers) ratings.

    Positive weights = better outcomes (hits, walks, etc.)
    Negative weights = worse outcomes (strikeouts, double plays)

    The same weights are applied to both vL and vR calculations.
    """

    # Offensive production weights
    hit: float = Field(default=1.0, description="Weight for base hit probability")
    on_base: float = Field(default=0.8, description="Weight for on-base probability")
    total_bases: float = Field(default=0.5, description="Weight for total bases (power)")
    home_run: float = Field(default=1.5, description="Weight for home run probability")
    walk: float = Field(default=0.6, description="Weight for walk probability")

    # Negative outcome weights (applied as penalties)
    strikeout: float = Field(default=-0.3, description="Penalty for strikeout probability")
    double_play: float = Field(default=-0.5, description="Penalty for double play probability")

    # Ballpark modifier weights
    bp_home_run: float = Field(default=0.3, description="Weight for ballpark HR modifier")
    bp_single: float = Field(default=0.1, description="Weight for ballpark single modifier")

    def calculate_rating(
        self,
        hit: float,
        on_base: float,
        total_bases: float,
        home_run: float,
        walk: float,
        strikeout: float,
        double_play: float,
        bp_home_run: float = 0.0,
        bp_single: float = 0.0,
    ) -> float:
        """
        Calculate composite rating using configured weights.

        All input values should be the raw stat values from the player card.
        Returns a single composite rating (higher = better).
        """
        return (
            hit * self.hit
            + on_base * self.on_base
            + total_bases * self.total_bases
            + home_run * self.home_run
            + walk * self.walk
            + strikeout * self.strikeout
            + double_play * self.double_play
            + bp_home_run * self.bp_home_run
            + bp_single * self.bp_single
        )


class APISettings(BaseModel):
    """Settings for the SBA League API."""

    base_url: str = Field(default="", description="Base URL for the league API")
    api_key: str = Field(default="", description="API key for authentication")
    timeout: int = Field(default=30, description="Request timeout in seconds")


class TeamSettings(BaseModel):
    """Settings for the user's team."""

    team_id: int = Field(default=548, description="Your team's ID in the league")
    team_abbrev: str = Field(default="WV", description="Your team's abbreviation")
    team_name: str = Field(default="West Virginia Black Bears", description="Full team name")
    current_season: int = Field(default=13, description="Current season number")
    swar_cap: float = Field(default=29.5, description="Season sWAR cap for roster")
    minor_league_slots: int = Field(default=5, description="Number of minor league roster slots")
    major_league_slots: int = Field(default=26, description="Number of major league roster slots")


class Settings(BaseSettings):
    """
    Main application settings.

    Settings can be loaded from:
    1. Environment variables (prefixed with SBA_SCOUT_)
    2. .env file in the project root
    3. config.json file in the data directory

    Environment variables use double underscore for nested settings:
    - SBA_SCOUT_TEAM__TEAM_ID=548
    - SBA_SCOUT_RATING_WEIGHTS__HIT=1.2
    """

    model_config = SettingsConfigDict(
        env_prefix="SBA_SCOUT_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database settings
    db_path: Path = Field(
        default=Path("data/sba_scout.db"), description="Path to SQLite database file"
    )

    # Nested settings
    rating_weights: RatingWeights = Field(default_factory=RatingWeights)
    api: APISettings = Field(default_factory=APISettings)
    team: TeamSettings = Field(default_factory=TeamSettings)

    # UI settings
    refresh_interval: int = Field(
        default=300, description="Auto-refresh interval in seconds (0 to disable)"
    )
    theme: str = Field(default="dark", description="UI theme (dark or light)")

    @model_validator(mode="after")
    def ensure_db_directory(self) -> Self:
        """Ensure the database directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return self

    def get_db_url(self) -> str:
        """Get SQLAlchemy database URL."""
        return f"sqlite+aiosqlite:///{self.db_path}"

    def save_rating_weights(self, weights: RatingWeights) -> None:
        """
        Save updated rating weights to a config file.

        This allows runtime modification of weights that persists across restarts.
        """
        import json

        config_path = self.db_path.parent / "rating_weights.json"
        config_path.write_text(json.dumps(weights.model_dump(), indent=2))

    def load_rating_weights(self) -> RatingWeights:
        """
        Load rating weights from config file if it exists.

        Falls back to default weights if no config file exists.
        """
        import json

        config_path = self.db_path.parent / "rating_weights.json"
        if config_path.exists():
            data = json.loads(config_path.read_text())
            return RatingWeights(**data)
        return self.rating_weights


# Global settings instance - lazy loaded
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
        # Load any saved rating weights
        _settings.rating_weights = _settings.load_rating_weights()
    return _settings


def reload_settings() -> Settings:
    """Force reload of settings (useful after config changes)."""
    global _settings
    _settings = None
    return get_settings()
