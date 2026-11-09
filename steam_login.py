# "Sign in through Steam" using Steam's OpenID. Steam checks the password, we only get the Steam id back.
import re
import requests
from urllib.parse import urlencode
from steam import SteamError

LOGIN_URL = "https://steamcommunity.com/openid/login"
OPENID = "http://specs.openid.net/auth/2.0"


def get_login_url(return_url, site_url):
    params = {
        "openid.ns": OPENID,
        "openid.mode": "checkid_setup",
        "openid.return_to": return_url,
        "openid.realm": site_url,
        "openid.identity": OPENID + "/identifier_select",
        "openid.claimed_id": OPENID + "/identifier_select",
    }
    return LOGIN_URL + "?" + urlencode(params)


def check_login(args, return_url):
    # args is what Steam put in the address when it sent the person back
    if args.get("openid.mode") == "cancel":
        raise SteamError("Sign in was cancelled.", 401)
    if args.get("openid.mode") != "id_res" or args.get("openid.op_endpoint") != LOGIN_URL:
        raise SteamError("That did not look like a reply from Steam. Try signing in again.", 401)
    if args.get("openid.return_to") != return_url:
        raise SteamError("That sign in was meant for a different site. Try again.", 401)
    claimed = args.get("openid.claimed_id", "")
    match = re.fullmatch(r"https://steamcommunity\.com/openid/id/(\d{17})", claimed)
    if not match or args.get("openid.identity") != claimed:
        raise SteamError("Steam did not return a valid profile. Try again.", 401)

    # ask Steam to confirm it really sent this reply
    check = {}
    for key in args:
        if key.startswith("openid."):
            check[key] = args[key]
    check["openid.mode"] = "check_authentication"
    try:
        reply = requests.post(LOGIN_URL, data=check, timeout=10)
    except requests.RequestException:
        raise SteamError("Could not reach Steam to confirm the sign in. Try again.", 503)
    if reply.status_code != 200 or "is_valid:true" not in reply.text.splitlines():
        raise SteamError("Steam could not confirm that sign in. Try again.", 401)
    return match.group(1)
