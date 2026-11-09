# SteamScope

A website that compares two Steam profiles: shared games, hours played, games owned and achievement completion, with charts.

## User guide

** Compare two people**
1. Type two profiles. A profile link, a custom name (the part after `/id/`) or a 17 digit Steam ID all work.
2. Click **Compare**. The first search for a big library can take up to 15 seconds.
3. Read the table (the higher number in each row is bold), the two charts, the shared games list and the news.

Optional: **Sign in through Steam** fills in your own profile as the first player. This only works on a site that is online (see Deploying).

**If something goes wrong**
| Message | What to do |
|---|---|
| game details are private | On Steam: Edit Profile > Privacy Settings > Game details > Public. Wait a minute. |
| No Steam profile found | Check the spelling or paste the full profile link. |
| Steam is busy or limiting requests | Wait a minute and try again. |
| no Steam API key / key rejected | Check `steam_key.txt` contains only the key, then restart the site. |

Notes: achievements are checked for the 12 most played shared games only (Steam needs one request per game). Data is saved for 6 hours so repeat searches are quick.

## For developers
- `app.py` pages and comparison logic, `steam.py` Steam API calls, `steam_login.py` sign in, `database.py` SQLite (WAL mode, one transaction per library save).