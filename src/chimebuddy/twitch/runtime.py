from __future__ import annotations

from collections.abc import Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

import aiohttp

from chimebuddy.config import Settings
from chimebuddy.database import Database
from chimebuddy.models import (
    OAuthCredential,
    OAuthCredentialKind,
)
from chimebuddy.repositories import (
    OAuthCredentialRepository,
)
from chimebuddy.twitch.helix_gateway import (
    TwitchHelixGateway,
)
from chimebuddy.twitch.oauth_client import (
    TwitchOAuthClient,
    TwitchOAuthError,
)
from chimebuddy.twitch.scopes import (
    BOT_CHAT_SCOPES,
    BROADCASTER_CHAT_SCOPES,
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


@dataclass(slots=True)
class TwitchRuntime:
    """Shared resources used by the Twitch worker."""

    session: aiohttp.ClientSession
    credential_repository: OAuthCredentialRepository
    oauth_client: TwitchOAuthClient
    token_manager: TwitchTokenManager
    helix_gateway: TwitchHelixGateway
    bot_twitch_user_id: str

    async def validate_bot_token(self) -> str:
        """Validate the bot credential immediately."""

        return await self.token_manager.validate_now(
            self.bot_twitch_user_id,
            OAuthCredentialKind.BOT,
            BOT_CHAT_SCOPES,
        )

    async def get_current_bot_credential(
        self,
    ) -> OAuthCredential:
        credential = (
            await self.credential_repository.get(
                self.bot_twitch_user_id,
                OAuthCredentialKind.BOT,
            )
        )

        if credential is None:
            raise BotCredentialNotFoundError(
                "The bot credential disappeared "
                "from the database."
            )

        return credential


def select_single_bot_credential(
    credentials: Sequence[OAuthCredential],
) -> OAuthCredential:
    """Require exactly one stored bot identity."""

    if not credentials:
        raise BotCredentialNotFoundError(
            "No Twitch bot credential exists in the "
            "database. Run chimebuddy-authorize-bot "
            "before starting the worker."
        )

    if len(credentials) > 1:
        user_ids = ", ".join(
            credential.twitch_user_id
            for credential in credentials
        )

        raise MultipleBotCredentialsError(
            "More than one Twitch bot credential "
            f"exists: {user_ids}."
        )

    return credentials[0]


@asynccontextmanager
async def create_twitch_runtime(
    settings: Settings,
    database: Database,
) -> AsyncIterator[TwitchRuntime]:
    """
    Create and safely close shared Twitch resources.

    Initial token validation occurs before the runtime
    is returned to the worker.
    """

    if not settings.twitch_client_id:
        raise TwitchStartupError(
            "TWITCH_CLIENT_ID is missing."
        )

    if not settings.twitch_client_secret:
        raise TwitchStartupError(
            "TWITCH_CLIENT_SECRET is missing."
        )

    credential_repository = (
        OAuthCredentialRepository(database)
    )

    credentials = (
        await credential_repository.list_by_kind(
            OAuthCredentialKind.BOT
        )
    )

    bot_credential = select_single_bot_credential(
            credentials
        )
    broadcaster_credentials = (
        await credential_repository.list_by_kind(
            OAuthCredentialKind.BROADCASTER
        )
    )

    session = aiohttp.ClientSession()

    try:
        oauth_client = TwitchOAuthClient(
            session=session,
            client_id=settings.twitch_client_id,
            client_secret=(
                settings.twitch_client_secret
            ),
        )

        token_manager = TwitchTokenManager(
            oauth_client=oauth_client,
            credential_repository=(
                credential_repository
            ),
        )

        token_manager.register(
            bot_credential.twitch_user_id,
            OAuthCredentialKind.BOT,
            BOT_CHAT_SCOPES,
        )
        for credential in broadcaster_credentials:
            token_manager.register(
                credential.twitch_user_id,
                OAuthCredentialKind.BROADCASTER,
                BROADCASTER_CHAT_SCOPES,
            )

        helix_gateway = TwitchHelixGateway(
            session=session,
            client_id=settings.twitch_client_id,
            bot_twitch_user_id=(
                bot_credential.twitch_user_id
            ),
            token_manager=token_manager,
        )

        runtime = TwitchRuntime(
            session=session,
            credential_repository=(
                credential_repository
            ),
            oauth_client=oauth_client,
            token_manager=token_manager,
            helix_gateway=helix_gateway,
            bot_twitch_user_id=(
                bot_credential.twitch_user_id
            ),
        )

        try:
            await token_manager.validate_registered()
        except (
            TokenManagerError,
            TwitchOAuthError,
        ) as exc:
            raise TwitchStartupError(
                "The Twitch bot credential health "
                f"check failed: {exc}"
            ) from exc

        yield runtime

    finally:
        await session.close()