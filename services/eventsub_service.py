import os
import json
import aiohttp
import asyncio
import logging
from services.command_router import CommandRouter

logger = logging.getLogger("ChimeBot.EventSub")

async def validate_token(token):
    headers = {
        "Authorization": f"OAuth {token}"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://id.twitch.tv/oauth2/validate",
            headers=headers
        ) as resp:
            return await resp.json()

class EventSubService:
    def __init__(self, client_id: str, client_secret: str, broadcaster_ids: list, bot_user_id: str, chat_service, pin_service, trigger_service, channels_config):
        self.client_id = client_id
        self.client_secret = client_secret
        self.broadcaster_ids = broadcaster_ids
        self.bot_user_id = bot_user_id
        self.websocket_url = "wss://eventsub.wss.twitch.tv/ws"
        self.command_router = CommandRouter(chat_service, pin_service, trigger_service, channels_config)

    async def start(self):
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    print("Connecting to Twitch EventSub WebSocket...")
                    async with session.ws_connect(self.websocket_url) as ws:
                        print("Connected to Twitch EventSub WebSocket successfully.")

                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                metadata = data.get("metadata", {})
                                message_type = metadata.get("message_type")
                                
                                if message_type == "session_welcome":
                                    session_id = data["payload"]["session"]["id"]
                                    print(f"EventSub session welcome received. Session ID: {session_id}")
                                    await self.subscribe_to_chat_messages(session_id)
                                    
                                elif message_type == "session_keepalive":
                                    continue
                                    
                                elif message_type == "notification":
                                    subscription_type = metadata.get("subscription_type")
                                    if subscription_type == "channel.chat.message":
                                        event_data = data["payload"]["event"]
                                        await self.command_router.handle_command(event_data)
                                        
                            elif msg.type == aiohttp.WSMsgType.CLOSED:
                                logger.warning("EventSub WebSocket connection closed.")
                                break
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logger.error("EventSub WebSocket encountered an error.")
                                break
            except Exception as e:
                logger.error(f"EventSub connection error: {e}. Reconnecting in 5 seconds...")
                await asyncio.sleep(5)

    async def subscribe_to_chat_messages(self, session_id: str):
        raw_token = os.getenv("TWITCH_TOKEN", "")
        token = raw_token.replace("oauth:", "") if raw_token else ""

        await validate_token(token)

        if not token:
            logger.error("❌ Error: TWITCH_TOKEN is missing or empty for EventSub subscription!")
            return

        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        url = "https://api.twitch.tv/helix/eventsub/subscriptions"
        
        async with aiohttp.ClientSession() as session:
            for b_id in self.broadcaster_ids:
                payload = {
                    "type": "channel.chat.message",
                    "version": "1",
                    "condition": {
                        "broadcaster_user_id": str(b_id),
                        "user_id": str(self.bot_user_id)
                    },
                    "transport": {
                        "method": "websocket",
                        "session_id": session_id
                    }
                }
                
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status == 202:
                        print(f"Successfully subscribed to chat messages for broadcaster ID: {b_id}")
                    else:
                        text = await resp.text()
                        logger.error(f"Failed to subscribe for broadcaster {b_id}: {resp.status} - {text}")