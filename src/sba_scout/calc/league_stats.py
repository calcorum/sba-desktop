"""
League statistics calculation for standardized scoring.

Calculates league-wide averages and standard deviations for batter and pitcher
card stats, which are used to convert raw values into standardized scores (-3 to +3).
"""

import statistics
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import BatterCard, PitcherCard


@dataclass
class StatDistribution:
    """Average and standard deviation for a single stat."""

    avg: float
    stdev: float

    def __repr__(self) -> str:
        return f"StatDistribution(avg={self.avg:.2f}, stdev={self.stdev:.2f})"


@dataclass
class BatterLeagueStats:
    """League-wide averages and standard deviations for batter card stats."""

    # vs Left-Handed Pitchers
    so_vlhp: StatDistribution
    bb_vlhp: StatDistribution
    hit_vlhp: StatDistribution
    ob_vlhp: StatDistribution
    tb_vlhp: StatDistribution
    hr_vlhp: StatDistribution
    dp_vlhp: StatDistribution
    bphr_vlhp: StatDistribution
    bp1b_vlhp: StatDistribution

    # vs Right-Handed Pitchers
    so_vrhp: StatDistribution
    bb_vrhp: StatDistribution
    hit_vrhp: StatDistribution
    ob_vrhp: StatDistribution
    tb_vrhp: StatDistribution
    hr_vrhp: StatDistribution
    dp_vrhp: StatDistribution
    bphr_vrhp: StatDistribution
    bp1b_vrhp: StatDistribution


@dataclass
class PitcherLeagueStats:
    """League-wide averages and standard deviations for pitcher card stats."""

    # vs Left-Handed Batters
    so_vlhb: StatDistribution
    bb_vlhb: StatDistribution
    hit_vlhb: StatDistribution
    ob_vlhb: StatDistribution
    tb_vlhb: StatDistribution
    hr_vlhb: StatDistribution
    dp_vlhb: StatDistribution
    bphr_vlhb: StatDistribution
    bp1b_vlhb: StatDistribution

    # vs Right-Handed Batters
    so_vrhb: StatDistribution
    bb_vrhb: StatDistribution
    hit_vrhb: StatDistribution
    ob_vrhb: StatDistribution
    tb_vrhb: StatDistribution
    hr_vrhb: StatDistribution
    dp_vrhb: StatDistribution
    bphr_vrhb: StatDistribution
    bp1b_vrhb: StatDistribution


def _calc_distribution(values: list[float]) -> StatDistribution:
    """Calculate average and standard deviation for a list of values."""
    # Filter out None and zero values for average calculation (matching spreadsheet AVERAGEIF)
    non_zero = [v for v in values if v and v > 0]

    if len(non_zero) < 2:
        # Not enough data - return defaults that will make all scores 0
        return StatDistribution(avg=0.0, stdev=1.0)

    avg = statistics.mean(non_zero)
    # Use all values (including zeros) for stdev calculation
    all_values = [v or 0 for v in values]
    stdev = statistics.stdev(all_values) if len(all_values) >= 2 else 1.0

    # Prevent division by zero
    if stdev == 0:
        stdev = 1.0

    return StatDistribution(avg=avg, stdev=stdev)


async def calculate_batter_league_stats(
    session: AsyncSession,
) -> BatterLeagueStats:
    """
    Calculate league-wide averages and standard deviations for all batter stats.

    Queries all batter cards in the database and computes statistics for each
    stat column, separated by vs-LHP and vs-RHP splits.

    Args:
        session: Database session

    Returns:
        BatterLeagueStats with avg/stdev for each stat
    """
    query = select(BatterCard)
    result = await session.execute(query)
    cards: Sequence[BatterCard] = result.scalars().all()

    if not cards:
        # Return default stats if no cards exist
        default = StatDistribution(avg=0.0, stdev=1.0)
        return BatterLeagueStats(
            so_vlhp=default,
            bb_vlhp=default,
            hit_vlhp=default,
            ob_vlhp=default,
            tb_vlhp=default,
            hr_vlhp=default,
            dp_vlhp=default,
            bphr_vlhp=default,
            bp1b_vlhp=default,
            so_vrhp=default,
            bb_vrhp=default,
            hit_vrhp=default,
            ob_vrhp=default,
            tb_vrhp=default,
            hr_vrhp=default,
            dp_vrhp=default,
            bphr_vrhp=default,
            bp1b_vrhp=default,
        )

    return BatterLeagueStats(
        # vs LHP
        so_vlhp=_calc_distribution([c.so_vlhp for c in cards]),
        bb_vlhp=_calc_distribution([c.bb_vlhp for c in cards]),
        hit_vlhp=_calc_distribution([c.hit_vlhp for c in cards]),
        ob_vlhp=_calc_distribution([c.ob_vlhp for c in cards]),
        tb_vlhp=_calc_distribution([c.tb_vlhp for c in cards]),
        hr_vlhp=_calc_distribution([c.hr_vlhp for c in cards]),
        dp_vlhp=_calc_distribution([c.dp_vlhp for c in cards]),
        bphr_vlhp=_calc_distribution([c.bphr_vlhp for c in cards]),
        bp1b_vlhp=_calc_distribution([c.bp1b_vlhp for c in cards]),
        # vs RHP
        so_vrhp=_calc_distribution([c.so_vrhp for c in cards]),
        bb_vrhp=_calc_distribution([c.bb_vrhp for c in cards]),
        hit_vrhp=_calc_distribution([c.hit_vrhp for c in cards]),
        ob_vrhp=_calc_distribution([c.ob_vrhp for c in cards]),
        tb_vrhp=_calc_distribution([c.tb_vrhp for c in cards]),
        hr_vrhp=_calc_distribution([c.hr_vrhp for c in cards]),
        dp_vrhp=_calc_distribution([c.dp_vrhp for c in cards]),
        bphr_vrhp=_calc_distribution([c.bphr_vrhp for c in cards]),
        bp1b_vrhp=_calc_distribution([c.bp1b_vrhp for c in cards]),
    )


