"""
Lineup Builder Screen - Set batting order and defensive positions.

Allows managers to:
- Select batters from their roster for the starting lineup
- Set batting order (1-9)
- Assign defensive positions based on eligibility
- Save/load named lineups (vs LHP, vs RHP, etc.)
"""

import logging
from dataclasses import dataclass, field
from typing import ClassVar, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
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
from textual.widgets.data_table import RowKey

from ..config import get_settings
from ..db.models import Lineup, Player
from ..db.queries import delete_lineup, get_lineups, get_my_roster, save_lineup, get_lineup_by_name
from ..db.schema import get_session

logger = logging.getLogger(__name__)


# Defensive positions in typical batting order
DEFENSIVE_POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]


@dataclass
class LineupSlot:
    """A slot in the batting order with position assignment."""

    order: int  # 1-9
    player: Optional[Player] = None
    position: Optional[str] = None

    @property
    def display_name(self) -> str:
        return self.player.name if self.player else "---"

    @property
    def display_position(self) -> str:
        return self.position or "---"


class LineupScreen(Screen):
    """Lineup builder for setting batting order and positions."""

    BINDINGS: ClassVar = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
        Binding("a", "add_to_lineup", "Add to Lineup"),
        Binding("r", "remove_from_lineup", "Remove"),
        Binding("k", "move_up", "Move Up"),
        Binding("j", "move_down", "Move Down"),
        Binding("p", "cycle_position", "Change Position"),
        Binding("s", "save_lineup", "Save"),
        Binding("l", "load_lineup", "Load"),
        Binding("d", "delete_lineup", "Delete Saved"),
        Binding("c", "clear_lineup", "Clear"),
    ]

    # Current lineup state
    lineup_slots: list[LineupSlot] = []
    available_batters: list[Player] = []
    saved_lineups: list[Lineup] = []
    current_lineup_name: str = ""

    # Track which table has focus for actions
    _focus_table: str = "available"  # "available" or "lineup"

    def compose(self) -> ComposeResult:
        """Compose the lineup builder layout."""
        yield Header()

        with Horizontal(id="lineup-container"):
            # Left panel - Available batters
            with Vertical(id="available-panel", classes="lineup-panel"):
                yield Label("Available Batters", classes="panel-title")
                with ScrollableContainer(id="available-container"):
                    yield DataTable(
                        id="available-table",
                        cursor_type="row",
                        zebra_stripes=True,
                    )
                yield Static("[a] Add to lineup", classes="hint-text")

            # Right panel - Current lineup
            with Vertical(id="lineup-panel", classes="lineup-panel"):
                yield Label("Current Lineup", classes="panel-title")
                with ScrollableContainer(id="lineup-scroll-container"):
                    yield DataTable(
                        id="lineup-table",
                        cursor_type="row",
                        zebra_stripes=True,
                    )
                yield Static("[k/j] Move Up/Down  [p] Change Pos  [r] Remove", classes="hint-text")

        # Bottom controls
        with Horizontal(id="lineup-controls"):
            yield Label("Name:")
            yield Input(
                placeholder="Lineup name (e.g., 'vs LHP')",
                id="lineup-name-input",
            )
            yield Select(
                options=[],
                prompt="Load saved...",
                id="lineup-select",
                allow_blank=True,
            )
            yield Button("Save [s]", id="btn-save", variant="success")
            yield Button("Clear [c]", id="btn-clear", variant="warning")

        yield Footer()

    async def on_mount(self) -> None:
        """Initialize when screen mounts."""
        self._init_lineup_slots()
        await self._setup_tables()
        await self._load_available_batters()
        await self._load_saved_lineups()

    def _init_lineup_slots(self) -> None:
        """Initialize empty lineup slots for 9 batters."""
        self.lineup_slots = [LineupSlot(order=i) for i in range(1, 10)]

    async def _setup_tables(self) -> None:
        """Configure both data tables."""
        # Available batters table
        avail_table = self.query_one("#available-table", DataTable)
        avail_table.add_column("Name", key="name", width=20)
        avail_table.add_column("Pos", key="pos", width=14)
        avail_table.add_column("H", key="hand", width=3)
        avail_table.add_column("vL", key="vl", width=5)
        avail_table.add_column("vR", key="vr", width=5)
        avail_table.add_column("sWAR", key="swar", width=6)

        # Lineup table
        lineup_table = self.query_one("#lineup-table", DataTable)
        lineup_table.add_column("#", key="order", width=3)
        lineup_table.add_column("Name", key="name", width=20)
        lineup_table.add_column("Pos", key="pos", width=5)
        lineup_table.add_column("Elig", key="elig", width=14)
        lineup_table.add_column("H", key="hand", width=3)
        lineup_table.add_column("sWAR", key="swar", width=6)

    async def _load_available_batters(self) -> None:
        """Load batters from roster."""
        settings = get_settings()

        try:
            async with get_session() as session:
                roster = await get_my_roster(
                    session,
                    settings.team.team_abbrev,
                    settings.team.current_season,
                )
                # Only major league batters
                self.available_batters = [p for p in roster.get("majors", []) if p.is_batter]

            self._populate_available_table()

        except Exception as e:
            logger.error(f"Failed to load batters: {e}")
            self.notify(f"Error loading batters: {e}", severity="error")

    async def _load_saved_lineups(self) -> None:
        """Load saved lineups for the dropdown."""
        try:
            async with get_session() as session:
                self.saved_lineups = list(await get_lineups(session))

            # Populate select
            lineup_select = self.query_one("#lineup-select", Select)
            options = [(f"{lu.name} ({lu.lineup_type})", lu.name) for lu in self.saved_lineups]
            lineup_select.set_options(options)

        except Exception as e:
            logger.error(f"Failed to load saved lineups: {e}")

    def _populate_available_table(self) -> None:
        """Populate the available batters table."""
        table = self.query_one("#available-table", DataTable)
        table.clear()

        # Get players already in lineup
        lineup_player_ids = {slot.player.id for slot in self.lineup_slots if slot.player}

        # Sort by name
        batters = sorted(self.available_batters, key=lambda p: p.name)

        for player in batters:
            # Skip if already in lineup
            if player.id in lineup_player_ids:
                continue

            positions = ", ".join(player.positions)
            hand = player.hand or "?"

            # Get ratings from card
            vl = "---"
            vr = "---"
            if player.batter_card:
                vl = (
                    f"{player.batter_card.rating_vl:.0f}" if player.batter_card.rating_vl else "---"
                )
                vr = (
                    f"{player.batter_card.rating_vr:.0f}" if player.batter_card.rating_vr else "---"
                )

            row = (
                player.name,
                positions,
                hand,
                vl,
                vr,
                f"{player.swar:.2f}" if player.swar else "0.00",
            )
            table.add_row(*row, key=str(player.id))

    def _populate_lineup_table(self) -> None:
        """Populate the current lineup table."""
        table = self.query_one("#lineup-table", DataTable)
        table.clear()

        for slot in self.lineup_slots:
            if slot.player:
                positions = ", ".join(slot.player.positions)
                hand = slot.player.hand or "?"
                row = (
                    str(slot.order),
                    slot.player.name,
                    slot.display_position,
                    positions,
                    hand,
                    f"{slot.player.swar:.2f}" if slot.player.swar else "0.00",
                )
            else:
                row = (
                    str(slot.order),
                    "---",
                    "---",
                    "---",
                    "-",
                    "---",
                )
            table.add_row(*row, key=f"slot-{slot.order}")

    def _get_selected_available_player(self) -> Optional[Player]:
        """Get the currently selected player from the available table."""
        table = self.query_one("#available-table", DataTable)

        # Get the cursor row index
        cursor_row = table.cursor_row
        if cursor_row is None:
            return None

        try:
            # Get all row keys in order
            row_keys = list(table.rows.keys())
            if cursor_row >= len(row_keys):
                return None

            # RowKey objects have a .value attribute containing the actual key
            row_key = row_keys[cursor_row]
            player_id_str = row_key.value  # This is the string we passed to add_row(key=...)
            player_id = int(player_id_str)

            return next((p for p in self.available_batters if p.id == player_id), None)
        except (IndexError, ValueError, KeyError, AttributeError) as e:
            logger.error(f"Failed to get selected player: {e}")
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

        # Positions already filled in lineup
        filled_positions = {
            slot.position for slot in self.lineup_slots if slot.position and slot.player
        }

        # Find first eligible position not yet filled
        for pos in positions:
            if pos in DEFENSIVE_POSITIONS and pos not in filled_positions:
                return pos

        # Default to DH if nothing else available
        if "DH" not in filled_positions:
            return "DH"

        # Just use first position if all else fails
        return positions[0] if positions else "DH"

    def _get_next_position(self, player: Player, current: Optional[str]) -> str:
        """Get next valid position for cycling."""
        positions = player.positions

        # Add DH if not already there
        if "DH" not in positions:
            positions = list(positions) + ["DH"]

        if not current or current not in positions:
            return positions[0] if positions else "DH"

        # Find next position in cycle
        idx = positions.index(current)
        return positions[(idx + 1) % len(positions)]

    # =========================================================================
    # Event Handlers
    # =========================================================================

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Track which table has focus."""
        if event.data_table.id == "available-table":
            self._focus_table = "available"
        elif event.data_table.id == "lineup-table":
            self._focus_table = "lineup"

    async def on_select_changed(self, event: Select.Changed) -> None:
        """Handle lineup selection from dropdown."""
        if event.select.id == "lineup-select":
            if event.value and event.value != Select.BLANK:
                await self._do_load_lineup(event.value)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        if event.button.id == "btn-save":
            await self.action_save_lineup()
        elif event.button.id == "btn-clear":
            await self.action_clear_lineup()

    # =========================================================================
    # Actions
    # =========================================================================

    async def action_add_to_lineup(self) -> None:
        """Add selected available batter to lineup."""
        player = self._get_selected_available_player()
        if not player:
            self.notify("Select a player from available batters", severity="warning")
            return

        slot = self._find_first_empty_slot()
        if not slot:
            self.notify("Lineup is full (9 batters)", severity="warning")
            return

        # Add player with suggested position
        slot.player = player
        slot.position = self._suggest_position(player)

        # Remember which slot the player was added to (0-indexed)
        added_slot_idx = slot.order - 1

        # Refresh both tables
        self._populate_available_table()
        self._populate_lineup_table()

        # Reset available batters cursor to top
        avail_table = self.query_one("#available-table", DataTable)
        if len(list(avail_table.rows)) > 0:
            avail_table.move_cursor(row=0)

        # Move lineup cursor to the newly added player and focus that table
        lineup_table = self.query_one("#lineup-table", DataTable)
        lineup_table.move_cursor(row=added_slot_idx)
        lineup_table.focus()

        self.notify(f"Added {player.name} at {slot.position}")

    async def action_remove_from_lineup(self) -> None:
        """Remove selected player from lineup."""
        lineup_table = self.query_one("#lineup-table", DataTable)
        cursor_row = lineup_table.cursor_row  # Save cursor position

        slot = self._get_selected_lineup_slot()
        if not slot or not slot.player:
            self.notify("Select a player in the lineup to remove", severity="warning")
            return

        player_name = slot.player.name
        slot.player = None
        slot.position = None

        # Refresh both tables
        self._populate_available_table()
        self._populate_lineup_table()

        # Restore cursor position
        if cursor_row is not None:
            lineup_table.move_cursor(row=cursor_row)

        self.notify(f"Removed {player_name}")

    async def action_move_up(self) -> None:
        """Move selected lineup slot up in batting order."""
        slot = self._get_selected_lineup_slot()
        if not slot:
            return

        idx = slot.order - 1  # 0-indexed
        if idx <= 0:
            self.notify("Already at top of order")
            return

        # Swap with slot above
        self.lineup_slots[idx], self.lineup_slots[idx - 1] = (
            self.lineup_slots[idx - 1],
            self.lineup_slots[idx],
        )

        # Update order numbers
        for i, s in enumerate(self.lineup_slots):
            s.order = i + 1

        # Refresh and move cursor
        self._populate_lineup_table()
        table = self.query_one("#lineup-table", DataTable)
        table.move_cursor(row=idx - 1)

    async def action_move_down(self) -> None:
        """Move selected lineup slot down in batting order."""
        slot = self._get_selected_lineup_slot()
        if not slot:
            return

        idx = slot.order - 1  # 0-indexed
        if idx >= 8:  # Already at position 9
            self.notify("Already at bottom of order")
            return

        # Swap with slot below
        self.lineup_slots[idx], self.lineup_slots[idx + 1] = (
            self.lineup_slots[idx + 1],
            self.lineup_slots[idx],
        )

        # Update order numbers
        for i, s in enumerate(self.lineup_slots):
            s.order = i + 1

        # Refresh and move cursor
        self._populate_lineup_table()
        table = self.query_one("#lineup-table", DataTable)
        table.move_cursor(row=idx + 1)

    async def action_cycle_position(self) -> None:
        """Cycle through available positions for selected player."""
        table = self.query_one("#lineup-table", DataTable)
        cursor_row = table.cursor_row  # Save cursor position

        slot = self._get_selected_lineup_slot()
        if not slot or not slot.player:
            self.notify("Select a player in the lineup", severity="warning")
            return

        slot.position = self._get_next_position(slot.player, slot.position)
        self._populate_lineup_table()

        # Restore cursor position
        if cursor_row is not None:
            table.move_cursor(row=cursor_row)

        self.notify(f"{slot.player.name} -> {slot.position}")

    async def action_save_lineup(self) -> None:
        """Save current lineup."""
        name_input = self.query_one("#lineup-name-input", Input)
        name = name_input.value.strip()

        if not name:
            self.notify("Enter a lineup name", severity="warning")
            name_input.focus()
            return

        # Build batting order and positions
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
                    lineup_type="standard",
                    description=f"Saved lineup with {len(batting_order)} batters",
                )
                await session.commit()

            self.current_lineup_name = name
            await self._load_saved_lineups()  # Refresh dropdown
            self.notify(f"Saved lineup: {name}", severity="information")

        except Exception as e:
            logger.error(f"Failed to save lineup: {e}")
            self.notify(f"Error saving lineup: {e}", severity="error")

    async def action_load_lineup(self) -> None:
        """Focus the lineup dropdown for selection."""
        self.query_one("#lineup-select", Select).focus()

    async def _do_load_lineup(self, name: str) -> None:
        """Load a specific lineup by name."""
        try:
            async with get_session() as session:
                lineup = await get_lineup_by_name(session, name)

                if not lineup:
                    self.notify(f"Lineup '{name}' not found", severity="error")
                    return

                # Reset slots
                self._init_lineup_slots()

                # Build player lookup
                player_lookup = {p.id: p for p in self.available_batters}

                # Load batting order
                batting_order = lineup.batting_order or []
                positions_map = lineup.positions or {}

                # Reverse map: player_id -> position
                player_positions = {v: k for k, v in positions_map.items()}

                for i, player_id in enumerate(batting_order[:9]):
                    player = player_lookup.get(player_id)
                    if player and i < len(self.lineup_slots):
                        self.lineup_slots[i].player = player
                        self.lineup_slots[i].position = player_positions.get(player_id)

                # Update UI
                self.current_lineup_name = name
                name_input = self.query_one("#lineup-name-input", Input)
                name_input.value = name

                self._populate_available_table()
                self._populate_lineup_table()

                self.notify(f"Loaded lineup: {name}")

        except Exception as e:
            logger.error(f"Failed to load lineup: {e}")
            self.notify(f"Error loading lineup: {e}", severity="error")

    async def action_clear_lineup(self) -> None:
        """Clear all slots in the current lineup."""
        self._init_lineup_slots()
        self._populate_available_table()
        self._populate_lineup_table()

        # Clear name input
        name_input = self.query_one("#lineup-name-input", Input)
        name_input.value = ""
        self.current_lineup_name = ""

        self.notify("Lineup cleared")

    async def action_delete_lineup(self) -> None:
        """Delete the currently loaded lineup from the database."""
        name_input = self.query_one("#lineup-name-input", Input)
        name = name_input.value.strip()

        if not name:
            self.notify("Enter or load a lineup name to delete", severity="warning")
            return

        # Check if this lineup exists
        lineup_exists = any(lu.name == name for lu in self.saved_lineups)
        if not lineup_exists:
            self.notify(f"Lineup '{name}' not found in saved lineups", severity="warning")
            return

        try:
            async with get_session() as session:
                deleted = await delete_lineup(session, name)
                await session.commit()

            if deleted:
                # Clear current lineup if it was the one deleted
                if self.current_lineup_name == name:
                    self._init_lineup_slots()
                    self._populate_available_table()
                    self._populate_lineup_table()
                    self.current_lineup_name = ""
                    name_input.value = ""

                await self._load_saved_lineups()  # Refresh dropdown
                self.notify(f"Deleted lineup: {name}", severity="information")
            else:
                self.notify(f"Lineup '{name}' not found", severity="error")

        except Exception as e:
            logger.error(f"Failed to delete lineup: {e}")
            self.notify(f"Error deleting lineup: {e}", severity="error")
