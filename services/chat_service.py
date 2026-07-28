import os
import token
import aiohttp

from dotenv import load_dotenv

load_dotenv(override=True)

class ChatService:
    def __init__(self, client_id: str, bot_user_id: str):
        self.client_id = client_id
        self.bot_user_id = bot_user_id

    async def send_message(self, broadcaster_id: str, message: str):
        """Sends a chat message via Twitch Helix API using the bot's User Access Token."""
        try:
            raw_token = os.getenv("TWITCH_TOKEN", "")
            token = raw_token.replace("oauth:", "") if raw_token else ""            
            
            if not token:
                print("❌ Error: TWITCH_TOKEN is missing or empty for sending chat message!")
                return None

            url = "https://api.twitch.tv/helix/chat/messages"

            headers = {
                "Client-Id": self.client_id,
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            payload = {
                "broadcaster_id": str(broadcaster_id),
                "sender_id": str(self.bot_user_id),
                "message": message
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        error_text = await response.text()
                        print(f"❌ Error sending chat message: {response.status} - {error_text}")
                        return None
        except Exception as e:
            print(f"❌ Exception during sending chat message: {e}")
            return None