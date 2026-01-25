"""
Data synchronization between league API and local database.

Handles importing and updating players, teams, and transactions.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db.models import Player, SyncStatus, Team, Transaction
from ..db.queries import get_sync_status, update_sync_status
from .client import LeagueAPIClient

logger = logging.getLogger(__name__)


async def sync_teams(
    session: AsyncSession,
    season: int,
    client: Optional[LeagueAPIClient] = None,
) -> int:
    """
    Sync teams from the league API.

    Args:
        session: Database session
        season: Season to sync
        client: Optional pre-initialized client

    Returns:
        Number of teams synced
    """
    close_client = client is None
    if client is None:
        client = LeagueAPIClient()

    try:
        if close_client:
            await client.__aenter__()

        logger.info(f"Syncing teams for season {season}")
        data = await client.get_teams(season=season, short_output=False)

        count = 0
        for team_data in data.get("teams", []):
            team = await session.get(Team, team_data["id"])

            if team:
                # Update existing team
                team.abbrev = team_data["abbrev"]
                team.short_name = team_data["sname"]
                team.long_name = team_data["lname"]
                team.thumbnail = team_data.get("thumbnail")
                team.color = team_data.get("color")
                team.dice_color = team_data.get("dice_color")
                team.stadium = team_data.get("stadium")
                team.salary_cap = team_data.get("salary_cap")
                team.synced_at = datetime.utcnow()

                # Manager info
                if team_data.get("manager1"):
                    team.manager1_name = team_data["manager1"].get("name")
                if team_data.get("manager2"):
                    team.manager2_name = team_data["manager2"].get("name")

                # Division info
                if team_data.get("division"):
                    team.division_id = team_data["division"].get("id")
                    team.division_name = team_data["division"].get("division_name")
                    team.league_abbrev = team_data["division"].get("league_abbrev")

                team.gm_discord_id = str(team_data.get("gmid")) if team_data.get("gmid") else None
                team.gm2_discord_id = (
                    str(team_data.get("gmid2")) if team_data.get("gmid2") else None
                )
            else:
                # Create new team
                team = Team(
                    id=team_data["id"],
                    abbrev=team_data["abbrev"],
                    short_name=team_data["sname"],
                    long_name=team_data["lname"],
                    season=season,
                    thumbnail=team_data.get("thumbnail"),
                    color=team_data.get("color"),
                    dice_color=team_data.get("dice_color"),
                    stadium=team_data.get("stadium"),
                    salary_cap=team_data.get("salary_cap"),
                    gm_discord_id=str(team_data.get("gmid")) if team_data.get("gmid") else None,
                    gm2_discord_id=str(team_data.get("gmid2")) if team_data.get("gmid2") else None,
                )

                if team_data.get("manager1"):
                    team.manager1_name = team_data["manager1"].get("name")
                if team_data.get("manager2"):
                    team.manager2_name = team_data["manager2"].get("name")
                if team_data.get("division"):
                    team.division_id = team_data["division"].get("id")
                    team.division_name = team_data["division"].get("division_name")
                    team.league_abbrev = team_data["division"].get("league_abbrev")

                session.add(team)

            count += 1

        await update_sync_status(session, "teams", count)
        logger.info(f"Synced {count} teams")
        return count

    finally:
        if close_client:
            await client.__aexit__(None, None, None)


async def sync_players(
    session: AsyncSession,
    season: int,
    team_id: Optional[list[int]] = None,
    client: Optional[LeagueAPIClient] = None,
) -> int:
    """
    Sync players from the league API.

    Args:
        session: Database session
        season: Season to sync
        team_id: Optional list of team IDs to filter
        client: Optional pre-initialized client

    Returns:
        Number of players synced
    """
    close_client = client is None
    if client is None:
        client = LeagueAPIClient()

    try:
        if close_client:
            await client.__aenter__()

        logger.info(f"Syncing players for season {season}")
        data = await client.get_players(season=season, team_id=team_id, short_output=False)

        count = 0
        for player_data in data.get("players", []):
            player = await session.get(Player, player_data["id"])

            # Extract team info
            team_info = player_data.get("team", {})
            player_team_id = team_info.get("id") if isinstance(team_info, dict) else None

            if player:
                # Update existing player
                player.name = player_data["name"]
                player.swar = player_data.get("wara", 0)
                player.card_image = player_data.get("image")
                player.card_image_alt = player_data.get("image2")
                player.headshot = player_data.get("headshot")
                player.vanity_card = player_data.get("vanity_card")
                player.team_id = player_team_id
                player.pos_1 = player_data.get("pos_1")
                player.pos_2 = player_data.get("pos_2")
                player.pos_3 = player_data.get("pos_3")
                player.pos_4 = player_data.get("pos_4")
                player.pos_5 = player_data.get("pos_5")
                player.pos_6 = player_data.get("pos_6")
                player.pos_7 = player_data.get("pos_7")
                player.pos_8 = player_data.get("pos_8")
                player.injury_rating = player_data.get("injury_rating")
                player.il_return = player_data.get("il_return")
                player.demotion_week = player_data.get("demotion_week")
                player.strat_code = player_data.get("strat_code")
                player.bbref_id = player_data.get("bbref_id")
                player.sbaplayer_id = player_data.get("sbaplayer")
                player.last_game = player_data.get("last_game")
                player.last_game2 = player_data.get("last_game2")
                player.synced_at = datetime.utcnow()

                # Extract hand from strat_code if available
                # Format is typically like "1p60" where the digit after 'p' might indicate something
                # Actually hand is not in the API response - we'll need to get it from card data
            else:
                # Create new player
                player = Player(
                    id=player_data["id"],
                    name=player_data["name"],
                    season=season,
                    swar=player_data.get("wara", 0),
                    card_image=player_data.get("image"),
                    card_image_alt=player_data.get("image2"),
                    headshot=player_data.get("headshot"),
                    vanity_card=player_data.get("vanity_card"),
                    team_id=player_team_id,
                    pos_1=player_data.get("pos_1"),
                    pos_2=player_data.get("pos_2"),
                    pos_3=player_data.get("pos_3"),
                    pos_4=player_data.get("pos_4"),
                    pos_5=player_data.get("pos_5"),
                    pos_6=player_data.get("pos_6"),
                    pos_7=player_data.get("pos_7"),
                    pos_8=player_data.get("pos_8"),
                    injury_rating=player_data.get("injury_rating"),
                    il_return=player_data.get("il_return"),
                    demotion_week=player_data.get("demotion_week"),
                    strat_code=player_data.get("strat_code"),
                    bbref_id=player_data.get("bbref_id"),
                    sbaplayer_id=player_data.get("sbaplayer"),
                    last_game=player_data.get("last_game"),
                    last_game2=player_data.get("last_game2"),
                )
                session.add(player)

            count += 1

        await update_sync_status(session, "players", count)
        logger.info(f"Synced {count} players")
        return count

    finally:
        if close_client:
            await client.__aexit__(None, None, None)


async def sync_transactions(
    session: AsyncSession,
    season: int,
    week_start: int = 0,
    week_end: Optional[int] = None,
    team_abbrev: Optional[list[str]] = None,
    client: Optional[LeagueAPIClient] = None,
) -> int:
    """
    Sync transactions from the league API.

    Args:
        session: Database session
        season: Season to sync
        week_start: Starting week
        week_end: Ending week
        team_abbrev: Optional team abbreviations to filter
        client: Optional pre-initialized client

    Returns:
        Number of transactions synced
    """
    close_client = client is None
    if client is None:
        client = LeagueAPIClient()

    try:
        if close_client:
            await client.__aenter__()

        logger.info(f"Syncing transactions for season {season}")
        data = await client.get_transactions(
            season=season,
            week_start=week_start,
            week_end=week_end,
            team_abbrev=team_abbrev,
            cancelled=False,
            frozen=False,
            short_output=False,
        )

        count = 0
        for trans_data in data.get("transactions", []):
            move_id = trans_data.get("moveid")
            player_info = trans_data.get("player", {})
            player_id = player_info.get("id") if isinstance(player_info, dict) else None

            if not move_id or not player_id:
                continue

            # Check if transaction exists
            from sqlalchemy import select

            existing = await session.execute(
                select(Transaction).where(
                    Transaction.move_id == move_id,
                    Transaction.player_id == player_id,
                )
            )
            transaction = existing.scalar_one_or_none()

            old_team = trans_data.get("oldteam", {})
            new_team = trans_data.get("newteam", {})

            if transaction:
                # Update existing
                transaction.cancelled = trans_data.get("cancelled", False)
                transaction.frozen = trans_data.get("frozen", False)
                transaction.synced_at = datetime.utcnow()
            else:
                # Create new
                transaction = Transaction(
                    season=season,
                    week=trans_data.get("week", 0),
                    move_id=move_id,
                    player_id=player_id,
                    from_team_id=old_team.get("id") if isinstance(old_team, dict) else None,
                    to_team_id=new_team.get("id") if isinstance(new_team, dict) else None,
                    cancelled=trans_data.get("cancelled", False),
                    frozen=trans_data.get("frozen", False),
                )
                session.add(transaction)

            count += 1

        await update_sync_status(session, "transactions", count)
        logger.info(f"Synced {count} transactions")
        return count

    finally:
        if close_client:
            await client.__aexit__(None, None, None)


async def sync_all(
    session: AsyncSession,
    season: int,
) -> dict[str, int]:
    """
    Sync all data for a season.

    Args:
        session: Database session
        season: Season to sync

    Returns:
        Dict with counts for each entity type
    """
    async with LeagueAPIClient() as client:
        teams = await sync_teams(session, season, client)
        players = await sync_players(session, season, client=client)
        transactions = await sync_transactions(session, season, client=client)

    return {
        "teams": teams,
        "players": players,
        "transactions": transactions,
    }
