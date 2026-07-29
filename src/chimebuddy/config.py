import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


VALID_ENVIRONMENTS = {
    "development",
    "test",
    "production",
}
VALID_LOG_LEVELS = {
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
}


class ConfigurationError(RuntimeError):
    """Raised when configuration is missing or invalid."""


def _optional_text(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _optional_positive_int(name: str) -> int | None:
    raw_value = os.getenv(name, "").strip()

    if not raw_value:
        return None

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(
            f"{name} must contain a numeric ID."
        ) from exc

    if value <= 0:
        raise ConfigurationError(
            f"{name} must be greater than zero."
        )

    return value


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    database_path: Path
    log_level: str

    twitch_client_id: str | None
    twitch_client_secret: str | None = field(
        repr=False
    )

    discord_token: str | None = field(repr=False)
    developer_discord_user_id: int | None
    discord_guild_id: int | None

    def validate_common(self) -> None:
        if self.environment not in VALID_ENVIRONMENTS:
            allowed = ", ".join(
                sorted(VALID_ENVIRONMENTS)
            )
            raise ConfigurationError(
                "CHIMEBUDDY_ENV must be one of: "
                f"{allowed}."
            )

        if self.log_level not in VALID_LOG_LEVELS:
            allowed = ", ".join(
                sorted(VALID_LOG_LEVELS)
            )
            raise ConfigurationError(
                "CHIMEBUDDY_LOG_LEVEL must be one of: "
                f"{allowed}."
            )

    def validate_for_twitch(self) -> None:
        self.validate_common()

        missing = []

        if not self.twitch_client_id:
            missing.append("TWITCH_CLIENT_ID")

        if not self.twitch_client_secret:
            missing.append("TWITCH_CLIENT_SECRET")

        if missing:
            raise ConfigurationError(
                "Missing Twitch configuration: "
                + ", ".join(missing)
            )

    def validate_for_discord(self) -> None:
        self.validate_common()

        missing = []

        if not self.discord_token:
            missing.append("DISCORD_TOKEN")

        if self.developer_discord_user_id is None:
            missing.append(
                "DEVELOPER_DISCORD_USER_ID"
            )

        if self.discord_guild_id is None:
            missing.append("DISCORD_GUILD_ID")

        if not self.twitch_client_id:
            missing.append("TWITCH_CLIENT_ID")

        if not self.twitch_client_secret:
            missing.append("TWITCH_CLIENT_SECRET")

        if missing:
            raise ConfigurationError(
                "Missing Discord configuration: "
                + ", ".join(missing)
            )


def load_settings(
    env_file: str | Path | None = ".env",
) -> Settings:
    """Load ChimeBuddy settings from the environment."""

    if env_file is not None:
        load_dotenv(
            dotenv_path=env_file,
            override=False,
        )

    environment = os.getenv(
        "CHIMEBUDDY_ENV",
        "development",
    ).strip().lower()

    log_level = os.getenv(
        "CHIMEBUDDY_LOG_LEVEL",
        "INFO",
    ).strip().upper()

    database_value = os.getenv(
        "CHIMEBUDDY_DATABASE_PATH",
        "var/chimebuddy-v2.db",
    ).strip()

    database_path = Path(
        database_value
    ).expanduser()

    if not database_path.is_absolute():
        database_path = (
            Path.cwd() / database_path
        ).resolve()

    settings = Settings(
        environment=environment,
        database_path=database_path,
        log_level=log_level,
        twitch_client_id=_optional_text(
            "TWITCH_CLIENT_ID"
        ),
        twitch_client_secret=_optional_text(
            "TWITCH_CLIENT_SECRET"
        ),
        discord_token=_optional_text(
            "DISCORD_TOKEN"
        ),
        developer_discord_user_id=(
            _optional_positive_int(
                "DEVELOPER_DISCORD_USER_ID"
            )
        ),
        discord_guild_id=_optional_positive_int(
            "DISCORD_GUILD_ID"
        ),
    )

    settings.validate_common()
    return settings