from dataclasses import dataclass


def _required_text(value: object, field_name: str) -> str:
    cleaned = str(value).strip()

    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty.")

    return cleaned


@dataclass(frozen=True, slots=True)
class TwitchChatBadge:
    set_id: str
    badge_id: str
    info: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "set_id",
            _required_text(self.set_id, "set_id"),
        )
        object.__setattr__(
            self,
            "badge_id",
            _required_text(self.badge_id, "badge_id"),
        )
        object.__setattr__(
            self,
            "info",
            str(self.info).strip(),
        )


@dataclass(frozen=True, slots=True)
class TwitchChatMessage:
    broadcaster_twitch_user_id: str
    broadcaster_login: str
    broadcaster_display_name: str

    chatter_twitch_user_id: str
    chatter_login: str
    chatter_display_name: str

    message_id: str
    text: str
    message_type: str
    badges: tuple[TwitchChatBadge, ...] = ()

    @property
    def badge_set_ids(self) -> frozenset[str]:
        return frozenset(
            badge.set_id for badge in self.badges
        )

    @property
    def is_broadcaster(self) -> bool:
        return (
            self.chatter_twitch_user_id
            == self.broadcaster_twitch_user_id
        )

    @property
    def is_moderator(self) -> bool:
        return "moderator" in self.badge_set_ids

    @property
    def is_vip(self) -> bool:
        return "vip" in self.badge_set_ids

    @property
    def is_subscriber(self) -> bool:
        return "subscriber" in self.badge_set_ids
