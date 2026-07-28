from dataclasses import dataclass, field
from typing import Any

import asyncio
import aiohttp

from chimebuddy.twitch.oauth_client import (
    OAuthResponseError,
    RefreshedTokens,
    TwitchOAuthClient,
)


DEVICE_URL = "https://id.twitch.tv/oauth2/device"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"

DEVICE_GRANT_TYPE = (
    "urn:ietf:params:oauth:grant-type:device_code"
)


class DeviceAuthorizationError(RuntimeError):
    """Base error for Twitch device authorization."""


class DeviceAuthorizationDeniedError(
    DeviceAuthorizationError
):
    """Raised when the user rejects authorization."""


class DeviceAuthorizationExpiredError(
    DeviceAuthorizationError
):
    """Raised when the device code expires."""


@dataclass(frozen=True, slots=True)
class DeviceAuthorization:
    device_code: str = field(repr=False)
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


class TwitchDeviceAuthorizationClient:
    """Implements Twitch's device authorization flow."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        client_id: str,
    ) -> None:
        self.session = session
        self.client_id = str(client_id).strip()

        if not self.client_id:
            raise ValueError(
                "client_id cannot be empty."
            )

    async def start(
        self,
        scopes: tuple[str, ...],
    ) -> DeviceAuthorization:
        scope_text = self._scope_text(scopes)
        timeout = aiohttp.ClientTimeout(total=15)

        async with self.session.post(
            DEVICE_URL,
            data={
                "client_id": self.client_id,
                "scopes": scope_text,
            },
            timeout=timeout,
        ) as response:
            data = await self._read_json(response)

            if response.status != 200:
                raise OAuthResponseError(
                    self._error_description(
                        response.status,
                        data,
                    )
                )

        return self.parse_authorization(data)

    async def poll(
        self,
        authorization: DeviceAuthorization,
        scopes: tuple[str, ...],
    ) -> RefreshedTokens | None:
        """
        Poll Twitch once.

        Returns None while the user is still authorizing.
        """

        timeout = aiohttp.ClientTimeout(total=15)

        async with self.session.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "scopes": self._scope_text(scopes),
                "device_code": (
                    authorization.device_code
                ),
                "grant_type": DEVICE_GRANT_TYPE,
            },
            timeout=timeout,
        ) as response:
            data = await self._read_json(response)

            if response.status == 200:
                return TwitchOAuthClient.parse_refresh(
                    data
                )

            message = self._normalized_message(data)

            if (
                response.status == 400
                and message == "authorization_pending"
            ):
                return None

            if "access_denied" in message:
                raise DeviceAuthorizationDeniedError(
                    "Twitch authorization was denied."
                )

            if (
                "expired" in message
                or "invalid_device_code" in message
            ):
                raise DeviceAuthorizationExpiredError(
                    "The Twitch device code expired."
                )

            raise OAuthResponseError(
                self._error_description(
                    response.status,
                    data,
                )
            )

    @staticmethod
    def parse_authorization(
        data: dict[str, Any],
    ) -> DeviceAuthorization:
        device_code = str(
            data.get("device_code", "")
        ).strip()

        user_code = str(
            data.get("user_code", "")
        ).strip()

        verification_uri = str(
            data.get("verification_uri", "")
        ).strip()

        if not device_code:
            raise OAuthResponseError(
                "Device response is missing device_code."
            )

        if not user_code:
            raise OAuthResponseError(
                "Device response is missing user_code."
            )

        if not verification_uri:
            raise OAuthResponseError(
                "Device response is missing "
                "verification_uri."
            )

        expires_in = (
            TwitchDeviceAuthorizationClient
            ._positive_int(
                data.get("expires_in"),
                "expires_in",
            )
        )

        interval = (
            TwitchDeviceAuthorizationClient
            ._positive_int(
                data.get("interval", 5),
                "interval",
            )
        )

        return DeviceAuthorization(
            device_code=device_code,
            user_code=user_code,
            verification_uri=verification_uri,
            expires_in=expires_in,
            interval=interval,
        )

    @staticmethod
    def _scope_text(
        scopes: tuple[str, ...],
    ) -> str:
        normalized = tuple(
            sorted(
                {
                    str(scope).strip()
                    for scope in scopes
                    if str(scope).strip()
                }
            )
        )

        if not normalized:
            raise ValueError(
                "At least one OAuth scope is required."
            )

        return " ".join(normalized)

    @staticmethod
    def _positive_int(
        value: Any,
        field_name: str,
    ) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise OAuthResponseError(
                f"{field_name} must be an integer."
            ) from exc

        if parsed <= 0:
            raise OAuthResponseError(
                f"{field_name} must be positive."
            )

        return parsed

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
            raise OAuthResponseError(
                "Twitch returned a non-JSON "
                "device authorization response."
            ) from exc

        if not isinstance(data, dict):
            raise OAuthResponseError(
                "Twitch returned an invalid "
                "device authorization response."
            )

        return data

    @staticmethod
    def _normalized_message(
        data: dict[str, Any],
    ) -> str:
        return (
            str(data.get("message", ""))
            .strip()
            .casefold()
            .replace(" ", "_")
        )

    @staticmethod
    def _error_description(
        status: int,
        data: dict[str, Any],
    ) -> str:
        message = str(
            data.get(
                "message",
                "Unknown device authorization error",
            )
        ).strip()

        return (
            "Twitch device authorization failed "
            f"({status}): {message}"
        )

async def wait_for_device_authorization(
    device_client: TwitchDeviceAuthorizationClient,
    authorization: DeviceAuthorization,
    scopes: tuple[str, ...],
) -> RefreshedTokens:
    """Poll Twitch until authorization finishes."""

    event_loop = asyncio.get_running_loop()

    deadline = (
        event_loop.time()
        + authorization.expires_in
    )

    while event_loop.time() < deadline:
        await asyncio.sleep(
            authorization.interval
        )

        tokens = await device_client.poll(
            authorization,
            scopes,
        )

        if tokens is not None:
            return tokens

    raise DeviceAuthorizationExpiredError(
        "The Twitch device authorization expired."
    )