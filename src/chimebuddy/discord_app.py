import asyncio
import logging

import aiohttp

from chimebuddy import __version__
from chimebuddy.config import (
    ConfigurationError,
    Settings,
    load_settings,
)
from chimebuddy.database import Database
from chimebuddy.discord_admin.client import (
    ChimeBuddyDiscordClient,
)
from chimebuddy.discord_admin.onboarding import (
    DiscordOnboardingController,
)
from chimebuddy.discord_admin.status_service import (
    DiscordAdminStatusService,
)
from chimebuddy.repositories import (
    AccountLinkCompletionRepository,
    AccountLinkSessionRepository,
    BroadcasterBlacklistRepository,
    BroadcasterRequestRepository,
    IdentityRepository,
    OAuthCredentialRepository,
)
from chimebuddy.services import (
    AccountLinkingService,
    OnboardingService,
)
from chimebuddy.twitch.device_authorization import (
    TwitchDeviceAuthorizationClient,
)
from chimebuddy.twitch.oauth_client import (
    TwitchOAuthClient,
)


logger = logging.getLogger("chimebuddy.discord")


async def run(settings: Settings) -> None:
    database = Database(settings.database_path)
    applied_migrations = await database.initialize()

    if applied_migrations:
        logger.info(
            "Applied database migrations: %s",
            applied_migrations,
        )
    else:
        logger.info(
            "Database schema is already current."
        )

    if settings.discord_token is None:
        raise ConfigurationError(
            "DISCORD_TOKEN is missing."
        )

    if settings.developer_discord_user_id is None:
        raise ConfigurationError(
            "DEVELOPER_DISCORD_USER_ID is missing."
        )

    if settings.discord_guild_id is None:
        raise ConfigurationError(
            "DISCORD_GUILD_ID is missing."
        )

    if settings.twitch_client_id is None:
        raise ConfigurationError(
            "TWITCH_CLIENT_ID is missing."
        )

    if settings.twitch_client_secret is None:
        raise ConfigurationError(
            "TWITCH_CLIENT_SECRET is missing."
        )

    identity_repository = IdentityRepository(
        database
    )
    credential_repository = (
        OAuthCredentialRepository(database)
    )
    session_repository = (
        AccountLinkSessionRepository(database)
    )
    blacklist_repository = (
        BroadcasterBlacklistRepository(database)
    )
    request_repository = (
        BroadcasterRequestRepository(database)
    )

    status_service = DiscordAdminStatusService(
        identity_repository
    )

    onboarding_service = OnboardingService(
        identity_repository=identity_repository,
        credential_repository=(
            credential_repository
        ),
        request_repository=request_repository,
        blacklist_repository=(
            blacklist_repository
        ),
    )

    async with aiohttp.ClientSession() as session:
        device_client = (
            TwitchDeviceAuthorizationClient(
                session=session,
                client_id=settings.twitch_client_id,
            )
        )

        oauth_client = TwitchOAuthClient(
            session=session,
            client_id=settings.twitch_client_id,
            client_secret=(
                settings.twitch_client_secret
            ),
        )

        account_linking_service = (
            AccountLinkingService(
                device_client=device_client,
                oauth_client=oauth_client,
                identity_repository=(
                    identity_repository
                ),
                session_repository=(
                    session_repository
                ),
                completion_repository=(
                    AccountLinkCompletionRepository(
                        database
                    )
                ),
                blacklist_repository=(
                    blacklist_repository
                ),
                onboarding_service=(
                    onboarding_service
                ),
            )
        )

        onboarding_controller = (
            DiscordOnboardingController(
                account_linking_service
            )
        )

        client = ChimeBuddyDiscordClient(
            developer_discord_user_id=(
                settings.developer_discord_user_id
            ),
            discord_guild_id=(
                settings.discord_guild_id
            ),
            status_service=status_service,
            onboarding_controller=(
                onboarding_controller
            ),
        )

        async with client:
            await client.start(
                settings.discord_token
            )


def main() -> None:
    """Start the Discord administration bot."""

    try:
        settings = load_settings()
        settings.validate_for_discord()
    except ConfigurationError as exc:
        raise SystemExit(
            f"Configuration error: {exc}"
        ) from exc

    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format=(
            "%(asctime)s | %(levelname)s | "
            "%(name)s | %(message)s"
        ),
    )

    logger.info(
        "Starting ChimeBuddy Discord admin v%s",
        __version__,
    )
    logger.info(
        "Environment: %s",
        settings.environment,
    )
    logger.info(
        "Database: %s",
        settings.database_path,
    )

    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        logger.info(
            "Discord administration bot stopped."
        )


if __name__ == "__main__":
    main()