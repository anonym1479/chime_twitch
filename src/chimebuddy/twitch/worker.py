from __future__ import annotations

import asyncio
import logging
import signal

from chimebuddy.database import Database
from chimebuddy.models.chat import TwitchChatMessage
from chimebuddy.repositories import (
    IdentityRepository,
    TriggerRepository,
)
from chimebuddy.services.stream_title_monitor import (
    StreamTitleMonitor,
)
from chimebuddy.services.trigger_coordinator import (
    TriggerCoordinator,
)
from chimebuddy.services.trigger_matcher import (
    TitleTriggerMatcher,
)
from chimebuddy.services.trigger_state_machine import (
    TriggerStateMachine,
)
from chimebuddy.twitch.eventsub_websocket import (
    EventSubWebSocketService,
)
from chimebuddy.services.twitch_command_router import (
    TwitchCommandContext,
    TwitchCommandPermission,
    TwitchCommandRouter,
)
from chimebuddy.twitch.runtime import TwitchRuntime


logger = logging.getLogger("chimebuddy.twitch.worker")

TITLE_POLL_INTERVAL_SECONDS = 60
TOKEN_VALIDATION_INTERVAL_SECONDS = 3600


class TwitchWorkerError(RuntimeError):
    """Raised when a background worker service fails."""


class RoutedChatMessageHandler:
    """Logs chat messages and routes Twitch commands."""

    def __init__(
        self,
        bot_twitch_user_id: str,
        command_router: TwitchCommandRouter,
    ) -> None:
        self.bot_twitch_user_id = str(
            bot_twitch_user_id
        ).strip()
        self.command_router = command_router

    async def handle_chat_message(
        self,
        message: TwitchChatMessage,
    ) -> None:
        # Prevent ChimeBuddy from handling its own replies.
        if (
            message.chatter_twitch_user_id
            == self.bot_twitch_user_id
        ):
            return

        role = self._role_for(message)

        log_method = (
            logger.info
            if message.text.lstrip().startswith("_")
            else logger.debug
        )

        log_method(
            "[%s] %s (%s): %s",
            message.broadcaster_login,
            message.chatter_login,
            role,
            message.text,
        )

        await self.command_router.route(message)

    @staticmethod
    def _role_for(
        message: TwitchChatMessage,
    ) -> str:
        if message.is_broadcaster:
            return "broadcaster"

        if message.is_moderator:
            return "moderator"

        if message.is_vip:
            return "vip"

        return "viewer"


def create_command_router(
    runtime: TwitchRuntime,
) -> TwitchCommandRouter:
    router = TwitchCommandRouter(prefix="_")

    async def handle_v2ping(
        context: TwitchCommandContext,
    ) -> None:
        await runtime.helix_gateway.send_message(
            context.message.broadcaster_twitch_user_id,
            "ChimeBuddy V2 is online.",
        )

    router.register(
        "v2ping",
        TwitchCommandPermission.BROADCASTER,
        handle_v2ping,
    )

    return router


def create_title_monitor(
    database: Database,
    runtime: TwitchRuntime,
) -> StreamTitleMonitor:
    identity_repository = IdentityRepository(database)
    trigger_repository = TriggerRepository(database)

    coordinator = TriggerCoordinator(
        repository=trigger_repository,
        matcher=TitleTriggerMatcher(),
        state_machine=TriggerStateMachine(),
        chat_gateway=runtime.helix_gateway,
        pin_gateway=runtime.helix_gateway,
    )

    return StreamTitleMonitor(
        identity_repository=identity_repository,
        stream_gateway=runtime.helix_gateway,
        trigger_coordinator=coordinator,
        poll_interval_seconds=(
            TITLE_POLL_INTERVAL_SECONDS
        ),
    )


