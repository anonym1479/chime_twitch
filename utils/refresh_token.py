import os
import requests
from dotenv import set_key

def _refresh_token_sync():
    """Synchronous token update logic."""
    client_id = os.getenv("TWITCH_CLIENT_ID")
    client_secret = os.getenv("TWITCH_CLIENT_SECRET")
    refresh_token = os.getenv("TWITCH_REFRESH_TOKEN")

    if not refresh_token:
        print("[WARNING] No TWITCH_REFRESH_TOKEN in .env!")
        return False

    url = "https://id.twitch.tv/oauth2/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    try:
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code == 200:
            data = response.json()
            new_access = data["access_token"]
            new_refresh = data.get("refresh_token", refresh_token)

            set_key(".env", "TWITCH_TOKEN", f"oauth:{new_access}")
            set_key(".env", "TWITCH_REFRESH_TOKEN", new_refresh)
            return True
        else:
            print(f"[WARNING] Failed to refresh token: {response.text}")
            return False
    except Exception as e:
        print(f"[ERROR] Exception during token refresh: {e}")
        return False