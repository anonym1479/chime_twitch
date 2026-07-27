import os
import json
import time
import requests

from dotenv import load_dotenv
from auth.scopes import SCOPES_STRING

load_dotenv()

CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

def authenticate():
    if not CLIENT_ID:
        print("❌ Error: TWITCH_CLIENT_ID not found in your environment or .env file.")
        return

    target_username = input("Enter the Twitch broadcaster username to authorize: ").strip()
    if not target_username:
        print("❌ Username cannot be empty.")
        return

    print("Requesting device authorization code from Twitch...")
    res = requests.post(
        "https://id.twitch.tv/oauth2/device",
        data={
            "client_id": CLIENT_ID,
            "scopes": SCOPES_STRING
        }
    )

    if res.status_code != 200:
        print(f"❌ Failed to start device auth: {res.status_code} - {res.text}")
        return

    data = res.json()
    device_code = data["device_code"]
    user_code = data["user_code"]
    verification_uri = data["verification_uri"]
    interval = data.get("interval", 5)
    expires_in = data.get("expires_in", 1800)

    print("\n" + "=" * 55)
    print(f"1. Open your browser and go to: {verification_uri}")
    print(f"2. Enter this code:             {user_code}")
    print("=" * 55 + "\n")
    print("Waiting for you to authorize in your browser", end="", flush=True)

    start_time = time.time()
    while time.time() - start_time < expires_in:
        time.sleep(interval)
        print(".", end="", flush=True)
        
        token_res = requests.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
            }
        )

        if token_res.status_code == 200:
            token_data = token_res.json()
            access_token = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token")
            
            print("\n\n[SUCCESS] Successfully authorized!")
            update_config_channel(target_username, access_token, refresh_token)
            return
        
        err_data = token_res.json()
        error = err_data.get("error")
        message = err_data.get("message")
        
        # Safely handle pending and slow down status responses
        if error == "authorization_pending" or message == "authorization_pending":
            continue
        elif error == "slow_down" or message == "slow_down":
            interval += 5
            continue
        elif error == "expired_token":
            print("\n❌ The device code has expired. Please run the script again.")
            break
        elif error == "access_denied":
            print("\n❌ Authorization was denied.")
            break
        else:
            print(f"\n❌ Unexpected error: {error} - {message}")
            break

def update_config_channel(username, access_token, refresh_token):
    config_path = "data/config.json"
    if not os.path.exists(config_path):
        print("⚠️ data/config.json not found, saving to .env instead.")
        env_path = ".env"
        with open(env_path, "a") as f:
            f.write(f"\nTWITCH_ACCESS_TOKEN={access_token}\nTWITCH_REFRESH_TOKEN={refresh_token}\n")
        print("Tokens appended to .env file.")
        return

    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)

    updated = False
    for ch in config_data.get("channels", []):
        if ch["username"].lower() == username.lower():
            ch["access_token"] = access_token
            ch["refresh_token"] = refresh_token
            updated = True
            break

    if updated:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)
        print(f"[SUCCESS] Saved tokens for {username} directly into data/config.json!")
    else:
        print(f"⚠️ Channel {username} not found in config.json channels list. Appending to .env instead.")
        env_path = ".env"
        with open(env_path, "a") as f:
            f.write(f"\nTWITCH_ACCESS_TOKEN={access_token}\nTWITCH_REFRESH_TOKEN={refresh_token}\n")

def validate_token(token):
    headers = {
        "Authorization": f"OAuth {token}"
    }

    res = requests.get(
        "https://id.twitch.tv/oauth2/validate",
        headers=headers
    )

    print(res.json())

if __name__ == "__main__":
    authenticate()