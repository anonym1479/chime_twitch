import os
import requests
from dotenv import load_dotenv, set_key
from bot import bot

load_dotenv()


def refresh_twitch_token_if_needed():
    client_id = os.getenv("TWITCH_CLIENT_ID")
    client_secret = os.getenv("TWITCH_CLIENT_SECRET")
    refresh_token = os.getenv("TWITCH_REFRESH_TOKEN")

    if not refresh_token:
        print("[WARNING] No TWITCH_REFRESH_TOKEN in .env!")
        return

    print("Checking/Refreshing Twitch Token...")
    url = "https://id.twitch.tv/oauth2/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    response = requests.post(url, data=payload)
    if response.status_code == 200:
        data = response.json()
        new_access = data["access_token"]
        new_refresh = data.get("refresh_token", refresh_token)

        set_key(".env", "TWITCH_TOKEN", f"oauth:{new_access}")
        set_key(".env", "TWITCH_REFRESH_TOKEN", new_refresh)
        print("[SUCCESS] Twitch token was automatically updated on launch!")
    else:
        print(f"[WARNING] Failed to refresh token: {response.text}")


if __name__ == "__main__":
    refresh_twitch_token_if_needed()
    bot.run()