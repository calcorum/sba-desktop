"""
Matchup calculation logic for SBA Scout.

Calculates batter performance ratings against specific pitchers using
standardized scoring based on league averages and standard deviations.

The calculation:
1. Convert each raw stat to a standardized score (-3 to +3) based on
   how it compares to the league average using standard deviations
2. Multiply by the stat's weight
3. Sum all weighted scores for batter component
4. Do the same for pitcher component
5. INVERT pitcher score (so pitcher allowing hits = good for batter)
6. Total = Batter Component + Inverted Pitcher Component

Supports two modes:
- Real-time calculation (calculate_matchup): Uses league stats passed in
- Cached calculation (calculate_matchup_cached): Uses pre-computed scores from DB
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import BatterCard, PitcherCard, Player, StandardizedScoreCache
from .league_stats import (
    BatterLeagueStats,
    PitcherLeagueStats,
)
from .weights import (
    BATTER_WEIGHTS,
    PITCHER_WEIGHTS,
    calculate_weighted_score,
    get_max_matchup_score,
)


@dataclass
class MatchupResult:
    """Result of a batter vs pitcher matchup calculation."""

    player: Player
    rating: float | None  # None if no card data
    tier: str  # A, B, C, D, F, or "--" if no data
    batter_hand: str  # L, R, or S (actual batting hand used)
    batter_split: str  # "vLHP" or "vRHP" - batter's split used
    pitcher_split: str  # "vLHB" or "vRHB" - pitcher's split used
    batter_component: float | None  # Batter's contribution to rating
    pitcher_component: float | None  # Pitcher's contribution (before inversion)

    @property
    def rating_display(self) -> str:
        """Format rating for display (e.g., '+15', '-3', 'N/A')."""
        if self.rating is None:
            return "N/A"
        sign = "+" if self.rating > 0 else ""
        return f"{sign}{self.rating:.0f}"

    @property
    def split_display(self) -> str:
        """Format splits for display (e.g., 'vR/vL')."""
        b = "vL" if self.batter_split == "vLHP" else "vR"
        p = "vL" if self.pitcher_split == "vLHB" else "vR"
        return f"{b}/{p}"


def get_tier(rating: float | None) -> str:
    """
    Assign a letter tier based on matchup rating.

    With standardized scoring (-3 to +3 per stat, weighted):
    - Max batter score: ~66 (all stats at +3)
    - Max pitcher score: ~69 (all stats at +3, then inverted)
    - Max combined: ~135

    Tier thresholds (roughly based on standard deviation bands):
        A: >= 40   (Excellent matchup - significantly above average)
        B: 20-39   (Good matchup - above average)
        C: -19 to 19 (Average matchup)
        D: -39 to -20 (Below average matchup)
        F: < -40   (Poor matchup - significantly below average)
    """
    if rating is None:
        return "--"
    if rating >= 40:
        return "A"
    if rating >= 20:
        return "B"
    if rating >= -19:
        return "C"
    if rating >= -39:
        return "D"
    return "F"


def _calculate_batter_component(
    card: BatterCard,
    vs_hand: Literal["L", "R"],
    league_stats: BatterLeagueStats,
) -> float:
    """
    Calculate batter's standardized weighted score vs a pitcher's hand.

    Args:
        card: Batter's card data
        vs_hand: Pitcher's throwing hand ("L" or "R")
        league_stats: League averages and standard deviations

    Returns:
        Batter's total weighted score
    """
    total = 0.0

    if vs_hand == "L":
        # vs Left-Handed Pitchers
        total += calculate_weighted_score(card.so_vlhp, league_stats.so_vlhp, BATTER_WEIGHTS["so"])
        total += calculate_weighted_score(card.bb_vlhp, league_stats.bb_vlhp, BATTER_WEIGHTS["bb"])
        total += calculate_weighted_score(
            card.hit_vlhp, league_stats.hit_vlhp, BATTER_WEIGHTS["hit"]
        )
        total += calculate_weighted_score(card.ob_vlhp, league_stats.ob_vlhp, BATTER_WEIGHTS["ob"])
        total += calculate_weighted_score(card.tb_vlhp, league_stats.tb_vlhp, BATTER_WEIGHTS["tb"])
        total += calculate_weighted_score(card.hr_vlhp, league_stats.hr_vlhp, BATTER_WEIGHTS["hr"])
        total += calculate_weighted_score(
            card.bphr_vlhp, league_stats.bphr_vlhp, BATTER_WEIGHTS["bphr"]
        )
        total += calculate_weighted_score(
            card.bp1b_vlhp, league_stats.bp1b_vlhp, BATTER_WEIGHTS["bp1b"]
        )
        total += calculate_weighted_score(card.dp_vlhp, league_stats.dp_vlhp, BATTER_WEIGHTS["dp"])
    else:
        # vs Right-Handed Pitchers
        total += calculate_weighted_score(card.so_vrhp, league_stats.so_vrhp, BATTER_WEIGHTS["so"])
        total += calculate_weighted_score(card.bb_vrhp, league_stats.bb_vrhp, BATTER_WEIGHTS["bb"])
        total += calculate_weighted_score(
            card.hit_vrhp, league_stats.hit_vrhp, BATTER_WEIGHTS["hit"]
        )
        total += calculate_weighted_score(card.ob_vrhp, league_stats.ob_vrhp, BATTER_WEIGHTS["ob"])
        total += calculate_weighted_score(card.tb_vrhp, league_stats.tb_vrhp, BATTER_WEIGHTS["tb"])
        total += calculate_weighted_score(card.hr_vrhp, league_stats.hr_vrhp, BATTER_WEIGHTS["hr"])
        total += calculate_weighted_score(
            card.bphr_vrhp, league_stats.bphr_vrhp, BATTER_WEIGHTS["bphr"]
        )
        total += calculate_weighted_score(
            card.bp1b_vrhp, league_stats.bp1b_vrhp, BATTER_WEIGHTS["bp1b"]
        )
        total += calculate_weighted_score(card.dp_vrhp, league_stats.dp_vrhp, BATTER_WEIGHTS["dp"])

    return total


def _calculate_pitcher_component(
    card: PitcherCard,
    vs_hand: Literal["L", "R"],
    league_stats: PitcherLeagueStats,
) -> float:
    """
    Calculate pitcher's standardized weighted score vs a batter's hand.

    Note: This returns the pitcher's score from the PITCHER's perspective
    (high = good for pitcher). The caller should INVERT this for matchup calc.

    Args:
        card: Pitcher's card data
        vs_hand: Batter's batting hand ("L" or "R")
        league_stats: League averages and standard deviations

    Returns:
        Pitcher's total weighted score (from pitcher's perspective)
    """
    total = 0.0

    if vs_hand == "L":
        # vs Left-Handed Batters
        total += calculate_weighted_score(card.so_vlhb, league_stats.so_vlhb, PITCHER_WEIGHTS["so"])
        total += calculate_weighted_score(card.bb_vlhb, league_stats.bb_vlhb, PITCHER_WEIGHTS["bb"])
        total += calculate_weighted_score(
            card.hit_vlhb, league_stats.hit_vlhb, PITCHER_WEIGHTS["hit"]
        )
        total += calculate_weighted_score(card.ob_vlhb, league_stats.ob_vlhb, PITCHER_WEIGHTS["ob"])
        total += calculate_weighted_score(card.tb_vlhb, league_stats.tb_vlhb, PITCHER_WEIGHTS["tb"])
        total += calculate_weighted_score(card.hr_vlhb, league_stats.hr_vlhb, PITCHER_WEIGHTS["hr"])
        total += calculate_weighted_score(
            card.bphr_vlhb, league_stats.bphr_vlhb, PITCHER_WEIGHTS["bphr"]
        )
        total += calculate_weighted_score(
            card.bp1b_vlhb, league_stats.bp1b_vlhb, PITCHER_WEIGHTS["bp1b"]
        )
        total += calculate_weighted_score(card.dp_vlhb, league_stats.dp_vlhb, PITCHER_WEIGHTS["dp"])
    else:
        # vs Right-Handed Batters
        total += calculate_weighted_score(card.so_vrhb, league_stats.so_vrhb, PITCHER_WEIGHTS["so"])
        total += calculate_weighted_score(card.bb_vrhb, league_stats.bb_vrhb, PITCHER_WEIGHTS["bb"])
        total += calculate_weighted_score(
            card.hit_vrhb, league_stats.hit_vrhb, PITCHER_WEIGHTS["hit"]
        )
        total += calculate_weighted_score(card.ob_vrhb, league_stats.ob_vrhb, PITCHER_WEIGHTS["ob"])
        total += calculate_weighted_score(card.tb_vrhb, league_stats.tb_vrhb, PITCHER_WEIGHTS["tb"])
        total += calculate_weighted_score(card.hr_vrhb, league_stats.hr_vrhb, PITCHER_WEIGHTS["hr"])
        total += calculate_weighted_score(
            card.bphr_vrhb, league_stats.bphr_vrhb, PITCHER_WEIGHTS["bphr"]
        )
        total += calculate_weighted_score(
            card.bp1b_vrhb, league_stats.bp1b_vrhb, PITCHER_WEIGHTS["bp1b"]
        )
        total += calculate_weighted_score(card.dp_vrhb, league_stats.dp_vrhb, PITCHER_WEIGHTS["dp"])

    return total


def calculate_matchup(
    player: Player,
    batter_card: BatterCard | None,
    pitcher: Player,
    pitcher_card: PitcherCard | None,
    batter_league_stats: BatterLeagueStats,
    pitcher_league_stats: PitcherLeagueStats,
) -> MatchupResult:
    """
    Calculate batter's expected performance against a specific pitcher.

    Uses standardized scoring:
    1. Each stat converted to -3 to +3 based on league avg/stdev
    2. Multiplied by weight
    3. Summed for batter and pitcher components
    4. Pitcher component INVERTED (bad pitcher = good for batter)
    5. Total = Batter + (-Pitcher)

    Args:
        player: The batter Player object
        batter_card: The batter's card data (may be None)
        pitcher: The pitcher Player object
        pitcher_card: The pitcher's card data (may be None)
        batter_league_stats: League stats for batters
        pitcher_league_stats: League stats for pitchers

    Returns:
        MatchupResult with combined rating, tier, and component breakdown
    """
    batter_hand = player.hand or "R"
    pitcher_hand = pitcher.hand or "R"

    # Determine batter's effective batting hand (for switch hitters)
    if batter_hand == "S":
        effective_batting_hand: Literal["L", "R"] = "L" if pitcher_hand == "R" else "R"
    else:
        effective_batting_hand = "L" if batter_hand == "L" else "R"

    # Determine which splits to use
    batter_split = "vLHP" if pitcher_hand == "L" else "vRHP"
    pitcher_split = "vLHB" if effective_batting_hand == "L" else "vRHB"

    # No batter card - return N/A result
    if batter_card is None:
        return MatchupResult(
            player=player,
            rating=None,
            tier="--",
            batter_hand=effective_batting_hand,
            batter_split=batter_split,
            pitcher_split=pitcher_split,
            batter_component=None,
            pitcher_component=None,
        )

    # Calculate batter's component
    batter_component = _calculate_batter_component(batter_card, pitcher_hand, batter_league_stats)

    # Calculate pitcher's component (if available)
    if pitcher_card is not None:
        pitcher_component = _calculate_pitcher_component(
            pitcher_card, effective_batting_hand, pitcher_league_stats
        )
        # INVERT pitcher component: good pitcher (high score) = bad for batter
        total_rating = batter_component + (-pitcher_component)
    else:
        pitcher_component = None
        total_rating = batter_component

    return MatchupResult(
        player=player,
        rating=total_rating,
        tier=get_tier(total_rating),
        batter_hand=effective_batting_hand,
        batter_split=batter_split,
        pitcher_split=pitcher_split,
        batter_component=batter_component,
        pitcher_component=pitcher_component,
    )


def calculate_team_matchups(
    batters: list[Player],
    pitcher: Player,
    pitcher_card: PitcherCard | None,
    batter_league_stats: BatterLeagueStats,
    pitcher_league_stats: PitcherLeagueStats,
) -> list[MatchupResult]:
    """
    Calculate matchups for all batters against a specific pitcher.

    Args:
        batters: List of batter Player objects (with batter_card relationship loaded)
        pitcher: The opposing pitcher Player object
        pitcher_card: The pitcher's card data (may be None)
        batter_league_stats: League stats for batters
        pitcher_league_stats: League stats for pitchers

    Returns:
        List of MatchupResults sorted by rating (highest first), with None ratings last
    """
    results = []
    for player in batters:
        result = calculate_matchup(
            player,
            player.batter_card,
            pitcher,
            pitcher_card,
            batter_league_stats,
            pitcher_league_stats,
        )
        results.append(result)

    # Sort: highest rating first, None ratings at the end
    def sort_key(r: MatchupResult) -> tuple[int, float]:
        if r.rating is None:
            return (1, 0)
        return (0, -r.rating)

    results.sort(key=sort_key)
    return results


# =============================================================================
# Cached Calculation Functions (use pre-computed scores from database)
# =============================================================================


async def calculate_matchup_cached(
    session: AsyncSession,
    player: Player,
    batter_card: BatterCard | None,
    pitcher: Player,
    pitcher_card: PitcherCard | None,
) -> MatchupResult:
    """
    Calculate matchup using pre-computed cached scores from the database.

    This is much faster than real-time calculation as it only requires
    two simple database lookups instead of computing standardized scores.

    Args:
        session: Database session for cache lookups
        player: The batter Player object
        batter_card: The batter's card data (may be None)
        pitcher: The pitcher Player object
        pitcher_card: The pitcher's card data (may be None)

    Returns:
        MatchupResult with combined rating, tier, and component breakdown
    """
    from .score_cache import get_cached_batter_score, get_cached_pitcher_score

    batter_hand = player.hand or "R"
    pitcher_hand = pitcher.hand or "R"

    # Determine batter's effective batting hand (for switch hitters)
    if batter_hand == "S":
        effective_batting_hand: Literal["L", "R"] = "L" if pitcher_hand == "R" else "R"
    else:
        effective_batting_hand = "L" if batter_hand == "L" else "R"

    # Determine which splits to use
    batter_split_name = "vLHP" if pitcher_hand == "L" else "vRHP"
    pitcher_split_name = "vLHB" if effective_batting_hand == "L" else "vRHB"

    # Convert to cache key format (lowercase)
    batter_split_key = "vlhp" if pitcher_hand == "L" else "vrhp"
    pitcher_split_key = "vlhb" if effective_batting_hand == "L" else "vrhb"

    # No batter card - return N/A result
    if batter_card is None:
        return MatchupResult(
            player=player,
            rating=None,
            tier="--",
            batter_hand=effective_batting_hand,
            batter_split=batter_split_name,
            pitcher_split=pitcher_split_name,
            batter_component=None,
            pitcher_component=None,
        )

    # Get cached batter score
    batter_cache = await get_cached_batter_score(session, batter_card.id, batter_split_key)
    if batter_cache is None:
        # Cache miss - should not happen if cache is properly maintained
        # Fall back to returning None
        return MatchupResult(
            player=player,
            rating=None,
            tier="--",
            batter_hand=effective_batting_hand,
            batter_split=batter_split_name,
            pitcher_split=pitcher_split_name,
            batter_component=None,
            pitcher_component=None,
        )

    batter_component = batter_cache.total_score

    # Get cached pitcher score (if available)
    if pitcher_card is not None:
        pitcher_cache = await get_cached_pitcher_score(session, pitcher_card.id, pitcher_split_key)
        if pitcher_cache is not None:
            pitcher_component = pitcher_cache.total_score
            # INVERT pitcher component
            total_rating = batter_component + (-pitcher_component)
        else:
            pitcher_component = None
            total_rating = batter_component
    else:
        pitcher_component = None
        total_rating = batter_component

    return MatchupResult(
        player=player,
        rating=total_rating,
        tier=get_tier(total_rating),
        batter_hand=effective_batting_hand,
        batter_split=batter_split_name,
        pitcher_split=pitcher_split_name,
        batter_component=batter_component,
        pitcher_component=pitcher_component,
    )


async def calculate_team_matchups_cached(
    session: AsyncSession,
    batters: list[Player],
    pitcher: Player,
    pitcher_card: PitcherCard | None,
) -> list[MatchupResult]:
    """
    Calculate matchups for all batters using cached scores.

    Args:
        session: Database session for cache lookups
        batters: List of batter Player objects (with batter_card relationship loaded)
        pitcher: The opposing pitcher Player object
        pitcher_card: The pitcher's card data (may be None)

    Returns:
        List of MatchupResults sorted by rating (highest first), with None ratings last
    """
    results = []
    for player in batters:
        result = await calculate_matchup_cached(
            session,
            player,
            player.batter_card,
            pitcher,
            pitcher_card,
        )
        results.append(result)

    # Sort: highest rating first, None ratings at the end
    def sort_key(r: MatchupResult) -> tuple[int, float]:
        if r.rating is None:
            return (1, 0)
        return (0, -r.rating)

    results.sort(key=sort_key)
    return results
