import os
import requests
from dotenv import load_dotenv

load_dotenv()

client_id = os.getenv("TWITCH_CLIENT_ID")
client_secret = os.getenv("TWITCH_CLIENT_SECRET")

if not client_id or not client_secret:
    print("Error: Please enter TWITCH_CLIENT_ID and CLIENT_SECRET in the .env file first!")
    exit()

redirect_uri = "http://localhost"
scopes = "chat:read chat:edit user:write:chat channel:moderate"

auth_url = (
    f"https://id.twitch.tv/oauth2/authorize?"
    f"client_id={client_id}&"
    f"redirect_uri={redirect_uri}&"
    f"response_type=code&"
    f"scope={scopes.replace(' ', '+')}"
)

print("\n" + "="*60)
print(" TWITCH OAUTH AUTHENTICATION (Code-based)")
print("="*60)
print("1. Open the following link in your browser:")
print(f"\n{auth_url}\n")
print("2. Sign in with your bot account and click on 'Authorize'.")
print("3. The page will redirect to a URL that starts with: http://localhost/?code=VALAMI")
print("   (If your browser says the page cannot be found, that's COMPLETELY NORMAL!)")
print("4. Copy the entire URL or just the 'code=' part after it, and paste it below.")
print("="*60 + "\n")

code_input = input("Paste the full redirected URL OR just the code: ").strip()

# If you entered the full URL, extract the code parameter from it.
if "code=" in code_input:
    try:
        code = code_input.split("code=")[1].split("&")[0]
    except IndexError:
        code = code_input
else:
    code = code_input

if not code:
    print("Error: You didn't provide a code!")
    exit()

print("\nFetching tokens from Twitch...")

token_url = "https://id.twitch.tv/oauth2/token"
payload = {
    "client_id": client_id,
    "client_secret": client_secret,
    "code": code,
    "grant_type": "authorization_code",
    "redirect_uri": redirect_uri
}

response = requests.post(token_url, data=payload)
data = response.json()

if "access_token" in data:
    access_token = data["access_token"]
    refresh_token = data.get("refresh_token", "")
    
    # We also request the bot's user ID for security reasons.
    headers = {
        "Client-ID": client_id,
        "Authorization": f"Bearer {access_token}"
    }
    user_res = requests.get("https://api.twitch.tv/helix/users", headers=headers).json()
    bot_id = user_res["data"][0]["id"]
    bot_username = user_res["data"][0]["login"]

    # We update/write the .env file
    env_content = f"""TWITCH_TOKEN=oauth:{access_token}
    TWITCH_REFRESH_TOKEN={refresh_token}
    TWITCH_CLIENT_ID={client_id}
    TWITCH_CLIENT_SECRET={client_secret}
    TWITCH_BOT_ID={bot_id}
    TWITCH_BOT_USERNAME={bot_username}
    """

    with open(".env", "w", encoding="utf-8") as f:
        f.write(env_content)

    print("\n[SUCCESS] Tokens successfully saved to the .env file!")
    print(f"Bot account: {bot_username} (ID: {bot_id})")
else:
    print(f"\nError occurred while fetching tokens: {data}")