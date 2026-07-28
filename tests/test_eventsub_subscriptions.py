import unittest

from chimebuddy.models import OAuthCredentialKind
from chimebuddy.twitch.eventsub_subscriptions import (
    EventSubSubscriptionClient,
    EventSubSubscriptionError,
)


class FakeResponse:
    def __init__(
        self,
        status: int,
        data: dict,
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
    ) -> None:
        return None

    async def json(self) -> dict:
        return self.data


class FakeSession:
    def __init__(
        self,
        responses: list[FakeResponse],
    ) -> None:
        self.responses = responses
        self.requests: list[dict] = []

    def post(
        self,
        url,
        *,
        headers,
        json,
        timeout,
    ) -> FakeResponse:
        self.requests.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )

        return self.responses.pop(0)


class FakeTokenManager:
    def __init__(self) -> None:
        self.get_calls: list[tuple] = []
        self.recovery_calls: list[tuple] = []

    async def get_access_token(
        self,
        twitch_user_id,
        credential_kind,
        required_scopes=(),
    ) -> str:
        self.get_calls.append(
            (
                twitch_user_id,
                credential_kind,
                tuple(required_scopes),
            )
        )
        return "initial-token"

    async def recover_after_unauthorized(
        self,
        twitch_user_id,
        credential_kind,
        rejected_access_token,
        required_scopes=(),
    ) -> str:
        self.recovery_calls.append(
            (
                twitch_user_id,
                credential_kind,
                rejected_access_token,
                tuple(required_scopes),
            )
        )
        return "refreshed-token"


def successful_response() -> FakeResponse:
    return FakeResponse(
        202,
        {
            "data": [
                {
                    "id": "subscription-1",
                    "status": "enabled",
                    "type": "channel.chat.message",
                }
            ]
        },
    )


class EventSubSubscriptionClientTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_creates_chat_subscription(
        self,
    ) -> None:
        session = FakeSession(
            [successful_response()]
        )
        token_manager = FakeTokenManager()

        client = EventSubSubscriptionClient(
            session=session,
            client_id="client-1",
            bot_twitch_user_id="1522303489",
            token_manager=token_manager,
        )

        result = await client.subscribe_to_chat(
            "websocket-session-1",
            "211164044",
        )

        self.assertEqual(
            result.subscription_id,
            "subscription-1",
        )
        self.assertEqual(
            result.broadcaster_twitch_user_id,
            "211164044",
        )

        request = session.requests[0]

        self.assertEqual(
            request["headers"]["Authorization"],
            "Bearer initial-token",
        )
        self.assertEqual(
            request["json"]["condition"],
            {
                "broadcaster_user_id": "211164044",
                "user_id": "1522303489",
            },
        )
        self.assertEqual(
            request["json"]["transport"],
            {
                "method": "websocket",
                "session_id": "websocket-session-1",
            },
        )

        self.assertEqual(
            token_manager.get_calls[0][1],
            OAuthCredentialKind.BOT,
        )

    async def test_recovers_once_after_401(
        self,
    ) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    401,
                    {
                        "error": "Unauthorized",
                        "message": "Invalid OAuth token",
                    },
                ),
                successful_response(),
            ]
        )
        token_manager = FakeTokenManager()

        client = EventSubSubscriptionClient(
            session=session,
            client_id="client-1",
            bot_twitch_user_id="1522303489",
            token_manager=token_manager,
        )

        await client.subscribe_to_chat(
            "websocket-session-1",
            "211164044",
        )

        self.assertEqual(len(session.requests), 2)
        self.assertEqual(
            session.requests[1]["headers"][
                "Authorization"
            ],
            "Bearer refreshed-token",
        )
        self.assertEqual(
            len(token_manager.recovery_calls),
            1,
        )

    async def test_reports_subscription_failure(
        self,
    ) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    403,
                    {
                        "error": "Forbidden",
                        "message": (
                            "subscription missing "
                            "proper authorization"
                        ),
                    },
                )
            ]
        )

        client = EventSubSubscriptionClient(
            session=session,
            client_id="client-1",
            bot_twitch_user_id="1522303489",
            token_manager=FakeTokenManager(),
        )

        with self.assertRaisesRegex(
            EventSubSubscriptionError,
            "proper authorization",
        ):
            await client.subscribe_to_chat(
                "websocket-session-1",
                "211164044",
            )


if __name__ == "__main__":
    unittest.main()