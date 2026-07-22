import requests


class ChatService:
    def __init__(self, client_id, token, bot_id):
        self.client_id = client_id
        self.token = token.replace("oauth:", "")
        self.bot_id = bot_id

    async def send_message(self, broadcaster_id, message):
        """Sends a chat message to a specific broadcaster's channel."""
        url = "https://api.twitch.tv/helix/chat/messages"
        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        body = {
            "broadcaster_id": broadcaster_id,
            "sender_id": self.bot_id,
            "message": message,
        }
        try:
            response = requests.post(url, headers=headers, json=body)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Failed to send chat message: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"Error in ChatService.send_message: {e}")
            return None