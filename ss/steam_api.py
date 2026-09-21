"""
steam_api.py — thin wrapper around the Steam Web API.

Endpoints used (see Section 2.1 / 2.2 of the proposal):
  - ResolveVanityURL      -> turn a custom profile URL into a SteamID64
  - GetPlayerSummaries    -> display name, avatar, profile visibility
  - GetOwnedGames         -> owned games + hours played
  - GetPlayerAchievements -> per-game achieved flags for one appid
  - GetSchemaForGame      -> total achievement count + display names for one appid

A private profile does not raise an HTTP error (Section 2.2 finding) — it
comes back with a restricted payload, so ProfilePrivateError is raised
explicitly once that's detected, and app.py turns it into the "private
profile" message required by Section 3.2.
"""
import requests

BASE_URL = "https://api.steampowered.com"
TIMEOUT = 8


class SteamAPIError(Exception):
    """Raised for network/API failures (Section 3.2 mitigation: cache + friendly error)."""


class ProfileNotFoundError(Exception):
    """Raised when a SteamID or vanity URL does not resolve to a profile."""


class ProfilePrivateError(Exception):
    """Raised when a profile (or its game details) is private."""

    def __init__(self, display_name=None):
        self.display_name = display_name
        super().__init__("This profile's details are private.")


class SteamAPI:
    def __init__(self, api_key: str):
        if not api_key:
            raise SteamAPIError(
                "No Steam Web API key configured. Set STEAM_API_KEY in your .env file."
            )
        self.api_key = api_key

    def _get(self, interface: str, method: str, version: str, params: dict):
        url = f"{BASE_URL}/{interface}/{method}/{version}/"
        params = {**params, "key": self.api_key, "format": "json"}
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise SteamAPIError(f"Could not reach the Steam Web API: {exc}") from exc
        if resp.status_code == 403:
            raise SteamAPIError("Steam rejected the API key. Check STEAM_API_KEY.")
        if resp.status_code == 429:
            raise SteamAPIError("Steam API rate limit hit — try again shortly.")
        if not resp.ok:
            raise SteamAPIError(f"Steam API returned HTTP {resp.status_code} for {method}.")
        try:
            return resp.json()
        except ValueError as exc:
            raise SteamAPIError(f"Steam API returned an unexpected response for {method}.") from exc

    def resolve_identifier(self, identifier: str) -> str:
        """Accept a raw SteamID64, a steamcommunity.com URL, or a vanity name -> SteamID64."""
        identifier = identifier.strip()
        for prefix in ("https://steamcommunity.com/id/", "http://steamcommunity.com/id/",
                       "https://steamcommunity.com/profiles/", "http://steamcommunity.com/profiles/"):
            if identifier.startswith(prefix):
                identifier = identifier[len(prefix):].strip("/")
                break

        if identifier.isdigit() and len(identifier) == 17:
            return identifier

        data = self._get("ISteamUser", "ResolveVanityURL", "v0001",
                          {"vanityurl": identifier})
        response = data.get("response", {})
        if response.get("success") != 1:
            raise ProfileNotFoundError(f"Could not resolve '{identifier}' to a Steam profile.")
        return response["steamid"]

    def get_player_summary(self, steam_id: str) -> dict:
        data = self._get("ISteamUser", "GetPlayerSummaries", "v0002",
                          {"steamids": steam_id})
        players = data.get("response", {}).get("players", [])
        if not players:
            raise ProfileNotFoundError(f"No Steam profile found for {steam_id}.")
        player = players[0]
        # communityvisibilitystate: 1 = private, 3 = public
        player["is_public"] = player.get("communityvisibilitystate") == 3
        return player

    def get_owned_games(self, steam_id: str) -> list:
        data = self._get("IPlayerService", "GetOwnedGames", "v0001", {
            "steamid": steam_id,
            "include_appinfo": 1,
            "include_played_free_games": 1,
        })
        response = data.get("response", {})
        if "games" not in response:
            # Empty response body with no game_count means the games list is private
            raise ProfilePrivateError()
        return response.get("games", [])

    def get_player_achievements(self, steam_id: str, app_id: int) -> dict:
        """Returns {'unlocked': int, 'total': int} for one game, or None if unavailable."""
        try:
            data = self._get("ISteamUserStats", "GetPlayerAchievements", "v0001", {
                "steamid": steam_id,
                "appid": app_id,
            })
        except SteamAPIError:
            return None
        game_stats = data.get("playerstats", {})
        if not game_stats.get("success"):
            # Game has no achievements, or the profile's achievement data is private
            return None
        achievements = game_stats.get("achievements", [])
        if not achievements:
            return None
        unlocked = sum(1 for a in achievements if a.get("achieved") == 1)
        return {"unlocked": unlocked, "total": len(achievements)}
