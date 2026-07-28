from __future__ import annotations

import asyncio
import logging
import signal

from chimebuddy.database import Database
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
from chimebuddy.twitch.runtime import TwitchRuntime


logger = logging.getLogger("chimebuddy.twitch.worker")

TITLE_POLL_INTERVAL_SECONDS = 60
TOKEN_VALIDATION_INTERVAL_SECONDS = 3600


class TwitchWorkerError(RuntimeError):
    """Raised when a background worker service fails."""


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