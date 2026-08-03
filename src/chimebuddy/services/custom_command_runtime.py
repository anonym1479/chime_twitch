from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Protocol

from chimebuddy.models import (
    CustomCommand,
    CustomCommandPermission,
)
from chimebuddy.models.chat import TwitchChatMessage
from chimebuddy.repositories import CustomCommandRepository
from chimebuddy.services.twitch_command_router import (
    CORE_TWITCH_COMMAND_NAMES,
    TwitchCommandPermission,
    TwitchCommandRouter,
)


logger = logging.getLogger(
    "chimebuddy.twitch.custom_commands"
)

RuntimeClock = Callable[[], float]


class CustomCommandChatGateway(Protocol):
    async def send_message(
        self,
        broadcaster_twitch_user_id: str,
        message: str,
    ) -> str:
        """Send a custom-command response to Twitch chat."""


class CustomCommandRuntime:
    """Executes enabled broadcaster commands safely."""

    def __init__(
        self,
        *,
        command_repository: CustomCommandRepository,
        chat_gateway: CustomCommandChatGateway,
        prefix: str = "_",
        clock: RuntimeClock = time.monotonic,
        reserved_names: frozenset[str] = (
            CORE_TWITCH_COMMAND_NAMES
        ),
    ) -> None:
        cleaned_prefix = str(prefix).strip()

        if not cleaned_prefix:
            raise ValueError(
                "Command prefix cannot be empty."
            )

        self.command_repository = command_repository
        self.chat_gateway = chat_gateway
        self.prefix = cleaned_prefix
        self.clock = clock
        self.reserved_names = frozenset(
            CustomCommand.normalize_name(name)
            for name in reserved_names
        )
        self._next_allowed_at: dict[int, float] = {}
        self._command_locks: dict[int, asyncio.Lock] = {}

    async def route(
        self,
        message: TwitchChatMessage,
    ) -> bool:
        command_name = self._parse_name(message.text)

        if (
            command_name is None
            or command_name in self.reserved_names
        ):
            return False

        command = (
            await self.command_repository
            .get_enabled_by_name(
                message.broadcaster_twitch_user_id,
                command_name,
            )
        )

        if command is None:
            return False

        lock = self._command_locks.setdefault(
            command.command_id,
            asyncio.Lock(),
        )

        async with lock:
            current = await self.command_repository.get(
                command.command_id
            )

            if (
                current is None
                or not current.enabled
                or current.broadcaster_twitch_user_id
                != message.broadcaster_twitch_user_id
                or current.name != command_name
            ):
                return False

            if not self._has_permission(current, message):
                logger.info(
                    "Denied custom Twitch command: "
                    "broadcaster=%s, command=%s, name=%r, "
                    "user=%s, required=%s, actual=%s.",
                    current.broadcaster_twitch_user_id,
                    current.command_id,
                    current.name,
                    message.chatter_twitch_user_id,
                    current.permission.value,
                    TwitchCommandRouter.permission_for(
                        message
                    ).name.lower(),
                )
                return False

            now = float(self.clock())
            next_allowed_at = self._next_allowed_at.get(
                current.command_id,
                0.0,
            )

            if now < next_allowed_at:
                logger.debug(
                    "Custom Twitch command suppressed by "
                    "cooldown: broadcaster=%s, command=%s, "
                    "name=%r, remaining_seconds=%.1f.",
                    current.broadcaster_twitch_user_id,
                    current.command_id,
                    current.name,
                    next_allowed_at - now,
                )
                return True

            try:
                await self.chat_gateway.send_message(
                    current.broadcaster_twitch_user_id,
                    current.response_message,
                )
            except Exception as exc:
                # Avoid hammering Twitch if a channel sends the
                # command repeatedly during a transient outage.
                self._next_allowed_at[current.command_id] = (
                    now
                    + min(current.cooldown_seconds, 30)
                )
                logger.error(
                    "Custom Twitch command response failed: "
                    "broadcaster=%s, command=%s, name=%r, "
                    "error_type=%s.",
                    current.broadcaster_twitch_user_id,
                    current.command_id,
                    current.name,
                    type(exc).__name__,
                )
                return True

            self._next_allowed_at[current.command_id] = (
                now + current.cooldown_seconds
            )

            logger.info(
                "Custom Twitch command executed: "
                "broadcaster=%s, command=%s, name=%r, "
                "permission=%s, cooldown_seconds=%s.",
                current.broadcaster_twitch_user_id,
                current.command_id,
                current.name,
                current.permission.value,
                current.cooldown_seconds,
            )
            return True

    def _parse_name(self, text: str) -> str | None:
        cleaned = str(text).strip()

        if not cleaned.startswith(self.prefix):
            return None

        command_text = cleaned[len(self.prefix):].strip()

        if not command_text:
            return None

        raw_name = command_text.split(maxsplit=1)[0]

        try:
            return CustomCommand.normalize_name(raw_name)
        except ValueError:
            return None

    @staticmethod
    def _has_permission(
        command: CustomCommand,
        message: TwitchChatMessage,
    ) -> bool:
        required = {
            CustomCommandPermission.EVERYONE: (
                TwitchCommandPermission.EVERYONE
            ),
            CustomCommandPermission.SUBSCRIBER: (
                TwitchCommandPermission.SUBSCRIBER
            ),
            CustomCommandPermission.VIP: (
                TwitchCommandPermission.VIP
            ),
            CustomCommandPermission.MODERATOR: (
                TwitchCommandPermission.MODERATOR
            ),
            CustomCommandPermission.BROADCASTER: (
                TwitchCommandPermission.BROADCASTER
            ),
        }[command.permission]

        return (
            TwitchCommandRouter.permission_for(message)
            >= required
        )
