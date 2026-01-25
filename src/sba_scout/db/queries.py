"""
Common database queries for SBA Scout.

Provides reusable query functions for accessing player, team, and card data.
"""

from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import (
    BatterCard,
    Lineup,
    MatchupCache,
    PitcherCard,
    Player,
    SyncStatus,
    Team,
    Transaction,
)


# =============================================================================
# Team Queries
# =============================================================================


async def get_all_teams(
    session: AsyncSession,
    season: int,
    active_only: bool = True,
) -> Sequence[Team]:
    """
    Get all teams for a season.

    Args:
        session: Database session
        season: Season number
        active_only: If True, exclude IL and MiL teams

    Returns:
        List of Team objects
    """
    query = select(Team).where(Team.season == season)

    if active_only:
        # Exclude teams ending in IL or MiL
        query = query.where(
            ~Team.abbrev.endswith("IL"),
            ~Team.abbrev.endswith("MiL"),
        )

    query = query.order_by(Team.abbrev)
    result = await session.execute(query)
    return result.scalars().all()


async def get_team_by_abbrev(
    session: AsyncSession,
    abbrev: str,
    season: int,
) -> Optional[Team]:
    """Get a team by abbreviation and season."""
    query = select(Team).where(Team.abbrev == abbrev, Team.season == season)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_team_by_id(session: AsyncSession, team_id: int) -> Optional[Team]:
    """Get a team by ID."""
    query = select(Team).where(Team.id == team_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()


# =============================================================================
# Player Queries
# =============================================================================


async def get_players_by_team(
    session: AsyncSession,
    team_id: int,
    include_cards: bool = True,
) -> Sequence[Player]:
    """
    Get all players on a team.

    Args:
        session: Database session
        team_id: Team ID
        include_cards: If True, eagerly load card data

    Returns:
        List of Player objects
    """
    query = select(Player).where(Player.team_id == team_id)

    if include_cards:
        query = query.options(
            selectinload(Player.batter_card),
            selectinload(Player.pitcher_card),
        )

    query = query.order_by(Player.name)
    result = await session.execute(query)
    return result.scalars().all()


async def get_player_by_id(
    session: AsyncSession,
    player_id: int,
    include_cards: bool = True,
) -> Optional[Player]:
    """Get a player by ID."""
    query = select(Player).where(Player.id == player_id)

    if include_cards:
        query = query.options(
            selectinload(Player.batter_card),
            selectinload(Player.pitcher_card),
        )

    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_player_by_name(
    session: AsyncSession,
    name: str,
    season: int,
    include_cards: bool = True,
) -> Optional[Player]:
    """Get a player by name and season (case-insensitive)."""
    query = select(Player).where(
        Player.name.ilike(name),
        Player.season == season,
    )

    if include_cards:
        query = query.options(
            selectinload(Player.batter_card),
            selectinload(Player.pitcher_card),
        )

    result = await session.execute(query)
    return result.scalar_one_or_none()


async def search_players(
    session: AsyncSession,
    query_str: str,
    season: int,
    limit: int = 20,
) -> Sequence[Player]:
    """
    Search players by name (partial match).

    Args:
        session: Database session
        query_str: Search string
        season: Season number
        limit: Maximum results to return

    Returns:
        List of matching Player objects
    """
    query = (
        select(Player)
        .where(
            Player.name.ilike(f"%{query_str}%"),
            Player.season == season,
        )
        .options(
            selectinload(Player.batter_card),
            selectinload(Player.pitcher_card),
        )
        .order_by(Player.name)
        .limit(limit)
    )

    result = await session.execute(query)
    return result.scalars().all()


async def get_pitchers(
    session: AsyncSession,
    team_id: Optional[int] = None,
    season: Optional[int] = None,
) -> Sequence[Player]:
    """Get all pitchers, optionally filtered by team."""
    query = select(Player).where(
        (Player.pos_1 == "SP")
        | (Player.pos_1 == "RP")
        | (Player.pos_1 == "CP")
        | (Player.pos_2 == "SP")
        | (Player.pos_2 == "RP")
        | (Player.pos_2 == "CP")
    )

    if team_id:
        query = query.where(Player.team_id == team_id)
    if season:
        query = query.where(Player.season == season)

    query = query.options(selectinload(Player.pitcher_card)).order_by(Player.name)
    result = await session.execute(query)
    return result.scalars().all()


async def get_batters(
    session: AsyncSession,
    team_id: Optional[int] = None,
    season: Optional[int] = None,
) -> Sequence[Player]:
    """Get all batters (non-pitcher position players)."""
    batter_positions = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]

    query = select(Player).where(Player.pos_1.in_(batter_positions))

    if team_id:
        query = query.where(Player.team_id == team_id)
    if season:
        query = query.where(Player.season == season)

    query = query.options(selectinload(Player.batter_card)).order_by(Player.name)
    result = await session.execute(query)
    return result.scalars().all()


# =============================================================================
# Card Data Queries
# =============================================================================


