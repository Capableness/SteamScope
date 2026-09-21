import os
from pathlib import Path

# Minimal .env loader so this stays dependency-free (no python-dotenv required).
_ENV_PATH = Path(__file__).parent / ".env"
if _ENV_PATH.exists():
    for line in _ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

STEAM_API_KEY = os.environ.get("STEAM_API_KEY", "")

# How many of a profile's most-played shared games get per-game achievement
# calls. GetPlayerAchievements is one HTTP call per game, so this keeps a
# comparison fast; Section 3.2 notes achievement comparison is the most
# complex feature, and this cap is what keeps it demonstrable within scope.
MAX_ACHIEVEMENT_LOOKUPS = 12
