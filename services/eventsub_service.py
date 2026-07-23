import asyncio
import aiohttp
import json
import os

class EventSubService:
    def __init__(self, client_id: str, client_secret: str, broadcaster_id: list, bot_user_id: str, chat_service):
        self.client_id = client_id
        self.client_secret = client_secret
        self.broadcaster_ids = broadcaster_id if isinstance(broadcaster_id, list) else [broadcaster_id]
        self.bot_user_id = bot_user_id
        self.chat_service = chat_service
        self.is_running = False

    async def start(self):
        """Starts the EventSub WebSocket background task."""
        self.is_running = True
        while self.is_running:
            try:
                ws_url = "https://eventsub.wss.twitch.tv/ws"
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(ws_url) as ws:
                        print("🔌 Connected to Twitch EventSub WebSocket...")
                        
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                msg_type = data.get("metadata", {}).get("message_type")
                                
                                if msg_type == "session_welcome":
                                    session_id = data["payload"]["session"]["id"]
                                    print(f"✅ EventSub session welcome received. Session ID: {session_id}")
                                    await self._subscribe_to_chat(session_id)
                                    
                                elif msg_type == "session_keepalive":
                                    pass # Twitch keepalive, no action needed
                                    
                                elif msg_type == "notification":
                                    sub_type = data.get("metadata", {}).get("subscription_type")
                                    if sub_type == "channel.chat.message":
                                        event = data.get("payload", {}).get("event", {})
                                        print(f"💬 [{event.get('broadcaster_user_login')}] {event.get('chatter_user_login')}: {event.get('message', {}).get('text')}")
                                        
                            elif msg.type == aiohttp.WSMsgType.CLOSED:
                                print("⚠️ EventSub WebSocket connection closed. Reconnecting...")
                                break
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                print("❌ EventSub WebSocket error occurred.")
                                break
            except Exception as e:
                print(f"❌ Error in EventSub loop: {e}")
                await asyncio.sleep(5)

    async def _subscribe_to_chat(self, session_id: str):
        """Registers the channel.chat.message subscription for all specified channels."""
        try:
            raw_token = os.getenv("TWITCH_TOKEN", "")
            token = raw_token.replace("oauth:", "") if raw_token else ""

            if not token:
                print("❌ Error: TWITCH_TOKEN is missing or empty for EventSub subscription!")
                return

            url = "https://api.twitch.tv/helix/eventsub/subscriptions"
            
            headers = {
                "Client-Id": self.client_id,
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
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
                    
                    async with session.post(url, headers=headers, json=payload) as response:
                        if response.status == 202:
                            print(f"✅ Successfully subscribed to channel (`{b_id}`) via EventSub!")
                        else:
                            text = await response.text()
                            print(f"❌ Error subscribing to EventSub ({b_id}): {response.status} - {text}")
        except Exception as e:
            print(f"❌ Exception during EventSub subscription: {e}")