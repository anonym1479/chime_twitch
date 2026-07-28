import logging

from chimebuddy import __version__


logger = logging.getLogger("chimebuddy.discord")


def main() -> None:
    """Start the ChimeBuddy Discord administration bot."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    logger.info("Starting ChimeBuddy Discord admin v%s", __version__)
    logger.info("Discord admin scaffold is ready.")


if __name__ == "__main__":
    main()