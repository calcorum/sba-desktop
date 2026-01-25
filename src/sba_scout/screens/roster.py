"""
Roster Screen - Full roster view organized by roster status.

Displays Majors/Minors/IL rosters with separate tables for batters and pitchers.
"""

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
    Static,
    TabbedContent,
    TabPane,
)

from ..config import get_settings
from ..db.models import Player
from ..db.queries import get_my_roster
from ..db.schema import get_session


class RosterScreen(Screen):
    """Roster screen showing full roster organized by roster status."""

    BINDINGS: ClassVar = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
        Binding("f", "refresh_roster", "Refresh"),
        Binding("1", "switch_tab('majors')", "Majors", show=False),
        Binding("2", "switch_tab('minors')", "Minors", show=False),
        Binding("3", "switch_tab('il')", "IL", show=False),
    ]

    def compose(self) -> ComposeResult:
        """Compose the roster layout."""
        settings = get_settings()

        yield Header()

        with Vertical(id="roster-container"):
            # Team header with sWAR summary
            with Horizontal(id="roster-header"):
                yield Label(f"Roster - {settings.team.team_name}", id="roster-title")
                yield Label("sWAR: --/--", id="swar-summary")

            # Tabbed roster views
            with TabbedContent(id="roster-tabs"):
                with TabPane(f"Majors ({settings.team.major_league_slots})", id="majors"):
                    yield self._create_roster_pane("majors")

                with TabPane(f"Minors ({settings.team.minor_league_slots})", id="minors"):
                    yield self._create_roster_pane("minors")

                with TabPane("IL", id="il"):
                    yield self._create_roster_pane("il")

        yield Footer()

    def _create_roster_pane(self, roster_type: str) -> ScrollableContainer:
        """Create a roster pane with batters and pitchers tables."""
        return ScrollableContainer(
            Label("Batters", classes="section-label"),
            DataTable(id=f"{roster_type}-batters-table", cursor_type="none", zebra_stripes=True),
            Label("Pitchers", classes="section-label"),
            DataTable(id=f"{roster_type}-pitchers-table", cursor_type="none", zebra_stripes=True),
            classes="roster-pane",
        )

    async def on_mount(self) -> None:
        """Load data when screen is mounted."""
        await self._setup_tables()
        await self._load_roster()

    async def _setup_tables(self) -> None:
        """Configure the data tables with columns."""
        # Batter columns: (name, width, header_prefix)
        # header_prefix adds leading spaces to align headers with right-aligned data
        batter_columns = [
            ("Name", 20, ""),
            ("H", 3, ""),  # Hand
            ("Pos", 14, ""),  # Positions
            ("vL", 5, "  "),  # Rating vs LHP - 2 spaces
            ("vR", 5, "  "),  # Rating vs RHP - 2 spaces
            ("Ovr", 5, " "),  # Overall rating - 1 space
            ("sWAR", 5, ""),
            ("Defense", None, ""),  # No fixed width - will wrap
        ]

        # Pitcher columns: (name, width, header_prefix)
        pitcher_columns = [
            ("Name", 20, ""),
            ("H", 3, ""),  # Hand
            ("Pos", 12, ""),  # Positions (SP, RP, CP) - wide enough for all 3
            ("vL", 5, "  "),  # Rating vs LHB - 2 spaces
            ("vR", 5, "  "),  # Rating vs RHB - 2 spaces
            ("Ovr", 5, " "),  # Overall rating - 1 space
            ("sWAR", 5, ""),
            ("S", 3, " "),  # Starter endurance
            ("R", 3, " "),  # Relief endurance
            ("C", 3, " "),  # Closer endurance
        ]

        for roster_type in ["majors", "minors", "il"]:
            # Setup batter table
            batter_table = self.query_one(f"#{roster_type}-batters-table", DataTable)
            for name, width, prefix in batter_columns:
                label = f"{prefix}{name}"
                if width:
                    batter_table.add_column(label, key=name.lower(), width=width)
                else:
                    batter_table.add_column(label, key=name.lower())

            # Setup pitcher table
            pitcher_table = self.query_one(f"#{roster_type}-pitchers-table", DataTable)
            for name, width, prefix in pitcher_columns:
                label = f"{prefix}{name}"
                if width:
                    pitcher_table.add_column(label, key=name.lower(), width=width)
                else:
                    pitcher_table.add_column(label, key=name.lower())

    async def _load_roster(self) -> None:
        """Load roster data from database."""
        settings = get_settings()

        try:
            async with get_session() as session:
                roster = await get_my_roster(
                    session,
                    settings.team.team_abbrev,
                    13,  # TODO: Get current season from config/API
                )

                # Calculate sWAR totals
                majors_swar = sum(p.swar or 0 for p in roster.get("majors", []))
                il_swar = sum(p.swar or 0 for p in roster.get("il", []))
                total_swar = majors_swar + il_swar

                # Update sWAR summary
                self.query_one("#swar-summary", Label).update(
                    f"sWAR: {total_swar:.1f}/{settings.team.swar_cap}"
                )

                # Populate tables for each roster type
                for roster_type in ["majors", "minors", "il"]:
                    players = roster.get(roster_type, [])
                    await self._populate_tables(roster_type, players)

        except Exception as e:
            self.notify(f"Error loading roster: {e}", severity="error")

    async def _populate_tables(self, roster_type: str, players: list[Player]) -> None:
        """Populate batter and pitcher tables with player data."""
        batter_table = self.query_one(f"#{roster_type}-batters-table", DataTable)
        pitcher_table = self.query_one(f"#{roster_type}-pitchers-table", DataTable)

        batter_table.clear()
        pitcher_table.clear()

        # Separate batters and pitchers
        batters = [p for p in players if p.is_batter and p.batter_card]
        pitchers = [p for p in players if p.is_pitcher and p.pitcher_card]

        # Players without cards go to appropriate table based on position
        for p in players:
            if not p.batter_card and not p.pitcher_card:
                if p.is_pitcher:
                    pitchers.append(p)
                else:
                    batters.append(p)

        # Sort alphabetically by name
        batters.sort(key=lambda p: p.name)
        pitchers.sort(key=lambda p: p.name)

        # Populate batter table
        for player in batters:
            row = self._make_batter_row(player)
            batter_table.add_row(*row, key=str(player.id))

        # Populate pitcher table
        for player in pitchers:
            row = self._make_pitcher_row(player)
            pitcher_table.add_row(*row, key=str(player.id))

    def _make_batter_row(self, player: Player) -> tuple:
        """Create a table row for a batter."""
        card = player.batter_card

        # Get positions string
        positions = ", ".join(player.positions)

        # Get ratings (right-aligned with padding for alignment)
        if card:
            rating_vl = f"{card.rating_vl:>4.0f}" if card.rating_vl is not None else "  --"
            rating_vr = f"{card.rating_vr:>4.0f}" if card.rating_vr is not None else "  --"
            rating_ovr = (
                f"{card.rating_overall:>4.0f}" if card.rating_overall is not None else "  --"
            )
            defense = card.fielding or "--"
        else:
            rating_vl = "  --"
            rating_vr = "  --"
            rating_ovr = "  --"
            defense = "--"

        return (
            player.name,
            player.hand or "-",
            positions,
            rating_vl,
            rating_vr,
            rating_ovr,
            f"{player.swar:.2f}" if player.swar else "0.00",
            defense,
        )

    def _make_pitcher_row(self, player: Player) -> tuple:
        """Create a table row for a pitcher."""
        card = player.pitcher_card

        # Get positions string (SP, RP, CP)
        positions = ", ".join(player.positions)

        # Get ratings (right-aligned with padding for alignment)
        if card:
            rating_vl = f"{card.rating_vlhb:>4.0f}" if card.rating_vlhb is not None else "  --"
            rating_vr = f"{card.rating_vrhb:>4.0f}" if card.rating_vrhb is not None else "  --"
            rating_ovr = (
                f"{card.rating_overall:>4.0f}" if card.rating_overall is not None else "  --"
            )
            endurance_s = f"{card.endurance_start:>2}" if card.endurance_start is not None else " -"
            endurance_r = (
                f"{card.endurance_relief:>2}" if card.endurance_relief is not None else " -"
            )
            endurance_c = f"{card.endurance_close:>2}" if card.endurance_close is not None else " -"
        else:
            rating_vl = "  --"
            rating_vr = "  --"
            rating_ovr = "  --"
            endurance_s = " -"
            endurance_r = " -"
            endurance_c = " -"

        return (
            player.name,
            player.hand or "-",
            positions,
            rating_vl,
            rating_vr,
            rating_ovr,
            f"{player.swar:.2f}" if player.swar else "0.00",
            endurance_s,
            endurance_r,
            endurance_c,
        )

    async def action_refresh_roster(self) -> None:
        """Refresh roster data from database."""
        self.notify("Refreshing roster...")
        await self._load_roster()
        self.notify("Roster refreshed", severity="information")

    def action_switch_tab(self, tab_id: str) -> None:
        """Switch to a specific roster tab."""
        tabs = self.query_one("#roster-tabs", TabbedContent)
        tabs.active = tab_id
