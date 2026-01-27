"""
Settings Screen - Configure application settings.

Allows users to:
- Set team abbreviation and season
- Configure API connection (base URL, API key)
- Adjust UI preferences (theme)
- View team info loaded from database

Settings are saved to data/settings.yaml and apply immediately.
"""

import logging
from typing import ClassVar, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
)

from ..config import (
    UserSettings,
    UserAPISettings,
    UserTeamSettings,
    UserUISettings,
    get_settings,
    get_user_settings_from_settings,
    reload_settings,
    save_user_settings_yaml,
)
from ..db.queries import get_team_by_abbrev
from ..db.schema import get_session

logger = logging.getLogger(__name__)


class SettingsScreen(Screen):
    """Settings configuration screen."""

    BINDINGS: ClassVar = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
        Binding("ctrl+s", "save_settings", "Save"),
    ]

    # Track if API key is visible
    _api_key_visible: bool = False

    def compose(self) -> ComposeResult:
        """Compose the settings layout."""
        settings = get_settings()

        yield Header()

        with ScrollableContainer(id="settings-container"):
            # Team Settings Section
            with Vertical(classes="settings-section"):
                yield Label("Team", classes="section-title")

                with Horizontal(classes="setting-row"):
                    yield Label("Abbreviation:", classes="setting-label")
                    yield Input(
                        value=settings.team.team_abbrev,
                        placeholder="e.g., WV",
                        id="team-abbrev-input",
                        max_length=10,
                    )

                with Horizontal(classes="setting-row"):
                    yield Label("Season:", classes="setting-label")
                    yield Input(
                        value=str(settings.team.current_season),
                        placeholder="e.g., 13",
                        id="team-season-input",
                        max_length=4,
                    )

                # Team info display (read-only, from database)
                yield Static("", id="team-info-display", classes="info-display")

            # API Settings Section
            with Vertical(classes="settings-section"):
                yield Label("API", classes="section-title")

                with Horizontal(classes="setting-row"):
                    yield Label("Base URL:", classes="setting-label")
                    yield Input(
                        value=settings.api.base_url,
                        placeholder="https://sba.manticorum.com/",
                        id="api-url-input",
                    )

                with Horizontal(classes="setting-row"):
                    yield Label("API Key:", classes="setting-label")
                    yield Input(
                        value=settings.api.api_key,
                        placeholder="Enter API key",
                        id="api-key-input",
                        password=True,
                    )
                    yield Button("Show", id="btn-toggle-key", variant="default")

            # UI Settings Section
            with Vertical(classes="settings-section"):
                yield Label("UI", classes="section-title")

                with Horizontal(classes="setting-row"):
                    yield Label("Theme:", classes="setting-label")
                    yield Select(
                        options=[
                            ("Dark", "dark"),
                            ("Light", "light"),
                        ],
                        value=settings.theme,
                        id="theme-select",
                        allow_blank=False,
                    )

            # Action Buttons
            with Horizontal(id="settings-buttons"):
                yield Button("Save", id="btn-save", variant="success")
                yield Button("Reset to Defaults", id="btn-reset", variant="warning")

        yield Footer()

    async def on_mount(self) -> None:
        """Load team info when screen mounts."""
        await self._refresh_team_info()

    async def _refresh_team_info(self) -> None:
        """Load and display team info from database."""
        abbrev_input = self.query_one("#team-abbrev-input", Input)
        season_input = self.query_one("#team-season-input", Input)
        info_display = self.query_one("#team-info-display", Static)

        abbrev = abbrev_input.value.strip().upper()
        try:
            season = int(season_input.value.strip())
        except ValueError:
            info_display.update("[yellow]Enter a valid season number[/yellow]")
            return

        if not abbrev:
            info_display.update("[yellow]Enter team abbreviation[/yellow]")
            return

        try:
            async with get_session() as session:
                team = await get_team_by_abbrev(session, abbrev, season)

            if team:
                info_display.update(
                    f"[green]Team found:[/green] {team.long_name}\n"
                    f"sWAR Cap: {team.salary_cap or 'N/A'} | "
                    f"ID: {team.id}"
                )
            else:
                info_display.update(
                    f"[red]Team not found:[/red] {abbrev} (Season {season})\n"
                    "Run Sync from dashboard to load team data"
                )
        except Exception as e:
            logger.error(f"Failed to load team info: {e}")
            info_display.update(f"[red]Error loading team:[/red] {e}")

    def _get_current_values(self) -> dict:
        """Get current values from all input fields."""
        return {
            "team_abbrev": self.query_one("#team-abbrev-input", Input).value.strip().upper(),
            "team_season": self.query_one("#team-season-input", Input).value.strip(),
            "api_url": self.query_one("#api-url-input", Input).value.strip(),
            "api_key": self.query_one("#api-key-input", Input).value,
            "theme": self.query_one("#theme-select", Select).value,
        }

    async def _validate_team(self) -> Optional[str]:
        """
        Validate that the team exists in the database.

        Returns error message if invalid, None if valid.
        """
        values = self._get_current_values()

        abbrev = values["team_abbrev"]
        if not abbrev:
            return "Team abbreviation is required"

        try:
            season = int(values["team_season"])
        except ValueError:
            return "Season must be a number"

        try:
            async with get_session() as session:
                team = await get_team_by_abbrev(session, abbrev, season)

            if not team:
                return f"Team '{abbrev}' not found for season {season}. Run Sync first."

            return None
        except Exception as e:
            return f"Error validating team: {e}"

    # =========================================================================
    # Event Handlers
    # =========================================================================

    async def on_input_changed(self, event: Input.Changed) -> None:
        """Refresh team info when team inputs change."""
        if event.input.id in ("team-abbrev-input", "team-season-input"):
            await self._refresh_team_info()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        if event.button.id == "btn-save":
            await self.action_save_settings()
        elif event.button.id == "btn-reset":
            await self._reset_to_defaults()
        elif event.button.id == "btn-toggle-key":
            self._toggle_api_key_visibility()

    def _toggle_api_key_visibility(self) -> None:
        """Toggle API key visibility."""
        api_key_input = self.query_one("#api-key-input", Input)
        toggle_btn = self.query_one("#btn-toggle-key", Button)

        self._api_key_visible = not self._api_key_visible
        api_key_input.password = not self._api_key_visible
        toggle_btn.label = "Hide" if self._api_key_visible else "Show"

    async def _reset_to_defaults(self) -> None:
        """Reset all settings to defaults."""
        default_settings = UserSettings()

        # Update inputs
        self.query_one("#team-abbrev-input", Input).value = default_settings.team.abbrev
        self.query_one("#team-season-input", Input).value = str(default_settings.team.season)
        self.query_one("#api-url-input", Input).value = default_settings.api.base_url
        self.query_one("#api-key-input", Input).value = default_settings.api.api_key
        self.query_one("#theme-select", Select).value = default_settings.ui.theme

        await self._refresh_team_info()
        self.notify("Settings reset to defaults (not saved yet)")

    # =========================================================================
    # Actions
    # =========================================================================

    async def action_save_settings(self) -> None:
        """Save settings to YAML file."""
        # Validate team first
        error = await self._validate_team()
        if error:
            self.notify(error, severity="error")
            return

        values = self._get_current_values()

        # Build user settings object
        user_settings = UserSettings(
            api=UserAPISettings(
                base_url=values["api_url"],
                api_key=values["api_key"],
                timeout=30,
            ),
            team=UserTeamSettings(
                abbrev=values["team_abbrev"],
                season=int(values["team_season"]),
            ),
            ui=UserUISettings(
                theme=values["theme"],
                refresh_interval=300,
            ),
        )

        try:
            # Save to YAML
            settings = get_settings()
            yaml_path = settings.get_settings_yaml_path()
            save_user_settings_yaml(user_settings, yaml_path)

            # Reload settings to apply changes
            reload_settings()

            self.notify(f"Settings saved to {yaml_path.name}", severity="information")
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
            self.notify(f"Error saving settings: {e}", severity="error")
