from dataclasses import dataclass

from chimebuddy.config import Settings
from chimebuddy.database import Database
from chimebuddy.twitch.runtime import (
    BotCredentialNotFoundError,
    MultipleBotCredentialsError,
    TwitchStartupError,
    create_twitch_runtime,
)


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
    Create the shared runtime and verify its bot token.

    No access or refresh token is returned or logged.
    """

    async with create_twitch_runtime(
        settings,
        database,
    ) as runtime:
        credential = (
            await runtime.get_current_bot_credential()
        )

        return BotCredentialHealth(
            twitch_user_id=(
                credential.twitch_user_id
            ),
            scopes=credential.scopes,
            expires_at=credential.expires_at,
        )


__all__ = [
    "BotCredentialHealth",
    "BotCredentialNotFoundError",
    "MultipleBotCredentialsError",
    "TwitchStartupError",
    "check_bot_credential",
]