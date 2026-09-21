"""
db.py — SQLite access layer for SteamScope.

Keeps every query in one place so app.py stays focused on routing/logic.
Uses row factory so rows behave like dicts (row["column"]).
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "steamscope.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection():
    # timeout: how long a connection waits for a lock held by another
    # connection before raising "database is locked", instead of failing
    # immediately (the default is effectively 5s but Windows + antivirus
    # scanning the file can make that too tight).
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets reads happen while a write is in progress, so the search
    # page / other requests don't queue up behind a sync.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db():
    """Create tables if they don't exist yet. Safe to call on every startup."""
    conn = get_connection()
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


def upsert_profile(steam_id: str, profile_url: str, last_synced: str) -> int:
    """Insert a steam_profiles row if new, else refresh last_synced. Returns profile_id."""
    conn = get_connection()
    cur = conn.execute("SELECT profile_id FROM steam_profiles WHERE steam_id = ?", (steam_id,))
    row = cur.fetchone()
    if row:
        profile_id = row["profile_id"]
        conn.execute(
            "UPDATE steam_profiles SET profile_url = ?, last_synced = ? WHERE profile_id = ?",
            (profile_url, last_synced, profile_id),
        )
    else:
        cur = conn.execute(
            "INSERT INTO steam_profiles (steam_id, profile_url, last_synced) VALUES (?, ?, ?)",
            (steam_id, profile_url, last_synced),
        )
        profile_id = cur.lastrowid
    conn.commit()
    conn.close()
    return profile_id


def upsert_game(app_id: int, title: str, header_image_url: str, genre: str = None) -> int:
    conn = get_connection()
    cur = conn.execute("SELECT game_id FROM games WHERE app_id = ?", (app_id,))
    row = cur.fetchone()
    if row:
        game_id = row["game_id"]
        conn.execute(
            "UPDATE games SET title = ?, header_image_url = ? WHERE game_id = ?",
            (title, header_image_url, game_id),
        )
    else:
        cur = conn.execute(
            "INSERT INTO games (app_id, title, genre, header_image_url) VALUES (?, ?, ?, ?)",
            (app_id, title, genre, header_image_url),
        )
        game_id = cur.lastrowid
    conn.commit()
    conn.close()
    return game_id


def upsert_owned_game(profile_id: int, game_id: int, hours_played: float,
                       achievements_unlocked, achievements_total):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO owned_games (profile_id, game_id, hours_played, achievements_unlocked, achievements_total)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(profile_id, game_id) DO UPDATE SET
            hours_played = excluded.hours_played,
            achievements_unlocked = excluded.achievements_unlocked,
            achievements_total = excluded.achievements_total
        """,
        (profile_id, game_id, hours_played, achievements_unlocked, achievements_total),
    )
    conn.commit()
    conn.close()


def sync_owned_games(profile_id: int, games: list) -> dict:
    """
    Write an entire owned-games library in ONE connection/transaction instead
    of one connect+commit+close per game. `games` is a list of dicts with
    app_id, title, header_image_url, hours_played. Returns {app_id: game_id}.
    This is what keeps a big library (100s of games) from being slow and
    from tripping SQLite's "database is locked" error under load.
    """
    conn = get_connection()
    game_id_by_app_id = {}
    try:
        for g in games:
            cur = conn.execute("SELECT game_id FROM games WHERE app_id = ?", (g["app_id"],))
            row = cur.fetchone()
            if row:
                game_id = row["game_id"]
                conn.execute(
                    "UPDATE games SET title = ?, header_image_url = ? WHERE game_id = ?",
                    (g["title"], g["header_image_url"], game_id),
                )
            else:
                cur = conn.execute(
                    "INSERT INTO games (app_id, title, header_image_url) VALUES (?, ?, ?)",
                    (g["app_id"], g["title"], g["header_image_url"]),
                )
                game_id = cur.lastrowid
            game_id_by_app_id[g["app_id"]] = game_id

            conn.execute(
                """
                INSERT INTO owned_games (profile_id, game_id, hours_played, achievements_unlocked, achievements_total)
                VALUES (?, ?, ?, NULL, NULL)
                ON CONFLICT(profile_id, game_id) DO UPDATE SET hours_played = excluded.hours_played
                """,
                (profile_id, game_id, g["hours_played"]),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return game_id_by_app_id


def record_comparison(profile_id_a: int, profile_id_b: int, shared_games_count: int) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO comparisons (profile_id_a, profile_id_b, shared_games_count) VALUES (?, ?, ?)",
        (profile_id_a, profile_id_b, shared_games_count),
    )
    conn.commit()
    comparison_id = cur.lastrowid
    conn.close()
    return comparison_id


def get_cached_owned_games(profile_id: int):
    """Return cached owned_games + games rows for a profile, used when the API is unavailable."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT g.app_id, g.title, g.header_image_url, og.hours_played,
               og.achievements_unlocked, og.achievements_total
        FROM owned_games og JOIN games g ON g.game_id = og.game_id
        WHERE og.profile_id = ?
        """,
        (profile_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def recent_comparisons(limit: int = 10):
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT c.comparison_id, c.shared_games_count, c.created_at,
               pa.steam_id AS steam_id_a, pb.steam_id AS steam_id_b
        FROM comparisons c
        JOIN steam_profiles pa ON pa.profile_id = c.profile_id_a
        JOIN steam_profiles pb ON pb.profile_id = c.profile_id_b
        ORDER BY c.created_at DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
