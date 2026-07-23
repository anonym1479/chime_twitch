import os
import json
import asyncio
from dotenv import load_dotenv
from twitchio.ext import commands
from cogs.stream_cog import StreamCog
from services.chat_service import ChatService
from services.eventsub_service import EventSubService
from utils.refresh_token import _refresh_token_sync

load_dotenv()

TOKEN = os.getenv("TWITCH_TOKEN")

# Load channels dynamically from config.json
with open("data/config.json", "r", encoding="utf-8") as f:
    config_data = json.load(f)
CHANNEL_USERNAMES = [ch["username"] for ch in config_data.get("channels", [])]
BROADCASTER_IDS = [ch["user_id"] for ch in config_data.get("channels", [])]


async def token_refresh_loop():
    """A background task that refreshes the token every 2 hours while the program is running."""
    while True:
        await asyncio.sleep(7200)  # 2 hours
        print("Running scheduled background Twitch token refresh...")
        await asyncio.to_thread(_refresh_token_sync)


class ChimeBot(commands.Bot):
    def __init__(self):
        super().__init__(
            token=TOKEN,
            prefix="_",
            initial_channels=CHANNEL_USERNAMES,
            initial_broadcaster_ids=BROADCASTER_IDS
        )

        self.chat_service = ChatService(
            client_id=os.getenv("TWITCH_CLIENT_ID"),
            bot_user_id=os.getenv("TWITCH_BOT_ID")
        )

        self.eventsub_service = EventSubService(
            client_id=os.getenv("TWITCH_CLIENT_ID"),
            client_secret=os.getenv("TWITCH_CLIENT_SECRET"),
            broadcaster_id=BROADCASTER_IDS,
            bot_user_id=os.getenv("TWITCH_BOT_ID"),
            chat_service=self.chat_service
        )

    async def event_ready(self):
        print("--------------------------------")
        print(f"Bot online: {self.nick}")
        print(f"Connected channels: {CHANNEL_USERNAMES}")
        print("--------------------------------")

        asyncio.create_task(token_refresh_loop())
        print("Token refresh background loop started.")

        asyncio.create_task(self.eventsub_service.start())
        print("EventSub service started in background.")

        self.add_cog(StreamCog(self))
        print("StreamCog loaded successfully.")

#   async def event_message(self, message):
#        if message.echo:
#            return
#        
#        print(f"[{message.channel.name}] {message.author.name}: {message.content}")
#        await self.handle_commands(message)

    async def event_message(self, message):
        if message.echo:
            return
        if message.content.startswith("_"):
            print(f"[{message.channel.name}] {message.author.name}: {message.content}")
        await self.handle_commands(message)


bot = ChimeBot()