import os
import json
import aiohttp
import asyncio
import logging

logger = logging.getLogger("ChimeBot.EventSub")

class EventSubService:
    def __init__(self, client_id: str = None, broadcaster_ids=None, broadcaster_id=None, client_secret: str = None, **kwargs):
        self.client_id = client_id or os.getenv("TWITCH_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("TWITCH_CLIENT_SECRET")
        
        raw_input = broadcaster_ids if broadcaster_ids is not None else broadcaster_id
        self.broadcaster_ids = []
        
        if raw_input is not None:
            items = raw_input if isinstance(raw_input, list) else [raw_input]
            for item in items:
                if isinstance(item, list):
                    self.broadcaster_ids.extend([str(sub_item) for sub_item in item])
                else:
                    self.broadcaster_ids.append(str(item))
            
        self.bot_user_id = os.getenv("TWITCH_BOT_USER_ID") or os.getenv("TWITCH_BOT_ID") or os.getenv("BOT_USER_ID")
        self.websocket_url = "https://eventsub.wss.twitch.tv/ws"

    async def start(self):
        """
        Connects to the Twitch EventSub WebSocket server, listens for the welcome message,
        and manages automatic reconnections.
        """
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    logger.info("Connecting to Twitch EventSub WebSocket...")
                    async with session.ws_connect(self.websocket_url) as ws:
                        logger.info("Connected to Twitch EventSub WebSocket successfully.")
                        
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                metadata = data.get("metadata", {})
                                message_type = metadata.get("message_type")
                                
                                if message_type == "session_welcome":
                                    session_id = data["payload"]["session"]["id"]
                                    logger.info(f"EventSub session welcome received. Session ID: {session_id}")
                                    await self.subscribe_to_chat_messages(session_id)
                                    
                                elif message_type == "session_keepalive":
                                    continue
                                    
                                elif message_type == "notification":
                                    subscription_type = metadata.get("subscription_type")
                                    if subscription_type == "channel.chat.message":
                                        event_data = data["payload"]["event"]
                                        logger.debug(f"Chat message event received from {event_data.get('broadcaster_user_login')}")
                                        
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
        """
        Subscribes to channel.chat.message for all configured broadcasters using the bot's User Access Token.
        """
        raw_token = os.getenv("TWITCH_TOKEN", "")
        token = raw_token.replace("oauth:", "") if raw_token else ""

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
                        logger.info(f"Successfully subscribed to chat messages for broadcaster ID: {b_id}")
                    else:
                        text = await resp.text()
                        logger.error(f"Failed to subscribe for broadcaster {b_id}: {resp.status} - {text}")