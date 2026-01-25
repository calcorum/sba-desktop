"""
Stat weights and standardized scoring for matchup calculations.

Converts raw card values into standardized scores (-3 to +3) based on
league averages and standard deviations, then applies weights.
"""

from dataclasses import dataclass
from typing import Literal

from .league_stats import StatDistribution


@dataclass
class StatWeight:
    """Weight and direction for a single stat."""

    weight: int
    high_is_better: bool  # If True, high values get positive scores


# =============================================================================
# Batter Stat Weights (for matchup calculation)
# =============================================================================

BATTER_WEIGHTS: dict[str, StatWeight] = {
    "so": StatWeight(weight=1, high_is_better=False),  # Strikeouts - low is better
    "bb": StatWeight(weight=1, high_is_better=True),  # Walks - high is better
    "hit": StatWeight(weight=2, high_is_better=True),  # Hits - high is better
    "ob": StatWeight(weight=5, high_is_better=True),  # On-base - high is better
    "tb": StatWeight(weight=5, high_is_better=True),  # Total bases - high is better
    "hr": StatWeight(weight=2, high_is_better=True),  # Home runs - high is better
    "bphr": StatWeight(weight=3, high_is_better=True),  # Ballpark HR - high is better
    "bp1b": StatWeight(weight=1, high_is_better=True),  # Ballpark 1B - high is better
    "dp": StatWeight(weight=2, high_is_better=False),  # Double plays - low is better
}


# =============================================================================
# Pitcher Stat Weights (for matchup calculation)
# =============================================================================

PITCHER_WEIGHTS: dict[str, StatWeight] = {
    "so": StatWeight(weight=3, high_is_better=True),  # Strikeouts - high is better for pitcher
    "bb": StatWeight(weight=1, high_is_better=False),  # Walks - low is better for pitcher
    "hit": StatWeight(weight=2, high_is_better=False),  # Hits - low is better for pitcher
    "ob": StatWeight(weight=5, high_is_better=False),  # On-base - low is better for pitcher
    "tb": StatWeight(weight=2, high_is_better=False),  # Total bases - low is better for pitcher
    "hr": StatWeight(weight=5, high_is_better=False),  # Home runs - low is better for pitcher
    "bphr": StatWeight(weight=2, high_is_better=False),  # Ballpark HR - low is better for pitcher
    "bp1b": StatWeight(weight=1, high_is_better=False),  # Ballpark 1B - low is better for pitcher
    "dp": StatWeight(weight=2, high_is_better=True),  # Double plays - high is better for pitcher
}


# =============================================================================
# Standardized Scoring Functions
# =============================================================================


def standardize_value(
    value: float | None,
    distribution: StatDistribution,
    high_is_better: bool,
) -> int:
    """
    Convert a raw stat value to a standardized score (-3 to +3).

    Uses the following thresholds based on standard deviations from the mean:
        > AVG + 2*STDEV:    -3 (or +3 if high_is_better)
        > AVG + 1*STDEV:    -2 (or +2)
        > AVG + 0.33*STDEV: -1 (or +1)
        > AVG - 0.33*STDEV:  0
        > AVG - 1*STDEV:    +1 (or -1)
        > AVG - 2*STDEV:    +2 (or -2)
        else:               +3 (or -3)

    Special case: value of 0 gets the best score (+3 for low_is_better, +3 for high after invert)

    Args:
        value: Raw stat value from card
        distribution: League average and standard deviation
        high_is_better: If True, high values get positive scores (inverted)

    Returns:
        Standardized score from -3 to +3
    """
    if value is None or value == 0:
        # Zero value = best possible (for stats like SO, HR where 0 is rare/great)
        return 3 if not high_is_better else 3

    avg = distribution.avg
    stdev = distribution.stdev

    # Calculate thresholds
    thresh_plus_2sd = avg + (2 * stdev)
    thresh_plus_1sd = avg + (1 * stdev)
    thresh_plus_033sd = avg + (0.33 * stdev)
    thresh_minus_033sd = avg - (0.33 * stdev)
    thresh_minus_1sd = avg - (1 * stdev)
    thresh_minus_2sd = avg - (2 * stdev)

    # Determine base score (before inversion)
    # High values get negative scores in base formula
    if value > thresh_plus_2sd:
        base_score = -3
    elif value > thresh_plus_1sd:
        base_score = -2
    elif value > thresh_plus_033sd:
        base_score = -1
    elif value > thresh_minus_033sd:
        base_score = 0
    elif value > thresh_minus_1sd:
        base_score = 1
    elif value > thresh_minus_2sd:
        base_score = 2
    else:
        base_score = 3

    # Invert if high values are better
    if high_is_better:
        return -base_score
    return base_score


def calculate_weighted_score(
    value: float | None,
    distribution: StatDistribution,
    stat_weight: StatWeight,
) -> float:
    """
    Calculate weighted score for a single stat.

    Args:
        value: Raw stat value
        distribution: League avg/stdev for this stat
        stat_weight: Weight and direction for this stat

    Returns:
        Weighted score (standardized_score * weight)
    """
    std_score = standardize_value(value, distribution, stat_weight.high_is_better)
    return std_score * stat_weight.weight


# =============================================================================
# Maximum Possible Scores (for reference)
# =============================================================================


def get_max_batter_score() -> int:
    """Get the maximum possible batter component score."""
    # All stats at +3, multiplied by weights
    return sum(3 * w.weight for w in BATTER_WEIGHTS.values())


def get_max_pitcher_score() -> int:
    """Get the maximum possible pitcher component score."""
    return sum(3 * w.weight for w in PITCHER_WEIGHTS.values())


def get_max_matchup_score() -> int:
    """Get the maximum possible combined matchup score."""
    return get_max_batter_score() + get_max_pitcher_score()


# Max scores:
# Batter: (1+1+2+5+5+2+3+1+2) * 3 = 22 * 3 = 66
# Pitcher: (3+1+2+5+2+5+2+1+2) * 3 = 23 * 3 = 69
# Combined max: 135
