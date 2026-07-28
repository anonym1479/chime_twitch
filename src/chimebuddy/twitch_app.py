import asyncio
import logging

from chimebuddy import __version__
from chimebuddy.config import (
    ConfigurationError,
    Settings,
    load_settings,
)
from chimebuddy.database import Database
from chimebuddy.twitch import (
    TwitchStartupError,
    check_bot_credential,
)


logger = logging.getLogger("chimebuddy.twitch")


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

    health = await check_bot_credential(
        settings,
        database,
    )

    logger.info(
        "Twitch bot credential is healthy."
    )
    logger.info(
        "Bot Twitch user ID: %s",
        health.twitch_user_id,
    )
    logger.info(
        "Granted bot scopes: %s",
        ", ".join(health.scopes),
    )

    logger.info(
        "Twitch worker startup health check completed."
    )


def main() -> None:
    """Start the ChimeBuddy Twitch worker."""

    try:
        settings = load_settings()
        settings.validate_for_twitch()
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
        "Starting ChimeBuddy Twitch worker v%s",
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
    except TwitchStartupError as exc:
        raise SystemExit(
            f"Twitch startup error: {exc}"
        ) from exc


if __name__ == "__main__":
    main()