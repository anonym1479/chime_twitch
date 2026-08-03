import re
from dataclasses import dataclass
from enum import StrEnum


CUSTOM_COMMAND_NAME_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9_-]*$"
)


def _required_text(
    value: object,
    field_name: str,
) -> str:
    cleaned = str(value).strip()

    if not cleaned:
        raise ValueError(
            f"{field_name} cannot be empty."
        )

    return cleaned


def _optional_text(value: object | None) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()
    return cleaned or None


class CustomCommandPermission(StrEnum):
    EVERYONE = "everyone"
    SUBSCRIBER = "subscriber"
    VIP = "vip"
    MODERATOR = "moderator"
    BROADCASTER = "broadcaster"


@dataclass(frozen=True, slots=True)
class CustomCommand:
    broadcaster_twitch_user_id: str
    name: str
    response_message: str
    permission: CustomCommandPermission = (
        CustomCommandPermission.EVERYONE
    )
    cooldown_seconds: int = 30
    enabled: bool = True
    command_id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "broadcaster_twitch_user_id",
            _required_text(
                self.broadcaster_twitch_user_id,
                "broadcaster_twitch_user_id",
            ),
        )

        normalized_name = self.normalize_name(self.name)

        if not CUSTOM_COMMAND_NAME_PATTERN.fullmatch(
            normalized_name
        ):
            raise ValueError(
                "name must begin with a letter or number "
                "and contain only lowercase letters, "
                "numbers, underscores, or hyphens."
            )

        object.__setattr__(
            self,
            "name",
            normalized_name,
        )

        response = _required_text(
            self.response_message,
            "response_message",
        )

        if "\n" in response or "\r" in response:
            raise ValueError(
                "response_message must be a single line."
            )

        object.__setattr__(
            self,
            "response_message",
            response,
        )
        object.__setattr__(
            self,
            "permission",
            CustomCommandPermission(self.permission),
        )

        cooldown = int(self.cooldown_seconds)

        if cooldown < 0:
            raise ValueError(
                "cooldown_seconds cannot be negative."
            )

        object.__setattr__(
            self,
            "cooldown_seconds",
            cooldown,
        )
        object.__setattr__(
            self,
            "enabled",
            bool(self.enabled),
        )

        if self.command_id is not None:
            command_id = int(self.command_id)

            if command_id <= 0:
                raise ValueError(
                    "command_id must be greater than zero."
                )

            object.__setattr__(
                self,
                "command_id",
                command_id,
            )

        object.__setattr__(
            self,
            "created_at",
            _optional_text(self.created_at),
        )
        object.__setattr__(
            self,
            "updated_at",
            _optional_text(self.updated_at),
        )

    @staticmethod
    def normalize_name(value: object) -> str:
        return _required_text(
            value,
            "name",
        ).casefold()
