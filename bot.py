import os
import json
import asyncio
from dotenv import load_dotenv
from services.pin_service import PinService
from services.chat_service import ChatService
from utils.refresh_token import _refresh_token_sync
from services.trigger_service import TriggerService
from services.eventsub_service import EventSubService
from services.stream_checker_service import StreamCheckerService

load_dotenv()

# Load channels dynamically from config.json
with open("data/config.json", "r", encoding="utf-8") as f:
    config_data = json.load(f)

CHANNELS_CONFIG = config_data.get("channels", [])
CHANNEL_USERNAMES = [ch["username"] for ch in CHANNELS_CONFIG]
BROADCASTER_IDS = [ch["user_id"] for ch in CHANNELS_CONFIG]


async def token_refresh_loop():
    """A background task that refreshes the token every 2 hours."""
    while True:
        await asyncio.sleep(7200)
        print("Running scheduled background Twitch token refresh...")
        await asyncio.to_thread(_refresh_token_sync)


class ChimeBot:
    def __init__(self):
        client_id = os.getenv("TWITCH_CLIENT_ID")
        client_secret = os.getenv("TWITCH_CLIENT_SECRET")
        token = os.getenv("TWITCH_TOKEN")
        bot_id = os.getenv("TWITCH_BOT_ID")
        bot_username = os.getenv("TWITCH_BOT_USERNAME", "chimebuddy")

        self.nick = bot_username
        self.chat_service = ChatService(client_id, bot_id)
        self.pin_service = PinService(client_id, token, bot_id)
        self.trigger_service = TriggerService()

        self.stream_checker = StreamCheckerService(
            self.chat_service,
            self.pin_service,
            self.trigger_service,
            CHANNELS_CONFIG
        )

        self.eventsub_service = EventSubService(
            client_id=client_id,
            client_secret=client_secret,
            broadcaster_ids=BROADCASTER_IDS,
            bot_user_id=bot_id,
            chat_service=self.chat_service,
            pin_service=self.pin_service,
            trigger_service=self.trigger_service,
            channels_config=CHANNELS_CONFIG
        )

    async def start(self):
        print("--------------------------------")
        print(f"Bot online: {self.nick}")
        print(f"Connected channels: {CHANNEL_USERNAMES}")
        print("--------------------------------")

        loop = asyncio.get_running_loop()

        # Start background services
        loop.create_task(token_refresh_loop())
        print("Token refresh background loop started.")

        loop.create_task(self.eventsub_service.start())
        print("EventSub WebSocket service started in background.")

        loop.create_task(self.stream_checker.start_checking(loop))
        print("StreamChecker background loop started.")

        # Keep application running
        while True:
            await asyncio.sleep(3600)

# --------------------
# NEEDS TO BE REWRITTEN TO USE THE NEW WEBSOCKET EVENT SUB SERVICE INSTEAD OF THE OLD CHAT SERVICE
# --------------------

#    async def event_message(self, message):
#        if message.echo:
#            return
#        
#        print(f"[{message.channel.name}] {message.author.name}: {message.content}")
#        await self.handle_commands(message)

#    async def event_message(self, message):
#        if message.echo:
#            return
#
#        if message.content.startswith("_"):
#            print(f"[{message.channel.name}] {message.author.name}: {message.content}")
#        await self.handle_commands(message)

def run_bot():
    bot = ChimeBot()
    try:
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        print("Bot stopped by user.")