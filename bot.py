import os
import json
from dotenv import load_dotenv
from twitchio.ext import commands
from cogs.stream_cog import StreamCog

load_dotenv()

TOKEN = os.getenv("TWITCH_TOKEN")

# Load channels dynamically from config.json
with open("data/config.json", "r", encoding="utf-8") as f:
    config_data = json.load(f)
CHANNEL_USERNAMES = [ch["username"] for ch in config_data.get("channels", [])]


class ChimeBot(commands.Bot):
    def __init__(self):
        super().__init__(
            token=TOKEN,
            prefix="_",
            initial_channels=CHANNEL_USERNAMES
        )

    async def event_ready(self):
        print("--------------------------------")
        print(f"Bot online: {self.nick}")
        print(f"Connected channels: {CHANNEL_USERNAMES}")
        print("--------------------------------")

        self.add_cog(StreamCog(self))
        print("StreamCog loaded successfully.")

#    async def event_message(self, message):
#        if message.echo:
#          return
#
#        if message.content:
#           print(f"[{message.channel.name}] {message.author.name}: {message.content}")
#        await self.handle_commands(message)

    async def event_message(self, message):
        if message.echo:
            return
        if message.content.startswith("_"):
            print(f"[{message.channel.name}] {message.author.name}: {message.content}")
        await self.handle_commands(message)

bot = ChimeBot()