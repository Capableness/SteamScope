# SteamScope: compare two Steam profiles.
# Run with:  python app.py   (set STEAM_API_KEY first, see README)
import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

import database
import steam
import steam_login

ACHIEVEMENT_LIMIT = 12  # Steam needs one request per game, so only check the most played shared games

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-before-deploying")
if os.environ.get("RENDER"):
    # Render serves the site over https behind a proxy
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config["SESSION_COOKIE_SECURE"] = True
database.create_tables()


def to_hours(minutes):
    return round(minutes / 60, 1)


def load_player(steam_id):
    # use saved data if it is recent, otherwise ask Steam
    player = database.get_saved_profile(steam_id)
    if player is not None:
        return player
    profile = steam.get_profile(steam_id)
    if not profile["public"]:
        raise steam.SteamError(steam.private_message(profile["name"]), 422)
    games = steam.get_owned_games(steam_id, profile["name"])
    database.save_profile(profile, games)
    profile["games"] = games
    return profile


def load_achievements(steam_id, appids):
    # returns the results and True if Steam refused some of the lookups
    results = database.get_saved_achievements(steam_id, appids)
    new_rows = []
    failed = False
    for appid in appids:
        if appid in results:
            continue
        if failed:
            results[appid] = (0, 0)  # Steam already refused, so stop asking
            continue
        try:
            found = steam.get_achievements(steam_id, appid)
        except steam.SteamError:
            failed = True
            results[appid] = (0, 0)  # not saved, so it is tried again next time
            continue
        if found is None:
            found = (0, 0)
        results[appid] = found
        new_rows.append((appid, found[0], found[1]))
    if new_rows:
        database.save_achievements(steam_id, new_rows)
    return results, failed


def make_row(label, a, b, suffix=""):
    # one line of the comparison table, higher number wins
    winner = None
    if a is not None and b is not None and a != b:
        winner = "a" if a > b else "b"
    shown = []
    for value in (a, b):
        if value is None:
            shown.append("n/a")
        elif isinstance(value, float):
            shown.append(format(value, ",.1f") + suffix)
        else:
            shown.append(format(value, ",") + suffix)
    return {"label": label, "a": shown[0], "b": shown[1], "winner": winner}


def achievement_text(result):
    if result is None or result[1] == 0:
        return "not checked"
    return str(result[0]) + "/" + str(result[1]) + " (" + str(round(100 * result[0] / result[1])) + "%)"