async def calculate_pitcher_league_stats(
    session: AsyncSession,
) -> PitcherLeagueStats:
    """
    Calculate league-wide averages and standard deviations for all pitcher stats.

    Queries all pitcher cards in the database and computes statistics for each
    stat column, separated by vs-LHB and vs-RHB splits.

    Args:
        session: Database session

    Returns:
        PitcherLeagueStats with avg/stdev for each stat
    """
    query = select(PitcherCard)
    result = await session.execute(query)
    cards: Sequence[PitcherCard] = result.scalars().all()

    if not cards:
        # Return default stats if no cards exist
        default = StatDistribution(avg=0.0, stdev=1.0)
        return PitcherLeagueStats(
            so_vlhb=default,
            bb_vlhb=default,
            hit_vlhb=default,
            ob_vlhb=default,
            tb_vlhb=default,
            hr_vlhb=default,
            dp_vlhb=default,
            bphr_vlhb=default,
            bp1b_vlhb=default,
            so_vrhb=default,
            bb_vrhb=default,
            hit_vrhb=default,
            ob_vrhb=default,
            tb_vrhb=default,
            hr_vrhb=default,
            dp_vrhb=default,
            bphr_vrhb=default,
            bp1b_vrhb=default,
        )

    return PitcherLeagueStats(
        # vs LHB
        so_vlhb=_calc_distribution([c.so_vlhb for c in cards]),
        bb_vlhb=_calc_distribution([c.bb_vlhb for c in cards]),
        hit_vlhb=_calc_distribution([c.hit_vlhb for c in cards]),
        ob_vlhb=_calc_distribution([c.ob_vlhb for c in cards]),
        tb_vlhb=_calc_distribution([c.tb_vlhb for c in cards]),
        hr_vlhb=_calc_distribution([c.hr_vlhb for c in cards]),
        dp_vlhb=_calc_distribution([c.dp_vlhb for c in cards]),
        bphr_vlhb=_calc_distribution([c.bphr_vlhb for c in cards]),
        bp1b_vlhb=_calc_distribution([c.bp1b_vlhb for c in cards]),
        # vs RHB
        so_vrhb=_calc_distribution([c.so_vrhb for c in cards]),
        bb_vrhb=_calc_distribution([c.bb_vrhb for c in cards]),
        hit_vrhb=_calc_distribution([c.hit_vrhb for c in cards]),
        ob_vrhb=_calc_distribution([c.ob_vrhb for c in cards]),
        tb_vrhb=_calc_distribution([c.tb_vrhb for c in cards]),
        hr_vrhb=_calc_distribution([c.hr_vrhb for c in cards]),
        dp_vrhb=_calc_distribution([c.dp_vrhb for c in cards]),
        bphr_vrhb=_calc_distribution([c.bphr_vrhb for c in cards]),
        bp1b_vrhb=_calc_distribution([c.bp1b_vrhb for c in cards]),
    )


# Cached league stats (computed once per session)
_batter_stats_cache: BatterLeagueStats | None = None
_pitcher_stats_cache: PitcherLeagueStats | None = None


async def get_batter_league_stats(session: AsyncSession) -> BatterLeagueStats:
    """Get cached batter league stats, computing if necessary."""
    global _batter_stats_cache
    if _batter_stats_cache is None:
        _batter_stats_cache = await calculate_batter_league_stats(session)
    return _batter_stats_cache


async def get_pitcher_league_stats(session: AsyncSession) -> PitcherLeagueStats:
    """Get cached pitcher league stats, computing if necessary."""
    global _pitcher_stats_cache
    if _pitcher_stats_cache is None:
        _pitcher_stats_cache = await calculate_pitcher_league_stats(session)
    return _pitcher_stats_cache


def clear_league_stats_cache() -> None:
    """Clear the cached league stats (call when card data changes)."""
    global _batter_stats_cache, _pitcher_stats_cache
    _batter_stats_cache = None
    _pitcher_stats_cache = None
