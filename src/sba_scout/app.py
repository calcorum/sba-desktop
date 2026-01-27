"""
SBA Scout - TUI Application for SBA Fantasy Baseball Scouting

Main application entry point using Textual framework.
"""

import asyncio
import logging
from typing import ClassVar

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, LoadingIndicator, Static

from .config import get_settings
from .db.schema import close_database, get_session, init_database
from .screens.gameday import GamedayScreen
from .screens.lineup import LineupScreen
from .screens.matchup import MatchupScreen
from .screens.roster import RosterScreen
from .screens.settings import SettingsScreen

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class DashboardScreen(Screen):
    """Main dashboard screen showing roster overview and quick actions."""

    BINDINGS: ClassVar = [
        Binding("r", "switch_screen('roster')", "Roster"),
        Binding("m", "switch_screen('matchup')", "Matchup Scout"),
        Binding("g", "switch_screen('gameday')", "Gameday"),
        Binding("l", "switch_screen('lineup')", "Lineup Builder"),
        Binding("t", "switch_screen('transactions')", "Transactions"),
        Binding("x", "switch_screen('settings')", "Settings"),
        Binding("s", "sync_data", "Sync Data"),
        Binding("q", "app.quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the dashboard layout."""
        settings = get_settings()

        yield Header()

        with Container(id="dashboard"):
            # Team header
            with Horizontal(id="team-header"):
                yield Label(f"{settings.team.team_name}", id="team-name")
                yield Label(f"Season 13", id="season-info")

            # Roster summary
            with Horizontal(id="roster-summary"):
                with Vertical(classes="summary-card"):
                    yield Label("Majors", classes="card-title")
                    yield Label(
                        f"--/{settings.team.major_league_slots}",
                        id="majors-count",
                        classes="card-value",
                    )

                with Vertical(classes="summary-card"):
                    yield Label("Minors", classes="card-title")
                    yield Label(
                        f"--/{settings.team.minor_league_slots}",
                        id="minors-count",
                        classes="card-value",
                    )

                with Vertical(classes="summary-card"):
                    yield Label("IL", classes="card-title")
                    yield Label("--", id="il-count", classes="card-value")

                with Vertical(classes="summary-card"):
                    yield Label("sWAR", classes="card-title")
                    yield Label(
                        f"--/{settings.team.swar_cap}", id="swar-usage", classes="card-value"
                    )

            # Quick actions
            with Vertical(id="quick-actions"):
                yield Label("Quick Actions", classes="section-title")

                with Horizontal(classes="action-buttons"):
                    yield Button("Gameday [g]", id="btn-gameday", variant="primary")
                    yield Button("Roster [r]", id="btn-roster", variant="primary")

                with Horizontal(classes="action-buttons"):
                    yield Button("Matchup Scout [m]", id="btn-matchup", variant="default")
                    yield Button("Lineup Builder [l]", id="btn-lineup", variant="default")

            # Status bar
            with Horizontal(id="status-bar"):
                yield Label("Last sync: Never", id="sync-status")
                yield Button("Sync Now [s]", id="btn-sync", variant="success")
                yield Button("Settings [x]", id="btn-settings", variant="default")

        yield Footer()

    async def on_mount(self) -> None:
        """Load data when screen is mounted."""
        await self.load_roster_summary()

    async def load_roster_summary(self) -> None:
        """Load and display roster summary from database."""
        try:
            from .db.queries import get_my_roster

            settings = get_settings()

            async with get_session() as session:
                roster = await get_my_roster(
                    session,
                    settings.team.team_abbrev,
                    settings.team.current_season,
                )

                majors_count = len(roster.get("majors", []))
                minors_count = len(roster.get("minors", []))
                il_count = len(roster.get("il", []))

                # Calculate sWAR
                swar_total = sum(p.swar for p in roster.get("majors", []))
                swar_total += sum(p.swar for p in roster.get("il", []))

                # Update labels
                self.query_one("#majors-count", Label).update(
                    f"{majors_count}/{settings.team.major_league_slots}"
                )
                self.query_one("#minors-count", Label).update(
                    f"{minors_count}/{settings.team.minor_league_slots}"
                )
                self.query_one("#il-count", Label).update(str(il_count))
                self.query_one("#swar-usage", Label).update(
                    f"{swar_total:.2f}/{settings.team.swar_cap}"
                )

        except Exception as e:
            logger.error(f"Failed to load roster summary: {e}")
            # Show placeholder values on error
            settings = get_settings()
            self.query_one("#majors-count", Label).update(f"--/{settings.team.major_league_slots}")

    @on(Button.Pressed, "#btn-gameday")
    def on_gameday(self) -> None:
        """Navigate to gameday screen."""
        self.app.push_screen("gameday")

    @on(Button.Pressed, "#btn-roster")
    def on_roster(self) -> None:
        """Navigate to roster screen."""
        self.app.push_screen("roster")

    @on(Button.Pressed, "#btn-matchup")
    def on_matchup(self) -> None:
        """Navigate to matchup scout screen."""
        self.app.push_screen("matchup")

    @on(Button.Pressed, "#btn-lineup")
    def on_lineup(self) -> None:
        """Navigate to lineup builder screen."""
        self.app.push_screen("lineup")

    @on(Button.Pressed, "#btn-transactions")
    def on_transactions(self) -> None:
        """Navigate to transactions screen."""
        self.app.push_screen("transactions")

    @on(Button.Pressed, "#btn-sync")
    async def on_sync(self) -> None:
        """Sync data from league API."""
        await self.action_sync_data()

    @on(Button.Pressed, "#btn-settings")
    def on_settings(self) -> None:
        """Navigate to settings screen."""
        self.app.push_screen("settings")

    async def action_sync_data(self) -> None:
        """Sync data from the league API."""
        from .api.sync import sync_all

        sync_btn = self.query_one("#btn-sync", Button)
        sync_status = self.query_one("#sync-status", Label)

        sync_btn.disabled = True
        sync_status.update("Syncing...")

        try:
            async with get_session() as session:
                counts = await sync_all(session, season=13)

            sync_status.update(f"Synced: {counts['teams']} teams, {counts['players']} players")

            # Refresh roster summary
            await self.load_roster_summary()

        except Exception as e:
            logger.error(f"Sync failed: {e}")
            sync_status.update(f"Sync failed: {str(e)[:50]}")

        finally:
            sync_btn.disabled = False


# RosterScreen, MatchupScreen, and LineupScreen are imported from screens module


class TransactionsScreen(Screen):
    """Transaction manager for roster moves."""

    BINDINGS: ClassVar = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Transactions - Coming Soon", id="placeholder")
        yield Footer()


class SBAScoutApp(App):
    """SBA Scout TUI Application."""

    TITLE = "SBA Scout"
    SUB_TITLE = "Fantasy Baseball Scouting Tool"

    CSS = """
    #dashboard {
        padding: 1 2;
    }

    #team-header {
        height: 3;
        margin-bottom: 1;
    }

    #team-name {
        text-style: bold;
        width: 1fr;
    }

    #season-info {
        width: auto;
        color: $text-muted;
    }

    #roster-summary {
        height: 5;
        margin-bottom: 1;
    }

    .summary-card {
        width: 1fr;
        height: 100%;
        border: solid $primary;
        padding: 0 1;
        margin-right: 1;
    }

    .summary-card:last-child {
        margin-right: 0;
    }

    .card-title {
        color: $text-muted;
    }

    .card-value {
        text-style: bold;
    }

    #quick-actions {
        margin-top: 1;
    }

    .section-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .action-buttons {
        height: 3;
        margin-bottom: 1;
    }

    .action-buttons Button {
        width: 1fr;
        margin-right: 1;
    }

    .action-buttons Button:last-child {
        margin-right: 0;
    }

    #status-bar {
        dock: bottom;
        height: 3;
        padding: 1;
        background: $surface;
    }

    #sync-status {
        width: 1fr;
    }

    #btn-sync {
        width: auto;
    }

    #placeholder {
        width: 100%;
        height: 100%;
        content-align: center middle;
        color: $text-muted;
    }

    /* Roster Screen Styles */
    #roster-container {
        height: 100%;
        padding: 1;
    }

    #roster-header {
        height: 3;
        margin-bottom: 1;
    }

    #roster-title {
        width: 1fr;
        text-style: bold;
    }

    #swar-summary {
        width: auto;
        color: $success;
        text-style: bold;
    }

    TabbedContent {
        height: 1fr;
    }

    TabPane {
        height: 1fr;
    }

    .roster-pane {
        height: 1fr;
        width: 100%;
        padding: 0 1;
    }

    .section-label {
        text-style: bold;
        background: $surface;
        padding: 0 1;
        margin-top: 1;
        margin-bottom: 0;
    }

    .roster-pane DataTable {
        width: 100%;
        max-height: 50%;
    }

    DataTable > .datatable--header {
        text-style: bold;
        background: $primary;
    }

    DataTable > .datatable--cursor {
        background: $accent;
    }

    /* Matchup Screen Styles */
    #matchup-container {
        height: 100%;
        padding: 1;
    }

    #matchup-selectors {
        height: 3;
        margin-bottom: 1;
    }

    #matchup-selectors Label {
        width: auto;
        padding: 0 1;
        content-align: center middle;
    }

    #matchup-selectors Select {
        width: 1fr;
        max-width: 40;
        margin-right: 2;
    }

    #pitcher-info {
        height: 2;
        background: $surface;
        padding: 0 1;
        margin-bottom: 1;
        text-style: bold;
        color: $warning;
    }

    #matchup-table-container {
        height: 1fr;
    }

    #matchup-table {
        width: 100%;
        height: 100%;
    }

    /* Lineup Builder Screen Styles */
    #lineup-container {
        height: 1fr;
        padding: 1;
    }

    .lineup-panel {
        width: 1fr;
        height: 100%;
        padding: 0 1;
        border: solid $primary;
        margin-right: 1;
    }

    .lineup-panel:last-of-type {
        margin-right: 0;
    }

    .panel-title {
        text-style: bold;
        background: $surface;
        padding: 0 1;
        margin-bottom: 1;
    }

    #available-container, #lineup-scroll-container {
        height: 1fr;
    }

    #available-table, #lineup-table {
        width: 100%;
        height: 100%;
    }

    .hint-text {
        color: $text-muted;
        height: 1;
        padding: 0 1;
    }

    #lineup-controls {
        height: 5;
        padding: 1;
        background: $surface;
        dock: bottom;
    }

    #lineup-controls Label {
        width: auto;
        padding: 0 1;
        height: 3;
        content-align: center middle;
    }

    #lineup-name-input {
        width: 30;
        height: 3;
        margin-right: 1;
    }

    #lineup-select {
        width: 25;
        height: 3;
        margin-right: 1;
    }

    #btn-save {
        width: auto;
        margin-right: 1;
    }

    #btn-clear {
        width: auto;
    }

    /* Gameday Screen Styles */
    #gameday-container {
        height: 1fr;
        padding: 1;
    }

    .gameday-panel {
        height: 100%;
        padding: 0 1;
        border: solid $primary;
    }

    #matchup-panel {
        width: 3fr;
        margin-right: 1;
    }

    #lineup-panel {
        width: 2fr;
    }

    #gameday-selectors {
        height: 3;
        margin-bottom: 1;
    }

    #gameday-selectors Label {
        width: auto;
        padding: 0 1;
        content-align: center middle;
    }

    #gameday-selectors Select {
        width: 1fr;
        margin-right: 1;
    }

    #gameday-selectors #team-select {
        max-width: 12;
    }

    #gameday-selectors #pitcher-select {
        max-width: 30;
    }

    #matchup-scroll, #lineup-scroll {
        height: 1fr;
    }

    #lineup-save-controls {
        height: 3;
        margin-bottom: 1;
    }

    #lineup-save-controls Input {
        width: 1fr;
        height: 3;
        margin-right: 1;
    }

    #lineup-save-controls Select {
        width: 1fr;
        height: 3;
        margin-right: 1;
    }

    #lineup-save-controls Button {
        width: auto;
    }

    /* Settings Screen Styles */
    #settings-container {
        padding: 1 2;
    }

    .settings-section {
        margin-bottom: 2;
        padding: 1;
        border: solid $primary;
    }

    .settings-section .section-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .setting-row {
        height: 3;
        margin-bottom: 1;
    }

    .setting-label {
        width: 15;
        content-align: left middle;
    }

    .setting-row Input {
        width: 1fr;
    }

    .setting-row Select {
        width: 1fr;
    }

    .setting-row Button {
        width: auto;
        margin-left: 1;
    }

    .info-display {
        margin-top: 1;
        padding: 1;
        background: $surface;
        height: auto;
    }

    #settings-buttons {
        margin-top: 2;
        height: 3;
    }

    #settings-buttons Button {
        margin-right: 1;
    }
    """

    SCREENS = {
        "dashboard": DashboardScreen,
        "roster": RosterScreen,
        "matchup": MatchupScreen,
        "gameday": GamedayScreen,
        "lineup": LineupScreen,
        "transactions": TransactionsScreen,
        "settings": SettingsScreen,
    }

    BINDINGS: ClassVar = [
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]

    async def on_mount(self) -> None:
        """Initialize the app on mount."""
        # Initialize database
        await init_database()

        # Push the dashboard screen
        self.push_screen("dashboard")

    async def on_unmount(self) -> None:
        """Clean up on app exit."""
        await close_database()


def main() -> None:
    """Main entry point."""
    app = SBAScoutApp()
    app.run()


if __name__ == "__main__":
    main()
