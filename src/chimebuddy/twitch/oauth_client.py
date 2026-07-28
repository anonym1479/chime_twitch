from dataclasses import dataclass, field
from typing import Any

import aiohttp


VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"


class TwitchOAuthError(RuntimeError):
    """Base error for Twitch OAuth requests."""


class InvalidAccessTokenError(TwitchOAuthError):
    """Raised when Twitch rejects an access token."""


class InvalidRefreshTokenError(TwitchOAuthError):
    """Raised when Twitch rejects a refresh token."""


class OAuthResponseError(TwitchOAuthError):
    """Raised when Twitch returns an unexpected response."""


@dataclass(frozen=True, slots=True)
class TokenValidation:
    client_id: str
    user_id: str | None
    login: str | None
    scopes: tuple[str, ...]
    expires_in: int


@dataclass(frozen=True, slots=True)
class RefreshedTokens:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    scopes: tuple[str, ...]
    expires_in: int
    token_type: str


class TwitchOAuthClient:
    """Makes validation and refresh requests to Twitch OAuth."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        client_id: str,
        client_secret: str,
    ) -> None:
        self.session = session
        self.client_id = client_id
        self.client_secret = client_secret

    async def validate(
        self,
        access_token: str,
    ) -> TokenValidation:
        token = str(access_token).strip()

        if not token:
            raise ValueError(
                "access_token cannot be empty."
            )

        timeout = aiohttp.ClientTimeout(total=15)

        async with self.session.get(
            VALIDATE_URL,
            headers={
                "Authorization": f"Bearer {token}",
            },
            timeout=timeout,
        ) as response:
            data = await self._read_json(response)

            if response.status == 401:
                raise InvalidAccessTokenError(
                    "Twitch rejected the access token."
                )

            if response.status != 200:
                raise OAuthResponseError(
                    self._error_description(
                        response.status,
                        data,
                    )
                )

        return self.parse_validation(data)

    async def refresh(
        self,
        refresh_token: str,
    ) -> RefreshedTokens:
        token = str(refresh_token).strip()

        if not token:
            raise ValueError(
                "refresh_token cannot be empty."
            )

        timeout = aiohttp.ClientTimeout(total=15)

        async with self.session.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": token,
            },
            timeout=timeout,
        ) as response:
            data = await self._read_json(response)

            if response.status in {400, 401}:
                raise InvalidRefreshTokenError(
                    "Twitch rejected the refresh token."
                )

            if response.status != 200:
                raise OAuthResponseError(
                    self._error_description(
                        response.status,
                        data,
                    )
                )

        return self.parse_refresh(data)

    @staticmethod
    def parse_validation(
        data: dict[str, Any],
    ) -> TokenValidation:
        client_id = str(
            data.get("client_id", "")
        ).strip()

        expires_in = TwitchOAuthClient._positive_int(
            data.get("expires_in"),
            "expires_in",
        )

        if not client_id:
            raise OAuthResponseError(
                "Validation response is missing client_id."
            )

        user_id_value = data.get("user_id")
        login_value = data.get("login")

        user_id = (
            str(user_id_value).strip()
            if user_id_value is not None
            else None
        )

        login = (
            str(login_value).strip().lower()
            if login_value is not None
            else None
        )

        return TokenValidation(
            client_id=client_id,
            user_id=user_id or None,
            login=login or None,
            scopes=TwitchOAuthClient._parse_scopes(
                data.get("scopes", ())
            ),
            expires_in=expires_in,
        )

    @staticmethod
    def parse_refresh(
        data: dict[str, Any],
    ) -> RefreshedTokens:
        access_token = str(
            data.get("access_token", "")
        ).strip()

        refresh_token = str(
            data.get("refresh_token", "")
        ).strip()

        token_type = str(
            data.get("token_type", "bearer")
        ).strip().lower()

        if not access_token:
            raise OAuthResponseError(
                "Refresh response is missing access_token."
            )

        if not refresh_token:
            raise OAuthResponseError(
                "Refresh response is missing refresh_token."
            )

        expires_in = TwitchOAuthClient._positive_int(
            data.get("expires_in"),
            "expires_in",
        )

        return RefreshedTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            scopes=TwitchOAuthClient._parse_scopes(
                data.get("scope", ())
            ),
            expires_in=expires_in,
            token_type=token_type,
        )

    @staticmethod
    def _parse_scopes(
        raw_scopes: Any,
    ) -> tuple[str, ...]:
        if isinstance(raw_scopes, str):
            values = raw_scopes.split()
        elif isinstance(raw_scopes, (list, tuple)):
            values = raw_scopes
        else:
            raise OAuthResponseError(
                "OAuth scopes must be a list or string."
            )

        return tuple(
            sorted(
                {
                    str(scope).strip()
                    for scope in values
                    if str(scope).strip()
                }
            )
        )

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
                f"{field_name} must be greater than zero."
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
                "Twitch returned a non-JSON OAuth response."
            ) from exc

        if not isinstance(data, dict):
            raise OAuthResponseError(
                "Twitch returned an invalid OAuth response."
            )

        return data

    @staticmethod
    def _error_description(
        status: int,
        data: dict[str, Any],
    ) -> str:
        message = str(
            data.get("message", "Unknown OAuth error")
        ).strip()

        return f"Twitch OAuth request failed ({status}): {message}"