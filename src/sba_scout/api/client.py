"""
League API client for syncing data.

Provides async HTTP client for the SBA Major Domo API.
"""

import logging
from typing import Any, Optional

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)


class LeagueAPIError(Exception):
    """Raised when the league API returns an error."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class LeagueAPIClient:
    """
    Async client for the SBA League API.

    Usage:
        async with LeagueAPIClient() as client:
            players = await client.get_players(season=13)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 30,
    ):
        """
        Initialize the API client.

        Args:
            base_url: API base URL (uses settings if not provided)
            api_key: API key for authentication (uses settings if not provided)
            timeout: Request timeout in seconds
        """
        settings = get_settings()
        self.base_url = (base_url or settings.api.base_url).rstrip("/")
        self.api_key = api_key or settings.api.api_key
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """Enter async context manager."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=self._get_headers(),
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit async context manager."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_headers(self) -> dict[str, str]:
        """Get request headers including auth if configured."""
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> Any:
        """
        Make an API request.

        Args:
            method: HTTP method
            endpoint: API endpoint (without base URL)
            params: Query parameters
            json: JSON body for POST/PUT

        Returns:
            Parsed JSON response

        Raises:
            LeagueAPIError: If request fails
        """
        if not self._client:
            raise LeagueAPIError("Client not initialized. Use 'async with' context manager.")

        url = f"/api/v3{endpoint}"
        logger.debug(f"API request: {method} {url} params={params}")

        try:
            response = await self._client.request(
                method=method,
                url=url,
                params=params,
                json=json,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"API error: {e.response.status_code} - {e.response.text}")
            raise LeagueAPIError(
                f"API request failed: {e.response.text}",
                status_code=e.response.status_code,
            )
        except httpx.RequestError as e:
            logger.error(f"Request error: {e}")
            raise LeagueAPIError(f"Request failed: {str(e)}")

    # =========================================================================
    # Players
    # =========================================================================

    async def get_players(
        self,
        season: int,
        team_id: Optional[list[int]] = None,
        pos: Optional[list[str]] = None,
        name: Optional[str] = None,
        short_output: bool = False,
    ) -> dict:
        """
        Get players for a season.

        Args:
            season: Season number
            team_id: Filter by team IDs
            pos: Filter by positions
            name: Filter by exact name
            short_output: If True, exclude nested relations

        Returns:
            Dict with 'count' and 'players' keys
        """
        params: dict[str, Any] = {"season": season, "short_output": short_output}
        if team_id:
            params["team_id"] = team_id
        if pos:
            params["pos"] = pos
        if name:
            params["name"] = name

        return await self._request("GET", "/players", params=params)

    async def get_player(self, player_id: int, short_output: bool = False) -> Optional[dict]:
        """Get a single player by ID."""
        params = {"short_output": short_output}
        return await self._request("GET", f"/players/{player_id}", params=params)

    async def search_players(
        self,
        query: str,
        season: Optional[int] = None,
        limit: int = 10,
    ) -> dict:
        """
        Search players by name.

        Args:
            query: Search string
            season: Limit to specific season (0 or None for all)
            limit: Maximum results

        Returns:
            Dict with search results
        """
        params: dict[str, Any] = {"q": query, "limit": limit}
        if season:
            params["season"] = season

        return await self._request("GET", "/players/search", params=params)

    # =========================================================================
    # Teams
    # =========================================================================

    async def get_teams(
        self,
        season: Optional[int] = None,
        team_abbrev: Optional[list[str]] = None,
        active_only: bool = False,
        short_output: bool = False,
    ) -> dict:
        """
        Get teams.

        Args:
            season: Filter by season
            team_abbrev: Filter by abbreviations
            active_only: Exclude IL and MiL teams
            short_output: Exclude nested relations

        Returns:
            Dict with 'count' and 'teams' keys
        """
        params: dict[str, Any] = {
            "active_only": active_only,
            "short_output": short_output,
        }
        if season:
            params["season"] = season
        if team_abbrev:
            params["team_abbrev"] = team_abbrev

        return await self._request("GET", "/teams", params=params)

    async def get_team(self, team_id: int) -> Optional[dict]:
        """Get a single team by ID."""
        return await self._request("GET", f"/teams/{team_id}")

    async def get_team_roster(
        self,
        team_id: int,
        which: str = "current",
    ) -> dict:
        """
        Get team roster.

        Args:
            team_id: Team ID
            which: "current" or "next" week

        Returns:
            Dict with 'active', 'shortil', 'longil' rosters
        """
        return await self._request("GET", f"/teams/{team_id}/roster/{which}")

    # =========================================================================
    # Transactions
    # =========================================================================

    async def get_transactions(
        self,
        season: int,
        team_abbrev: Optional[list[str]] = None,
        week_start: int = 0,
        week_end: Optional[int] = None,
        cancelled: Optional[bool] = False,
        frozen: Optional[bool] = False,
        short_output: bool = True,
    ) -> dict:
        """
        Get transactions.

        Args:
            season: Season number
            team_abbrev: Filter by team abbreviations
            week_start: Start week
            week_end: End week
            cancelled: Include cancelled transactions
            frozen: Include frozen transactions
            short_output: Exclude nested relations

        Returns:
            Dict with 'count' and 'transactions' keys
        """
        params: dict[str, Any] = {
            "season": season,
            "week_start": week_start,
            "cancelled": cancelled,
            "frozen": frozen,
            "short_output": short_output,
        }
        if team_abbrev:
            params["team_abbrev"] = team_abbrev
        if week_end:
            params["week_end"] = week_end

        return await self._request("GET", "/transactions", params=params)

    # =========================================================================
    # Current Season Info
    # =========================================================================

    async def get_current(self) -> dict:
        """Get current season/week info."""
        return await self._request("GET", "/current")

    # =========================================================================
    # Schedules
    # =========================================================================

    async def get_schedule(
        self,
        season: int,
        week: Optional[int] = None,
        team_id: Optional[int] = None,
    ) -> dict:
        """
        Get schedule.

        Args:
            season: Season number
            week: Specific week
            team_id: Filter by team

        Returns:
            Schedule data
        """
        params: dict[str, Any] = {"season": season}
        if week:
            params["week"] = week
        if team_id:
            params["team_id"] = team_id

        return await self._request("GET", "/schedules", params=params)

    # =========================================================================
    # Standings
    # =========================================================================

    async def get_standings(self, season: int) -> dict:
        """Get standings for a season."""
        params = {"season": season}
        return await self._request("GET", "/standings", params=params)
