import os
import time
import aiohttp
from datetime import datetime, timezone

class CommandRouter:
    def __init__(self, chat_service, pin_service, trigger_service, channels_config):
        self.chat_service = chat_service
        self.pin_service = pin_service
        self.trigger_service = trigger_service
        self.channels_config = channels_config

    def _get_broadcaster_id_by_username(self, username: str):
        for ch in self.channels_config:
            if ch["username"].lower() == username.lower():
                return ch["user_id"]
        return None

    def _parse_badges(self, event: dict) -> dict:
        """Parses badges from EventSub channel.chat.message payload."""
        badges = event.get("badges", [])
        result = {}
        for badge in badges:
            set_id = badge.get("set_id")
            badge_id = badge.get("id")
            if set_id:
                result[set_id] = badge_id
        return result

    def _is_authorized(self, event: dict, level: str) -> bool:
        """Evaluates hierarchical permissions using EventSub metadata."""
        broadcaster_id = event.get("broadcaster_user_id")
        chatter_id = event.get("chatter_user_id")
        is_broadcaster = chatter_id == broadcaster_id

        badges = self._parse_badges(event)
        is_mod = is_broadcaster or "moderator" in badges or "lead_moderator" in badges or "staff" in badges or "admin" in badges
        is_vip = is_mod or "vip" in badges
        is_sub = is_vip or "subscriber" in badges or "founder" in badges

        if level == "lead_mod":
            return is_broadcaster or "lead_moderator" in badges or "staff" in badges or "admin" in badges
        elif level == "mod":
            return is_mod
        elif level == "vip":
            return is_vip
        elif level == "sub":
            return is_sub
        return True

    async def handle_command(self, event: dict):
        message_text = event.get("message", {}).get("text", "")
        if not message_text.startswith("_"):
            return

        channel_name = event.get("broadcaster_user_login", "").lower()
        chatter_name = event.get("chatter_user_login", "")
        broadcaster_id = event.get("broadcaster_user_id")

        print(f"[{channel_name}] {chatter_name}: {message_text}")

        parts = message_text[1:].strip().split(" ")
        cmd = parts[0].lower()
        args = parts[1:]

        # --- COMMANDS ---

        if cmd == "test":
            if not self._is_authorized(event, "mod"):
                await self.chat_service.send_message(broadcaster_id, f"@{chatter_name} ❌ This command requires moderator permissions!")
                return
            await self.chat_service.send_message(broadcaster_id, "Test was successful 🟢")

        elif cmd == "testlead":
            if not self._is_authorized(event, "lead_mod"):
                await self.chat_service.send_message(broadcaster_id, f"@{chatter_name} ❌ This command requires lead moderator permissions!")
                return
            await self.chat_service.send_message(broadcaster_id, f"@{chatter_name} ✅ You are a lead moderator or the streamer!")

        elif cmd == "testmod":
            if not self._is_authorized(event, "mod"):
                await self.chat_service.send_message(broadcaster_id, f"@{chatter_name} ❌ This command requires moderator permissions!")
                return
            await self.chat_service.send_message(broadcaster_id, f"@{chatter_name} ✅ You are a moderator!")

        elif cmd == "testvip":
            if not self._is_authorized(event, "vip"):
                await self.chat_service.send_message(broadcaster_id, f"@{chatter_name} ❌ This command requires VIP permissions!")
                return
            await self.chat_service.send_message(broadcaster_id, f"@{chatter_name} ✅ You are a VIP!")

        elif cmd == "testsub":
            if not self._is_authorized(event, "sub"):
                await self.chat_service.send_message(broadcaster_id, f"@{chatter_name} ❌ This command requires subscriber permissions!")
                return
            await self.chat_service.send_message(broadcaster_id, f"@{chatter_name} ✅ You are a subscriber!")

        elif cmd == "pin":
            if not self._is_authorized(event, "mod"):
                await self.chat_service.send_message(broadcaster_id, f"@{chatter_name} ❌ This command requires moderator permissions!")
                return
            result = await self.chat_service.send_message(broadcaster_id, "📌 This is a test pin message!")
            try:
                message_id = result["data"][0]["message_id"]
                await self.pin_service.set_pin_status(broadcaster_id, message_id, pin_status=True)
            except (KeyError, IndexError, TypeError) as e:
                print(f"Error pinning via command: {e}")

        elif cmd == "checktitle":
            if not self._is_authorized(event, "lead_mod"):
                await self.chat_service.send_message(broadcaster_id, f"@{chatter_name} ❌ This command requires lead moderator permissions!")
                return
            
            custom_title = " ".join(args) if args else None
            client_id = os.getenv("TWITCH_CLIENT_ID")
            client_secret = os.getenv("TWITCH_CLIENT_SECRET")
            from services.twitch_api import TwitchAPI
            twitch_api = TwitchAPI(client_id, client_secret)

            if not custom_title:
                async with aiohttp.ClientSession() as session:
                    stream = await twitch_api.get_stream(session, channel_name)
                    if not stream:
                        await self.chat_service.send_message(broadcaster_id, "Stream is currently offline or not found.")
                        return
                custom_title = stream.get("title", "")

            print(f"[{channel_name}] Stream title: {custom_title}")
            await self.chat_service.send_message(broadcaster_id, f"Stream title: {custom_title}")

            trigger = self.trigger_service.check(channel_name, custom_title)
            if trigger:
                print(f"[{channel_name}] Trigger matched: {trigger['message']}")
                await self.chat_service.send_message(broadcaster_id, f"trigger matched:\n{trigger['message']}")
            else:
                print(f"[{channel_name}] No trigger found.")
                await self.chat_service.send_message(broadcaster_id, "No trigger found.")

        elif cmd in ["online", "jelen"]:
            await self.chat_service.send_message(broadcaster_id, "I'm here!")

        elif cmd == "uptime":            
            client_id = os.getenv("TWITCH_CLIENT_ID")
            client_secret = os.getenv("TWITCH_CLIENT_SECRET")
            from services.twitch_api import TwitchAPI
            twitch_api = TwitchAPI(client_id, client_secret)

            async with aiohttp.ClientSession() as session:
                stream = await twitch_api.get_stream(session, channel_name)
                if not stream:
                    await self.chat_service.send_message(broadcaster_id, f"@{chatter_name} 🔴 The stream is currently offline.")
                    return
                
                started_at_str = stream.get("started_at")
                if not started_at_str:
                    await self.chat_service.send_message(broadcaster_id, f"@{chatter_name} Could not determine stream start time.")
                    return

                # Parse Twitch ISO timestamp
                started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                diff = now - started_at

                hours, remainder = divmod(int(diff.total_seconds()), 3600)
                minutes, _ = divmod(remainder, 60)

                viewers = stream.get("viewer_count", 0)
                game_name = stream.get("game_name", "Unknown")

                msg = f"🟢 Live for: {hours} hours and {minutes} minutes | Category: {game_name} | Viewers: {viewers}"
                await self.chat_service.send_message(broadcaster_id, msg)

        elif cmd == "ping":
            if not self._is_authorized(event, "mod"):
                await self.chat_service.send_message(broadcaster_id, f"@{chatter_name} ❌ This command is available only to moderators!")
                return
            await self.chat_service.send_message(broadcaster_id, f"@{chatter_name} Pong! 🏓 EventSub WebSockets & Helix API are fully operational.")
            return