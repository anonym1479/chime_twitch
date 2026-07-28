import logging

from chimebuddy import __version__
from chimebuddy.config import ConfigurationError, load_settings


logger = logging.getLogger("chimebuddy.twitch")


def main() -> None:
    """Start the ChimeBuddy Twitch worker."""

    try:
        settings = load_settings()
        settings.validate_for_twitch()
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    logger.info("Starting ChimeBuddy Twitch worker v%s", __version__)
    logger.info("Environment: %s", settings.environment)
    logger.info("Database: %s", settings.database_path)
    logger.info("Twitch worker configuration is valid.")


if __name__ == "__main__":
    main()