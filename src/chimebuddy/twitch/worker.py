from __future__ import annotations

import asyncio
import logging
import signal

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from chimebuddy.database import Database
from chimebuddy.models import OAuthCredentialKind
from chimebuddy.models.chat import TwitchChatMessage
from chimebuddy.repositories import (
    BroadcasterRequestRepository,
    CustomCommandRepository,
    IdentityRepository,
    RuntimeHealthRepository,
    RewardVipRepository,
    RewardActionLogRepository,
    TriggerRepository,
)
from chimebuddy.repositories.ban_or_vip_user_settings_repository import BanOrVipUserSettingsRepository
from chimebuddy.services.custom_command_runtime import (
    CustomCommandRuntime,
)
from chimebuddy.services.ban_or_vip_service import BanOrVipService
from chimebuddy.repositories.app_settings_repository import AppSettingsRepository
from chimebuddy.services.stream_title_monitor import (
    BroadcasterTitleCheck,
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
    V2PING_COMMAND_NAME,
)
from chimebuddy.twitch import runtime
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


async def _record_health_success(
    repository: RuntimeHealthRepository | None,
    component: str,
    subject_id: str,
    **kwargs: Any,
) -> None:
    if repository is None:
        return

    try:
        await repository.mark_success(
            component,
            subject_id,
            **kwargs,
        )
    except Exception:
        logger.exception(
            "Failed to persist successful runtime health: "
            "component=%s, subject_id=%s.",
            component,
            subject_id,
        )


async def _record_health_failure(
    repository: RuntimeHealthRepository | None,
    component: str,
    subject_id: str,
    **kwargs: Any,
) -> None:
    if repository is None:
        return

    try:
        await repository.mark_failure(
            component,
            subject_id,
            **kwargs,
        )
    except Exception:
        logger.exception(
            "Failed to persist failed runtime health: "
            "component=%s, subject_id=%s.",
            component,
            subject_id,
        )


async def _record_health_status(
    repository: RuntimeHealthRepository | None,
    component: str,
    subject_id: str,
    **kwargs: Any,
) -> None:
    if repository is None:
        return

    try:
        await repository.set_status(
            component,
            subject_id,
            **kwargs,
        )
    except Exception:
        logger.exception(
            "Failed to persist runtime health status: "
            "component=%s, subject_id=%s.",
            component,
            subject_id,
        )


class RoutedChatMessageHandler:
    """Logs chat messages and routes Twitch commands."""

    def __init__(
        self,
        bot_twitch_user_id: str,
        command_router: TwitchCommandRouter,
        custom_command_runtime: (
            CustomCommandRuntime | None
        ) = None,
        ban_or_vip_service: BanOrVipService | None = None,
    ) -> None:
        self.bot_twitch_user_id = str(
            bot_twitch_user_id
        ).strip()
        self.command_router = command_router
        self.custom_command_runtime = (
            custom_command_runtime
        )
        self.ban_or_vip_service = ban_or_vip_service

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

        if self.ban_or_vip_service is not None:
            await self.ban_or_vip_service.observe_chat_message(message)

        handled = await self.command_router.route(message)

        if (
            not handled
            and self.custom_command_runtime is not None
        ):
            await self.custom_command_runtime.route(message)

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

        if message.is_subscriber:
            return "subscriber"

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
        V2PING_COMMAND_NAME,
        TwitchCommandPermission.BROADCASTER,
        handle_v2ping,
    )

    return router


