import json

with open("config.json", "r", encoding="utf-8") as file:
    config = json.load(file)

# List of all channels for TwitchIO to join
CHANNELS = config.get("channels", [])
CHANNEL_USERNAMES = [ch["username"] for ch in CHANNELS]
CHANNEL_MAP = {ch["username"]: ch["user_id"] for ch in CHANNELS}