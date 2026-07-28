import logging

from chimebuddy import __version__
from chimebuddy.config import ConfigurationError, load_settings


logger = logging.getLogger("chimebuddy.discord")


def main() -> None:
    """Start the ChimeBuddy Discord administration bot."""

    try:
        settings = load_settings()
        settings.validate_for_discord()
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    logger.info("Starting ChimeBuddy Discord admin v%s", __version__)
    logger.info("Environment: %s", settings.environment)
    logger.info("Database: %s", settings.database_path)
    logger.info("Discord admin configuration is valid.")


if __name__ == "__main__":
    main()