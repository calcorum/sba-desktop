"""
Standardized score caching system.

Pre-calculates and stores standardized scores for all card stats to avoid
expensive real-time calculations during matchup analysis.
"""

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import BatterCard, PitcherCard, StandardizedScoreCache
from .league_stats import (
    BatterLeagueStats,
    PitcherLeagueStats,
    StatDistribution,
    calculate_batter_league_stats,
    calculate_pitcher_league_stats,
)
from .weights import (
    BATTER_WEIGHTS,
    PITCHER_WEIGHTS,
    StatWeight,
    standardize_value,
)

logger = logging.getLogger(__name__)


@dataclass
class StatScore:
    """Score details for a single stat."""

    raw: float
    std: int  # Standardized score (-3 to +3)
    weighted: float  # std * weight


def _compute_weights_hash() -> str:
    """Generate hash of current weight configuration."""
    weights_data = {
        "batter": {k: (v.weight, v.high_is_better) for k, v in BATTER_WEIGHTS.items()},
        "pitcher": {k: (v.weight, v.high_is_better) for k, v in PITCHER_WEIGHTS.items()},
    }
    return hashlib.sha256(json.dumps(weights_data, sort_keys=True).encode()).hexdigest()[:16]


def _compute_league_stats_hash(
    batter_stats: BatterLeagueStats,
    pitcher_stats: PitcherLeagueStats,
) -> str:
    """Generate hash of league statistics."""
    # Just hash a few key values to detect significant changes
    key_values = [
        batter_stats.hit_vrhp.avg,
        batter_stats.hit_vrhp.stdev,
        batter_stats.so_vrhp.avg,
        pitcher_stats.hit_vrhb.avg,
        pitcher_stats.so_vrhb.avg,
    ]
    return hashlib.sha256(str(key_values).encode()).hexdigest()[:16]


def _calculate_batter_split_scores(
    card: BatterCard,
    split: str,  # "vlhp" or "vrhp"
    league_stats: BatterLeagueStats,
) -> tuple[float, dict[str, dict]]:
    """
    Calculate standardized scores for all stats on a batter card split.

    Returns:
        Tuple of (total_score, stat_scores_dict)
    """
    if split == "vlhp":
        stats = [
            ("so", card.so_vlhp, league_stats.so_vlhp),
            ("bb", card.bb_vlhp, league_stats.bb_vlhp),
            ("hit", card.hit_vlhp, league_stats.hit_vlhp),
            ("ob", card.ob_vlhp, league_stats.ob_vlhp),
            ("tb", card.tb_vlhp, league_stats.tb_vlhp),
            ("hr", card.hr_vlhp, league_stats.hr_vlhp),
            ("bphr", card.bphr_vlhp, league_stats.bphr_vlhp),
            ("bp1b", card.bp1b_vlhp, league_stats.bp1b_vlhp),
            ("dp", card.dp_vlhp, league_stats.dp_vlhp),
        ]
    else:  # vrhp
        stats = [
            ("so", card.so_vrhp, league_stats.so_vrhp),
            ("bb", card.bb_vrhp, league_stats.bb_vrhp),
            ("hit", card.hit_vrhp, league_stats.hit_vrhp),
            ("ob", card.ob_vrhp, league_stats.ob_vrhp),
            ("tb", card.tb_vrhp, league_stats.tb_vrhp),
            ("hr", card.hr_vrhp, league_stats.hr_vrhp),
            ("bphr", card.bphr_vrhp, league_stats.bphr_vrhp),
            ("bp1b", card.bp1b_vrhp, league_stats.bp1b_vrhp),
            ("dp", card.dp_vrhp, league_stats.dp_vrhp),
        ]

    total = 0.0
    stat_scores = {}

    for stat_name, raw_val, dist in stats:
        sw = BATTER_WEIGHTS[stat_name]
        std_score = standardize_value(raw_val, dist, sw.high_is_better)
        weighted = std_score * sw.weight
        total += weighted
        stat_scores[stat_name] = {
            "raw": raw_val or 0,
            "std": std_score,
            "weighted": weighted,
        }

    return total, stat_scores


def _calculate_pitcher_split_scores(
    card: PitcherCard,
    split: str,  # "vlhb" or "vrhb"
    league_stats: PitcherLeagueStats,
) -> tuple[float, dict[str, dict]]:
    """
    Calculate standardized scores for all stats on a pitcher card split.

    Returns:
        Tuple of (total_score, stat_scores_dict)
    """
    if split == "vlhb":
        stats = [
            ("so", card.so_vlhb, league_stats.so_vlhb),
            ("bb", card.bb_vlhb, league_stats.bb_vlhb),
            ("hit", card.hit_vlhb, league_stats.hit_vlhb),
            ("ob", card.ob_vlhb, league_stats.ob_vlhb),
            ("tb", card.tb_vlhb, league_stats.tb_vlhb),
            ("hr", card.hr_vlhb, league_stats.hr_vlhb),
            ("bphr", card.bphr_vlhb, league_stats.bphr_vlhb),
            ("bp1b", card.bp1b_vlhb, league_stats.bp1b_vlhb),
            ("dp", card.dp_vlhb, league_stats.dp_vlhb),
        ]
    else:  # vrhb
        stats = [
            ("so", card.so_vrhb, league_stats.so_vrhb),
            ("bb", card.bb_vrhb, league_stats.bb_vrhb),
            ("hit", card.hit_vrhb, league_stats.hit_vrhb),
            ("ob", card.ob_vrhb, league_stats.ob_vrhb),
            ("tb", card.tb_vrhb, league_stats.tb_vrhb),
            ("hr", card.hr_vrhb, league_stats.hr_vrhb),
            ("bphr", card.bphr_vrhb, league_stats.bphr_vrhb),
            ("bp1b", card.bp1b_vrhb, league_stats.bp1b_vrhb),
            ("dp", card.dp_vrhb, league_stats.dp_vrhb),
        ]

    total = 0.0
    stat_scores = {}

    for stat_name, raw_val, dist in stats:
        sw = PITCHER_WEIGHTS[stat_name]
        std_score = standardize_value(raw_val, dist, sw.high_is_better)
        weighted = std_score * sw.weight
        total += weighted
        stat_scores[stat_name] = {
            "raw": raw_val or 0,
            "std": std_score,
            "weighted": weighted,
        }

    return total, stat_scores