def create_title_monitor(
    database: Database,
    runtime: TwitchRuntime,
    health_repository: (
        RuntimeHealthRepository | None
    ) = None,
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

    async def record_title_check(
        check: BroadcasterTitleCheck,
    ) -> None:
        if health_repository is None:
            return

        if check.error is None:
            await _record_health_success(
                health_repository,
                "title_monitor",
                check.broadcaster_twitch_user_id,
                details={"is_live": check.is_live},
            )
        else:
            trigger_failed = bool(
                check.trigger_report
                and check.trigger_report.has_errors
            )
            await _record_health_failure(
                health_repository,
                "title_monitor",
                check.broadcaster_twitch_user_id,
                error_code=(
                    "title_trigger_failed"
                    if trigger_failed
                    else "title_check_failed"
                ),
                safe_message=(
                    "A stream-title trigger operation "
                    "could not be completed."
                    if trigger_failed
                    else (
                        "The latest stream-title check "
                        "could not be completed."
                    )
                ),
            )

    return StreamTitleMonitor(
        identity_repository=identity_repository,
        stream_gateway=runtime.helix_gateway,
        trigger_coordinator=coordinator,
        poll_interval_seconds=(
            TITLE_POLL_INTERVAL_SECONDS
        ),
        check_observer=record_title_check,
    )


def create_eventsub_service(
    runtime: TwitchRuntime,
    broadcaster_twitch_user_ids: tuple[str, ...],
    health_repository: (
        RuntimeHealthRepository | None
    ) = None,
    custom_command_runtime: (
        CustomCommandRuntime | None
    ) = None,
    ban_or_vip_service: BanOrVipService | None = None,
) -> EventSubWebSocketService:
    logger.info(
        "Preparing EventSub chat reception for "
        "%s broadcaster(s).",
        len(broadcaster_twitch_user_ids),
    )

    async def record_eventsub_status(
        status: str,
        broadcaster_ids: tuple[str, ...],
        error_code: str | None,
        safe_message: str | None,
    ) -> None:
        if health_repository is None:
            return

        for broadcaster_id in broadcaster_ids:
            if (
                error_code is not None
                and safe_message is not None
            ):
                await _record_health_failure(
                    health_repository,
                    "eventsub",
                    broadcaster_id,
                    status=status,
                    error_code=error_code,
                    safe_message=safe_message,
                )
            elif status == "healthy":
                await _record_health_success(
                    health_repository,
                    "eventsub",
                    broadcaster_id,
                )
            else:
                await _record_health_status(
                    health_repository,
                    "eventsub",
                    broadcaster_id,
                    status=status,
                )

    return EventSubWebSocketService(
        session=runtime.session,
        subscription_client=(
            runtime.eventsub_subscription_client
        ),
        redemption_subscription_client=(
            runtime.eventsub_subscription_client
        ),
        broadcaster_twitch_user_ids=(
            broadcaster_twitch_user_ids
        ),
        chat_message_handler=(
            RoutedChatMessageHandler(
                runtime.bot_twitch_user_id,
                create_command_router(runtime),
                custom_command_runtime,
                ban_or_vip_service,
            )
        ),
        redemption_handler=ban_or_vip_service,
        status_observer=record_eventsub_status,
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
    health_repository: (
        RuntimeHealthRepository | None
    ) = None,
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
            await _record_health_success(
                health_repository,
                "token_validation",
                broadcaster_id,
            )

        except BROADCASTER_REAUTHORIZATION_ERRORS as exc:
            await _record_health_failure(
                health_repository,
                "token_validation",
                broadcaster_id,
                status="reauthorization_required",
                error_code="reauthorization_required",
                safe_message=(
                    "Twitch authorization must be "
                    "renewed."
                ),
            )
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
            await _record_health_failure(
                health_repository,
                "token_validation",
                broadcaster_id,
                status="degraded",
                error_code=(
                    "oauth_temporarily_unavailable"
                ),
                safe_message=(
                    "Twitch authorization could not "
                    "be checked and will be retried."
                ),
            )
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
    health_repository: (
        RuntimeHealthRepository | None
    ) = None,
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
        try:
            await runtime.validate_bot_token()
        except Exception:
            await _record_health_failure(
                health_repository,
                "token_validation",
                runtime.bot_twitch_user_id,
                error_code="bot_authorization_failed",
                safe_message=(
                    "The ChimeBuddy bot authorization "
                    "could not be validated."
                ),
            )
            raise
        else:
            await _record_health_success(
                health_repository,
                "token_validation",
                runtime.bot_twitch_user_id,
            )

        await validate_enabled_broadcaster_credentials(
            runtime,
            identity_repository,
            reauthorization_handler,
            health_repository,
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
    health_repository = RuntimeHealthRepository(
        database
    )

    remove_signal_handlers = (
        _install_signal_handlers(stop_event)
    )

    title_monitor = create_title_monitor(
        database,
        runtime,
        health_repository,
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
    custom_command_runtime = CustomCommandRuntime(
        command_repository=CustomCommandRepository(
            database
        ),
        chat_gateway=runtime.helix_gateway,
    )
    ban_or_vip_service = BanOrVipService(
        settings_repository=AppSettingsRepository(database),
        user_settings_repository=BanOrVipUserSettingsRepository(database),
        vip_repository=RewardVipRepository(database),
        helix_gateway=runtime.helix_gateway,
        action_log_repository=RewardActionLogRepository(database),
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
        health_repository,
    )

    await _record_health_success(
        health_repository,
        "token_validation",
        runtime.bot_twitch_user_id,
    )

    def eventsub_factory(
        broadcaster_ids: tuple[str, ...],
    ) -> EventSubWebSocketService:
        return create_eventsub_service(
            runtime,
            broadcaster_ids,
            health_repository,
            custom_command_runtime,
            ban_or_vip_service,
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
                health_repository=health_repository,
            ),
            name="token-validation",
        ),
        asyncio.create_task(
            ban_or_vip_service.vip_expiry_loop(stop_event),
            name="reward-vip-expiry",
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
