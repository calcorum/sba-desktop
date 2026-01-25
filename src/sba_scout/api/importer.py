"""
Card data importer for importing Strat-o-Matic card values from CSV files.

Imports batter and pitcher card data from exported spreadsheet CSVs.
The CSVs contain pre-calculated vL/vR/Total ratings from the master spreadsheet.
"""

import csv
import logging
import re
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import BatterCard, PitcherCard, Player

logger = logging.getLogger(__name__)


def parse_float(value: str, default: float = 0.0) -> float:
    """Safely parse a float from a string."""
    if not value or value.strip() == "":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def parse_int(value: str, default: int = 0) -> int:
    """Safely parse an int from a string."""
    if not value or value.strip() == "":
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


def parse_endurance(endurance_str: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """
    Parse endurance string like 'S(5) R(4)' or 'R(1) C(6)'.

    Returns (start, relief, close) tuple.
    """
    start = relief = close = None

    if not endurance_str:
        return start, relief, close

    s_match = re.search(r"S\((\d+)\*?\)", endurance_str)
    r_match = re.search(r"R\((\d+)\)", endurance_str)
    c_match = re.search(r"C\((\d+)\)", endurance_str)

    if s_match:
        start = int(s_match.group(1))
    if r_match:
        relief = int(r_match.group(1))
    if c_match:
        close = int(c_match.group(1))

    return start, relief, close


async def import_batter_cards(
    session: AsyncSession,
    csv_path: Path,
    update_existing: bool = True,
) -> tuple[int, int, list[str]]:
    """
    Import batter card data from CSV.

    Expected CSV columns (from BatterCalcs export):
    - player_id, Name, sWAR, hand
    - SO vlhp, SO v rhp, BB v lhp, BB v rhp
    - HIT v lhp, HIT v rhp, OB v lhp, OB v rhp
    - TB v lhp, TB v rhp, HR v lhp, HR v rhp
    - BPHR v lhp, BPHR v rhp, BP1B v lhp, BP1B v rhp
    - DP v lhp, DP v rhp
    - STEALING, STL, SPD, B, H (bunt, hit-run)
    - FIELDING
    - vL, vR, Total (computed ratings in sheet)

    Args:
        session: Database session
        csv_path: Path to CSV file
        update_existing: If True, update existing cards; if False, skip them

    Returns:
        Tuple of (imported_count, skipped_count, errors)
    """
    imported = 0
    skipped = 0
    errors = []

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            try:
                player_id = parse_int(row.get("player_id", ""))
                if not player_id:
                    continue

                # Check if player exists
                player = await session.get(Player, player_id)
                if not player:
                    errors.append(
                        f"Player {player_id} ({row.get('Name', 'Unknown')}) not found in database"
                    )
                    continue

                # Update player hand if available
                hand = row.get("hand", "").strip()
                if hand and hand in ("L", "R", "S"):
                    player.hand = hand

                # Check for existing card
                existing = await session.execute(
                    select(BatterCard).where(BatterCard.player_id == player_id)
                )
                card = existing.scalar_one_or_none()

                if card and not update_existing:
                    skipped += 1
                    continue

                if not card:
                    card = BatterCard(player_id=player_id)
                    session.add(card)

                # Parse stats vs LHP
                card.so_vlhp = parse_float(row.get("SO vlhp", ""))
                card.bb_vlhp = parse_float(row.get("BB v lhp", ""))
                card.hit_vlhp = parse_float(row.get("HIT v lhp", ""))
                card.ob_vlhp = parse_float(row.get("OB v lhp", ""))
                card.tb_vlhp = parse_float(row.get("TB v lhp", ""))
                card.hr_vlhp = parse_float(row.get("HR v lhp", ""))
                card.dp_vlhp = parse_float(row.get("DP v lhp", ""))
                card.bphr_vlhp = parse_float(row.get("BPHR v lhp", ""))
                card.bp1b_vlhp = parse_float(row.get("BP1B v lhp", ""))

                # Parse stats vs RHP
                card.so_vrhp = parse_float(row.get("SO v rhp", ""))
                card.bb_vrhp = parse_float(row.get("BB v rhp", ""))
                card.hit_vrhp = parse_float(row.get("HIT v rhp", ""))
                card.ob_vrhp = parse_float(row.get("OB v rhp", ""))
                card.tb_vrhp = parse_float(row.get("TB v rhp", ""))
                card.hr_vrhp = parse_float(row.get("HR v rhp", ""))
                card.dp_vrhp = parse_float(row.get("DP v rhp", ""))
                card.bphr_vrhp = parse_float(row.get("BPHR v rhp", ""))
                card.bp1b_vrhp = parse_float(row.get("BP1B v rhp", ""))

                # Running game
                card.stealing = row.get("STEALING", "").strip()
                card.steal_rating = row.get("STL", "").strip()
                card.speed = parse_int(row.get("SPD", "10"), 10)

                # Batting extras
                card.bunt = row.get("B", "").strip()
                card.hit_run = row.get("H", "").strip()

                # Fielding - store raw string from CSV
                card.fielding = row.get("FIELDING", "").strip()

                # Catcher arm from separate column if present
                catcher_arm = row.get("cArm", "") or row.get("CA", "")
                if catcher_arm:
                    card.catcher_arm = parse_int(catcher_arm)

                # Import pre-calculated ratings from CSV
                card.rating_vl = parse_float(row.get("vL", ""))
                card.rating_vr = parse_float(row.get("vR", ""))
                card.rating_overall = parse_float(row.get("Total", ""))

                card.source = str(csv_path.name)

                imported += 1

            except Exception as e:
                player_name = row.get("Name", "Unknown")
                errors.append(f"Error importing {player_name}: {str(e)}")
                logger.exception(f"Error importing batter {player_name}")

    return imported, skipped, errors


async def import_pitcher_cards(
    session: AsyncSession,
    csv_path: Path,
    update_existing: bool = True,
) -> tuple[int, int, list[str]]:
    """
    Import pitcher card data from CSV.

    Expected CSV columns (from PitcherCalcs export):
    - player_id, Name, sWAR, hand
    - SO vlhp, SO v rhp, BB vlhp, BB v rhp
    - HIT v lhp, HIT v rhp, OB v lhp, OB v rhp
    - TB v lhp, TB v rhp, HR v lhp, HR v rhp
    - BPHR vL, BPHR vR, BP1B v lhp, BP1b v rhp
    - DP vlhp, DP v rhp
    - HO (hold rating), ENDURANCE
    - Range, Error, BK, WP
    - vL, vR, Total

    Args:
        session: Database session
        csv_path: Path to CSV file
        update_existing: If True, update existing cards

    Returns:
        Tuple of (imported_count, skipped_count, errors)
    """
    imported = 0
    skipped = 0
    errors = []

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            try:
                player_id = parse_int(row.get("player_id", ""))
                if not player_id:
                    continue

                # Check if player exists
                player = await session.get(Player, player_id)
                if not player:
                    errors.append(
                        f"Player {player_id} ({row.get('Name', 'Unknown')}) not found in database"
                    )
                    continue

                # Update player hand if available
                hand = row.get("hand", "").strip()
                if hand and hand in ("L", "R"):
                    player.hand = hand

                # Check for existing card
                existing = await session.execute(
                    select(PitcherCard).where(PitcherCard.player_id == player_id)
                )
                card = existing.scalar_one_or_none()

                if card and not update_existing:
                    skipped += 1
                    continue

                if not card:
                    card = PitcherCard(player_id=player_id)
                    session.add(card)

                # Note: For pitchers, "vlhp" means "vs left-handed batters"
                # Parse stats vs LH Batters
                card.so_vlhb = parse_float(row.get("SO vlhp", ""))
                card.bb_vlhb = parse_float(row.get("BB vlhp", ""))
                card.hit_vlhb = parse_float(row.get("HIT v lhp", ""))
                card.ob_vlhb = parse_float(row.get("OB v lhp", ""))
                card.tb_vlhb = parse_float(row.get("TB v lhp", ""))
                card.hr_vlhb = parse_float(row.get("HR v lhp", ""))
                card.dp_vlhb = parse_float(row.get("DP vlhp", ""))
                card.bphr_vlhb = parse_float(row.get("BPHR vL", ""))
                card.bp1b_vlhb = parse_float(row.get("BP1B v lhp", ""))

                # Parse stats vs RH Batters
                card.so_vrhb = parse_float(row.get("SO v rhp", ""))
                card.bb_vrhb = parse_float(row.get("BB v rhp", ""))
                card.hit_vrhb = parse_float(row.get("HIT v rhp", ""))
                card.ob_vrhb = parse_float(row.get("OB v rhp", ""))
                card.tb_vrhb = parse_float(row.get("TB v rhp", ""))
                card.hr_vrhb = parse_float(row.get("HR v rhp", ""))
                card.dp_vrhb = parse_float(row.get("DP v rhp", ""))
                card.bphr_vrhb = parse_float(row.get("BPHR vR", ""))
                card.bp1b_vrhb = parse_float(row.get("BP1b v rhp", ""))

                # Hold rating
                card.hold_rating = parse_int(row.get("HO", "0"))

                # Endurance
                endurance_str = row.get("ENDURANCE", "") or row.get("cleanEndur", "")
                start, relief, close = parse_endurance(endurance_str)
                card.endurance_start = start
                card.endurance_relief = relief
                card.endurance_close = close

                # Also check SP/RP/CP columns
                if row.get("SP"):
                    card.endurance_start = parse_int(row.get("SP"))
                if row.get("RP"):
                    card.endurance_relief = parse_int(row.get("RP"))
                if row.get("CP"):
                    card.endurance_close = parse_int(row.get("CP"))

                # Fielding
                card.fielding_range = parse_int(row.get("Range", ""))
                card.fielding_error = parse_int(row.get("Error", ""))

                # Wild pitch / Balk
                card.wild_pitch = parse_int(row.get("WP", "0"))
                card.balk = parse_int(row.get("BK", "0"))

                # Batting (NL pitchers)
                card.batting_rating = row.get("BAT-B", "").strip()

                # Import pre-calculated ratings from CSV
                card.rating_vlhb = parse_float(row.get("vL", ""))
                card.rating_vrhb = parse_float(row.get("vR", ""))
                card.rating_overall = parse_float(row.get("Total", ""))

                card.source = str(csv_path.name)

                imported += 1

            except Exception as e:
                player_name = row.get("Name", "Unknown")
                errors.append(f"Error importing {player_name}: {str(e)}")
                logger.exception(f"Error importing pitcher {player_name}")

    return imported, skipped, errors


async def import_all_cards(
    session: AsyncSession,
    batter_csv: Optional[Path] = None,
    pitcher_csv: Optional[Path] = None,
    update_existing: bool = True,
) -> dict:
    """
    Import all card data from CSVs.

    Args:
        session: Database session
        batter_csv: Path to batter CSV (defaults to docs/sheets_export/BatterCalcs.csv)
        pitcher_csv: Path to pitcher CSV (defaults to docs/sheets_export/PitcherCalcs.csv)
        update_existing: Whether to update existing cards

    Returns:
        Dict with import results
    """
    base_path = Path(__file__).parent.parent.parent.parent / "docs" / "sheets_export"

    if batter_csv is None:
        batter_csv = base_path / "BatterCalcs.csv"
    if pitcher_csv is None:
        pitcher_csv = base_path / "PitcherCalcs.csv"

    results = {
        "batters": {"imported": 0, "skipped": 0, "errors": []},
        "pitchers": {"imported": 0, "skipped": 0, "errors": []},
    }

    if batter_csv.exists():
        imported, skipped, errors = await import_batter_cards(session, batter_csv, update_existing)
        results["batters"] = {
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
        }
        logger.info(f"Imported {imported} batter cards, skipped {skipped}")
    else:
        logger.warning(f"Batter CSV not found: {batter_csv}")
        results["batters"]["errors"].append(f"File not found: {batter_csv}")

    if pitcher_csv.exists():
        imported, skipped, errors = await import_pitcher_cards(
            session, pitcher_csv, update_existing
        )
        results["pitchers"] = {
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
        }
        logger.info(f"Imported {imported} pitcher cards, skipped {skipped}")
    else:
        logger.warning(f"Pitcher CSV not found: {pitcher_csv}")
        results["pitchers"]["errors"].append(f"File not found: {pitcher_csv}")

    return results
