from collections.abc import Mapping
from typing import Any

from chimebuddy.models.chat import (
    TwitchChatBadge,
    TwitchChatMessage,
)


class EventSubMessageError(ValueError):
    """Raised when an EventSub message is malformed."""


def _mapping(
    value: object,
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EventSubMessageError(
            f"{field_name} must be an object."
        )

    return value


def _required_text(
    data: Mapping[str, Any],
    field_name: str,
) -> str:
    value = data.get(field_name)

    if value is None:
        raise EventSubMessageError(
            f"EventSub message is missing {field_name}."
        )

    cleaned = str(value).strip()

    if not cleaned:
        raise EventSubMessageError(
            f"EventSub field {field_name} cannot be empty."
        )

    return cleaned


def parse_channel_chat_message(
    envelope: Mapping[str, Any],
) -> TwitchChatMessage:
    metadata = _mapping(
        envelope.get("metadata"),
        "metadata",
    )

    if _required_text(
        metadata,
        "message_type",
    ) != "notification":
        raise EventSubMessageError(
            "EventSub message is not a notification."
        )

    if _required_text(
        metadata,
        "subscription_type",
    ) != "channel.chat.message":
        raise EventSubMessageError(
            "EventSub notification is not a chat message."
        )

    payload = _mapping(
        envelope.get("payload"),
        "payload",
    )
    event = _mapping(
        payload.get("event"),
        "payload.event",
    )
    message = _mapping(
        event.get("message"),
        "payload.event.message",
    )

    raw_badges = event.get("badges", [])

    if not isinstance(raw_badges, list):
        raise EventSubMessageError(
            "payload.event.badges must be a list."
        )

    badges: list[TwitchChatBadge] = []

    for index, raw_badge in enumerate(raw_badges):
        badge = _mapping(
            raw_badge,
            f"payload.event.badges[{index}]",
        )

        badges.append(
            TwitchChatBadge(
                set_id=_required_text(
                    badge,
                    "set_id",
                ),
                badge_id=_required_text(
                    badge,
                    "id",
                ),
                info=str(
                    badge.get("info", "")
                ).strip(),
            )
        )

    return TwitchChatMessage(
        broadcaster_twitch_user_id=_required_text(
            event,
            "broadcaster_user_id",
        ),
        broadcaster_login=_required_text(
            event,
            "broadcaster_user_login",
        ).lower(),
        broadcaster_display_name=_required_text(
            event,
            "broadcaster_user_name",
        ),
        chatter_twitch_user_id=_required_text(
            event,
            "chatter_user_id",
        ),
        chatter_login=_required_text(
            event,
            "chatter_user_login",
        ).lower(),
        chatter_display_name=_required_text(
            event,
            "chatter_user_name",
        ),
        message_id=_required_text(
            event,
            "message_id",
        ),
        text=_required_text(
            message,
            "text",
        ),
        message_type=_required_text(
            event,
            "message_type",
        ),
        badges=tuple(badges),
    )