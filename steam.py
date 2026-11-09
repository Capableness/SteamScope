# Everything that talks to the Steam Web API lives in this file.
import os
import re
import time
import requests

BASE_URL = "https://api.steampowered.com/"
KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "steam_key.txt")


class SteamError(Exception):
    # message is shown to the user, code is the HTTP status for the page
    def __init__(self, message, code=502):
        Exception.__init__(self, message)
        self.message = message
        self.code = code


def get_api_key():
    # the key comes from the STEAM_API_KEY variable, or from a file called steam_key.txt
    key = os.environ.get("STEAM_API_KEY")
    if key and key.strip():
        return key.strip()
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE) as f:
            return f.read().strip()
    return None


def call_steam(path, params):
    key = get_api_key()
    if not key:
        raise SteamError("No Steam API key found. Put it in a file called steam_key.txt next to app.py (or set STEAM_API_KEY).", 500)
    params["key"] = key
    for attempt in range(3):
        try:
            response = requests.get(BASE_URL + path, params=params, timeout=10)
        except requests.RequestException:
            raise SteamError("Could not reach Steam. Check the connection and try again.", 503)
        if response.status_code != 429 and response.status_code < 500:
            return response
        # shown in the terminal so we can see what Steam actually said
        print("Steam returned", response.status_code, "for", path)
        time.sleep(attempt + 1)  # wait a bit longer each time
    raise SteamError("Steam is busy or limiting requests. Wait a minute and try again.", 503)


def check_key(response):
    if response.status_code in (401, 403):
        raise SteamError("Steam rejected the API key. Check that STEAM_API_KEY is correct.", 500)


def get_steam_id(text):
    # accepts a 17 digit id, a profile link, or a custom name
    text = text.strip()
    if text == "":
        raise SteamError("Enter a Steam profile for both players.", 400)
    if re.fullmatch(r"\d{17}", text):
        return text
    match = re.search(r"steamcommunity\.com/profiles/(\d{17})", text)
    if match:
        return match.group(1)
    match = re.search(r"steamcommunity\.com/id/([A-Za-z0-9_-]+)", text)
    if match:
        name = match.group(1)
    elif re.fullmatch(r"[A-Za-z0-9_-]{2,32}", text):
        name = text
    else:
        raise SteamError("'" + text[:40] + "' is not a Steam profile. Use a profile link, a custom name or a 17 digit Steam ID.", 400)

    # custom names have to be turned into a Steam id
    response = call_steam("ISteamUser/ResolveVanityURL/v1/", {"vanityurl": name})
    check_key(response)
    data = response.json()["response"]
    if data.get("success") != 1:
        raise SteamError("No Steam profile found for '" + name + "'.", 404)
    return data["steamid"]


def get_profile(steam_id):
    response = call_steam("ISteamUser/GetPlayerSummaries/v2/", {"steamids": steam_id})
    check_key(response)
    players = response.json()["response"]["players"]
    if len(players) == 0:
        raise SteamError("No Steam profile found for ID " + steam_id + ".", 404)
    player = players[0]
    return {
        "steam_id": steam_id,
        "name": player.get("personaname", steam_id),
        "avatar": player.get("avatarfull"),
        "url": player.get("profileurl"),
        "public": player.get("communityvisibilitystate") == 3,
    }


def private_message(name):
    return name + "'s game details are private. On Steam go to Edit Profile > Privacy Settings and set Game details to Public."


def get_owned_games(steam_id, name):
    response = call_steam("IPlayerService/GetOwnedGames/v1/", {"steamid": steam_id, "include_appinfo": 1, "include_played_free_games": 1})
    check_key(response)
    data = response.json()["response"]
    if "game_count" not in data:
        # Steam sends back an empty response when game details are private
        raise SteamError(private_message(name), 422)
    games = []
    for g in data.get("games", []):
        games.append({
            "appid": g["appid"],
            "name": g.get("name", "App " + str(g["appid"])),
            "icon": g.get("img_icon_url"),
            "minutes": g.get("playtime_forever", 0),
        })
    return games


def get_achievements(steam_id, appid):
    # returns (unlocked, total) or None if the game has no achievements we can read
    response = call_steam("ISteamUserStats/GetPlayerAchievements/v1/", {"steamid": steam_id, "appid": appid})
    if response.status_code != 200:
        return None
    stats = response.json().get("playerstats", {})
    achievements = stats.get("achievements")
    if not stats.get("success") or not achievements:
        return None
    unlocked = 0
    for a in achievements:
        if a.get("achieved") == 1:
            unlocked += 1
    return (unlocked, len(achievements))


def get_news(appid, count=3):
    response = call_steam("ISteamNews/GetNewsForApp/v2/", {"appid": appid, "count": count, "maxlength": 1})
    if response.status_code != 200:
        return []
    items = []
    for n in response.json().get("appnews", {}).get("newsitems", []):
        if n.get("url", "").startswith("http"):
            items.append({"title": n.get("title", ""), "url": n["url"], "date": n.get("date", 0)})
    return items
