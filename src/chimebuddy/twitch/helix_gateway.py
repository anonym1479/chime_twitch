from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import aiohttp

from chimebuddy.models import OAuthCredentialKind
from chimebuddy.twitch.scopes import BOT_CHAT_SCOPES
from chimebuddy.twitch.token_manager import (
    TwitchTokenManager,
)


HELIX_BASE_URL = "https://api.twitch.tv/helix"


class TwitchAPIError(RuntimeError):
    """Raised when Twitch rejects a Helix request."""

    def __init__(
        self,
        status: int,
        message: str,
    ) -> None:
        self.status = status
        self.message = message

        super().__init__(
            f"Twitch API request failed "
            f"({status}): {message}"
        )


class ChatMessageDroppedError(RuntimeError):
    """Raised when Twitch accepts but drops a message."""


class InvalidTwitchResponseError(RuntimeError):
    """Raised when Twitch returns malformed data."""


@dataclass(frozen=True, slots=True)
class ChannelInformation:
    broadcaster_twitch_user_id: str
    login: str
    display_name: str
    title: str
    game_id: str
    game_name: str

@dataclass(frozen=True, slots=True)
class StreamInformation:
    broadcaster_twitch_user_id: str
    login: str
    display_name: str
    title: str
    game_id: str
    game_name: str
    started_at: str


