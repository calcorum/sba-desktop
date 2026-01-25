"""
SQLAlchemy models for SBA Scout database.

This module defines the local database schema for:
- Synced data from the league API (players, teams, transactions)
- Locally managed card data (batter/pitcher Strat-o-Matic card values)
- User preferences (lineups, roster assignments)
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


# =============================================================================
# Core Entities (synced from league API)
# =============================================================================


class Team(Base):
    """
    Team entity - synced from league API.

    Teams include main roster teams, IL teams (e.g., WVIL), and minor league teams (e.g., WVMiL).
    """

    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)  # Matches league API team_id
    abbrev = Column(String(10), nullable=False)
    short_name = Column(String(50), nullable=False)
    long_name = Column(String(100), nullable=False)
    season = Column(Integer, nullable=False)

    # Manager info
    manager1_name = Column(String(100), nullable=True)
    manager2_name = Column(String(100), nullable=True)
    gm_discord_id = Column(String(20), nullable=True)
    gm2_discord_id = Column(String(20), nullable=True)

    # Division/League
    division_id = Column(Integer, nullable=True)
    division_name = Column(String(50), nullable=True)
    league_abbrev = Column(String(10), nullable=True)

    # Visual
    thumbnail = Column(String(500), nullable=True)
    color = Column(String(10), nullable=True)
    dice_color = Column(String(10), nullable=True)
    stadium = Column(String(200), nullable=True)

    # Roster limits
    salary_cap = Column(Float, nullable=True)

    # Sync metadata
    synced_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    players = relationship("Player", back_populates="team")

    __table_args__ = (UniqueConstraint("abbrev", "season", name="uq_team_season"),)


class Player(Base):
    """
    Player entity - synced from league API.

    Contains player metadata. Card stats are stored in BatterCard/PitcherCard.
    """

    __tablename__ = "players"

    id = Column(Integer, primary_key=True)  # Matches league API player_id
    name = Column(String(200), nullable=False)
    season = Column(Integer, nullable=False)

    # Team assignment
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    team = relationship("Team", back_populates="players")

    # sWAR (salary/value metric)
    swar = Column(Float, default=0.0)

    # Card images
    card_image = Column(String(500), nullable=True)
    card_image_alt = Column(String(500), nullable=True)
    headshot = Column(String(500), nullable=True)
    vanity_card = Column(String(500), nullable=True)

    # Positions (up to 8)
    pos_1 = Column(String(5), nullable=True)
    pos_2 = Column(String(5), nullable=True)
    pos_3 = Column(String(5), nullable=True)
    pos_4 = Column(String(5), nullable=True)
    pos_5 = Column(String(5), nullable=True)
    pos_6 = Column(String(5), nullable=True)
    pos_7 = Column(String(5), nullable=True)
    pos_8 = Column(String(5), nullable=True)

    # Hand (L/R/S for switch)
    hand = Column(String(1), nullable=True)

    # Injury info
    injury_rating = Column(String(20), nullable=True)
    il_return = Column(String(20), nullable=True)

    # Demotion tracking
    demotion_week = Column(Integer, nullable=True)

    # External references
    strat_code = Column(String(100), nullable=True)
    bbref_id = Column(String(50), nullable=True)
    sbaplayer_id = Column(Integer, nullable=True)

    # Last game appearances
    last_game = Column(String(20), nullable=True)
    last_game2 = Column(String(20), nullable=True)

    # Sync metadata
    synced_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    batter_card = relationship("BatterCard", back_populates="player", uselist=False)
    pitcher_card = relationship("PitcherCard", back_populates="player", uselist=False)

    @property
    def positions(self) -> list[str]:
        """Return list of all positions this player can play."""
        return [
            p
            for p in [
                self.pos_1,
                self.pos_2,
                self.pos_3,
                self.pos_4,
                self.pos_5,
                self.pos_6,
                self.pos_7,
                self.pos_8,
            ]
            if p
        ]

    @property
    def is_pitcher(self) -> bool:
        """Check if player is a pitcher."""
        pitcher_positions = {"SP", "RP", "CP"}
        return bool(pitcher_positions & set(self.positions))

    @property
    def is_batter(self) -> bool:
        """Check if player can bat (has non-pitcher positions or is DH)."""
        batter_positions = {"C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"}
        return bool(batter_positions & set(self.positions))


# =============================================================================
# Card Data (locally managed, imported from Strat-o-Matic)
# =============================================================================


class BatterCard(Base):
    """
    Strat-o-Matic batter card data.

    Contains all the probability values from the physical/digital card.
    This data is imported manually (CSV, Excel, or future API).
    """

    __tablename__ = "batter_cards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False, unique=True)
    player = relationship("Player", back_populates="batter_card")

    # vs Left-Handed Pitchers
    so_vlhp = Column(Float, default=0)  # Strikeout chance
    bb_vlhp = Column(Float, default=0)  # Walk chance
    hit_vlhp = Column(Float, default=0)  # Hit chance
    ob_vlhp = Column(Float, default=0)  # On-base chance
    tb_vlhp = Column(Float, default=0)  # Total bases
    hr_vlhp = Column(Float, default=0)  # Home run chance
    dp_vlhp = Column(Float, default=0)  # Double play chance

    # vs Right-Handed Pitchers
    so_vrhp = Column(Float, default=0)
    bb_vrhp = Column(Float, default=0)
    hit_vrhp = Column(Float, default=0)
    ob_vrhp = Column(Float, default=0)
    tb_vrhp = Column(Float, default=0)
    hr_vrhp = Column(Float, default=0)
    dp_vrhp = Column(Float, default=0)

    # Ballpark modifiers
    bphr_vlhp = Column(Float, default=0)  # Ballpark HR modifier vs LHP
    bphr_vrhp = Column(Float, default=0)  # Ballpark HR modifier vs RHP
    bp1b_vlhp = Column(Float, default=0)  # Ballpark single modifier vs LHP
    bp1b_vrhp = Column(Float, default=0)  # Ballpark single modifier vs RHP

    # Running game
    stealing = Column(String(50), nullable=True)  # e.g., "*4,5/- (19-12)"
    steal_rating = Column(String(5), nullable=True)  # e.g., "A", "B", "C"
    speed = Column(Integer, default=10)  # Speed rating 1-20

    # Batting extras
    bunt = Column(String(5), nullable=True)  # Bunt rating
    hit_run = Column(String(5), nullable=True)  # Hit and run rating

    # Fielding data - raw string from CSV (e.g., "cf-3(-1)e5 rf-2e5 lf-2e5")
    fielding = Column(String(500), nullable=True)

    # Catcher-specific
    catcher_arm = Column(Integer, nullable=True)
    catcher_pb = Column(Integer, nullable=True)  # Passed ball rating
    catcher_t = Column(Integer, nullable=True)  # T-rating for throwing

    # Computed ratings (updated when weights change)
    rating_vl = Column(Float, nullable=True)  # Composite rating vs LHP
    rating_vr = Column(Float, nullable=True)  # Composite rating vs RHP
    rating_overall = Column(Float, nullable=True)  # Combined rating

    # Import metadata
    imported_at = Column(DateTime, default=datetime.utcnow)
    source = Column(String(100), nullable=True)  # Where the data came from


class PitcherCard(Base):
    """
    Strat-o-Matic pitcher card data.

    Contains all the probability values from the physical/digital card.
    This data is imported manually (CSV, Excel, or future API).
    """

    __tablename__ = "pitcher_cards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False, unique=True)
    player = relationship("Player", back_populates="pitcher_card")

    # vs Left-Handed Batters
    so_vlhb = Column(Float, default=0)  # Strikeout chance
    bb_vlhb = Column(Float, default=0)  # Walk chance
    hit_vlhb = Column(Float, default=0)  # Hit chance
    ob_vlhb = Column(Float, default=0)  # On-base chance
    tb_vlhb = Column(Float, default=0)  # Total bases
    hr_vlhb = Column(Float, default=0)  # Home run chance
    dp_vlhb = Column(Float, default=0)  # Double play chance

    # Ballpark columns for pitcher
    bphr_vlhb = Column(Float, default=0)
    bp1b_vlhb = Column(Float, default=0)

    # vs Right-Handed Batters
    so_vrhb = Column(Float, default=0)
    bb_vrhb = Column(Float, default=0)
    hit_vrhb = Column(Float, default=0)
    ob_vrhb = Column(Float, default=0)
    tb_vrhb = Column(Float, default=0)
    hr_vrhb = Column(Float, default=0)
    dp_vrhb = Column(Float, default=0)
    bphr_vrhb = Column(Float, default=0)
    bp1b_vrhb = Column(Float, default=0)

    # Hold rating (pitcher's card reading probability)
    hold_rating = Column(Integer, default=0)  # -3 to +3 typical range

    # Endurance
    endurance_start = Column(Integer, nullable=True)  # SP endurance
    endurance_relief = Column(Integer, nullable=True)  # RP endurance
    endurance_close = Column(Integer, nullable=True)  # CP endurance

    # Fielding
    fielding_range = Column(Integer, nullable=True)
    fielding_error = Column(Integer, nullable=True)

    # Wild pitch / Balk
    wild_pitch = Column(Integer, default=0)
    balk = Column(Integer, default=0)

    # Batting (for NL/interleague)
    batting_rating = Column(String(10), nullable=True)

    # Computed ratings (updated when weights change)
    rating_vlhb = Column(Float, nullable=True)  # Rating vs LH batters
    rating_vrhb = Column(Float, nullable=True)  # Rating vs RH batters
    rating_overall = Column(Float, nullable=True)

    # Import metadata
    imported_at = Column(DateTime, default=datetime.utcnow)
    source = Column(String(100), nullable=True)


# =============================================================================
# Transactions (synced from league API)
# =============================================================================


class Transaction(Base):
    """
    Transaction record - synced from league API.

    Tracks player moves between teams.
    """

    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    season = Column(Integer, nullable=False)
    week = Column(Integer, nullable=False)
    move_id = Column(String(50), nullable=False)  # Unique identifier for the move

    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    from_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    to_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)

    # Status
    cancelled = Column(Boolean, default=False)
    frozen = Column(Boolean, default=False)

    # Sync metadata
    synced_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("move_id", "player_id", name="uq_transaction_move_player"),)


# =============================================================================
# User Data (local only)
# =============================================================================


class Lineup(Base):
    """
    Saved lineup configuration.

    Users can save multiple lineups (e.g., "vs LHP", "vs RHP", "Standard").
    """

    __tablename__ = "lineups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    # Lineup type
    lineup_type = Column(String(20), default="standard")  # standard, vs_lhp, vs_rhp

    # Batting order (JSON array of player_ids)
    # Format: [player_id_1, player_id_2, ..., player_id_9]
    batting_order = Column(JSON, nullable=True)

    # Position assignments (JSON object)
    # Format: {"C": player_id, "1B": player_id, "2B": player_id, ...}
    positions = Column(JSON, nullable=True)

    # Pitcher
    starting_pitcher_id = Column(Integer, ForeignKey("players.id"), nullable=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MatchupCache(Base):
    """
    Cached matchup calculations.

    Stores pre-computed matchup results for quick lookup during games.
    Invalidated when card data or weights change.
    """

    __tablename__ = "matchup_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batter_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    pitcher_id = Column(Integer, ForeignKey("players.id"), nullable=False)

    # Calculated values
    rating = Column(Float, nullable=False)
    tier = Column(String(1), nullable=True)  # A, B, C, D, F

    # Detailed breakdown (JSON)
    details = Column(JSON, nullable=True)

    # Cache validity
    computed_at = Column(DateTime, default=datetime.utcnow)
    weights_hash = Column(String(64), nullable=True)  # Hash of weights used

    __table_args__ = (
        UniqueConstraint("batter_id", "pitcher_id", name="uq_matchup_batter_pitcher"),
    )


class SyncStatus(Base):
    """
    Tracks sync status with the league API.

    Helps determine when data needs refreshing.
    """

    __tablename__ = "sync_status"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(50), nullable=False, unique=True)  # players, teams, etc.
    last_sync = Column(DateTime, nullable=True)
    last_sync_count = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
