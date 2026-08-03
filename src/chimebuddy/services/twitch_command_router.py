from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import IntEnum

from chimebuddy.models.chat import TwitchChatMessage


logger = logging.getLogger(
    "chimebuddy.twitch.commands"
)

V2PING_COMMAND_NAME = "v2ping"

CORE_TWITCH_COMMAND_NAMES = frozenset(
    {
        V2PING_COMMAND_NAME,
    }
)


class TwitchCommandPermission(IntEnum):
    """
    Minimum permission required by a Twitch command.

    Higher roles may use commands belonging to lower roles.
    """

    EVERYONE = 0
    SUBSCRIBER = 5
    VIP = 10
    MODERATOR = 20
    BROADCASTER = 30


@dataclass(frozen=True, slots=True)
class TwitchCommandContext:
    message: TwitchChatMessage
    command_name: str
    arguments: tuple[str, ...]
    raw_arguments: str


CommandHandler = Callable[
    [TwitchCommandContext],
    Awaitable[None],
]


@dataclass(frozen=True, slots=True)
class RegisteredTwitchCommand:
    name: str
    minimum_permission: TwitchCommandPermission
    handler: CommandHandler


class TwitchCommandRouter:
    """Routes Twitch chat commands after permission checks."""

    def __init__(
        self,
        *,
        prefix: str = "_",
    ) -> None:
        cleaned_prefix = str(prefix).strip()

        if not cleaned_prefix:
            raise ValueError(
                "Command prefix cannot be empty."
            )

        self.prefix = cleaned_prefix

        self._commands: dict[
            str,
            RegisteredTwitchCommand,
        ] = {}

    def register(
        self,
        name: str,
        minimum_permission: TwitchCommandPermission,
        handler: CommandHandler,
    ) -> None:
        normalized_name = self._normalize_name(name)

        if normalized_name in self._commands:
            raise ValueError(
                f"Command is already registered: "
                f"{normalized_name}"
            )

        self._commands[normalized_name] = (
            RegisteredTwitchCommand(
                name=normalized_name,
                minimum_permission=(
                    minimum_permission
                ),
                handler=handler,
            )
        )

    async def route(
        self,
        message: TwitchChatMessage,
    ) -> bool:
        parsed = self._parse(message)

        if parsed is None:
            return False

        command_name, arguments, raw_arguments = parsed

        command = self._commands.get(command_name)

        if command is None:
            return False

        actual_permission = self.permission_for(
            message
        )

        if (
            actual_permission
            < command.minimum_permission
        ):
            logger.warning(
                "Denied Twitch command %s from "
                "user %s in channel %s. "
                "Required: %s; actual: %s.",
                command_name,
                message.chatter_twitch_user_id,
                message.broadcaster_twitch_user_id,
                command.minimum_permission.name.lower(),
                actual_permission.name.lower(),
            )
            return False

        context = TwitchCommandContext(
            message=message,
            command_name=command_name,
            arguments=arguments,
            raw_arguments=raw_arguments,
        )

        await command.handler(context)
        return True

    def _parse(
        self,
        message: TwitchChatMessage,
    ) -> tuple[
        str,
        tuple[str, ...],
        str,
    ] | None:
        text = message.text.strip()

        if not text.startswith(self.prefix):
            return None

        command_text = text[
            len(self.prefix):
        ].strip()

        if not command_text:
            return None

        command_parts = command_text.split()

        command_name = self._normalize_name(
            command_parts[0]
        )
        arguments = tuple(command_parts[1:])

        raw_arguments = command_text[
            len(command_parts[0]):
        ].strip()

        return (
            command_name,
            arguments,
            raw_arguments,
        )

    @staticmethod
    def permission_for(
        message: TwitchChatMessage,
    ) -> TwitchCommandPermission:
        if message.is_broadcaster:
            return TwitchCommandPermission.BROADCASTER

        if message.is_moderator:
            return TwitchCommandPermission.MODERATOR

        if message.is_vip:
            return TwitchCommandPermission.VIP

        if message.is_subscriber:
            return TwitchCommandPermission.SUBSCRIBER

        return TwitchCommandPermission.EVERYONE

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = str(name).strip().casefold()

        if not normalized:
            raise ValueError(
                "Command name cannot be empty."
            )

        if any(character.isspace() for character in normalized):
            raise ValueError(
                "Command name cannot contain whitespace."
            )

        return normalized
