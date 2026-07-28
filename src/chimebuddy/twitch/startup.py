from __future__ import annotations

from dataclasses import dataclass

import aiohttp

from chimebuddy.config import Settings
from chimebuddy.database import Database
from chimebuddy.models import OAuthCredentialKind
from chimebuddy.repositories import (
    OAuthCredentialRepository,
)
from chimebuddy.twitch.oauth_client import (
    TwitchOAuthClient,
    TwitchOAuthError,
)
from chimebuddy.twitch.scopes import (
    BOT_CHAT_SCOPES,
)
from chimebuddy.twitch.token_manager import (
    TokenManagerError,
    TwitchTokenManager,
)


class TwitchStartupError(RuntimeError):
    """Raised when the Twitch worker cannot start safely."""


class BotCredentialNotFoundError(TwitchStartupError):
    """Raised when no bot credential exists in SQLite."""


class MultipleBotCredentialsError(TwitchStartupError):
    """Raised when multiple bot identities are configured."""


@dataclass(frozen=True, slots=True)
class BotCredentialHealth:
    twitch_user_id: str
    scopes: tuple[str, ...]
    expires_at: int


async def check_bot_credential(
    settings: Settings,
    database: Database,
) -> BotCredentialHealth:
    """
    Load and validate the bot's stored OAuth credential.

    No access or refresh token is returned or logged.
    """

    if not settings.twitch_client_id:
        raise TwitchStartupError(
            "TWITCH_CLIENT_ID is missing."
        )

    if not settings.twitch_client_secret:
        raise TwitchStartupError(
            "TWITCH_CLIENT_SECRET is missing."
        )

    repository = OAuthCredentialRepository(database)

    credentials = await repository.list_by_kind(
        OAuthCredentialKind.BOT
    )

    if not credentials:
        raise BotCredentialNotFoundError(
            "No Twitch bot credential exists in the "
            "database. The OAuth setup step must be "
            "completed before starting the worker."
        )

    if len(credentials) > 1:
        user_ids = ", ".join(
            credential.twitch_user_id
            for credential in credentials
        )

        raise MultipleBotCredentialsError(
            "More than one Twitch bot credential exists: "
            f"{user_ids}. ChimeBuddy currently supports "
            "one bot identity."
        )

    credential = credentials[0]

    async with aiohttp.ClientSession() as session:
        oauth_client = TwitchOAuthClient(
            session=session,
            client_id=settings.twitch_client_id,
            client_secret=settings.twitch_client_secret,
        )

        token_manager = TwitchTokenManager(
            oauth_client=oauth_client,
            credential_repository=repository,
        )

        try:
            await token_manager.get_access_token(
                credential.twitch_user_id,
                OAuthCredentialKind.BOT,
                BOT_CHAT_SCOPES,
            )
        except (TokenManagerError, TwitchOAuthError) as exc:
            raise TwitchStartupError(
                "The Twitch bot credential health check "
                f"failed: {exc}"
            ) from exc

    updated_credential = await repository.get(
        credential.twitch_user_id,
        OAuthCredentialKind.BOT,
    )

    if updated_credential is None:
        raise TwitchStartupError(
            "The bot credential disappeared during "
            "the startup health check."
        )

    return BotCredentialHealth(
        twitch_user_id=updated_credential.twitch_user_id,
        scopes=updated_credential.scopes,
        expires_at=updated_credential.expires_at,
    )