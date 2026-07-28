from dataclasses import dataclass
from enum import StrEnum


def _clean_required(value: str, field_name: str) -> str:
    cleaned = str(value).strip()

    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty.")

    return cleaned


class AccountLinkStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class TwitchAccount:
    twitch_user_id: str
    login: str
    display_name: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "twitch_user_id",
            _clean_required(
                self.twitch_user_id,
                "twitch_user_id",
            ),
        )
        object.__setattr__(
            self,
            "login",
            _clean_required(self.login, "login").lower(),
        )
        object.__setattr__(
            self,
            "display_name",
            _clean_required(
                self.display_name,
                "display_name",
            ),
        )


@dataclass(frozen=True, slots=True)
class DiscordAccount:
    discord_user_id: str
    username: str
    display_name: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "discord_user_id",
            _clean_required(
                self.discord_user_id,
                "discord_user_id",
            ),
        )
        object.__setattr__(
            self,
            "username",
            _clean_required(self.username, "username"),
        )
        object.__setattr__(
            self,
            "display_name",
            _clean_required(
                self.display_name,
                "display_name",
            ),
        )


@dataclass(frozen=True, slots=True)
class AccountLink:
    twitch_user_id: str
    discord_user_id: str
    status: AccountLinkStatus
    verification_method: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "twitch_user_id",
            _clean_required(
                self.twitch_user_id,
                "twitch_user_id",
            ),
        )
        object.__setattr__(
            self,
            "discord_user_id",
            _clean_required(
                self.discord_user_id,
                "discord_user_id",
            ),
        )

        if self.verification_method is not None:
            cleaned_method = self.verification_method.strip()
            object.__setattr__(
                self,
                "verification_method",
                cleaned_method or None,
            )


@dataclass(frozen=True, slots=True)
class Broadcaster:
    twitch_user_id: str
    owner_discord_user_id: str
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "twitch_user_id",
            _clean_required(
                self.twitch_user_id,
                "twitch_user_id",
            ),
        )
        object.__setattr__(
            self,
            "owner_discord_user_id",
            _clean_required(
                self.owner_discord_user_id,
                "owner_discord_user_id",
            ),
        )


@dataclass(frozen=True, slots=True)
class BroadcasterProfile:
    twitch_user_id: str
    twitch_login: str
    twitch_display_name: str
    owner_discord_user_id: str
    owner_discord_username: str
    owner_discord_display_name: str
    enabled: bool
    link_status: AccountLinkStatus