async def create_eventsub_service(
    database: Database,
    runtime: TwitchRuntime,
) -> EventSubWebSocketService | None:
    identity_repository = IdentityRepository(database)

    broadcasters = (
        await identity_repository.list_broadcasters(
            enabled_only=True
        )
    )

    broadcaster_ids = tuple(
        broadcaster.twitch_user_id
        for broadcaster in broadcasters
    )

    if not broadcaster_ids:
        logger.warning(
            "No enabled broadcasters exist. "
            "EventSub chat reception will not start."
        )
        return None

    logger.info(
        "Preparing EventSub chat reception for "
        "%s broadcaster(s).",
        len(broadcaster_ids),
    )

    return EventSubWebSocketService(
        session=runtime.session,
        subscription_client=(
            runtime.eventsub_subscription_client
        ),
        broadcaster_twitch_user_ids=(
            broadcaster_ids
        ),
        chat_message_handler=(
            RoutedChatMessageHandler(
                runtime.bot_twitch_user_id,
                create_command_router(runtime),
            )
        ),
    )


async def token_validation_loop(
    runtime: TwitchRuntime,
    stop_event: asyncio.Event,
    *,
    validation_interval_seconds: float = (
        TOKEN_VALIDATION_INTERVAL_SECONDS
    ),
) -> None:
    if validation_interval_seconds <= 0:
        raise ValueError(
            "validation_interval_seconds must be positive."
        )

    logger.info(
        "Hourly Twitch token validation started."
    )

    while not stop_event.is_set():
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=validation_interval_seconds,
            )
            break
        except TimeoutError:
            pass

        logger.info(
            "Running scheduled Twitch token validation."
        )

        await runtime.token_manager.validate_registered()

        logger.info(
            "Scheduled Twitch token validation succeeded."
        )

    logger.info(
        "Twitch token validation stopped."
    )


async def run_twitch_worker(
    database: Database,
    runtime: TwitchRuntime,
) -> None:
    stop_event = asyncio.Event()

    remove_signal_handlers = (
        _install_signal_handlers(stop_event)
    )

    title_monitor = create_title_monitor(
        database,
        runtime,
    )

    eventsub_service = await create_eventsub_service(
        database,
        runtime,
    )

    tasks = [
        asyncio.create_task(
            title_monitor.run(stop_event),
            name="stream-title-monitor",
        ),
        asyncio.create_task(
            token_validation_loop(
                runtime,
                stop_event,
            ),
            name="token-validation",
        ),
    ]

    if eventsub_service is not None:
        tasks.append(
            asyncio.create_task(
                eventsub_service.run(stop_event),
                name="eventsub-websocket",
            )
        )

    for task in tasks:
        task.add_done_callback(
            lambda completed_task: stop_event.set()
        )

    logger.info(
        "ChimeBuddy Twitch worker is running."
    )
    logger.info(
        "Press Ctrl+C to stop it gracefully."
    )

    try:
        await stop_event.wait()

        results = await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        failures = [
            result
            for result in results
            if isinstance(result, BaseException)
            and not isinstance(
                result,
                asyncio.CancelledError,
            )
        ]

        if failures:
            raise TwitchWorkerError(
                "A Twitch worker service stopped "
                f"unexpectedly: {failures[0]}"
            ) from failures[0]

    finally:
        stop_event.set()

        for task in tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        remove_signal_handlers()

        logger.info(
            "ChimeBuddy Twitch worker stopped."
        )


def _install_signal_handlers(
    stop_event: asyncio.Event,
):
    loop = asyncio.get_running_loop()
    installed_signals = []

    for signal_value in (
        signal.SIGINT,
        signal.SIGTERM,
    ):
        try:
            loop.add_signal_handler(
                signal_value,
                stop_event.set,
            )
            installed_signals.append(signal_value)
        except (
            NotImplementedError,
            RuntimeError,
        ):
            continue

    def remove_handlers() -> None:
        for signal_value in installed_signals:
            loop.remove_signal_handler(signal_value)

    return remove_handlers