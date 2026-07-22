import aiohttp


class TwitchAPI:

    def __init__(self, client_id, token):
        self.client_id = client_id
        self.token = token

    async def get_stream(self, broadcaster_id):
        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {self.token}"
        }
        url = (
            "https://api.twitch.tv/helix/streams"
            f"?user_id={broadcaster_id}"
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers
            ) as response:
                data = await response.json()
                if not data.get("data"):
                    return None
                return data["data"][0]