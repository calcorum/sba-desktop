"""
Matchup Scout Screen - Analyze batters vs opposing pitchers.

Core scouting feature that helps set optimal lineups based on
batter/pitcher handedness matchups.
"""

import logging
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Label,
    Select,
    Static,
)

from ..calc.matchup import MatchupResult, calculate_team_matchups_cached
from ..calc.score_cache import ensure_cache_exists
from ..config import get_settings
from ..db.models import Player, Team
from ..db.queries import get_all_teams, get_my_roster, get_pitchers, get_team_by_id
from ..db.schema import get_session

logger = logging.getLogger(__name__)


class MatchupScreen(Screen):
    """Matchup scouting screen for analyzing batters vs pitchers."""

    BINDINGS: ClassVar = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
        Binding("r", "refresh_matchups", "Refresh"),
        Binding("s", "sort_by_rating", "Sort: Rating", show=True),
        Binding("n", "sort_by_name", "Sort: Name", show=True),
        Binding("p", "sort_by_position", "Sort: Position", show=True),
    ]

    # Current state
    teams: list[Team] = []
    opponent_pitchers: list[Player] = []
    my_batters: list[Player] = []
    selected_team_id: int | None = None
    selected_pitcher: Player | None = None
    matchup_results: list[MatchupResult] = []
    current_sort: str = "rating"  # "rating", "name", or "position"

    def compose(self) -> ComposeResult:
        """Compose the matchup scout layout."""
        yield Header()

        with Vertical(id="matchup-container"):
            # Selection row
            with Horizontal(id="matchup-selectors"):
                yield Label("Opponent:", id="opponent-label")
                yield Select(
                    options=[],
                    prompt="Select Team",
                    id="team-select",
                    allow_blank=True,
                )
                yield Label("Pitcher:", id="pitcher-label")
                yield Select(
                    options=[],
                    prompt="Select Pitcher",
                    id="pitcher-select",
                    allow_blank=True,
                )

            # Pitcher info header
            yield Static("Select an opponent team and pitcher", id="pitcher-info")

            # Matchup table
            with ScrollableContainer(id="matchup-table-container"):
                yield DataTable(id="matchup-table", cursor_type="none", zebra_stripes=True)

        yield Footer()

    async def on_mount(self) -> None:
        """Load initial data when screen mounts."""
        await self._setup_table()
        await self._ensure_score_cache()
        await self._load_teams()
        await self._load_my_batters()

    async def _ensure_score_cache(self) -> None:
        """Ensure standardized score cache exists, building if necessary."""
        try:
            async with get_session() as session:
                await ensure_cache_exists(session)
        except Exception as e:
            logger.error(f"Failed to ensure score cache: {e}")
            self.notify(f"Error building score cache: {e}", severity="error")

    async def _setup_table(self) -> None:
        """Configure the matchup data table columns."""
        table = self.query_one("#matchup-table", DataTable)

        # Columns: suggested order, name, hand, positions, rating, tier, sWAR
        columns = [
            ("#", 3, ""),  # Suggested batting order position
            ("Name", 20, ""),
            ("H", 3, ""),  # Batter's hand
            ("Pos", 14, ""),  # Positions
            ("Rating", 8, ""),  # Matchup rating
            ("Tier", 5, ""),  # Letter grade
            ("sWAR", 6, ""),
            ("Split", 5, ""),  # Which split was used (vL/vR)
        ]

        for name, width, prefix in columns:
            label = f"{prefix}{name}"
            table.add_column(label, key=name.lower(), width=width)

    async def _load_teams(self) -> None:
        """Load all teams for the opponent selector."""
        settings = get_settings()

        try:
            async with get_session() as session:
                self.teams = list(
                    await get_all_teams(session, settings.team.current_season, active_only=True)
                )

            # Populate team select - exclude my team
            team_select = self.query_one("#team-select", Select)
            options = [
                (f"{t.abbrev} - {t.short_name}", t.id)
                for t in self.teams
                if t.abbrev != settings.team.team_abbrev
            ]
            team_select.set_options(options)

        except Exception as e:
            logger.error(f"Failed to load teams: {e}")
            self.notify(f"Error loading teams: {e}", severity="error")

    async def _load_my_batters(self) -> None:
        """Load my team's batters for matchup analysis."""
        settings = get_settings()

        try:
            async with get_session() as session:
                roster = await get_my_roster(
                    session,
                    settings.team.team_abbrev,
                    settings.team.current_season,
                )
                # Only include major league batters
                self.my_batters = [p for p in roster.get("majors", []) if p.is_batter]

        except Exception as e:
            logger.error(f"Failed to load batters: {e}")
            self.notify(f"Error loading batters: {e}", severity="error")

    async def _load_opponent_pitchers(self, team_id: int) -> None:
        """Load pitchers for the selected opponent team."""
        settings = get_settings()

        try:
            async with get_session() as session:
                self.opponent_pitchers = list(
                    await get_pitchers(
                        session, team_id=team_id, season=settings.team.current_season
                    )
                )

            # Populate pitcher select
            pitcher_select = self.query_one("#pitcher-select", Select)
            options = [(f"{p.name} ({p.hand or '?'}HP)", p.id) for p in self.opponent_pitchers]
            pitcher_select.set_options(options)

            # Clear current pitcher selection
            self.selected_pitcher = None
            self.query_one("#pitcher-info", Static).update("Select a pitcher to see matchups")
            self._clear_table()

        except Exception as e:
            logger.error(f"Failed to load pitchers: {e}")
            self.notify(f"Error loading pitchers: {e}", severity="error")

    def _clear_table(self) -> None:
        """Clear the matchup table."""
        table = self.query_one("#matchup-table", DataTable)
        table.clear()
        self.matchup_results = []

    async def _calculate_and_display_matchups(self) -> None:
        """Calculate matchups and populate the table."""
        if not self.selected_pitcher:
            return

        pitcher_hand = self.selected_pitcher.hand or "R"
        if pitcher_hand not in ("L", "R"):
            pitcher_hand = "R"  # Default to R if unknown

        # Get pitcher's card data
        pitcher_card = self.selected_pitcher.pitcher_card

        # Calculate matchups using cached scores
        async with get_session() as session:
            self.matchup_results = await calculate_team_matchups_cached(
                session,
                self.my_batters,
                self.selected_pitcher,
                pitcher_card,
            )

        # Apply current sort
        self._apply_sort()

        # Update pitcher info - show if pitcher has card data
        pitcher_info = self.query_one("#pitcher-info", Static)
        positions = ", ".join(self.selected_pitcher.positions)
        card_status = "" if pitcher_card else " [no card]"
        pitcher_info.update(
            f"vs {self.selected_pitcher.name} ({pitcher_hand}HP) - {positions}{card_status}"
        )

        # Populate table
        self._populate_table()

    def _apply_sort(self) -> None:
        """Sort matchup results based on current sort mode."""
        if self.current_sort == "rating":
            # Sort by rating descending (None at end)
            def rating_key(r: MatchupResult) -> tuple[int, float]:
                if r.rating is None:
                    return (1, 0)
                return (0, -r.rating)

            self.matchup_results.sort(key=rating_key)

        elif self.current_sort == "name":
            self.matchup_results.sort(key=lambda r: r.player.name)

        elif self.current_sort == "position":
            # Sort by primary position, then name
            def pos_key(r: MatchupResult) -> tuple[str, str]:
                positions = r.player.positions
                primary = positions[0] if positions else "ZZ"
                return (primary, r.player.name)

            self.matchup_results.sort(key=pos_key)

    def _populate_table(self) -> None:
        """Populate the table with matchup results."""
        table = self.query_one("#matchup-table", DataTable)
        table.clear()

        for i, result in enumerate(self.matchup_results, start=1):
            player = result.player
            positions = ", ".join(player.positions)

            row = (
                str(i),  # Suggested order
                player.name,
                result.batter_hand,
                positions,
                result.rating_display,
                result.tier,
                f"{player.swar:.2f}" if player.swar else "0.00",
                result.split_display,  # e.g., "vR/vL" showing batter/pitcher splits
            )
            table.add_row(*row, key=str(player.id))

    # =========================================================================
    # Event Handlers
    # =========================================================================

    async def on_select_changed(self, event: Select.Changed) -> None:
        """Handle selection changes in dropdowns."""
        if event.select.id == "team-select":
            if event.value and event.value != Select.BLANK:
                self.selected_team_id = event.value
                await self._load_opponent_pitchers(event.value)
            else:
                self.selected_team_id = None
                # Clear pitcher select
                pitcher_select = self.query_one("#pitcher-select", Select)
                pitcher_select.set_options([])
                self._clear_table()
                self.query_one("#pitcher-info", Static).update(
                    "Select an opponent team and pitcher"
                )

        elif event.select.id == "pitcher-select":
            if event.value and event.value != Select.BLANK:
                # Find the selected pitcher
                self.selected_pitcher = next(
                    (p for p in self.opponent_pitchers if p.id == event.value),
                    None,
                )
                await self._calculate_and_display_matchups()
            else:
                self.selected_pitcher = None
                self._clear_table()
                self.query_one("#pitcher-info", Static).update("Select a pitcher to see matchups")

    # =========================================================================
    # Actions
    # =========================================================================

    async def action_refresh_matchups(self) -> None:
        """Refresh matchup calculations."""
        if self.selected_pitcher:
            await self._calculate_and_display_matchups()
            self.notify("Matchups refreshed", severity="information")
        else:
            self.notify("Select a pitcher first", severity="warning")

    def action_sort_by_rating(self) -> None:
        """Sort table by matchup rating."""
        self.current_sort = "rating"
        if self.matchup_results:
            self._apply_sort()
            self._populate_table()
            self.notify("Sorted by rating")

    def action_sort_by_name(self) -> None:
        """Sort table by player name."""
        self.current_sort = "name"
        if self.matchup_results:
            self._apply_sort()
            self._populate_table()
            self.notify("Sorted by name")

    def action_sort_by_position(self) -> None:
        """Sort table by position."""
        self.current_sort = "position"
        if self.matchup_results:
            self._apply_sort()
            self._populate_table()
            self.notify("Sorted by position")
