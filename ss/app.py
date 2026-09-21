"""
app.py — SteamScope Flask application.

Routes
  GET  /            search page (profile A / profile B by SteamID or URL)
  POST /compare      resolves both profiles, pulls Steam data, stores it,
                      and renders the comparison dashboard
  GET  /about         scope + tech notes pulled from the proposal, for markers/teachers
"""
from datetime import datetime, timezone

from flask import Flask, render_template, request

import db
from config import STEAM_API_KEY, MAX_ACHIEVEMENT_LOOKUPS
from steam_api import SteamAPI, SteamAPIError, ProfileNotFoundError, ProfilePrivateError

app = Flask(__name__)
db.init_db()


def _sync_profile(api: SteamAPI, identifier: str, label: str) -> dict:
    """
    Resolve + fetch a single profile's summary and owned games, caching
    everything in SQLite. Returns a plain dict the templates can use.
    Raises ProfileNotFoundError / ProfilePrivateError / SteamAPIError.
    """
    steam_id = api.resolve_identifier(identifier)
    summary = api.get_player_summary(steam_id)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    profile_id = db.upsert_profile(steam_id, summary.get("profileurl", ""), now)

    profile = {
        "label": label,
        "steam_id": steam_id,
        "profile_id": profile_id,
        "display_name": summary.get("personaname", "Unknown"),
        "avatar": summary.get("avatarfull", ""),
        "profile_url": summary.get("profileurl", ""),
        "is_public": summary.get("is_public", False),
        "games": [],
        "total_hours": 0,
        "total_games": 0,
        "private": False,
    }

    if not profile["is_public"]:
        profile["private"] = True
        # Fall back to whatever was cached from a previous sync, if any
        cached = db.get_cached_owned_games(profile_id)
        profile["games"] = cached
        profile["total_games"] = len(cached)
        profile["total_hours"] = round(sum(g["hours_played"] for g in cached) / 60, 1)
        return profile

    try:
        owned = api.get_owned_games(steam_id)
    except ProfilePrivateError:
        profile["private"] = True
        cached = db.get_cached_owned_games(profile_id)
        profile["games"] = cached
        profile["total_games"] = len(cached)
        profile["total_hours"] = round(sum(g["hours_played"] for g in cached) / 60, 1)
        return profile

    games = []
    for g in owned:
        hours = round(g.get("playtime_forever", 0) / 60, 1)
        header_url = (
            f"https://cdn.akamai.steamstatic.com/steam/apps/{g['appid']}/header.jpg"
        )
        games.append({
            "app_id": g["appid"],
            "title": g.get("name", f"App {g['appid']}"),
            "header_image_url": header_url,
            "hours_played": hours,
            "achievements_unlocked": None,
            "achievements_total": None,
        })

    # One connection/transaction for the whole library, not one per game —
    # avoids slow syncs and "database is locked" errors on large libraries.
    db.sync_owned_games(profile_id, games)

    games.sort(key=lambda g: g["hours_played"], reverse=True)
    profile["games"] = games
    profile["total_games"] = len(games)
    profile["total_hours"] = round(sum(g["hours_played"] for g in games), 1)
    return profile


def _attach_achievements(api: SteamAPI, profile: dict, shared_app_ids: set):
    """Fill in achievement completion for a profile's most-played shared games only
    (Section 3.2: achievement comparison is the highest-cost feature, so it's scoped
    to the games that actually matter for the comparison)."""
    if profile["private"]:
        return
    lookups = 0
    for game in profile["games"]:
        if game["app_id"] not in shared_app_ids:
            continue
        if lookups >= MAX_ACHIEVEMENT_LOOKUPS:
            break
        result = api.get_player_achievements(profile["steam_id"], game["app_id"])
        lookups += 1
        if result:
            game["achievements_unlocked"] = result["unlocked"]
            game["achievements_total"] = result["total"]
            db.upsert_owned_game(
                profile["profile_id"],
                db.upsert_game(game["app_id"], game["title"], game["header_image_url"]),
                game["hours_played"], result["unlocked"], result["total"],
            )


def _build_shared_games(profile_a: dict, profile_b: dict) -> list:
    games_a = {g["app_id"]: g for g in profile_a["games"]}
    games_b = {g["app_id"]: g for g in profile_b["games"]}
    shared_ids = set(games_a) & set(games_b)

    shared = []
    for app_id in shared_ids:
        ga, gb = games_a[app_id], games_b[app_id]
        shared.append({
            "app_id": app_id,
            "title": ga["title"],
            "header_image_url": ga["header_image_url"],
            "hours_a": ga["hours_played"],
            "hours_b": gb["hours_played"],
            "achv_unlocked_a": ga.get("achievements_unlocked"),
            "achv_total_a": ga.get("achievements_total"),
            "achv_unlocked_b": gb.get("achievements_unlocked"),
            "achv_total_b": gb.get("achievements_total"),
        })
    shared.sort(key=lambda g: g["hours_a"] + g["hours_b"], reverse=True)
    return shared


@app.route("/")
def index():
    return render_template("index.html", recent=db.recent_comparisons(5))


@app.route("/compare", methods=["POST"])
def compare():
    id_a = request.form.get("profile_a", "").strip()
    id_b = request.form.get("profile_b", "").strip()

    if not id_a or not id_b:
        return render_template("index.html", recent=db.recent_comparisons(5),
                                error="Enter a SteamID or profile URL for both players.")

    try:
        api = SteamAPI(STEAM_API_KEY)
        profile_a = _sync_profile(api, id_a, "Player A")
        profile_b = _sync_profile(api, id_b, "Player B")

        shared_ids = {g["app_id"] for g in profile_a["games"]} & {g["app_id"] for g in profile_b["games"]}
        # Rank shared games by combined playtime before capping achievement lookups
        ranked_shared = sorted(
            shared_ids,
            key=lambda aid: next(g["hours_played"] for g in profile_a["games"] if g["app_id"] == aid)
                            + next(g["hours_played"] for g in profile_b["games"] if g["app_id"] == aid),
            reverse=True,
        )
        top_shared = set(ranked_shared[:MAX_ACHIEVEMENT_LOOKUPS])

        _attach_achievements(api, profile_a, top_shared)
        _attach_achievements(api, profile_b, top_shared)

        shared_games = _build_shared_games(profile_a, profile_b)

        db.record_comparison(profile_a["profile_id"], profile_b["profile_id"], len(shared_games))

    except ProfileNotFoundError as exc:
        return render_template("index.html", recent=db.recent_comparisons(5), error=str(exc))
    except SteamAPIError as exc:
        return render_template("index.html", recent=db.recent_comparisons(5), error=str(exc))

    return render_template(
        "comparison.html",
        a=profile_a,
        b=profile_b,
        shared_games=shared_games,
        shared_count=len(shared_games),
    )


@app.route("/about")
def about():
    return render_template("about.html")


if __name__ == "__main__":
    app.run(debug=True)
