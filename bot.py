import os
import aiohttp
import asyncio
from twitchio.ext import commands
from services.twitch_api import TwitchAPI
from services.trigger_service import TriggerService

from config import CHANNEL_USERNAME


TOKEN = os.getenv("TWITCH_TOKEN")
CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
BOT_ID = os.getenv("TWITCH_BOT_ID")
CHANNEL_ID = os.getenv("CHANNEL_ID")
BROADCASTER_ID = os.getenv("TWITCH_BROADCASTER_ID")


twitch_api = TwitchAPI(
    os.getenv("TWITCH_CLIENT_ID"),
    os.getenv("TWITCH_APP_TOKEN")
)

trigger_service = TriggerService()


class ChimeBot(commands.Bot):

    def __init__(self):
        super().__init__(
            token=TOKEN,
            prefix="!",
            initial_channels=[CHANNEL_USERNAME]
        )

        self.last_stream_id = None
        self.stream_checker_task = None


    async def event_ready(self):
        print("--------------------------------")
        print(f"Bot online: {self.nick}")
        print(f"Channel: {CHANNEL_USERNAME}")
        print("--------------------------------")

        if self.stream_checker_task is None:
            self.stream_checker_task = asyncio.create_task(
                self.stream_checker()
            )


    async def event_message(self, message):
        if message.echo:
            return

        print(f"{message.author.name}: {message.content}")

        await self.handle_commands(message)


    async def send_chat_message(self, text):

        url = "https://api.twitch.tv/helix/chat/messages"

        headers = {
            "Authorization": f"Bearer {TOKEN.replace('oauth:', '')}",
            "Client-Id": CLIENT_ID,
            "Content-Type": "application/json",
        }

        payload = {
            "broadcaster_id": CHANNEL_ID,
            "sender_id": BOT_ID,
            "message": text
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers=headers,
                json=payload
            ) as response:

                data = await response.json()

                print("CHAT API RESPONSE:")
                print(data)

                return data


    async def pin_message(self, message_id):

        url = "https://api.twitch.tv/helix/chat/pins"

        headers = {
            "Authorization": f"Bearer {TOKEN.replace('oauth:', '')}",
            "Client-Id": CLIENT_ID,
        }

        params = {
            "broadcaster_id": CHANNEL_ID,
            "moderator_id": BOT_ID,
            "message_id": message_id
        }

        async with aiohttp.ClientSession() as session:
            async with session.put(
                url,
                headers=headers,
                params=params
            ) as response:
                if response.status == 204:
                    print("PIN SUCCESSFUL")
                    return {}

                data = await response.json()

                print("PIN API RESPONSE:")
                print(data)

                return data


    async def stream_checker(self):

        await self.wait_for_ready()

        while True:
            try:
                stream = await twitch_api.get_stream(
                    BROADCASTER_ID
                )

                if stream:
                    stream_id = stream["id"]
                    title = stream["title"]

                    if stream_id != self.last_stream_id:
                        print("----------------------------")
                        print("NEW STREAM DETECTED")
                        print(title)
                        print("----------------------------")

                        self.last_stream_id = stream_id

                        trigger = trigger_service.check(title)

                        if trigger:
                            print("TRIGGER FOUND:")
                            print(trigger["message"])

                            await self.send_chat_message(
                                trigger["message"]
                            )

                else:
                    if self.last_stream_id is not None:
                        print("Stream ended.")

                    self.last_stream_id = None

            except Exception as e:
                print("STREAM CHECK ERROR:")
                print(e)

            await asyncio.sleep(60)


    @commands.command(name="test")
    async def test(self, ctx):

        print("TEST COMMAND RAN")

        try:
            await ctx.send(
                "Test was successful 🟢"
            )
            print("MESSAGE SENT")

        except Exception as e:
            print("SEND ERROR:")
            print(e)


    @commands.command(name="pin")
    async def pin(self, ctx):
        print("PIN COMMAND RAN")
        result = await self.send_chat_message(
            "📌 This is a test pin message!"
        )
        message_id = result["data"][0]["message_id"]
        await self.pin_message(
            message_id
        )


    @commands.command(name="checktitle")
    async def checktitle(self, ctx, *, test_title=None):

        if test_title:
            title = test_title

        else:
            stream = await twitch_api.get_stream(
                BROADCASTER_ID
            )
            if not stream:
                await ctx.send(
                    "There is no live stream."
                )
                return

            title = stream["title"]

        await ctx.send(
            f"Stream title: {title}"
        )

        trigger = trigger_service.check(title)

        if trigger:
            await ctx.send(
                trigger["message"]
            )

        else:
            await ctx.send(
                "No results."
            )