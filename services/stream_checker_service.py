import asyncio
import json
import os
import aiohttp
from services.twitch_api import TwitchAPI

class StreamCheckerService:
    def __init__(self, chat_service, pin_service, trigger_service, channels_config):
        client_id = os.getenv("TWITCH_CLIENT_ID")
        client_secret = os.getenv("TWITCH_CLIENT_SECRET")
        
        self.twitch_api = TwitchAPI(client_id, client_secret)
        self.chat_service = chat_service
        self.pin_service = pin_service
        self.trigger_service = trigger_service
        self.channels_config = channels_config
        self.state_file = "data/pin_states.json"
        self.states = self._load_states()

    def _load_states(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_states(self):
        os.makedirs("data", exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.states, f, indent=4)

    async def start_checking(self, loop):
        """Indítja a háttérben futó ciklust, amely 60 másodpercenként ellenőrzi a címeket."""
        while True:
            await self.check_all_channels()
            await asyncio.sleep(60)

    async def check_all_channels(self):
        usernames = [ch["username"] for ch in self.channels_config]
        
        async with aiohttp.ClientSession() as session:
            try:
                active_streams = await self.twitch_api.get_streams(session, usernames)
            except Exception as e:
                print(f"[CHECKER ERROR] Failed to fetch streams: {e}")
                return

            for ch in self.channels_config:
                username = ch["username"].lower()
                broadcaster_id = ch["user_id"]

                stream = active_streams.get(username)
                channel_state = self.states.get(str(broadcaster_id), {"active": False, "message_id": None})

                if stream:
                    title = stream.get("title", "")
                    trigger = self.trigger_service.check(username, title)

                    if trigger:
                        if not channel_state["active"]:
                            message_text = trigger["message"]
                            result = await self.chat_service.send_message(broadcaster_id, message_text)
                            try:
                                message_id = result["data"][0]["message_id"]
                                success = await self.pin_service.set_pin_status(broadcaster_id, message_id, pin_status=True)
                                if success:
                                    self.states[str(broadcaster_id)] = {
                                    "active": True,
                                    "message_id": message_id
                                }
                                    self._save_states()
                                    print(f"[{username}] Trigger matched. Message pinned successfully.")
                            except (KeyError, IndexError, TypeError) as e:
                                print(f"Error pinning message automatically for {username}: {e}")
                    else:
                        if channel_state["active"] and channel_state["message_id"]:
                            message_id = channel_state["message_id"]
                            success = await self.pin_service.set_pin_status(broadcaster_id, message_id, pin_status=False)
                            if success:
                                print(f"[{username}] Trigger removed from title. Pin removed successfully.")
                            
                            self.states[str(broadcaster_id)] = {
                                "active": False,
                                "message_id": None
                            }
                            self._save_states()
                else:
                    if channel_state["active"]:
                        self.states[str(broadcaster_id)] = {
                            "active": False,
                            "message_id": None
                        }
                        self._save_states()