class TwitchHelixGateway:
    """
    Implements the trigger coordinator's Twitch gateways.

    The same object supplies channel information, chat
    messages, and pin operations.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        client_id: str,
        bot_twitch_user_id: str,
        token_manager: TwitchTokenManager,
    ) -> None:
        self.session = session
        self.client_id = self._required_text(
            client_id,
            "client_id",
        )
        self.bot_twitch_user_id = self._required_text(
            bot_twitch_user_id,
            "bot_twitch_user_id",
        )
        self.token_manager = token_manager

    async def get_channel_information(
        self,
        broadcaster_twitch_user_id: str,
    ) -> ChannelInformation | None:
        broadcaster_id = self._required_text(
            broadcaster_twitch_user_id,
            "broadcaster_twitch_user_id",
        )

        status, data = await self._request(
            "GET",
            "/channels",
            params={
                "broadcaster_id": broadcaster_id,
            },
            required_scopes=(),
        )

        if status != 200:
            self._raise_api_error(status, data)

        items = self._data_list(data)

        if not items:
            return None

        item = items[0]

        return ChannelInformation(
            broadcaster_twitch_user_id=(
                self._required_response_text(
                    item,
                    "broadcaster_id",
                )
            ),
            login=self._required_response_text(
                item,
                "broadcaster_login",
            ),
            display_name=(
                self._required_response_text(
                    item,
                    "broadcaster_name",
                )
            ),
            title=str(
                item.get("title", "")
            ),
            game_id=str(
                item.get("game_id", "")
            ),
            game_name=str(
                item.get("game_name", "")
            ),
        )

    async def get_stream_information(
        self,
        broadcaster_twitch_user_id: str,
    ) -> StreamInformation | None:
        """
        Return the active stream or None when offline.
        """

        broadcaster_id = self._required_text(
            broadcaster_twitch_user_id,
            "broadcaster_twitch_user_id",
        )

        status, data = await self._request(
            "GET",
            "/streams",
            params={
                "user_id": broadcaster_id,
            },
            required_scopes=(),
        )

        if status != 200:
            self._raise_api_error(status, data)

        items = self._data_list(data)

        if not items:
            return None

        item = items[0]

        return StreamInformation(
            broadcaster_twitch_user_id=(
                self._required_response_text(
                    item,
                    "user_id",
                )
            ),
            login=self._required_response_text(
                item,
                "user_login",
            ),
            display_name=(
                self._required_response_text(
                    item,
                    "user_name",
                )
            ),
            title=str(item.get("title", "")),
            game_id=str(item.get("game_id", "")),
            game_name=str(
                item.get("game_name", "")
            ),
            started_at=self._required_response_text(
                item,
                "started_at",
            ),
        )

    async def send_message(
        self,
        broadcaster_twitch_user_id: str,
        message: str,
    ) -> str:
        broadcaster_id = self._required_text(
            broadcaster_twitch_user_id,
            "broadcaster_twitch_user_id",
        )

        message_text = self._required_text(
            message,
            "message",
        )

        status, data = await self._request(
            "POST",
            "/chat/messages",
            json_body={
                "broadcaster_id": broadcaster_id,
                "sender_id": self.bot_twitch_user_id,
                "message": message_text,
            },
            required_scopes=BOT_CHAT_SCOPES,
        )

        if status != 200:
            self._raise_api_error(status, data)

        items = self._data_list(data)

        if not items:
            raise InvalidTwitchResponseError(
                "Send Chat Message returned no data."
            )

        result = items[0]

        if result.get("is_sent") is not True:
            drop_reason = result.get("drop_reason")

            if isinstance(drop_reason, dict):
                reason = str(
                    drop_reason.get(
                        "message",
                        drop_reason.get(
                            "code",
                            "Unknown reason",
                        ),
                    )
                )
            else:
                reason = "Unknown reason"

            raise ChatMessageDroppedError(
                "Twitch dropped the chat message: "
                f"{reason}"
            )

        return self._required_response_text(
            result,
            "message_id",
        )

    async def pin_message(
        self,
        broadcaster_twitch_user_id: str,
        message_id: str,
    ) -> None:
        broadcaster_id = self._required_text(
            broadcaster_twitch_user_id,
            "broadcaster_twitch_user_id",
        )

        clean_message_id = self._required_text(
            message_id,
            "message_id",
        )

        status, data = await self._request(
            "PUT",
            "/chat/pins",
            params={
                "broadcaster_id": broadcaster_id,
                "moderator_id": self.bot_twitch_user_id,
                "message_id": clean_message_id,
            },
            required_scopes=BOT_CHAT_SCOPES,
        )

        # Twitch returns 409 if this exact message
        # is already pinned. That is already our goal.
        if status not in {204, 409}:
            self._raise_api_error(status, data)

    async def unpin_message(
        self,
        broadcaster_twitch_user_id: str,
        message_id: str,
    ) -> None:
        broadcaster_id = self._required_text(
            broadcaster_twitch_user_id,
            "broadcaster_twitch_user_id",
        )

        clean_message_id = self._required_text(
            message_id,
            "message_id",
        )

        status, data = await self._request(
            "DELETE",
            "/chat/pins",
            params={
                "broadcaster_id": broadcaster_id,
                "moderator_id": self.bot_twitch_user_id,
                "message_id": clean_message_id,
            },
            required_scopes=BOT_CHAT_SCOPES,
        )

        # A missing pin already satisfies our desired state.
        if status not in {204, 404}:
            self._raise_api_error(status, data)

    async def add_vip(
        self,
        broadcaster_twitch_user_id: str,
        user_twitch_user_id: str,
    ) -> None:
        await self._manage_vip(
            "POST", broadcaster_twitch_user_id, user_twitch_user_id
        )

    async def list_custom_rewards(
        self,
        broadcaster_twitch_user_id: str,
    ) -> list[dict[str, Any]]:
        broadcaster_id = self._required_text(
            broadcaster_twitch_user_id,
            "broadcaster_twitch_user_id",
        )
        status, data = await self._request_as_broadcaster(
            "GET",
            "/channel_points/custom_rewards",
            broadcaster_id,
            params={"broadcaster_id": broadcaster_id},
            required_scopes=("channel:read:redemptions",),
        )
        if status != 200:
            self._raise_api_error(status, data)
        return self._data_list(data)

    async def refund_redemption(
        self,
        broadcaster_twitch_user_id: str,
        reward_id: str,
        redemption_id: str,
    ) -> None:
        broadcaster_id = self._required_text(
            broadcaster_twitch_user_id,
            "broadcaster_twitch_user_id",
        )
        clean_reward_id = self._required_text(
            reward_id,
            "reward_id",
        )
        clean_redemption_id = self._required_text(
            redemption_id,
            "redemption_id",
        )

        status, data = await self._request_as_broadcaster(
            "PATCH",
            "/channel_points/custom_rewards/redemptions",
            broadcaster_id,
            params={
                "broadcaster_id": broadcaster_id,
                "reward_id": clean_reward_id,
                "id": clean_redemption_id,
            },
            json_body={
                "status": "CANCELED",
            },
            required_scopes=("channel:manage:redemptions",),
        )

        if status != 200:
            self._raise_api_error(status, data)

    async def remove_vip(
        self,
        broadcaster_twitch_user_id: str,
        user_twitch_user_id: str,
    ) -> None:
        await self._manage_vip(
            "DELETE", broadcaster_twitch_user_id, user_twitch_user_id
        )

    async def _manage_vip(
        self,
        method: str,
        broadcaster_twitch_user_id: str,
        user_twitch_user_id: str,
    ) -> None:
        broadcaster_id = self._required_text(
            broadcaster_twitch_user_id,
            "broadcaster_twitch_user_id",
        )
        status, data = await self._request_as_broadcaster(
            method,
            "/channels/vips",
            broadcaster_id,
            params={
                "broadcaster_id": broadcaster_id,
                "user_id": self._required_text(
                    user_twitch_user_id,
                    "user_twitch_user_id",
                ),
            },
            required_scopes=("channel:manage:vips",),
        )
        if status != 204:
            self._raise_api_error(status, data)

    async def timeout_user(
        self,
        broadcaster_twitch_user_id: str,
        user_twitch_user_id: str,
        duration_seconds: int,
    ) -> None:
        broadcaster_id = self._required_text(
            broadcaster_twitch_user_id,
            "broadcaster_twitch_user_id",
        )
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive.")
        status, data = await self._request(
            "POST",
            "/moderation/bans",
            params={
                "broadcaster_id": broadcaster_id,
                "moderator_id": self.bot_twitch_user_id,
            },
            json_body={
                "data": {
                    "user_id": self._required_text(
                        user_twitch_user_id,
                        "user_twitch_user_id",
                    ),
                    "duration": duration_seconds,
                }
            },
            required_scopes=("moderator:manage:banned_users",),
        )
        if status != 200:
            self._raise_api_error(status, data)

    async def _request_as_broadcaster(
        self,
        method: str,
        path: str,
        broadcaster_twitch_user_id: str,
        *,
        params: dict[str, str],
        json_body: dict[str, Any] | None = None,
        required_scopes: tuple[str, ...],
    ) -> tuple[int, Any]:
        broadcaster_id = self._required_text(
            broadcaster_twitch_user_id,
            "broadcaster_twitch_user_id",
        )
        access_token = await self.token_manager.get_access_token(
            broadcaster_id,
            OAuthCredentialKind.BROADCASTER,
            required_scopes,
        )
        status, data = await self._perform_request(
            method,
            path,
            access_token,
            params=params,
            json_body=json_body,
        )
        if status != 401:
            return status, data

        token = await self.token_manager.recover_after_unauthorized(
            broadcaster_id,
            OAuthCredentialKind.BROADCASTER,
            access_token,
            required_scopes,
        )
        return await self._perform_request(
            method,
            path,
            token,
            params=params,
            json_body=json_body,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        required_scopes: tuple[str, ...] = (),
    ) -> tuple[int, Any]:
        access_token = (
            await self.token_manager.get_access_token(
                self.bot_twitch_user_id,
                OAuthCredentialKind.BOT,
                required_scopes,
            )
        )

        status, data = await self._perform_request(
            method,
            path,
            access_token,
            params=params,
            json_body=json_body,
        )

        if status != 401:
            return status, data

        new_access_token = (
            await self.token_manager
            .recover_after_unauthorized(
                self.bot_twitch_user_id,
                OAuthCredentialKind.BOT,
                rejected_access_token=access_token,
                required_scopes=required_scopes,
            )
        )

        return await self._perform_request(
            method,
            path,
            new_access_token,
            params=params,
            json_body=json_body,
        )

    async def _perform_request(
        self,
        method: str,
        path: str,
        access_token: str,
        *,
        params: dict[str, str] | None,
        json_body: dict[str, Any] | None,
    ) -> tuple[int, Any]:
        url = f"{HELIX_BASE_URL}{path}"

        timeout = aiohttp.ClientTimeout(total=15)

        async with self.session.request(
            method,
            url,
            params=params,
            json=json_body,
            headers={
                "Client-Id": self.client_id,
                "Authorization": (
                    f"Bearer {access_token}"
                ),
            },
            timeout=timeout,
        ) as response:
            data = await self._read_body(response)
            return response.status, data

    @staticmethod
    async def _read_body(
        response: aiohttp.ClientResponse,
    ) -> Any:
        text = await response.text()

        if not text.strip():
            return None

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {
                "message": text.strip(),
            }

    @staticmethod
    def _data_list(data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, dict):
            raise InvalidTwitchResponseError(
                "Twitch response must be an object."
            )

        items = data.get("data")

        if not isinstance(items, list):
            raise InvalidTwitchResponseError(
                "Twitch response is missing its data list."
            )

        if not all(
            isinstance(item, dict)
            for item in items
        ):
            raise InvalidTwitchResponseError(
                "Twitch response data contains "
                "an invalid item."
            )

        return items

    @staticmethod
    def _raise_api_error(
        status: int,
        data: Any,
    ) -> None:
        if isinstance(data, dict):
            message = str(
                data.get(
                    "message",
                    "Unknown Twitch API error",
                )
            )
        else:
            message = "Unknown Twitch API error"

        raise TwitchAPIError(status, message)

    @staticmethod
    def _required_text(
        value: str,
        field_name: str,
    ) -> str:
        cleaned = str(value).strip()

        if not cleaned:
            raise ValueError(
                f"{field_name} cannot be empty."
            )

        return cleaned

    @staticmethod
    def _required_response_text(
        data: dict[str, Any],
        field_name: str,
    ) -> str:
        cleaned = str(
            data.get(field_name, "")
        ).strip()

        if not cleaned:
            raise InvalidTwitchResponseError(
                "Twitch response is missing "
                f"{field_name}."
            )

        return cleaned
