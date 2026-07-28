from dataclasses import dataclass
from typing import Any

import aiohttp

from chimebuddy.models import OAuthCredentialKind
from chimebuddy.twitch.token_manager import (
    TwitchTokenManager,
)


EVENTSUB_SUBSCRIPTIONS_URL = (
    "https://api.twitch.tv/helix/eventsub/subscriptions"
)

CHAT_SUBSCRIPTION_SCOPES = (
    "user:bot",
    "user:read:chat",
)


class EventSubSubscriptionError(RuntimeError):
    """Raised when an EventSub subscription fails."""


@dataclass(frozen=True, slots=True)
class EventSubSubscription:
    subscription_id: str
    status: str
    subscription_type: str
    broadcaster_twitch_user_id: str


class EventSubSubscriptionClient:
    """Creates Twitch EventSub WebSocket subscriptions."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        client_id: str,
        bot_twitch_user_id: str,
        token_manager: TwitchTokenManager,
    ) -> None:
        self.session = session
        self.client_id = str(client_id).strip()
        self.bot_twitch_user_id = str(
            bot_twitch_user_id
        ).strip()
        self.token_manager = token_manager

        if not self.client_id:
            raise ValueError("client_id cannot be empty.")

        if not self.bot_twitch_user_id:
            raise ValueError(
                "bot_twitch_user_id cannot be empty."
            )

    async def subscribe_to_chat(
        self,
        websocket_session_id: str,
        broadcaster_twitch_user_id: str,
    ) -> EventSubSubscription:
        session_id = str(
            websocket_session_id
        ).strip()
        broadcaster_id = str(
            broadcaster_twitch_user_id
        ).strip()

        if not session_id:
            raise ValueError(
                "websocket_session_id cannot be empty."
            )

        if not broadcaster_id:
            raise ValueError(
                "broadcaster_twitch_user_id "
                "cannot be empty."
            )

        access_token = (
            await self.token_manager.get_access_token(
                self.bot_twitch_user_id,
                OAuthCredentialKind.BOT,
                CHAT_SUBSCRIPTION_SCOPES,
            )
        )

        status, data = await self._request(
            access_token,
            session_id,
            broadcaster_id,
        )

        if status == 401:
            access_token = (
                await self.token_manager
                .recover_after_unauthorized(
                    self.bot_twitch_user_id,
                    OAuthCredentialKind.BOT,
                    access_token,
                    CHAT_SUBSCRIPTION_SCOPES,
                )
            )

            status, data = await self._request(
                access_token,
                session_id,
                broadcaster_id,
            )

        if status != 202:
            message = str(
                data.get(
                    "message",
                    "Unknown EventSub error",
                )
            ).strip()

            raise EventSubSubscriptionError(
                "Twitch rejected the chat subscription "
                f"for broadcaster {broadcaster_id} "
                f"({status}): {message}"
            )

        return self._parse_subscription(
            data,
            broadcaster_id,
        )

    async def _request(
        self,
        access_token: str,
        session_id: str,
        broadcaster_id: str,
    ) -> tuple[int, dict[str, Any]]:
        timeout = aiohttp.ClientTimeout(total=15)

        async with self.session.post(
            EVENTSUB_SUBSCRIPTIONS_URL,
            headers={
                "Authorization": (
                    f"Bearer {access_token}"
                ),
                "Client-Id": self.client_id,
                "Content-Type": "application/json",
            },
            json={
                "type": "channel.chat.message",
                "version": "1",
                "condition": {
                    "broadcaster_user_id": (
                        broadcaster_id
                    ),
                    "user_id": (
                        self.bot_twitch_user_id
                    ),
                },
                "transport": {
                    "method": "websocket",
                    "session_id": session_id,
                },
            },
            timeout=timeout,
        ) as response:
            data = await self._read_json(response)
            return response.status, data

    @staticmethod
    async def _read_json(
        response: aiohttp.ClientResponse,
    ) -> dict[str, Any]:
        try:
            data = await response.json()
        except (
            aiohttp.ContentTypeError,
            ValueError,
        ) as exc:
            raise EventSubSubscriptionError(
                "Twitch returned a non-JSON "
                "EventSub response."
            ) from exc

        if not isinstance(data, dict):
            raise EventSubSubscriptionError(
                "Twitch returned an invalid "
                "EventSub response."
            )

        return data

    @staticmethod
    def _parse_subscription(
        data: dict[str, Any],
        broadcaster_id: str,
    ) -> EventSubSubscription:
        subscriptions = data.get("data")

        if (
            not isinstance(subscriptions, list)
            or not subscriptions
            or not isinstance(subscriptions[0], dict)
        ):
            raise EventSubSubscriptionError(
                "Twitch subscription response "
                "contains no subscription."
            )

        subscription = subscriptions[0]

        subscription_id = str(
            subscription.get("id", "")
        ).strip()
        status = str(
            subscription.get("status", "")
        ).strip()
        subscription_type = str(
            subscription.get("type", "")
        ).strip()

        if not subscription_id:
            raise EventSubSubscriptionError(
                "Twitch subscription response "
                "is missing its ID."
            )

        if not status:
            raise EventSubSubscriptionError(
                "Twitch subscription response "
                "is missing its status."
            )

        if subscription_type != "channel.chat.message":
            raise EventSubSubscriptionError(
                "Twitch returned an unexpected "
                "subscription type."
            )

        return EventSubSubscription(
            subscription_id=subscription_id,
            status=status,
            subscription_type=subscription_type,
            broadcaster_twitch_user_id=(
                broadcaster_id
            ),
        )