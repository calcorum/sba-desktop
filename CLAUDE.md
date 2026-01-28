# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SBA Scout is a TUI (Terminal User Interface) application for SBA fantasy baseball scouting and team management. Built with Textual for the interface, SQLAlchemy for async database operations, and pydantic-settings for configuration.

## Commands

```bash
# Install dependencies (use uv, not pip)
uv pip install -e .

# Run the application
sba-scout          # via console script
python main.py     # direct execution

# Lint code
ruff check src/
ruff check --fix src/   # auto-fix

# Format code
ruff format src/
```

There is no test suite currently (tests/ directory exists but is empty).

## Architecture

### Layer Structure

```
src/sba_scout/
├── api/           # External API integration
├── calc/          # Scoring and statistics calculations
├── db/            # SQLAlchemy models and queries
├── screens/       # Textual UI screens
├── app.py         # Main application and DashboardScreen
└── config.py      # Pydantic settings management
```

### Data Flow

1. **API Layer** (`api/`) syncs data from League API → SQLite database
2. **CSV Import** (`api/importer.py`) loads batter/pitcher card data from spreadsheets
3. **Database Layer** (`db/`) stores teams, players, cards, lineups
4. **Calc Layer** (`calc/`) computes standardized matchup scores using league stats
5. **UI Layer** (`screens/`, `app.py`) displays data via Textual TUI

### Key Patterns

- **Async throughout**: SQLAlchemy async with aiosqlite, httpx async client
- **Lazy singletons**: `get_settings()` returns global Settings, database engine initialized on first use
- **Context managers**: API client and database sessions use `async with`
- **Layered config**: Pydantic defaults → .env file → data/settings.yaml (user editable)

### Database Models (db/models.py)

Core models: `Team`, `Player`, `BatterCard`, `PitcherCard`, `Lineup`, `MatchupCache`, `StandardizedScoreCache`, `SyncStatus`, `Transaction`

### Screens (screens/)

- `roster.py` - Tabbed roster view (majors/minors/IL)
- `matchup.py` - Batter vs pitcher analysis
- `lineup.py` - Lineup builder with drag/drop
- `gameday.py` - Combined matchup + lineup view
- `settings.py` - Configuration UI with YAML persistence

### Matchup Scoring System (calc/)

- Standardizes stats to -3 to +3 range based on league averages/stdev
- Handedness-aware (vLHP/vRHP for batters, vLHB/vRHB for pitchers)
- Weighted composite scores with tier assignment (A/B/C/D/F)
- Cached for performance in `StandardizedScoreCache`

## Configuration

Environment variables use `SBA_SCOUT_` prefix with `__` for nesting:
- `SBA_SCOUT_API__BASE_URL`
- `SBA_SCOUT_API__API_KEY`
- `SBA_SCOUT_TEAM__TEAM_ABBREV`

User settings saved to `data/settings.yaml` (editable via Settings screen or directly).

## Code Style

- Line length: 100 characters
- Python 3.12+
- Ruff rules: E, F, I, N, W, UP (standard + imports + naming + upgrades)
