from __future__ import annotations

import asyncio
import logging
import signal

from collections.abc import Awaitable, Callable
from typing import Protocol

from chimebuddy.database import Database
from chimebuddy.models import OAuthCredentialKind
from chimebuddy.models.chat import TwitchChatMessage
from chimebuddy.repositories import (
    BroadcasterRequestRepository,
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
from chimebuddy.services.twitch_command_router import (
    TwitchCommandContext,
    TwitchCommandPermission,
    TwitchCommandRouter,
)
from chimebuddy.twitch.eventsub_websocket import (
    EventSubWebSocketService,
)
from chimebuddy.twitch.oauth_client import TwitchOAuthError
from chimebuddy.twitch.runtime import TwitchRuntime
from chimebuddy.twitch.scopes import (
    BROADCASTER_CHAT_SCOPES,
)
from chimebuddy.twitch.token_manager import (
    CredentialNotFoundError,
    MissingScopesError,
    ReauthorizationRequiredError,
    TokenClientMismatchError,
    TokenIdentityMismatchError,
)


logger = logging.getLogger(
    "chimebuddy.twitch.worker"
)

TITLE_POLL_INTERVAL_SECONDS = 60
TOKEN_VALIDATION_INTERVAL_SECONDS = 3600
BROADCASTER_SYNC_INTERVAL_SECONDS = 30


class TwitchWorkerError(RuntimeError):
    """Raised when a background worker service fails."""


class EventSubServiceFactory(Protocol):
    def __call__(
        self,
        broadcaster_twitch_user_ids: tuple[str, ...],
    ) -> EventSubWebSocketService:
        """Create an EventSub service for these IDs."""

BroadcasterCleanup = Callable[
    [tuple[str, ...]],
    Awaitable[None],
]

BroadcasterReauthorizationHandler = Callable[
    [str, str],
    Awaitable[None],
]

BROADCASTER_REAUTHORIZATION_ERRORS = (
    CredentialNotFoundError,
    MissingScopesError,
    ReauthorizationRequiredError,
    TokenClientMismatchError,
    TokenIdentityMismatchError,
)

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


def create_eventsub_service(
    runtime: TwitchRuntime,
    broadcaster_twitch_user_ids: tuple[str, ...],
) -> EventSubWebSocketService:
    logger.info(
        "Preparing EventSub chat reception for "
        "%s broadcaster(s).",
        len(broadcaster_twitch_user_ids),
    )

    return EventSubWebSocketService(
        session=runtime.session,
        subscription_client=(
            runtime.eventsub_subscription_client
        ),
        broadcaster_twitch_user_ids=(
            broadcaster_twitch_user_ids
        ),
        chat_message_handler=(
            RoutedChatMessageHandler(
                runtime.bot_twitch_user_id,
                create_command_router(runtime),
            )
        ),
    )


async def load_enabled_broadcaster_ids(
    identity_repository: IdentityRepository,
) -> tuple[str, ...]:
    broadcasters = (
        await identity_repository.list_broadcasters(
            enabled_only=True
        )
    )

    return tuple(
        sorted(
            broadcaster.twitch_user_id
            for broadcaster in broadcasters
        )
    )

async def cleanup_broadcaster_triggers(
    trigger_coordinator: TriggerCoordinator,
    broadcaster_twitch_user_ids: tuple[str, ...],
) -> None:
    """
    Deactivate trigger messages before broadcasters
    leave the active worker set.
    """

    for broadcaster_id in broadcaster_twitch_user_ids:
        report = await trigger_coordinator.process_title(
            broadcaster_id,
            "",
        )

        if report.errors:
            errors_text = "; ".join(report.errors)

            raise TwitchWorkerError(
                "Trigger cleanup failed for broadcaster "
                f"{broadcaster_id}: {errors_text}"
            )

        logger.info(
            "Cleaned broadcaster trigger state before "
            "deactivation: broadcaster_id=%s, "
            "deactivated=%s, reset=%s.",
            broadcaster_id,
            (
                report.deactivated_trigger_ids
                or "none"
            ),
            report.reset_trigger_ids or "none",
        )

async def eventsub_supervisor_loop(
    identity_repository: IdentityRepository,
    service_factory: EventSubServiceFactory,
    stop_event: asyncio.Event,
    *,
    broadcaster_cleanup:(
        BroadcasterCleanup | None
    ) = None,
    sync_interval_seconds: float = (
        BROADCASTER_SYNC_INTERVAL_SECONDS
    ),
) -> None:
    """
    Keep EventSub synchronized with enabled broadcasters.

    Only the EventSub child connection is restarted when
    the broadcaster list changes.
    """

    if sync_interval_seconds <= 0:
        raise ValueError(
            "sync_interval_seconds must be positive."
        )

    current_ids: tuple[str, ...] | None = None
    eventsub_task: asyncio.Task | None = None
    eventsub_stop_event: asyncio.Event | None = None

    logger.info(
        "Broadcaster synchronization started with a "
        "%s-second interval.",
        sync_interval_seconds,
    )

    try:
        while not stop_event.is_set():
            if (
                eventsub_task is not None
                and eventsub_task.done()
            ):
                try:
                    await eventsub_task
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    raise TwitchWorkerError(
                        "The EventSub child service "
                        f"stopped unexpectedly: {exc}"
                    ) from exc

                raise TwitchWorkerError(
                    "The EventSub child service stopped "
                    "unexpectedly without an error."
                )

            desired_ids = (
                await load_enabled_broadcaster_ids(
                    identity_repository
                )
            )

            if desired_ids != current_ids:
                previous_ids = current_ids or ()

                added_ids = tuple(
                    sorted(
                        set(desired_ids)
                        - set(previous_ids)
                    )
                )
                removed_ids = tuple(
                    sorted(
                        set(previous_ids)
                        - set(desired_ids)
                    )
                )

                cleanup_succeeded = True

                if (
                    removed_ids
                    and broadcaster_cleanup is not None
                ):
                    try:
                        await broadcaster_cleanup(
                            removed_ids
                        )
                    except Exception:
                        cleanup_succeeded = False

                        logger.exception(
                            "Broadcaster removal cleanup "
                            "failed for %s. The Twitch "
                            "worker will retry before "
                            "removing these broadcasters.",
                            removed_ids,
                        )

                if cleanup_succeeded:
                    if (
                        eventsub_task is not None
                        and eventsub_stop_event is not None
                    ):
                        eventsub_stop_event.set()

                        result = await asyncio.gather(
                            eventsub_task,
                            return_exceptions=True,
                        )

                        child_result = result[0]

                        if (
                            isinstance(
                                child_result,
                                BaseException,
                            )
                            and not isinstance(
                                child_result,
                                asyncio.CancelledError,
                            )
                        ):
                            raise TwitchWorkerError(
                                "The EventSub child service "
                                "failed while reconfiguring."
                            ) from child_result

                        eventsub_task = None
                        eventsub_stop_event = None

                    current_ids = desired_ids

                    logger.info(
                        "Enabled broadcaster list changed. "
                        "Total: %s, added: %s, removed: %s.",
                        len(current_ids),
                        added_ids or "none",
                        removed_ids or "none",
                    )

                    if current_ids:
                        service = service_factory(
                            current_ids
                        )

                        eventsub_stop_event = (
                            asyncio.Event()
                        )

                        eventsub_task = (
                            asyncio.create_task(
                                service.run(
                                    eventsub_stop_event
                                ),
                                name="eventsub-websocket",
                            )
                        )

                    else:
                        logger.warning(
                            "No enabled broadcasters "
                            "exist. EventSub is waiting "
                            "for a broadcaster to be "
                            "activated."
                        )

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=sync_interval_seconds,
                )
            except TimeoutError:
                pass

    finally:
        if (
            eventsub_task is not None
            and eventsub_stop_event is not None
        ):
            eventsub_stop_event.set()

            await asyncio.gather(
                eventsub_task,
                return_exceptions=True,
            )

    logger.info(
        "Broadcaster synchronization stopped."
    )


