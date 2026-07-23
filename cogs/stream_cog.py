import os
import json
import aiohttp
from twitchio.ext import commands
from services.chat_service import ChatService
from services.pin_service import PinService
from services.stream_service import StreamService
from services.trigger_service import TriggerService
from services.stream_checker_service import StreamCheckerService


class StreamCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Load channels configuration from data folder
        config_path = "data/config.json"
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                self.config_data = json.load(f)
                self.channels_config = self.config_data.get("channels", [])
        else:
            self.channels_config = []
        
        # Load environment variables
        client_id = os.getenv("TWITCH_CLIENT_ID")
        token = os.getenv("TWITCH_TOKEN")
        bot_id = os.getenv("TWITCH_BOT_ID")
        bot_id = os.getenv("TWITCH_BOT_ID")
        
        # Initialize services
        self.chat_service = bot.chat_service
        self.pin_service = PinService(client_id, token, bot_id)
        self.trigger_service = TriggerService()
        
        # Initialize background stream checker service with multi-channel support
        self.stream_checker = StreamCheckerService(
            self.chat_service,
            self.pin_service,
            self.trigger_service,
            self.channels_config
        )
        
        # Start background check loop
        self.bot.loop.create_task(
            self.stream_checker.start_checking(self.bot.loop)
        )

    def _get_broadcaster_id_by_username(self, username):
        """Helper to find the numeric broadcaster ID by channel username."""
        for ch in self.channels_config:
            if ch["username"].lower() == username.lower():
                return ch["user_id"]
        return None


# =========================
#        COMMANDS
# ==========================

    @commands.command(name="test")
    async def test(self, ctx):
        """Command visible to users: tests bot responsiveness via Helix API."""
        print(f"TEST COMMAND RAN in {ctx.channel.name}")
        broadcaster_id = self._get_broadcaster_id_by_username(ctx.channel.name)
        if not broadcaster_id:
            return

        try:
            await self.chat_service.send_message(broadcaster_id, "Test was successful 🟢")
        except Exception as e:
            print(f"SEND ERROR: {e}")


    @commands.command(name="pin")
    async def pin(self, ctx):
        """Command visible to users: tests manual message pinning in the current channel."""
        print(f"PIN COMMAND RAN in {ctx.channel.name}")
        broadcaster_id = self._get_broadcaster_id_by_username(ctx.channel.name)
        if not broadcaster_id:
            await self.chat_service.send_message(broadcaster_id, "Error: Channel ID not found in config.")
            return

        result = await self.chat_service.send_message(broadcaster_id, "📌 This is a test pin message!")
        try:
            message_id = result["data"][0]["message_id"]
            await self.pin_service.set_pin_status(broadcaster_id, message_id, pin_status=True)
        except (KeyError, IndexError, TypeError) as e:
            print(f"Error pinning via command: {e}")


    @commands.command(name="checktitle")
    async def checktitle(self, ctx: commands.Context, *, custom_title: str = None):
        """Command visible to users: checks current stream title against channel-specific triggers."""
        channel_name = ctx.channel.name.lower()
        broadcaster_id = self._get_broadcaster_id_by_username(channel_name)
        
        if not broadcaster_id:
            await self.chat_service.send_message(broadcaster_id, "Error: Channel not configured.")
            return

        if not custom_title:
            async with aiohttp.ClientSession() as session:
                stream = await self.stream_checker.twitch_api.get_stream(session, channel_name)
                if not stream:
                    self.chat_service.send_message(broadcaster_id, "Stream is currently offline or not found.")
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


    @commands.command(name="online", aliases=["jelen"])
    async def online_command(self, ctx: commands.Context):
        """Responds if the bot is online and listening via Helix API."""
        broadcaster_id = self._get_broadcaster_id_by_username(ctx.channel.name)
        if broadcaster_id:
            await self.chat_service.send_message(broadcaster_id, "Jelen!")