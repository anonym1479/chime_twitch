import json
import unittest
from types import SimpleNamespace

import aiohttp

from chimebuddy.twitch.eventsub_websocket import (
    EventSubWebSocketService,
)


def welcome_envelope() -> dict:
    return {
        "metadata": {
            "message_id": "welcome-1",
            "message_type": "session_welcome",
        },
        "payload": {
            "session": {
                "id": "session-1",
                "status": "connected",
                "keepalive_timeout_seconds": 30,
                "reconnect_url": None,
            }
        },
    }


def chat_envelope(
    event_message_id: str = "event-1",
) -> dict:
    return {
        "metadata": {
            "message_id": event_message_id,
            "message_type": "notification",
            "subscription_type": "channel.chat.message",
            "subscription_version": "1",
        },
        "payload": {
            "subscription": {
                "type": "channel.chat.message",
            },
            "event": {
                "broadcaster_user_id": "211164044",
                "broadcaster_user_login": "anonym_poal",
                "broadcaster_user_name": "Anonym_Poal",
                "chatter_user_id": "123456789",
                "chatter_user_login": "example_user",
                "chatter_user_name": "Example_User",
                "message_id": "chat-message-1",
                "message": {
                    "text": "_test",
                    "fragments": [],
                },
                "message_type": "text",
                "badges": [
                    {
                        "set_id": "vip",
                        "id": "1",
                        "info": "",
                    }
                ],
            },
        },
    }


class FakeWebSocketMessage:
    def __init__(self, data: dict) -> None:
        self.type = aiohttp.WSMsgType.TEXT
        self.data = json.dumps(data)


class FakeWebSocket:
    def __init__(self, messages: list[dict]) -> None:
        self.messages = [
            FakeWebSocketMessage(message)
            for message in messages
        ]
        self.closed = False

    async def receive(self):
        return self.messages.pop(0)

    async def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, websocket) -> None:
        self.websocket = websocket
        self.urls: list[str] = []

    async def ws_connect(
        self,
        url,
        *,
        autoping,
    ):
        self.urls.append(url)
        return self.websocket


class FakeSubscriptionClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def subscribe_to_chat(
        self,
        websocket_session_id,
        broadcaster_twitch_user_id,
    ):
        self.calls.append(
            (
                websocket_session_id,
                broadcaster_twitch_user_id,
            )
        )

        return SimpleNamespace(
            subscription_id="subscription-1",
            status="enabled",
        )


class RecordingHandler:
    def __init__(
        self,
        stop_event=None,
    ) -> None:
        self.messages = []
        self.stop_event = stop_event

    async def handle_chat_message(
        self,
        message,
    ) -> None:
        self.messages.append(message)

        if self.stop_event is not None:
            self.stop_event.set()


def create_service(
    *,
    websocket=None,
    handler=None,
    status_observer=None,
):
    if websocket is None:
        websocket = FakeWebSocket([])

    if handler is None:
        handler = RecordingHandler()

    subscription_client = FakeSubscriptionClient()

    service = EventSubWebSocketService(
        session=FakeSession(websocket),
        subscription_client=subscription_client,
        broadcaster_twitch_user_ids=(
            "211164044",
        ),
        chat_message_handler=handler,
        reconnect_delay_seconds=0,
        status_observer=status_observer,
    )

    return service, subscription_client, handler


class EventSubWebSocketTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_connects_subscribes_and_routes_chat(
        self,
    ) -> None:
        stop_event = __import__("asyncio").Event()
        handler = RecordingHandler(stop_event)

        websocket = FakeWebSocket(
            [
                welcome_envelope(),
                chat_envelope(),
            ]
        )

        service, subscription_client, _ = (
            create_service(
                websocket=websocket,
                handler=handler,
            )
        )

        await service.run(stop_event)

        self.assertEqual(
            subscription_client.calls,
            [
                (
                    "session-1",
                    "211164044",
                )
            ],
        )
        self.assertEqual(len(handler.messages), 1)
        self.assertEqual(
            handler.messages[0].text,
            "_test",
        )
        self.assertTrue(
            handler.messages[0].is_vip
        )
        self.assertTrue(websocket.closed)

    async def test_reports_connection_health(
        self,
    ) -> None:
        import asyncio

        stop_event = asyncio.Event()
        handler = RecordingHandler(stop_event)
        statuses = []

        async def observe(
            status,
            broadcaster_ids,
            error_code,
            safe_message,
        ):
            statuses.append(
                (
                    status,
                    broadcaster_ids,
                    error_code,
                    safe_message,
                )
            )

        service, _, _ = create_service(
            websocket=FakeWebSocket(
                [
                    welcome_envelope(),
                    chat_envelope(),
                ]
            ),
            handler=handler,
            status_observer=observe,
        )

        await service.run(stop_event)

        self.assertEqual(
            [item[0] for item in statuses],
            ["connecting", "healthy", "stopped"],
        )
        self.assertTrue(
            all(
                item[1] == ("211164044",)
                for item in statuses
            )
        )
    async def test_duplicate_event_is_ignored(
        self,
    ) -> None:
        service, _, handler = create_service()

        notification = chat_envelope(
            "duplicate-event"
        )

        await service._handle_notification(
            notification
        )
        await service._handle_notification(
            notification
        )

        self.assertEqual(len(handler.messages), 1)

    async def test_handler_failure_is_contained(
        self,
    ) -> None:
        class FailingHandler:
            async def handle_chat_message(
                self,
                message,
            ) -> None:
                raise RuntimeError(
                    "Simulated command failure."
                )

        service, _, _ = create_service(
            handler=FailingHandler()
        )

        # The exception must be logged and contained,
        # not escape into the WebSocket loop.
        await service._handle_notification(
            chat_envelope()
        )


if __name__ == "__main__":
    unittest.main()
