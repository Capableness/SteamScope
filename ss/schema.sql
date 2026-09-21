-- SteamScope database schema
-- Matches Figure 1 in the project proposal (5 tables).
-- USERS and STEAM_PROFILES are kept separate so one account could later
-- link multiple Steam profiles, even though this prototype doesn't require login.

CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT UNIQUE,
    password_hash TEXT,
    display_name  TEXT,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS steam_profiles (
    profile_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    steam_id    TEXT UNIQUE NOT NULL,
    profile_url TEXT,
    last_synced TEXT,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

CREATE TABLE IF NOT EXISTS games (
    game_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id          INTEGER UNIQUE NOT NULL,
    title           TEXT,
    genre           TEXT,
    header_image_url TEXT
);

CREATE TABLE IF NOT EXISTS owned_games (
    owned_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id            INTEGER NOT NULL,
    game_id               INTEGER NOT NULL,
    hours_played          REAL DEFAULT 0,
    achievements_unlocked INTEGER,
    achievements_total    INTEGER,
    FOREIGN KEY (profile_id) REFERENCES steam_profiles (profile_id),
    FOREIGN KEY (game_id) REFERENCES games (game_id),
    UNIQUE (profile_id, game_id)
);

CREATE TABLE IF NOT EXISTS comparisons (
    comparison_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id_a        INTEGER NOT NULL,
    profile_id_b        INTEGER NOT NULL,
    shared_games_count  INTEGER,
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (profile_id_a) REFERENCES steam_profiles (profile_id),
    FOREIGN KEY (profile_id_b) REFERENCES steam_profiles (profile_id)
);

CREATE INDEX IF NOT EXISTS idx_owned_profile_game ON owned_games (profile_id, game_id);
CREATE INDEX IF NOT EXISTS idx_comparisons_pair ON comparisons (profile_id_a, profile_id_b);
