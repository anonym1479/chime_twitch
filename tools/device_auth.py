import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

client_id = os.getenv("TWITCH_CLIENT_ID")
if not client_id:
    print("Hiba: A TWITCH_CLIENT_ID hiányzik a .env fájrból!")
    exit()

scopes = "chat:read chat:edit user:write:chat channel:moderate moderator:manage:chat_messages"

# 1. Request a device code from Twitch
print("Getting code from Twitch...")
res = requests.post(
    "https://id.twitch.tv/oauth2/device",
    data={
        "client_id": client_id,
        "scopes": scopes
    }
).json()

if "device_code" not in res:
    print("An error occurred:", res)
    exit()

device_code = res["device_code"]
user_code = res["user_code"]
verification_uri = res["verification_uri"]
interval = res.get("interval", 5)

print("\n" + "="*60)
print(" TWITCH DEVICE-BASED AUTHENTICATION")
print("="*60)
print(f"1. Open this link on your phone or in your browser:")
print(f"   {verification_uri}")
print(f"2. Add the following code: {user_code}")
print(f"3. Sign in with your bot account and approve the request.")
print("="*60 + "\n")
print("Waiting for approval...")

# 2. Replacement (Waiting for the user to approve in the browser)
token_url = "https://id.twitch.tv/oauth2/token"
payload = {
    "client_id": client_id,
    "device_code": device_code,
    "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
}

while True:
    time.sleep(interval)
    response = requests.post(token_url, data=payload)
    data = response.json()
    
    if "access_token" in data:
        access_token = data["access_token"]
        refresh_token = data.get("refresh_token", "")
        
        # Retrieving bot data via the Helix API
        headers = {
            "Client-ID": client_id,
            "Authorization": f"Bearer {access_token}"
        }
        user_res = requests.get("https://api.twitch.tv/helix/users", headers=headers).json()
        bot_id = user_res["data"][0]["id"]
        bot_username = user_res["data"][0]["login"]
        client_secret = os.getenv("TWITCH_CLIENT_SECRET", "")

        # Update .env file with correct user token
        env_content = f"""TWITCH_TOKEN=oauth:{access_token}
                        TWITCH_REFRESH_TOKEN={refresh_token}
                        TWITCH_CLIENT_ID={client_id}
                        TWITCH_CLIENT_SECRET={client_secret}
                        TWITCH_BOT_ID={bot_id}
                        TWITCH_BOT_USERNAME={bot_username}
                        """

        with open(".env", "w", encoding="utf-8") as f:
            f.write(env_content)

        print(f"\n[SUCCESS] Authentication complete! Bot: {bot_username} (ID: {bot_id})")
        break
    elif data.get("error") == "authorization_pending":
        print(".", end="", flush=True)
    elif data.get("error") in ["expired_token", "access_denied"]:
        print(f"\n[ERROR] Authentication failed: {data.get('error')}.")
        break