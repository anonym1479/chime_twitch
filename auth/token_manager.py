import os
import json
import requests


class BroadcasterTokenManager:

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.config_path = "data/config.json"

    def refresh_all(self):
        """Refresh every broadcaster token stored in config.json."""

        if not os.path.exists(self.config_path):
            print("No config.json found.")
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        changed = False

        for channel in config.get("channels", []):

            refresh_token = channel.get("refresh_token")

            if not refresh_token:
                continue

            print(f"Refreshing {channel['username']}...")

            response = requests.post(
                "https://id.twitch.tv/oauth2/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                timeout=10,
            )

            if response.status_code != 200:
                print(
                    f"❌ Failed to refresh {channel['username']}: "
                    f"{response.status_code}"
                )
                print(response.text)
                continue

            token_data = response.json()

            channel["access_token"] = token_data["access_token"]

            if "refresh_token" in token_data:
                channel["refresh_token"] = token_data["refresh_token"]

            changed = True

            print(f"✅ Refreshed {channel['username']}")

        if changed:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)

            print("\nSaved updated broadcaster tokens.")

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    manager = BroadcasterTokenManager(
        os.getenv("TWITCH_CLIENT_ID"),
        os.getenv("TWITCH_CLIENT_SECRET"),
    )

    manager.refresh_all()