def compare_players(text_a, text_b):
    id_a = steam.get_steam_id(text_a)
    id_b = steam.get_steam_id(text_b)
    if id_a == id_b:
        raise steam.SteamError("Pick two different profiles to compare.", 400)
    player_a = load_player(id_a)
    player_b = load_player(id_b)

    games_a = {}
    for g in player_a["games"]:
        games_a[g["appid"]] = g
    games_b = {}
    for g in player_b["games"]:
        games_b[g["appid"]] = g

    # games both players own
    shared = []
    for appid in games_a:
        if appid in games_b:
            shared.append({
                "appid": appid,
                "name": games_a[appid]["name"],
                "icon": games_a[appid]["icon"],
                "minutes_a": games_a[appid]["minutes"],
                "minutes_b": games_b[appid]["minutes"],
            })
    shared.sort(key=lambda g: g["minutes_a"] + g["minutes_b"], reverse=True)

    # achievements for the most played shared games
    top = shared[:ACHIEVEMENT_LIMIT]
    appids = [g["appid"] for g in top]
    ach_a, failed_a = load_achievements(id_a, appids)
    ach_b, failed_b = load_achievements(id_b, appids)
    unlocked = [0, 0]
    total = [0, 0]
    for g in top:
        g["ach_a"] = ach_a[g["appid"]]
        g["ach_b"] = ach_b[g["appid"]]
        for i, result in enumerate((g["ach_a"], g["ach_b"])):
            unlocked[i] += result[0]
            total[i] += result[1]
    pct = []
    for i in range(2):
        pct.append(round(100 * unlocked[i] / total[i]) if total[i] > 0 else None)

    hours_a = to_hours(sum(g["minutes"] for g in player_a["games"]))
    hours_b = to_hours(sum(g["minutes"] for g in player_b["games"]))
    played_a = len([g for g in player_a["games"] if g["minutes"] > 0])
    played_b = len([g for g in player_b["games"] if g["minutes"] > 0])
    rows = [
        make_row("Games owned", len(player_a["games"]), len(player_b["games"])),
        make_row("Games played", played_a, played_b),
        make_row("Hours played", hours_a, hours_b),
        make_row("Achievement completion", pct[0], pct[1], "%"),
    ]

    # rows for the hours chart: bars grow out from the middle, the biggest value gets the longest bar
    top_ten = shared[:10]
    biggest = max([max(g["minutes_a"], g["minutes_b"]) for g in top_ten]) if top_ten else 0
    hours_rows = []
    for g in top_ten:
        width_a = round(80 * g["minutes_a"] / biggest) if biggest > 0 else 0
        width_b = round(80 * g["minutes_b"] / biggest) if biggest > 0 else 0
        hours_rows.append({"name": g["name"], "a": to_hours(g["minutes_a"]), "b": to_hours(g["minutes_b"]),
                           "width_a": width_a, "width_b": width_b})

    # rows for the achievement chart: two dots on a 0 to 100 line
    ach_rows = []
    for g in top:
        if g["ach_a"][1] > 0 and g["ach_b"][1] > 0:
            pct_a = round(100 * g["ach_a"][0] / g["ach_a"][1])
            pct_b = round(100 * g["ach_b"][0] / g["ach_b"][1])
            ach_rows.append({"name": g["name"], "a": pct_a, "b": pct_b,
                             "low": min(pct_a, pct_b), "gap": abs(pct_a - pct_b)})

    # news for the most played shared game (nice to have, so ignore failures)
    news = []
    if len(shared) > 0:
        try:
            for n in steam.get_news(shared[0]["appid"]):
                date = datetime.fromtimestamp(n["date"]).strftime("%d %b %Y").lstrip("0")
                news.append({"title": n["title"], "url": n["url"], "date": date})
        except steam.SteamError:
            news = []

    database.save_search(id_a, id_b, len(shared))
    return {"players": [player_a, player_b], "rows": rows, "shared": shared,
            "checked": len(top), "limit": ACHIEVEMENT_LIMIT, "ach_failed": failed_a or failed_b, "hours_rows": hours_rows, "ach_rows": ach_rows, "news": news,
            "top_game": shared[0]["name"] if shared else "",
            "top_appid": shared[0]["appid"] if shared else None}


def render_home(error=None, a="", b="", status=200):
    # the home page also shows lists made from the saved data
    try:
        lists = {"recent_searches": database.get_recent_searches(),
                 "recent_profiles": database.get_recent_profiles(),
                 "popular_games": database.get_popular_games()}
    except Exception:
        lists = {"recent_searches": [], "recent_profiles": [], "popular_games": []}
    return render_template("index.html", error=error, a=a, b=b, **lists), status


@app.route("/")
def index():
    user = session.get("user")
    first = user["steam_id"] if user else ""
    return render_home(a=first)


@app.route("/compare")
def compare():
    result = compare_players(request.args.get("a", ""), request.args.get("b", ""))
    return render_template("results.html", r=result, achievement_text=achievement_text, to_hours=to_hours)


@app.route("/login")
def login():
    return redirect(steam_login.get_login_url(url_for("login_return", _external=True), request.host_url))


@app.route("/login/return")
def login_return():
    steam_id = steam_login.check_login(request.args.to_dict(), url_for("login_return", _external=True))
    try:
        name = steam.get_profile(steam_id)["name"]
    except steam.SteamError:
        name = steam_id
    session.clear()
    session["user"] = {"steam_id": steam_id, "name": name}
    return redirect(url_for("index"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/health")
def health():
    return "ok"


@app.errorhandler(steam.SteamError)
def steam_error(error):
    return render_home(error.message, request.args.get("a", ""), request.args.get("b", ""), error.code)


@app.errorhandler(404)
def not_found(error):
    return render_home("That page does not exist.", status=404)


@app.errorhandler(500)
def server_error(error):
    return render_home("Something went wrong on the server. Try again.", status=500)


if __name__ == "__main__":
    if not steam.get_api_key():
        print("Warning: no Steam API key found. Put it in steam_key.txt next to app.py.")
    app.run(debug=True)
