# SteamScope

Compares two public Steam profiles — hours played, owned games, shared games,
and achievement completion — on one dashboard. Built to match the project
proposal: Flask + SQLite backend, Steam Web API for data, Chart.js for charts.

## Setup

```bash
cd steamscope
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Get a free Steam Web API key at <https://steamcommunity.com/dev/apikey>
(you need a Steam account with a purchase on it to register one), then:

```bash
cp .env.example .env
# edit .env and paste your key in place of your_steam_web_api_key_here
```

Run it:

```bash
python app.py
```

Open <http://127.0.0.1:5000>. Enter two SteamID64s, full profile URLs
(`https://steamcommunity.com/id/...` or `.../profiles/...`), or vanity
names, and press Compare.

Both profiles need **Game details** set to public in Steam privacy settings
(Steam → Profile → Edit Profile → Privacy Settings) for a full comparison —
otherwise SteamScope shows a "profile is private" message and falls back to
any data cached from a previous sync.

## Project structure

```
app.py            routes + comparison logic
steam_api.py       Steam Web API wrapper (auth, vanity URL resolution,
                    private-profile detection)
db.py              SQLite access layer
config.py          loads STEAM_API_KEY from .env
schema.sql         database schema (matches the proposal's ERD)
templates/         index.html (search), comparison.html (dashboard),
                    about.html
static/css/        design system
```

## Notes

- `owned_games` and `games` rows are cached on every successful sync, so a
  repeat comparison — or a profile that's gone private since the last
  visit — can still show its last known data.
- Achievement lookups (`GetPlayerAchievements`) are one HTTP call per game,
  so they're capped to each pair's `MAX_ACHIEVEMENT_LOOKUPS` (default 12)
  most-played shared games — tune this in `config.py`.
- This is a prototype, not a Steam replacement: no login system, no
  purchasing, no messaging. See `/about` in the running app.