async def rebuild_score_cache(session: AsyncSession) -> dict[str, int]:
    """
    Rebuild the entire standardized score cache.

    Deletes all existing cached scores and recalculates from scratch
    using current league statistics and weights.

    Args:
        session: Database session

    Returns:
        Dict with counts: {"batter_splits": N, "pitcher_splits": M}
    """
    logger.info("Rebuilding standardized score cache...")

    # Calculate current league stats
    batter_league_stats = await calculate_batter_league_stats(session)
    pitcher_league_stats = await calculate_pitcher_league_stats(session)

    # Get hashes for cache validity tracking
    weights_hash = _compute_weights_hash()
    league_hash = _compute_league_stats_hash(batter_league_stats, pitcher_league_stats)

    # Clear existing cache
    await session.execute(delete(StandardizedScoreCache))

    # Get all batter cards
    batter_result = await session.execute(select(BatterCard))
    batter_cards: Sequence[BatterCard] = batter_result.scalars().all()

    # Get all pitcher cards
    pitcher_result = await session.execute(select(PitcherCard))
    pitcher_cards: Sequence[PitcherCard] = pitcher_result.scalars().all()

    batter_count = 0
    pitcher_count = 0
    now = datetime.utcnow()

    # Calculate and cache batter scores
    for card in batter_cards:
        for split in ["vlhp", "vrhp"]:
            total, stat_scores = _calculate_batter_split_scores(card, split, batter_league_stats)
            cache_entry = StandardizedScoreCache(
                batter_card_id=card.id,
                pitcher_card_id=None,
                split=split,
                total_score=total,
                stat_scores=stat_scores,
                computed_at=now,
                weights_hash=weights_hash,
                league_stats_hash=league_hash,
            )
            session.add(cache_entry)
            batter_count += 1

    # Calculate and cache pitcher scores
    for card in pitcher_cards:
        for split in ["vlhb", "vrhb"]:
            total, stat_scores = _calculate_pitcher_split_scores(card, split, pitcher_league_stats)
            cache_entry = StandardizedScoreCache(
                batter_card_id=None,
                pitcher_card_id=card.id,
                split=split,
                total_score=total,
                stat_scores=stat_scores,
                computed_at=now,
                weights_hash=weights_hash,
                league_stats_hash=league_hash,
            )
            session.add(cache_entry)
            pitcher_count += 1

    await session.flush()
    logger.info(
        f"Score cache rebuilt: {batter_count} batter splits, {pitcher_count} pitcher splits"
    )

    return {"batter_splits": batter_count, "pitcher_splits": pitcher_count}


async def get_cached_batter_score(
    session: AsyncSession,
    batter_card_id: int,
    split: str,  # "vlhp" or "vrhp"
) -> StandardizedScoreCache | None:
    """Get cached score for a batter card split."""
    query = select(StandardizedScoreCache).where(
        StandardizedScoreCache.batter_card_id == batter_card_id,
        StandardizedScoreCache.split == split,
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_cached_pitcher_score(
    session: AsyncSession,
    pitcher_card_id: int,
    split: str,  # "vlhb" or "vrhb"
) -> StandardizedScoreCache | None:
    """Get cached score for a pitcher card split."""
    query = select(StandardizedScoreCache).where(
        StandardizedScoreCache.pitcher_card_id == pitcher_card_id,
        StandardizedScoreCache.split == split,
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def is_cache_valid(session: AsyncSession) -> bool:
    """
    Check if the score cache is valid (exists and has current weights/stats).

    Returns False if:
    - Cache is empty
    - Weights have changed
    - League stats have changed significantly
    """
    # Check if any cache entries exist
    query = select(StandardizedScoreCache).limit(1)
    result = await session.execute(query)
    entry = result.scalar_one_or_none()

    if entry is None:
        return False

    # Check weights hash
    current_weights_hash = _compute_weights_hash()
    if entry.weights_hash != current_weights_hash:
        logger.info("Cache invalid: weights have changed")
        return False

    # Could also check league_stats_hash here, but that would require
    # recalculating stats which defeats the purpose of caching.
    # For now, trust that cache is rebuilt when cards are imported.

    return True


async def ensure_cache_exists(session: AsyncSession) -> None:
    """Ensure score cache exists, rebuilding if necessary."""
    if not await is_cache_valid(session):
        await rebuild_score_cache(session)
        await session.commit()