async def validate_enabled_broadcaster_credentials(
    runtime: TwitchRuntime,
    identity_repository: IdentityRepository,
    reauthorization_handler: (
        BroadcasterReauthorizationHandler
    ),
) -> None:
    """
    Validate broadcasters independently.

    Permanent authorization failures pause only the
    affected broadcaster. Temporary Twitch failures are
    logged and retried during the next validation cycle.
    """

    broadcaster_ids = await load_enabled_broadcaster_ids(
        identity_repository
    )

    for broadcaster_id in broadcaster_ids:
        try:
            await runtime.token_manager.validate_now(
                broadcaster_id,
                OAuthCredentialKind.BROADCASTER,
                BROADCASTER_CHAT_SCOPES,
            )

        except BROADCASTER_REAUTHORIZATION_ERRORS as exc:
            await reauthorization_handler(
                broadcaster_id,
                str(exc),
            )

            logger.error(
                "Paused broadcaster %s because Twitch "
                "authorization must be renewed. The "
                "worker will continue for other "
                "broadcasters.",
                broadcaster_id,
            )

        except TwitchOAuthError:
            logger.exception(
                "Temporary Twitch OAuth validation "
                "failure for broadcaster %s. The "
                "broadcaster remains enabled and will "
                "be checked again later.",
                broadcaster_id,
            )


async def token_validation_loop(
    runtime: TwitchRuntime,
    identity_repository: IdentityRepository,
    reauthorization_handler: (
        BroadcasterReauthorizationHandler
    ),
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

        # Losing the bot credential is fatal because no
        # Twitch feature can operate safely without it.
        await runtime.validate_bot_token()

        await validate_enabled_broadcaster_credentials(
            runtime,
            identity_repository,
            reauthorization_handler,
        )

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

    async def broadcaster_cleanup(
        broadcaster_ids: tuple[str, ...],
    ) -> None:
        await cleanup_broadcaster_triggers(
            title_monitor.trigger_coordinator,
            broadcaster_ids,
        )

    identity_repository = IdentityRepository(
        database
    )
    request_repository = BroadcasterRequestRepository(
        database
    )

    async def require_reauthorization(
        broadcaster_id: str,
        reason: str,
    ) -> None:
        changed = (
            await request_repository
            .require_reauthorization_for_broadcaster(
                broadcaster_id,
                reason=reason,
            )
        )

        if not changed:
            raise TwitchWorkerError(
                "Could not safely pause broadcaster "
                f"{broadcaster_id} after its Twitch "
                "authorization failed."
            )

    # Check active broadcasters before EventSub or the
    # title monitor starts using their credentials.
    await validate_enabled_broadcaster_credentials(
        runtime,
        identity_repository,
        require_reauthorization,
    )

    def eventsub_factory(
        broadcaster_ids: tuple[str, ...],
    ) -> EventSubWebSocketService:
        return create_eventsub_service(
            runtime,
            broadcaster_ids,
        )

    tasks = [
        asyncio.create_task(
            title_monitor.run(stop_event),
            name="stream-title-monitor",
        ),
        asyncio.create_task(
            token_validation_loop(
                runtime,
                identity_repository,
                require_reauthorization,
                stop_event,
            ),
            name="token-validation",
        ),
        asyncio.create_task(
            eventsub_supervisor_loop(
                identity_repository,
                eventsub_factory,
                stop_event,
                broadcaster_cleanup=(
                    broadcaster_cleanup
                ),
            ),
            name="broadcaster-sync",
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
