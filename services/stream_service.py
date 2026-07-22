from services.twitch_api import TwitchAPI


class StreamService:
    def __init__(self, client_id, app_token):
        self.twitch_api = TwitchAPI(client_id, app_token)

    async def get_stream_for_broadcaster(self, broadcaster_id):
        """Fetches and returns the current stream information for a specific broadcaster ID if live, otherwise None."""
        try:
            stream = await self.twitch_api.get_stream(broadcaster_id)
            return stream
        except Exception as e:
            print(f"Error fetching stream data for broadcaster {broadcaster_id}: {e}")
            return None