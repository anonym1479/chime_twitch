import aiohttp


class PinService:

    def __init__(self, client_id, token, bot_id):
        self.client_id = client_id
        self.token = token.replace("oauth:", "")
        self.bot_id = bot_id

    async def set_pin_status(self, broadcaster_id, message_id, pin_status=True):
        """Sets or unsets the pin status of a message using async aiohttp."""
        url = "https://api.twitch.tv/helix/chat/pins"
        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        body = {
            "broadcaster_id": broadcaster_id,
            "moderator_id": self.bot_id,
            "message_id": message_id,
            "is_pinned": pin_status,
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.put(
                    url, headers=headers, json=body
                ) as response:
                    response_text = await response.text()
                    if response.status in [200, 204]:
                        return True
                    else:
                        print(
                            f"[PIN ERROR] Failed ({response.status}): {response_text}"
                        )
                        print(
                            f"-> Broadcaster: {broadcaster_id}, Moderator (Bot ID): {self.bot_id}"
                        )
                        return False
            except Exception as e:
                print(f"Error in PinService.set_pin_status: {e}")
                return False