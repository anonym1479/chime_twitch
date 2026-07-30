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
    AppSettingsRepository,
    BroadcasterBlacklistRepository,
    BroadcasterRequestRepository,
    IdentityRepository,
    OAuthCredentialRepository,
    BroadcasterPanelRepository,
    TriggerRepository,
)
from chimebuddy.services import (
    AccountLinkingService,
    BroadcasterLifecycleService,
    BroadcasterPanelStatusService,
    BroadcasterProvisioningService,
    OnboardingService,
    ReviewDecisionService,
    TriggerManagementService,
)
from chimebuddy.twitch.device_authorization import (
    TwitchDeviceAuthorizationClient,
)
from chimebuddy.twitch.oauth_client import (
    TwitchOAuthClient,
)
from chimebuddy.discord_admin.review import (
    DiscordReviewController,
)
from chimebuddy.discord_admin.provisioning import (
    DiscordBroadcasterPanelGateway,
)
from chimebuddy.discord_admin.broadcaster_panel import (
    DiscordBroadcasterPanelController,
)
from chimebuddy.discord_admin.trigger_management import (
    DiscordTriggerManagementController,
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

    panel_repository = (
        BroadcasterPanelRepository(database)
    )
    trigger_repository = (
        TriggerRepository(database)
    )

    settings_repository = (
        AppSettingsRepository(database)
    )

    status_service = DiscordAdminStatusService(
        identity_repository
    )

    broadcaster_panel_status_service = (
        BroadcasterPanelStatusService(
            panel_repository=panel_repository,
            identity_repository=(
                identity_repository
            ),
            request_repository=request_repository,
            credential_repository=(
                credential_repository
            ),
            trigger_repository=trigger_repository,
        )
    )

    broadcaster_lifecycle_service = (
        BroadcasterLifecycleService(
            identity_repository=(
                identity_repository
            ),
            credential_repository=(
                credential_repository
            ),
        )
    )

    trigger_management_service = (
        TriggerManagementService(
            trigger_repository=trigger_repository,
            identity_repository=identity_repository,
        )
    )

    trigger_management_controller = (
        DiscordTriggerManagementController(
            management_service=(
                trigger_management_service
            ),
            status_service=(
                broadcaster_panel_status_service
            ),
            developer_discord_user_id=(
                settings.developer_discord_user_id
            ),
        )
    )

    broadcaster_panel_controller = (
        DiscordBroadcasterPanelController(
            status_service=(
                broadcaster_panel_status_service
            ),
            lifecycle_service=(
                broadcaster_lifecycle_service
            ),
            panel_repository=panel_repository,
            developer_discord_user_id=(
                settings.developer_discord_user_id
            ),
            trigger_management_controller=(
                trigger_management_controller
            ),
        )
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

    panel_gateway = (
        DiscordBroadcasterPanelGateway(
            settings_repository=(
                settings_repository
            ),
            discord_guild_id=(
                settings.discord_guild_id
            ),
        )
    )

    provisioning_service = (
        BroadcasterProvisioningService(
            onboarding_service=(
                onboarding_service
            ),
            identity_repository=(
                identity_repository
            ),
            request_repository=(
                request_repository
            ),
            panel_repository=(
                panel_repository
            ),
            panel_gateway=panel_gateway,
        )
    )

    review_decision_service = (
        ReviewDecisionService(
            request_repository
        )
    )

    review_controller = (
        DiscordReviewController(
            settings_repository=settings_repository,
            request_repository=request_repository,
            identity_repository=identity_repository,
            decision_service=(
                review_decision_service
            ),
            developer_discord_user_id=(
                settings.developer_discord_user_id
            ),
            provisioning_service=(
                provisioning_service
            ),
        )
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
                account_linking_service,
                review_controller=review_controller,
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
            review_controller=review_controller,
            broadcaster_panel_controller=(
                broadcaster_panel_controller
            ),
        )

        panel_gateway.bind_client(client)

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