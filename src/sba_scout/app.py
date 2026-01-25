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
from .screens.roster import RosterScreen

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
        Binding("l", "switch_screen('lineup')", "Lineup Builder"),
        Binding("t", "switch_screen('transactions')", "Transactions"),
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
                    yield Button("Roster [r]", id="btn-roster", variant="primary")
                    yield Button("Matchup Scout [m]", id="btn-matchup", variant="primary")

                with Horizontal(classes="action-buttons"):
                    yield Button("Lineup Builder [l]", id="btn-lineup", variant="default")
                    yield Button("Transactions [t]", id="btn-transactions", variant="default")

            # Status bar
            with Horizontal(id="status-bar"):
                yield Label("Last sync: Never", id="sync-status")
                yield Button("Sync Now [s]", id="btn-sync", variant="success")

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
                    13,  # TODO: Get current season from API
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


# RosterScreen is imported from screens.roster


class MatchupScreen(Screen):
    """Matchup scouting screen for analyzing batters vs pitchers."""

    BINDINGS: ClassVar = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Matchup Scout - Coming Soon", id="placeholder")
        yield Footer()


class LineupScreen(Screen):
    """Lineup builder for setting batting order and positions."""

    BINDINGS: ClassVar = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Lineup Builder - Coming Soon", id="placeholder")
        yield Footer()


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
    """

    SCREENS = {
        "dashboard": DashboardScreen,
        "roster": RosterScreen,
        "matchup": MatchupScreen,
        "lineup": LineupScreen,
        "transactions": TransactionsScreen,
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