async def get_batter_card(
    session: AsyncSession,
    player_id: int,
) -> Optional[BatterCard]:
    """Get batter card data for a player."""
    query = select(BatterCard).where(BatterCard.player_id == player_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_pitcher_card(
    session: AsyncSession,
    player_id: int,
) -> Optional[PitcherCard]:
    """Get pitcher card data for a player."""
    query = select(PitcherCard).where(PitcherCard.player_id == player_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_players_missing_cards(
    session: AsyncSession,
    season: int,
    card_type: str = "batter",
) -> Sequence[Player]:
    """
    Get players who don't have card data imported yet.

    Args:
        session: Database session
        season: Season number
        card_type: "batter" or "pitcher"

    Returns:
        List of Player objects without card data
    """
    if card_type == "batter":
        # Get batters without batter cards
        subquery = select(BatterCard.player_id)
        query = (
            select(Player)
            .where(
                Player.season == season,
                Player.pos_1.in_(["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]),
                ~Player.id.in_(subquery),
            )
            .order_by(Player.name)
        )
    else:
        # Get pitchers without pitcher cards
        subquery = select(PitcherCard.player_id)
        query = (
            select(Player)
            .where(
                Player.season == season,
                Player.pos_1.in_(["SP", "RP", "CP"]),
                ~Player.id.in_(subquery),
            )
            .order_by(Player.name)
        )

    result = await session.execute(query)
    return result.scalars().all()


# =============================================================================
# Roster Queries (for your team)
# =============================================================================


async def get_my_roster(
    session: AsyncSession,
    team_abbrev: str,
    season: int,
) -> dict[str, Sequence[Player]]:
    """
    Get full roster for your team including IL and MiL.

    Returns:
        Dict with keys 'majors', 'minors', 'il' containing player lists
    """
    # Main roster
    majors_team = await get_team_by_abbrev(session, team_abbrev, season)
    majors = await get_players_by_team(session, majors_team.id) if majors_team else []

    # IL roster
    il_team = await get_team_by_abbrev(session, f"{team_abbrev}IL", season)
    il = await get_players_by_team(session, il_team.id) if il_team else []

    # Minor league roster
    mil_team = await get_team_by_abbrev(session, f"{team_abbrev}MiL", season)
    minors = await get_players_by_team(session, mil_team.id) if mil_team else []

    return {
        "majors": majors,
        "minors": minors,
        "il": il,
    }


# =============================================================================
# Sync Status Queries
# =============================================================================


async def get_sync_status(
    session: AsyncSession,
    entity_type: str,
) -> Optional[SyncStatus]:
    """Get sync status for an entity type."""
    query = select(SyncStatus).where(SyncStatus.entity_type == entity_type)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def update_sync_status(
    session: AsyncSession,
    entity_type: str,
    count: int,
    error: Optional[str] = None,
) -> None:
    """Update sync status after a sync operation."""
    status = await get_sync_status(session, entity_type)

    if status:
        status.last_sync = datetime.utcnow()
        status.last_sync_count = count
        status.last_error = error
    else:
        status = SyncStatus(
            entity_type=entity_type,
            last_sync=datetime.utcnow(),
            last_sync_count=count,
            last_error=error,
        )
        session.add(status)


# =============================================================================
# Matchup Cache Queries
# =============================================================================


async def get_cached_matchup(
    session: AsyncSession,
    batter_id: int,
    pitcher_id: int,
    weights_hash: str,
) -> Optional[MatchupCache]:
    """Get cached matchup if it exists and weights haven't changed."""
    query = select(MatchupCache).where(
        MatchupCache.batter_id == batter_id,
        MatchupCache.pitcher_id == pitcher_id,
        MatchupCache.weights_hash == weights_hash,
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def invalidate_matchup_cache(session: AsyncSession) -> int:
    """
    Invalidate all matchup cache entries.

    Called when weights change.

    Returns:
        Number of entries deleted
    """
    result = await session.execute(
        MatchupCache.__table__.delete()  # type: ignore
    )
    return result.rowcount or 0


# =============================================================================
# Lineup Queries
# =============================================================================


async def get_lineups(session: AsyncSession) -> Sequence[Lineup]:
    """Get all saved lineups."""
    query = select(Lineup).order_by(Lineup.name)
    result = await session.execute(query)
    return result.scalars().all()


async def get_lineup_by_name(
    session: AsyncSession,
    name: str,
) -> Optional[Lineup]:
    """Get a lineup by name."""
    query = select(Lineup).where(Lineup.name == name)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def save_lineup(
    session: AsyncSession,
    name: str,
    batting_order: list[int],
    positions: dict[str, int],
    lineup_type: str = "standard",
    description: Optional[str] = None,
    starting_pitcher_id: Optional[int] = None,
) -> Lineup:
    """Save or update a lineup."""
    existing = await get_lineup_by_name(session, name)

    if existing:
        existing.batting_order = batting_order
        existing.positions = positions
        existing.lineup_type = lineup_type
        existing.description = description
        existing.starting_pitcher_id = starting_pitcher_id
        existing.updated_at = datetime.utcnow()
        return existing
    else:
        lineup = Lineup(
            name=name,
            batting_order=batting_order,
            positions=positions,
            lineup_type=lineup_type,
            description=description,
            starting_pitcher_id=starting_pitcher_id,
        )
        session.add(lineup)
        return lineup
