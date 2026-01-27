"""
Configuration management for SBA Scout.

Uses pydantic-settings for environment variable support and type validation.
User settings are stored in data/settings.yaml for easy editing.

Load order:
1. Pydantic defaults
2. .env file (for backwards compatibility / CI overrides)
3. data/settings.yaml (user-editable, takes precedence)
"""

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# =============================================================================
# User Settings (saved to YAML)
# =============================================================================


class UserAPISettings(BaseModel):
    """User-configurable API settings."""

    base_url: str = Field(
        default="https://sba.manticorum.com/", description="Base URL for the league API"
    )
    api_key: str = Field(default="", description="API key for authentication")
    timeout: int = Field(default=30, description="Request timeout in seconds")


class UserTeamSettings(BaseModel):
    """User-configurable team settings.

    Only abbrev and season are user-editable.
    Other team data (name, sWAR cap, roster slots) comes from the database.
    """

    abbrev: str = Field(default="WV", description="Your team's abbreviation")
    season: int = Field(default=13, description="Current season number")


class UserUISettings(BaseModel):
    """User-configurable UI settings."""

    theme: str = Field(default="dark", description="UI theme (dark or light)")
    refresh_interval: int = Field(
        default=300, description="Auto-refresh interval in seconds (0 to disable)"
    )


class UserSettings(BaseModel):
    """
    User-editable settings saved to data/settings.yaml.

    These settings can be modified via the Settings screen in the app
    or by editing the YAML file directly.
    """

    api: UserAPISettings = Field(default_factory=UserAPISettings)
    team: UserTeamSettings = Field(default_factory=UserTeamSettings)
    ui: UserUISettings = Field(default_factory=UserUISettings)


# =============================================================================
# Rating Weights (kept for backwards compatibility)
# =============================================================================


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


# =============================================================================
# Legacy Settings Classes (for .env compatibility)
# =============================================================================


class APISettings(BaseModel):
    """Settings for the SBA League API."""

    base_url: str = Field(default="", description="Base URL for the league API")
    api_key: str = Field(default="", description="API key for authentication")
    timeout: int = Field(default=30, description="Request timeout in seconds")


class TeamSettings(BaseModel):
    """Settings for the user's team.

    Note: team_abbrev and current_season are the primary user settings.
    Other fields (team_id, team_name, swar_cap, slots) are loaded from
    the database after syncing.
    """

    team_id: int = Field(default=0, description="Your team's ID in the league (from DB)")
    team_abbrev: str = Field(default="WV", description="Your team's abbreviation")
    team_name: str = Field(default="", description="Full team name (from DB)")
    current_season: int = Field(default=13, description="Current season number")
    swar_cap: float = Field(default=0.0, description="Season sWAR cap for roster (from DB)")
    minor_league_slots: int = Field(default=6, description="Number of minor league roster slots")
    major_league_slots: int = Field(default=26, description="Number of major league roster slots")


# =============================================================================
# Main Settings Class
# =============================================================================


class Settings(BaseSettings):
    """
    Main application settings.

    Settings can be loaded from:
    1. Environment variables (prefixed with SBA_SCOUT_)
    2. .env file in the project root
    3. data/settings.yaml file (user-editable, takes precedence)

    Environment variables use double underscore for nested settings:
    - SBA_SCOUT_TEAM__TEAM_ABBREV=WV
    - SBA_SCOUT_API__BASE_URL=https://...
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

    def get_settings_yaml_path(self) -> Path:
        """Get the path to the user settings YAML file."""
        return self.db_path.parent / "settings.yaml"

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


# =============================================================================
# YAML Settings Management
# =============================================================================


def get_default_user_settings() -> UserSettings:
    """Get default user settings."""
    return UserSettings()


def load_user_settings_yaml(settings_path: Path) -> UserSettings | None:
    """
    Load user settings from YAML file.

    Returns None if file doesn't exist.
    """
    if not settings_path.exists():
        return None

    try:
        with open(settings_path, "r") as f:
            data = yaml.safe_load(f)

        if data is None:
            return None

        return UserSettings(**data)
    except Exception as e:
        import logging

        logging.getLogger(__name__).error(f"Failed to load settings.yaml: {e}")
        return None


def save_user_settings_yaml(user_settings: UserSettings, settings_path: Path) -> None:
    """
    Save user settings to YAML file.

    Creates the parent directory if it doesn't exist.
    """
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    # Add a header comment
    header = """# SBA Scout User Settings
# Edit this file or use the Settings screen in the app
# Changes take effect immediately when saved via the app

"""

    yaml_content = yaml.dump(
        user_settings.model_dump(),
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )

    with open(settings_path, "w") as f:
        f.write(header + yaml_content)


def apply_user_settings_to_settings(settings: Settings, user_settings: UserSettings) -> None:
    """
    Apply user settings from YAML to the main Settings object.

    This merges user settings on top of defaults/.env values.
    """
    # API settings
    settings.api.base_url = user_settings.api.base_url
    settings.api.api_key = user_settings.api.api_key
    settings.api.timeout = user_settings.api.timeout

    # Team settings (only abbrev and season from user settings)
    settings.team.team_abbrev = user_settings.team.abbrev
    settings.team.current_season = user_settings.team.season

    # UI settings
    settings.theme = user_settings.ui.theme
    settings.refresh_interval = user_settings.ui.refresh_interval


def get_user_settings_from_settings(settings: Settings) -> UserSettings:
    """
    Extract user-editable settings from the main Settings object.

    Used when saving settings to YAML.
    """
    return UserSettings(
        api=UserAPISettings(
            base_url=settings.api.base_url,
            api_key=settings.api.api_key,
            timeout=settings.api.timeout,
        ),
        team=UserTeamSettings(
            abbrev=settings.team.team_abbrev,
            season=settings.team.current_season,
        ),
        ui=UserUISettings(
            theme=settings.theme,
            refresh_interval=settings.refresh_interval,
        ),
    )


# =============================================================================
# Global Settings Instance
# =============================================================================


# Global settings instance - lazy loaded
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()

        # Load any saved rating weights
        _settings.rating_weights = _settings.load_rating_weights()

        # Load user settings from YAML if it exists
        yaml_path = _settings.get_settings_yaml_path()
        user_settings = load_user_settings_yaml(yaml_path)
        if user_settings:
            apply_user_settings_to_settings(_settings, user_settings)

    return _settings


def reload_settings() -> Settings:
    """Force reload of settings (useful after config changes)."""
    global _settings
    _settings = None
    return get_settings()
