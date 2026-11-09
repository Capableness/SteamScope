# Saves Steam data in SQLite so repeat searches are quick.
import os
import sqlite3
import time

DB_FILE = os.environ.get("DATABASE_PATH", "steamscope.db")
CACHE_SECONDS = 6 * 60 * 60  # saved data is used for 6 hours


def get_connection():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def create_tables():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS profiles (
            steam_id TEXT PRIMARY KEY, name TEXT, avatar TEXT, url TEXT, updated REAL);
        CREATE TABLE IF NOT EXISTS games (
            appid INTEGER PRIMARY KEY, name TEXT, icon TEXT);
        CREATE TABLE IF NOT EXISTS owned_games (
            steam_id TEXT REFERENCES profiles(steam_id) ON DELETE CASCADE,
            appid INTEGER REFERENCES games(appid),
            minutes INTEGER,
            PRIMARY KEY (steam_id, appid));
        CREATE TABLE IF NOT EXISTS achievements (
            steam_id TEXT REFERENCES profiles(steam_id) ON DELETE CASCADE,
            appid INTEGER REFERENCES games(appid),
            unlocked INTEGER, total INTEGER, updated REAL,
            PRIMARY KEY (steam_id, appid));
        CREATE TABLE IF NOT EXISTS searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            steam_id_a TEXT, steam_id_b TEXT, shared_games INTEGER, searched REAL);
    """)
    conn.commit()
    conn.close()


def get_saved_profile(steam_id, max_age=CACHE_SECONDS):
    conn = get_connection()
    row = conn.execute("SELECT * FROM profiles WHERE steam_id = ?", (steam_id,)).fetchone()
    if row is None or time.time() - row["updated"] > max_age:
        conn.close()
        return None
    rows = conn.execute(
        "SELECT g.appid, g.name, g.icon, o.minutes FROM owned_games o "
        "JOIN games g ON g.appid = o.appid WHERE o.steam_id = ?", (steam_id,)).fetchall()
    conn.close()
    games = []
    for r in rows:
        games.append({"appid": r["appid"], "name": r["name"], "icon": r["icon"], "minutes": r["minutes"]})
    return {"steam_id": steam_id, "name": row["name"], "avatar": row["avatar"], "url": row["url"], "games": games}


def save_profile(profile, games):
    # one connection and one commit for the whole library (one per game was too slow and got locked)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO profiles (steam_id, name, avatar, url, updated) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(steam_id) DO UPDATE SET name=excluded.name, avatar=excluded.avatar, "
            "url=excluded.url, updated=excluded.updated",
            (profile["steam_id"], profile["name"], profile["avatar"], profile["url"], time.time()))
        game_rows = []
        owned_rows = []
        for g in games:
            game_rows.append((g["appid"], g["name"], g["icon"]))
            owned_rows.append((profile["steam_id"], g["appid"], g["minutes"]))
        conn.executemany(
            "INSERT INTO games (appid, name, icon) VALUES (?, ?, ?) "
            "ON CONFLICT(appid) DO UPDATE SET name=excluded.name, icon=excluded.icon", game_rows)
        conn.execute("DELETE FROM owned_games WHERE steam_id = ?", (profile["steam_id"],))
        conn.executemany("INSERT INTO owned_games (steam_id, appid, minutes) VALUES (?, ?, ?)", owned_rows)
        conn.commit()
    finally:
        conn.close()


def get_saved_achievements(steam_id, appids, max_age=CACHE_SECONDS):
    # returns {appid: (unlocked, total)}, a total of 0 means the game has no achievements
    saved = {}
    conn = get_connection()
    for appid in appids:
        row = conn.execute("SELECT unlocked, total, updated FROM achievements WHERE steam_id = ? AND appid = ?",
                           (steam_id, appid)).fetchone()
        if row is not None and time.time() - row["updated"] <= max_age:
            saved[appid] = (row["unlocked"], row["total"])
    conn.close()
    return saved


def save_achievements(steam_id, rows):
    # rows is a list of (appid, unlocked, total)
    conn = get_connection()
    try:
        conn.executemany(
            "INSERT INTO achievements (steam_id, appid, unlocked, total, updated) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(steam_id, appid) DO UPDATE SET unlocked=excluded.unlocked, "
            "total=excluded.total, updated=excluded.updated",
            [(steam_id, a, u, t, time.time()) for (a, u, t) in rows])
        conn.commit()
    finally:
        conn.close()


def save_search(steam_id_a, steam_id_b, shared_games):
    conn = get_connection()
    conn.execute("INSERT INTO searches (steam_id_a, steam_id_b, shared_games, searched) VALUES (?, ?, ?, ?)",
                 (steam_id_a, steam_id_b, shared_games, time.time()))
    conn.commit()
    conn.close()


def get_recent_searches(limit=8):
    # newest comparisons first, each pair of profiles only once
    conn = get_connection()
    rows = conn.execute(
        "SELECT s.steam_id_a, s.steam_id_b, s.shared_games, pa.name AS name_a, pb.name AS name_b "
        "FROM searches s JOIN profiles pa ON pa.steam_id = s.steam_id_a "
        "JOIN profiles pb ON pb.steam_id = s.steam_id_b ORDER BY s.id DESC LIMIT ?", (limit * 5,)).fetchall()
    conn.close()
    results = []
    seen = []
    for r in rows:
        pair = (r["steam_id_a"], r["steam_id_b"])
        if pair in seen:
            continue
        seen.append(pair)
        results.append(dict(r))
        if len(results) == limit:
            break
    return results


def get_recent_profiles(limit=8):
    conn = get_connection()
    rows = conn.execute(
        "SELECT p.steam_id, p.name, p.avatar, "
        "(SELECT COUNT(*) FROM owned_games o WHERE o.steam_id = p.steam_id) AS game_count "
        "FROM profiles p ORDER BY p.updated DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_popular_games(limit=8):
    # games owned by the most saved profiles, ties broken by total hours played
    conn = get_connection()
    rows = conn.execute(
        "SELECT g.appid, g.name, g.icon, COUNT(*) AS owners, SUM(o.minutes) AS minutes "
        "FROM owned_games o JOIN games g ON g.appid = o.appid "
        "GROUP BY g.appid ORDER BY owners DESC, minutes DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
