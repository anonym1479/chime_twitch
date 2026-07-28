import asyncio
import logging

from chimebuddy import __version__
from chimebuddy.config import (
    ConfigurationError,
    Settings,
    load_settings,
)
from chimebuddy.database import Database


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
        logger.info("Database schema is already current.")

    logger.info("Discord admin scaffold is ready.")


def main() -> None:
    """Start the ChimeBuddy Discord administration bot."""

    try:
        settings = load_settings()
        settings.validate_for_discord()
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

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
    logger.info("Environment: %s", settings.environment)
    logger.info("Database: %s", settings.database_path)

    asyncio.run(run(settings))


if __name__ == "__main__":
    main()