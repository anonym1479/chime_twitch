import logging

from chimebuddy import __version__


logger = logging.getLogger("chimebuddy.twitch")


def main() -> None:
    """Start the ChimeBuddy Twitch worker."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    logger.info("Starting ChimeBuddy Twitch worker v%s", __version__)
    logger.info("Twitch worker scaffold is ready.")


if __name__ == "__main__":
    main()