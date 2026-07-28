import json
import unittest

from chimebuddy.twitch import (
    ChatMessageDroppedError,
    TwitchHelixGateway,
)


BOT_ID = "1522303489"
BROADCASTER_ID = "211164044"


class FakeResponse:
    def __init__(
        self,
        status: int,
        data=None,
    ) -> None:
        self.status = status
        self.data = data

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        traceback,
    ):
        return False

    async def text(self):
        if self.data is None:
            return ""

        return json.dumps(self.data)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(
        self,
        method,
        url,
        **kwargs,
    ):
        self.requests.append(
            {
                "method": method,
                "url": url,
                **kwargs,
            }
        )

        return self.responses.pop(0)


class FakeTokenManager:
    def __init__(self):
        self.access_token = "access-old"
        self.recovery_calls = []

    async def get_access_token(
        self,
        twitch_user_id,
        credential_kind,
        required_scopes=(),
    ):
        return self.access_token

    async def recover_after_unauthorized(
        self,
        twitch_user_id,
        credential_kind,
        rejected_access_token,
        required_scopes=(),
    ):
        self.recovery_calls.append(
            rejected_access_token
        )
        self.access_token = "access-new"
        return self.access_token


class TwitchHelixGatewayTests(
    unittest.IsolatedAsyncioTestCase
):
    def create_gateway(self, responses):
        self.session = FakeSession(responses)
        self.token_manager = FakeTokenManager()

        return TwitchHelixGateway(
            session=self.session,
            client_id="client-id",
            bot_twitch_user_id=BOT_ID,
            token_manager=self.token_manager,
        )

    async def test_gets_channel_title(self):
        gateway = self.create_gateway(
            [
                FakeResponse(
                    200,
                    {
                        "data": [
                            {
                                "broadcaster_id": (
                                    BROADCASTER_ID
                                ),
                                "broadcaster_login": (
                                    "example_streamer"
                                ),
                                "broadcaster_name": (
                                    "Example Streamer"
                                ),
                                "title": (
                                    "Ranked solo gameplay"
                                ),
                                "game_id": "123",
                                "game_name": (
                                    "Example Game"
                                ),
                            }
                        ]
                    },
                )
            ]
        )

        channel = (
            await gateway.get_channel_information(
                BROADCASTER_ID
            )
        )

        self.assertEqual(
            channel.title,
            "Ranked solo gameplay",
        )

    async def test_sends_message_and_returns_id(self):
        gateway = self.create_gateway(
            [
                FakeResponse(
                    200,
                    {
                        "data": [
                            {
                                "message_id": (
                                    "message-123"
                                ),
                                "is_sent": True,
                                "drop_reason": None,
                            }
                        ]
                    },
                )
            ]
        )

        message_id = await gateway.send_message(
            BROADCASTER_ID,
            "Hello from ChimeBuddy.",
        )

        self.assertEqual(
            message_id,
            "message-123",
        )

    async def test_recovers_once_after_401(self):
        gateway = self.create_gateway(
            [
                FakeResponse(
                    401,
                    {
                        "message": (
                            "Invalid OAuth token"
                        )
                    },
                ),
                FakeResponse(
                    200,
                    {
                        "data": [
                            {
                                "message_id": (
                                    "message-456"
                                ),
                                "is_sent": True,
                                "drop_reason": None,
                            }
                        ]
                    },
                ),
            ]
        )

        message_id = await gateway.send_message(
            BROADCASTER_ID,
            "Retry test.",
        )

        self.assertEqual(
            message_id,
            "message-456",
        )
        self.assertEqual(
            self.token_manager.recovery_calls,
            ["access-old"],
        )

        first_headers = (
            self.session.requests[0]["headers"]
        )
        second_headers = (
            self.session.requests[1]["headers"]
        )

        self.assertEqual(
            first_headers["Authorization"],
            "Bearer access-old",
        )
        self.assertEqual(
            second_headers["Authorization"],
            "Bearer access-new",
        )

    async def test_reports_dropped_message(self):
        gateway = self.create_gateway(
            [
                FakeResponse(
                    200,
                    {
                        "data": [
                            {
                                "message_id": "",
                                "is_sent": False,
                                "drop_reason": {
                                    "code": "automod_held",
                                    "message": (
                                        "The message was "
                                        "held by AutoMod."
                                    ),
                                },
                            }
                        ]
                    },
                )
            ]
        )

        with self.assertRaises(
            ChatMessageDroppedError
        ):
            await gateway.send_message(
                BROADCASTER_ID,
                "Test message.",
            )

    async def test_pin_and_missing_unpin_succeed(self):
        gateway = self.create_gateway(
            [
                FakeResponse(204),
                FakeResponse(
                    404,
                    {
                        "message": (
                            "Pinned message not found"
                        )
                    },
                ),
            ]
        )

        await gateway.pin_message(
            BROADCASTER_ID,
            "message-123",
        )

        await gateway.unpin_message(
            BROADCASTER_ID,
            "message-123",
        )


if __name__ == "__main__":
    unittest.main()