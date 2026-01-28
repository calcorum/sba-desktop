"""
Gameday Screen - Integrated Matchup Scout + Lineup Builder.

Pre-game workflow: analyze matchups against opposing pitcher,
then build your lineup based on the matchup advantages.

Left panel: Matchup analysis (team/pitcher selection, batter ratings)
Right panel: Lineup builder (batting order with positions)
"""

import logging
from dataclasses import dataclass
from typing import ClassVar, Optional

from textual.app import ComposeResult, on
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.events import Click
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
)

from ..calc.matchup import MatchupResult, calculate_team_matchups_cached
from ..calc.score_cache import ensure_cache_exists
from ..config import get_settings
from ..db.models import Lineup, Player, Team
from ..db.queries import (
    delete_lineup,
    get_all_teams,
    get_lineups,
    get_lineup_by_name,
    get_my_roster,
    get_pitchers,
    save_lineup,
)
from ..db.schema import get_session

logger = logging.getLogger(__name__)


# Defensive positions
DEFENSIVE_POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]


@dataclass
class LineupSlot:
    """A slot in the batting order with position assignment."""

    order: int  # 1-9
    player: Optional[Player] = None
    position: Optional[str] = None
    matchup_rating: Optional[float] = None  # Rating vs current pitcher


class GamedayScreen(Screen):
    """Integrated matchup scout and lineup builder for game day preparation."""

    BINDINGS: ClassVar = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
        # Matchup controls
        Binding("s", "sort_by_rating", "Sort: Rating"),
        Binding("n", "sort_by_name", "Sort: Name"),
        # Lineup controls
        Binding("a", "add_to_lineup", "Add to Lineup"),
        Binding("r", "remove_from_lineup", "Remove"),
        Binding("k", "move_up", "Move Up"),
        Binding("j", "move_down", "Move Down"),
        Binding("p", "cycle_position", "Change Pos"),
        Binding("ctrl+s", "save_lineup", "Save Lineup"),
        Binding("c", "clear_lineup", "Clear"),
    ]

    # Matchup state
    teams: list[Team] = []
    opponent_pitchers: list[Player] = []
    my_batters: list[Player] = []
    selected_team_id: int | None = None
    selected_pitcher: Player | None = None
    matchup_results: list[MatchupResult] = []
    current_sort: str = "rating"

    # Lineup state
    lineup_slots: list[LineupSlot] = []
    saved_lineups: list[Lineup] = []
    current_lineup_name: str = ""
    _last_lineup_row: int | None = None  # Track last selected row for deselect toggle

    def compose(self) -> ComposeResult:
        """Compose the gameday layout with side-by-side panels."""
        yield Header()

        with Horizontal(id="gameday-container"):
            # Left panel - Matchup Scout
            with Vertical(id="matchup-panel", classes="gameday-panel"):
                yield Label("Matchup Scout", classes="panel-title")

                # Team/Pitcher selectors
                with Horizontal(id="gameday-selectors"):
                    yield Label("vs")
                    yield Select(
                        options=[],
                        prompt="Team",
                        id="team-select",
                        allow_blank=True,
                    )
                    yield Select(
                        options=[],
                        prompt="Pitcher",
                        id="pitcher-select",
                        allow_blank=True,
                    )

                # Pitcher info
                yield Static("Select opponent", id="pitcher-info")

                # Matchup table
                with ScrollableContainer(id="matchup-scroll"):
                    yield DataTable(
                        id="matchup-table",
                        cursor_type="row",
                        zebra_stripes=True,
                    )

                yield Static("[a] Add to lineup  [s/n] Sort", classes="hint-text")

            # Right panel - Lineup Builder
            with Vertical(id="lineup-panel", classes="gameday-panel"):
                # Save/Load controls at top
                with Horizontal(id="lineup-save-controls"):
                    yield Input(
                        placeholder="Lineup name",
                        id="lineup-name-input",
                    )
                    yield Select(
                        options=[],
                        prompt="Load",
                        id="lineup-select",
                        allow_blank=True,
                    )
                    yield Button("Save", id="btn-save", variant="success")

                yield Label("Game Lineup", classes="panel-title")

                # Lineup table
                with ScrollableContainer(id="lineup-scroll"):
                    yield DataTable(
                        id="lineup-table",
                        cursor_type="row",
                        zebra_stripes=True,
                    )

                yield Static("[k/j] Move  [p] Pos  [r] Remove", classes="hint-text")

        yield Footer()

    async def on_mount(self) -> None:
        """Initialize when screen mounts."""
        self._init_lineup_slots()
        await self._setup_tables()
        await self._ensure_score_cache()
        await self._load_teams()
        await self._load_my_batters()
        await self._load_saved_lineups()

    def _init_lineup_slots(self) -> None:
        """Initialize empty lineup slots for 9 batters."""
        self.lineup_slots = [LineupSlot(order=i) for i in range(1, 10)]

    async def _setup_tables(self) -> None:
        """Configure both data tables."""
        # Matchup table
        matchup_table = self.query_one("#matchup-table", DataTable)
        matchup_table.add_column("#", key="rank", width=3)
        matchup_table.add_column("Name", key="name", width=18)
        matchup_table.add_column("Pos", key="pos", width=12)
        matchup_table.add_column("H", key="hand", width=2)
        matchup_table.add_column("Rating", key="rating", width=7)
        matchup_table.add_column("Tier", key="tier", width=4)

        # Lineup table
        lineup_table = self.query_one("#lineup-table", DataTable)
        lineup_table.add_column("#", key="order", width=2)
        lineup_table.add_column("H", key="hand", width=2)
        lineup_table.add_column("Name", key="name", width=16)
        lineup_table.add_column("Pos", key="pos", width=4)
        lineup_table.add_column("Rating", key="rating", width=7)
        lineup_table.add_column("Tier", key="tier", width=4)

    async def _ensure_score_cache(self) -> None:
        """Ensure standardized score cache exists."""
        try:
            async with get_session() as session:
                await ensure_cache_exists(session)
        except Exception as e:
            logger.error(f"Failed to ensure score cache: {e}")

    async def _load_teams(self) -> None:
        """Load all teams for the opponent selector."""
        settings = get_settings()
        try:
            async with get_session() as session:
                self.teams = list(
                    await get_all_teams(session, settings.team.current_season, active_only=True)
                )

            team_select = self.query_one("#team-select", Select)
            options = [
                (f"{t.abbrev}", t.id) for t in self.teams if t.abbrev != settings.team.team_abbrev
            ]
            team_select.set_options(options)
        except Exception as e:
            logger.error(f"Failed to load teams: {e}")

    async def _load_my_batters(self) -> None:
        """Load my team's batters."""
        settings = get_settings()
        try:
            async with get_session() as session:
                roster = await get_my_roster(
                    session,
                    settings.team.team_abbrev,
                    settings.team.current_season,
                )
                self.my_batters = [p for p in roster.get("majors", []) if p.is_batter]
        except Exception as e:
            logger.error(f"Failed to load batters: {e}")

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

            pitcher_select = self.query_one("#pitcher-select", Select)
            options = [(f"{p.name} ({p.hand or '?'})", p.id) for p in self.opponent_pitchers]
            pitcher_select.set_options(options)

            self.selected_pitcher = None
            self.query_one("#pitcher-info", Static).update("Select a pitcher")
            self._clear_matchup_table()
        except Exception as e:
            logger.error(f"Failed to load pitchers: {e}")

    async def _load_saved_lineups(self) -> None:
        """Load saved lineups for the dropdown."""
        try:
            async with get_session() as session:
                self.saved_lineups = list(await get_lineups(session))

            lineup_select = self.query_one("#lineup-select", Select)
            options = [(lu.name, lu.name) for lu in self.saved_lineups]
            lineup_select.set_options(options)
        except Exception as e:
            logger.error(f"Failed to load saved lineups: {e}")

    def _clear_matchup_table(self) -> None:
        """Clear the matchup table."""
        table = self.query_one("#matchup-table", DataTable)
        table.clear()
        self.matchup_results = []

    async def _calculate_and_display_matchups(self) -> None:
        """Calculate matchups and populate the table."""
        if not self.selected_pitcher:
            return

        pitcher_card = self.selected_pitcher.pitcher_card

        async with get_session() as session:
            self.matchup_results = await calculate_team_matchups_cached(
                session,
                self.my_batters,
                self.selected_pitcher,
                pitcher_card,
            )

        self._apply_sort()
        self._populate_matchup_table()
        self._update_lineup_ratings()

        # Update pitcher info
        pitcher_info = self.query_one("#pitcher-info", Static)
        hand = self.selected_pitcher.hand or "?"
        card_status = "" if pitcher_card else " [no card]"
        pitcher_info.update(f"vs {self.selected_pitcher.name} ({hand}HP){card_status}")

    def _apply_sort(self) -> None:
        """Sort matchup results."""
        if self.current_sort == "rating":

            def rating_key(r: MatchupResult) -> tuple[int, float]:
                if r.rating is None:
                    return (1, 0)
                return (0, -r.rating)

            self.matchup_results.sort(key=rating_key)
        elif self.current_sort == "name":
            self.matchup_results.sort(key=lambda r: r.player.name)

    def _populate_matchup_table(self) -> None:
        """Populate the matchup table."""
        table = self.query_one("#matchup-table", DataTable)
        table.clear()

        # Get players already in lineup
        lineup_player_ids = {slot.player.id for slot in self.lineup_slots if slot.player}

        for i, result in enumerate(self.matchup_results, start=1):
            player = result.player
            positions = ", ".join(player.positions[:3])  # Limit to 3 positions

            # Mark if already in lineup
            name = player.name
            if player.id in lineup_player_ids:
                name = f"* {name}"

            row = (
                str(i),
                name,
                positions,
                result.batter_hand,
                result.rating_display,
                result.tier,
            )
            table.add_row(*row, key=str(player.id))

    def _populate_lineup_table(self) -> None:
        """Populate the lineup table."""
        table = self.query_one("#lineup-table", DataTable)
        cursor_row = table.cursor_row
        table.clear()

        # Build rating lookup from current matchup results
        rating_lookup = {r.player.id: r for r in self.matchup_results}

        for slot in self.lineup_slots:
            if slot.player:
                # Get matchup rating if available
                matchup = rating_lookup.get(slot.player.id)
                rating_str = matchup.rating_display if matchup else "---"
                tier_str = matchup.tier if matchup else "-"
                hand = slot.player.hand or "?"

                row = (
                    str(slot.order),
                    hand,
                    slot.player.name,
                    slot.position or "---",
                    rating_str,
                    tier_str,
                )
            else:
                row = (str(slot.order), "-", "---", "---", "---", "-")
            table.add_row(*row, key=f"slot-{slot.order}")

        # Restore cursor
        if cursor_row is not None and cursor_row < 9:
            table.move_cursor(row=cursor_row)

    def _update_lineup_ratings(self) -> None:
        """Update ratings in lineup table after matchup calculation."""
        self._populate_lineup_table()

    def _get_selected_matchup_player(self) -> Optional[Player]:
        """Get the currently selected player from matchup table."""
        table = self.query_one("#matchup-table", DataTable)
        cursor_row = table.cursor_row
        if cursor_row is None:
            return None

        try:
            row_keys = list(table.rows.keys())
            if cursor_row >= len(row_keys):
                return None
            player_id = int(row_keys[cursor_row].value)
            return next((p for p in self.my_batters if p.id == player_id), None)
        except (IndexError, ValueError, AttributeError):
            return None

    def _get_selected_lineup_slot(self) -> Optional[LineupSlot]:
        """Get the currently selected lineup slot."""
        table = self.query_one("#lineup-table", DataTable)
        if table.cursor_row is None:
            return None
        if 0 <= table.cursor_row < len(self.lineup_slots):
            return self.lineup_slots[table.cursor_row]
        return None

    def _find_first_empty_slot(self) -> Optional[LineupSlot]:
        """Find the first empty slot in the lineup."""
        for slot in self.lineup_slots:
            if slot.player is None:
                return slot
        return None

    def _suggest_position(self, player: Player) -> str:
        """Suggest the best available position for a player."""
        positions = player.positions
        filled_positions = {
            slot.position for slot in self.lineup_slots if slot.position and slot.player
        }
        for pos in positions:
            if pos in DEFENSIVE_POSITIONS and pos not in filled_positions:
                return pos
        if "DH" not in filled_positions:
            return "DH"
        return positions[0] if positions else "DH"

    def _get_next_position(self, player: Player, current: Optional[str]) -> str:
        """Get next valid position for cycling."""
        positions = list(player.positions)
        if "DH" not in positions:
            positions.append("DH")
        if not current or current not in positions:
            return positions[0] if positions else "DH"
        idx = positions.index(current)
        return positions[(idx + 1) % len(positions)]

    # =========================================================================
    # Event Handlers
    # =========================================================================

    async def on_select_changed(self, event: Select.Changed) -> None:
        """Handle selection changes."""
        if event.select.id == "team-select":
            if event.value and event.value != Select.BLANK:
                self.selected_team_id = event.value
                await self._load_opponent_pitchers(event.value)
            else:
                self.selected_team_id = None
                self.query_one("#pitcher-select", Select).set_options([])
                self._clear_matchup_table()
                self.query_one("#pitcher-info", Static).update("Select opponent")

        elif event.select.id == "pitcher-select":
            if event.value and event.value != Select.BLANK:
                self.selected_pitcher = next(
                    (p for p in self.opponent_pitchers if p.id == event.value), None
                )
                await self._calculate_and_display_matchups()
            else:
                self.selected_pitcher = None
                self._clear_matchup_table()
                self.query_one("#pitcher-info", Static).update("Select a pitcher")

        elif event.select.id == "lineup-select":
            if event.value and event.value != Select.BLANK:
                await self._do_load_lineup(event.value)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        if event.button.id == "btn-save":
            await self.action_save_lineup()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection - toggle cursor off only if clicking same row twice."""
        table = event.data_table
        if table.id == "lineup-table":
            current_row = event.cursor_row
            # Only toggle off if clicking the same row that was already selected
            if table.cursor_type == "row" and current_row == self._last_lineup_row:
                table.cursor_type = "none"
                self._last_lineup_row = None
            else:
                table.cursor_type = "row"
                self._last_lineup_row = current_row

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Re-enable cursor when navigating with keys."""
        table = event.data_table
        if table.id == "lineup-table" and table.cursor_type == "none":
            # Re-enable cursor when user navigates
            table.cursor_type = "row"

    @on(Click, "#lineup-table")
    def on_lineup_table_click(self, event: Click) -> None:
        """Re-enable cursor when lineup table is clicked while deselected."""
        lineup_table = self.query_one("#lineup-table", DataTable)
        if lineup_table.cursor_type == "none":
            lineup_table.cursor_type = "row"
            self._last_lineup_row = None

    # =========================================================================
    # Actions
    # =========================================================================

    def action_sort_by_rating(self) -> None:
        """Sort matchup table by rating."""
        self.current_sort = "rating"
        if self.matchup_results:
            self._apply_sort()
            self._populate_matchup_table()

    def action_sort_by_name(self) -> None:
        """Sort matchup table by name."""
        self.current_sort = "name"
        if self.matchup_results:
            self._apply_sort()
            self._populate_matchup_table()

    async def action_add_to_lineup(self) -> None:
        """Add selected matchup batter to lineup."""
        player = self._get_selected_matchup_player()
        if not player:
            self.notify("Select a batter from matchup results", severity="warning")
            return

        # Check if already in lineup
        if any(slot.player and slot.player.id == player.id for slot in self.lineup_slots):
            self.notify(f"{player.name} already in lineup", severity="warning")
            return

        slot = self._find_first_empty_slot()
        if not slot:
            self.notify("Lineup is full (9 batters)", severity="warning")
            return

        slot.player = player
        slot.position = self._suggest_position(player)
        added_slot_idx = slot.order - 1

        self._populate_matchup_table()  # Update to show * prefix
        self._populate_lineup_table()

        # Move lineup cursor to new player
        lineup_table = self.query_one("#lineup-table", DataTable)
        lineup_table.move_cursor(row=added_slot_idx)

        self.notify(f"Added {player.name} at {slot.position}")

    async def action_remove_from_lineup(self) -> None:
        """Remove selected player from lineup."""
        lineup_table = self.query_one("#lineup-table", DataTable)
        cursor_row = lineup_table.cursor_row

        slot = self._get_selected_lineup_slot()
        if not slot or not slot.player:
            self.notify("Select a player in the lineup", severity="warning")
            return

        player_name = slot.player.name
        slot.player = None
        slot.position = None

        self._populate_matchup_table()  # Update to remove * prefix
        self._populate_lineup_table()

        if cursor_row is not None:
            lineup_table.move_cursor(row=cursor_row)

        self.notify(f"Removed {player_name}")

    async def action_move_up(self) -> None:
        """Move selected slot up in batting order."""
        slot = self._get_selected_lineup_slot()
        if not slot:
            return

        idx = slot.order - 1
        if idx <= 0:
            return

        self.lineup_slots[idx], self.lineup_slots[idx - 1] = (
            self.lineup_slots[idx - 1],
            self.lineup_slots[idx],
        )
        for i, s in enumerate(self.lineup_slots):
            s.order = i + 1

        self._populate_lineup_table()
        self.query_one("#lineup-table", DataTable).move_cursor(row=idx - 1)

    async def action_move_down(self) -> None:
        """Move selected slot down in batting order."""
        slot = self._get_selected_lineup_slot()
        if not slot:
            return

        idx = slot.order - 1
        if idx >= 8:
            return

        self.lineup_slots[idx], self.lineup_slots[idx + 1] = (
            self.lineup_slots[idx + 1],
            self.lineup_slots[idx],
        )
        for i, s in enumerate(self.lineup_slots):
            s.order = i + 1

        self._populate_lineup_table()
        self.query_one("#lineup-table", DataTable).move_cursor(row=idx + 1)

    async def action_cycle_position(self) -> None:
        """Cycle through positions for selected player."""
        lineup_table = self.query_one("#lineup-table", DataTable)
        cursor_row = lineup_table.cursor_row

        slot = self._get_selected_lineup_slot()
        if not slot or not slot.player:
            self.notify("Select a player in the lineup", severity="warning")
            return

        slot.position = self._get_next_position(slot.player, slot.position)
        self._populate_lineup_table()

        if cursor_row is not None:
            lineup_table.move_cursor(row=cursor_row)

        self.notify(f"{slot.player.name} -> {slot.position}")

    async def action_save_lineup(self) -> None:
        """Save current lineup."""
        name_input = self.query_one("#lineup-name-input", Input)
        name = name_input.value.strip()

        if not name:
            self.notify("Enter a lineup name", severity="warning")
            name_input.focus()
            return

        batting_order = []
        positions = {}
        for slot in self.lineup_slots:
            if slot.player:
                batting_order.append(slot.player.id)
                if slot.position:
                    positions[slot.position] = slot.player.id

        if not batting_order:
            self.notify("Lineup is empty", severity="warning")
            return

        try:
            async with get_session() as session:
                await save_lineup(
                    session,
                    name=name,
                    batting_order=batting_order,
                    positions=positions,
                    lineup_type="gameday",
                )
                await session.commit()

            self.current_lineup_name = name
            await self._load_saved_lineups()
            self.notify(f"Saved: {name}")
        except Exception as e:
            logger.error(f"Failed to save lineup: {e}")
            self.notify(f"Error saving: {e}", severity="error")

    async def _do_load_lineup(self, name: str) -> None:
        """Load a lineup by name."""
        try:
            async with get_session() as session:
                lineup = await get_lineup_by_name(session, name)
                if not lineup:
                    self.notify(f"Lineup '{name}' not found", severity="error")
                    return

                self._init_lineup_slots()
                player_lookup = {p.id: p for p in self.my_batters}
                batting_order = lineup.batting_order or []
                positions_map = lineup.positions or {}
                player_positions = {v: k for k, v in positions_map.items()}

                for i, player_id in enumerate(batting_order[:9]):
                    player = player_lookup.get(player_id)
                    if player and i < len(self.lineup_slots):
                        self.lineup_slots[i].player = player
                        self.lineup_slots[i].position = player_positions.get(player_id)

                self.current_lineup_name = name
                self.query_one("#lineup-name-input", Input).value = name

                self._populate_matchup_table()
                self._populate_lineup_table()
                self.notify(f"Loaded: {name}")
        except Exception as e:
            logger.error(f"Failed to load lineup: {e}")
            self.notify(f"Error loading: {e}", severity="error")

    async def action_clear_lineup(self) -> None:
        """Clear the lineup."""
        self._init_lineup_slots()
        self._populate_matchup_table()
        self._populate_lineup_table()
        self.query_one("#lineup-name-input", Input).value = ""
        self.current_lineup_name = ""
        self.notify("Lineup cleared")
