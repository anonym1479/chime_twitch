from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import aiohttp

from chimebuddy.models.chat import TwitchChatMessage
from chimebuddy.twitch.eventsub_messages import (
    EventSubMessageError,
    parse_channel_chat_message,
    parse_channel_point_redemption,
)
from chimebuddy.twitch.eventsub_subscriptions import (
    EventSubSubscriptionClient,
)


logger = logging.getLogger(
    "chimebuddy.twitch.eventsub"
)

EVENTSUB_WEBSOCKET_URL = (
    "wss://eventsub.wss.twitch.tv/ws"
    "?keepalive_timeout_seconds=30"
)

CONNECTION_TIMEOUT_SECONDS = 15
WELCOME_TIMEOUT_SECONDS = 10
DEFAULT_RECONNECT_DELAY_SECONDS = 5
MESSAGE_ID_CACHE_SIZE = 1000


class EventSubWebSocketError(RuntimeError):
    """Raised when the EventSub connection fails."""


class ChatMessageHandler(Protocol):
    async def handle_chat_message(
        self,
        message: TwitchChatMessage,
    ) -> None:
        """Handle one parsed Twitch chat message."""


class RedemptionHandler(Protocol):
    async def handle_redemption(self, redemption) -> None:
        """Handle a configured Channel Points redemption."""


EventSubStatusObserver = Callable[
    [
        str,
        tuple[str, ...],
        str | None,
        str | None,
    ],
    Awaitable[None],
]


@dataclass(frozen=True, slots=True)
class EventSubWelcome:
    session_id: str
    keepalive_timeout_seconds: int


class EventSubWebSocketService:
    """Maintains Twitch's EventSub WebSocket connection."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        subscription_client: EventSubSubscriptionClient,
        broadcaster_twitch_user_ids: tuple[str, ...],
        chat_message_handler: ChatMessageHandler,
        redemption_handler: RedemptionHandler | None = None,
        *,
        reconnect_delay_seconds: float = (
            DEFAULT_RECONNECT_DELAY_SECONDS
        ),
        status_observer: (
            EventSubStatusObserver | None
        ) = None,
    ) -> None:
        broadcaster_ids = tuple(
            dict.fromkeys(
                str(user_id).strip()
                for user_id in broadcaster_twitch_user_ids
                if str(user_id).strip()
            )
        )

        if not broadcaster_ids:
            raise ValueError(
                "At least one broadcaster is required."
            )

        if reconnect_delay_seconds < 0:
            raise ValueError(
                "reconnect_delay_seconds cannot be negative."
            )

        self.session = session
        self.subscription_client = subscription_client
        self.broadcaster_twitch_user_ids = (
            broadcaster_ids
        )
        self.chat_message_handler = chat_message_handler
        self.redemption_handler = redemption_handler
        self.reconnect_delay_seconds = (
            reconnect_delay_seconds
        )
        self.status_observer = status_observer

        self._recent_message_ids: deque[str] = deque()
        self._recent_message_id_set: set[str] = set()
        self._interruption_started_at: float | None = None
        self._interruption_reason: str | None = None

    async def run(
        self,
        stop_event: asyncio.Event,
    ) -> None:
        logger.info(
            "Twitch EventSub WebSocket service started."
        )
        await self._notify_status("connecting")

        while not stop_event.is_set():
            try:
                await self._run_connection(stop_event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if stop_event.is_set():
                    break

                reason = self._connection_failure_reason(exc)
                self._record_interruption(reason)

                await self._notify_status(
                    "reconnecting",
                    error_code="eventsub_connection_failed",
                    safe_message=(
                        "Twitch chat connection was "
                        "interrupted and is reconnecting."
                    ),
                )
                if reason == "unexpected_error":
                    logger.exception(
                        "Twitch EventSub connection "
                        "failed unexpectedly."
                    )
                else:
                    logger.warning(
                        "Twitch EventSub connection "
                        "interrupted: reason=%s. "
                        "Reconnecting automatically.",
                        reason,
                    )
                    logger.debug(
                        "EventSub interruption traceback.",
                        exc_info=True,
                    )

            if stop_event.is_set():
                break

            logger.info(
                "Reconnecting to Twitch EventSub in "
                "%s seconds.",
                self.reconnect_delay_seconds,
            )

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self.reconnect_delay_seconds,
                )
            except TimeoutError:
                pass

        logger.info(
            "Twitch EventSub WebSocket service stopped."
        )
        await self._notify_status("stopped")

    async def _run_connection(
        self,
        stop_event: asyncio.Event,
    ) -> None:
        websocket, welcome = await self._connect(
            EVENTSUB_WEBSOCKET_URL
        )

        try:
            subscribed_ids, failed_ids = (
                await self._subscribe_all(
                    welcome.session_id
                )
            )

            logger.info(
                "Twitch EventSub session %s is ready.",
                welcome.session_id,
            )
            self._log_recovery(len(subscribed_ids))
            await self._notify_status(
                "healthy",
                broadcaster_ids=subscribed_ids,
            )

            if failed_ids:
                await self._notify_status(
                    "error",
                    broadcaster_ids=failed_ids,
                    error_code=(
                        "eventsub_subscription_failed"
                    ),
                    safe_message=(
                        "Twitch chat subscription could "
                        "not be started."
                    ),
                )

            while not stop_event.is_set():
                reconnect_url = (
                    await self._consume_until_reconnect(
                        websocket,
                        welcome.keepalive_timeout_seconds,
                        stop_event,
                    )
                )

                if (
                    reconnect_url is None
                    or stop_event.is_set()
                ):
                    return

                logger.info(
                    "Twitch requested an EventSub "
                    "WebSocket handover."
                )

                replacement, replacement_welcome = (
                    await self._connect(reconnect_url)
                )

                # Twitch transfers the subscriptions to the
                # replacement connection automatically.
                await websocket.close()

                websocket = replacement
                welcome = replacement_welcome

                logger.info(
                    "Twitch EventSub handover completed. "
                    "New session: %s",
                    welcome.session_id,
                )

        finally:
            if not websocket.closed:
                await websocket.close()

    async def _connect(
        self,
        url: str,
    ) -> tuple[
        aiohttp.ClientWebSocketResponse,
        EventSubWelcome,
    ]:
        logger.info(
            "Connecting to Twitch EventSub WebSocket."
        )

        websocket = await asyncio.wait_for(
            self.session.ws_connect(
                url,
                autoping=True,
            ),
            timeout=CONNECTION_TIMEOUT_SECONDS,
        )

        try:
            message = await asyncio.wait_for(
                websocket.receive(),
                timeout=WELCOME_TIMEOUT_SECONDS,
            )

            envelope = self._decode_message(message)

            if envelope is None:
                raise EventSubWebSocketError(
                    "Twitch closed the connection before "
                    "sending its welcome message."
                )

            welcome = self._parse_welcome(envelope)

        except Exception:
            await websocket.close()
            raise

        logger.info(
            "Connected to Twitch EventSub WebSocket. "
            "Session: %s",
            welcome.session_id,
        )

        return websocket, welcome

    def _record_interruption(self, reason: str) -> None:
        if self._interruption_started_at is None:
            self._interruption_started_at = (
                asyncio.get_running_loop().time()
            )

        self._interruption_reason = reason

    def _log_recovery(
        self,
        subscribed_broadcaster_count: int,
    ) -> None:
        if self._interruption_started_at is None:
            return

        downtime_seconds = max(
            0.0,
            asyncio.get_running_loop().time()
            - self._interruption_started_at,
        )

        logger.info(
            "Twitch EventSub connection recovered: "
            "broadcasters=%s, downtime_seconds=%.1f, "
            "previous_reason=%s.",
            subscribed_broadcaster_count,
            downtime_seconds,
            self._interruption_reason or "unknown",
        )

        self._interruption_started_at = None
        self._interruption_reason = None

    @staticmethod
    def _connection_failure_reason(
        error: Exception,
    ) -> str:
        if isinstance(error, EventSubWebSocketError):
            if "keepalive timed out" in str(error).casefold():
                return "keepalive_timeout"

            return "eventsub_protocol_error"

        if isinstance(error, aiohttp.ClientConnectionError):
            return "transport_closed"

        if isinstance(error, TimeoutError):
            return "connection_timeout"

        return "unexpected_error"

    async def _notify_status(
        self,
        status: str,
        error_code: str | None = None,
        safe_message: str | None = None,
        broadcaster_ids: tuple[str, ...] | None = None,
    ) -> None:
        if self.status_observer is None:
            return

        try:
            await self.status_observer(
                status,
                (
                    self.broadcaster_twitch_user_ids
                    if broadcaster_ids is None
                    else broadcaster_ids
                ),
                error_code,
                safe_message,
            )
        except Exception:
            logger.exception(
                "Failed to persist EventSub health."
            )

    async def _subscribe_all(
        self,
        websocket_session_id: str,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        successful_ids = []
        failed_ids = []
        for broadcaster_id in self.broadcaster_twitch_user_ids:
            try:
                await self.subscription_client.subscribe_to_chat(
                    websocket_session_id, broadcaster_id,
                )
                if self.redemption_handler is not None:
                    await self.subscription_client.subscribe_to_redemptions(
                        websocket_session_id, broadcaster_id,
                    )
            except Exception as result:
                failed_ids.append(broadcaster_id)
                logger.error(
                    "Failed to subscribe to Twitch events for "
                    "broadcaster %s: %s",
                    broadcaster_id,
                    result,
                )
                continue

            successful_ids.append(broadcaster_id)

            logger.info(
                "Subscribed to Twitch chat for "
                "broadcaster %s.",
                broadcaster_id,
            )

        if not successful_ids:
            raise EventSubWebSocketError(
                "No Twitch chat subscriptions succeeded."
            )

        return (
            tuple(successful_ids),
            tuple(failed_ids),
        )

    async def _consume_until_reconnect(
        self,
        websocket: aiohttp.ClientWebSocketResponse,
        keepalive_timeout_seconds: int,
        stop_event: asyncio.Event,
    ) -> str | None:
        silence_timeout = (
            keepalive_timeout_seconds + 10
        )

        while not stop_event.is_set():
            message = await self._receive_or_stop(
                websocket,
                stop_event,
                silence_timeout,
            )

            if message is None:
                return None

            envelope = self._decode_message(message)

            if envelope is None:
                return None

            metadata = envelope.get("metadata")

            if not isinstance(metadata, Mapping):
                logger.warning(
                    "Ignored EventSub message without "
                    "valid metadata."
                )
                continue

            message_type = str(
                metadata.get("message_type", "")
            ).strip()

            if message_type == "session_reconnect":
                return self._parse_reconnect_url(
                    envelope
                )

            if message_type == "session_keepalive":
                continue

            if message_type == "notification":
                await self._handle_notification(
                    envelope
                )
                continue

            if message_type == "revocation":
                self._log_revocation(envelope)
                continue

            logger.debug(
                "Ignored EventSub message type: %s",
                message_type or "<missing>",
            )

        return None

    @staticmethod
    async def _receive_or_stop(
        websocket: aiohttp.ClientWebSocketResponse,
        stop_event: asyncio.Event,
        timeout: float,
    ):
        receive_task = asyncio.create_task(
            websocket.receive()
        )
        stop_task = asyncio.create_task(
            stop_event.wait()
        )

        done, pending = await asyncio.wait(
            {receive_task, stop_task},
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )

        if not done:
            receive_task.cancel()
            stop_task.cancel()

            await asyncio.gather(
                receive_task,
                stop_task,
                return_exceptions=True,
            )

            raise EventSubWebSocketError(
                "Twitch EventSub keepalive timed out."
            )

        for task in pending:
            task.cancel()

        await asyncio.gather(
            *pending,
            return_exceptions=True,
        )

        if stop_task in done:
            if receive_task in done:
                await asyncio.gather(
                    receive_task,
                    return_exceptions=True,
                )

            return None

        return receive_task.result()

    async def _handle_notification(
        self,
        envelope: Mapping[str, Any],
    ) -> None:
        metadata = envelope.get("metadata")

        if not isinstance(metadata, Mapping):
            return

        subscription_type = str(
            metadata.get("subscription_type", "")
        ).strip()

        if subscription_type == (
            "channel.channel_points_custom_reward_redemption.add"
        ):
            await self._handle_redemption(envelope)
            return

        if subscription_type != "channel.chat.message":
            return

        event_message_id = str(
            metadata.get("message_id", "")
        ).strip()

        if (
            event_message_id
            and not self._remember_message_id(
                event_message_id
            )
        ):
            logger.debug(
                "Ignored duplicate EventSub message %s.",
                event_message_id,
            )
            return

        try:
            message = parse_channel_chat_message(
                envelope
            )
        except EventSubMessageError as exc:
            logger.warning(
                "Ignored malformed Twitch chat "
                "notification: %s",
                exc,
            )
            return

        try:
            await self.chat_message_handler.handle_chat_message(
                message
            )
        except Exception:
            # One broken command must never destroy the
            # EventSub connection.
            logger.exception(
                "Twitch chat message handling failed "
                "for message %s.",
                message.message_id,
            )

    async def _handle_redemption(
        self,
        envelope: Mapping[str, Any],
    ) -> None:
        if self.redemption_handler is None:
            return
        try:
            redemption = parse_channel_point_redemption(envelope)
        except EventSubMessageError as exc:
            logger.warning("Ignored malformed reward redemption: %s", exc)
            return
        asyncio.create_task(
            self._run_redemption_handler(redemption),
            name=f"reward-redemption-{redemption.redemption_id}",
        )

    async def _run_redemption_handler(self, redemption) -> None:
        try:
            await self.redemption_handler.handle_redemption(redemption)
        except Exception:
            logger.exception("Channel-point redemption handling failed.")

    def _remember_message_id(
        self,
        message_id: str,
    ) -> bool:
        if message_id in self._recent_message_id_set:
            return False

        if (
            len(self._recent_message_ids)
            >= MESSAGE_ID_CACHE_SIZE
        ):
            oldest = self._recent_message_ids.popleft()
            self._recent_message_id_set.discard(oldest)

        self._recent_message_ids.append(message_id)
        self._recent_message_id_set.add(message_id)

        return True

    @staticmethod
    def _decode_message(
        message,
    ) -> dict[str, Any] | None:
        if message.type is aiohttp.WSMsgType.TEXT:
            try:
                data = json.loads(message.data)
            except (TypeError, json.JSONDecodeError) as exc:
                raise EventSubWebSocketError(
                    "Twitch sent invalid JSON over "
                    "EventSub."
                ) from exc

            if not isinstance(data, dict):
                raise EventSubWebSocketError(
                    "Twitch sent an invalid EventSub "
                    "message."
                )

            return data

        if message.type in {
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.CLOSING,
        }:
            return None

        if message.type is aiohttp.WSMsgType.ERROR:
            raise EventSubWebSocketError(
                "Twitch EventSub WebSocket reported "
                f"an error: {message.data}"
            )

        return {}

    @staticmethod
    def _parse_welcome(
        envelope: Mapping[str, Any],
    ) -> EventSubWelcome:
        metadata = envelope.get("metadata")
        payload = envelope.get("payload")

        if (
            not isinstance(metadata, Mapping)
            or not isinstance(payload, Mapping)
            or metadata.get("message_type")
            != "session_welcome"
        ):
            raise EventSubWebSocketError(
                "The first EventSub message was not "
                "a welcome message."
            )

        session = payload.get("session")

        if not isinstance(session, Mapping):
            raise EventSubWebSocketError(
                "EventSub welcome message has no session."
            )

        session_id = str(
            session.get("id", "")
        ).strip()

        try:
            keepalive_timeout = int(
                session.get(
                    "keepalive_timeout_seconds"
                )
            )
        except (TypeError, ValueError) as exc:
            raise EventSubWebSocketError(
                "EventSub welcome message has an "
                "invalid keepalive timeout."
            ) from exc

        if not session_id:
            raise EventSubWebSocketError(
                "EventSub welcome message has no "
                "session ID."
            )

        if keepalive_timeout <= 0:
            raise EventSubWebSocketError(
                "EventSub keepalive timeout must "
                "be positive."
            )

        return EventSubWelcome(
            session_id=session_id,
            keepalive_timeout_seconds=(
                keepalive_timeout
            ),
        )

    @staticmethod
    def _parse_reconnect_url(
        envelope: Mapping[str, Any],
    ) -> str:
        payload = envelope.get("payload")

        if not isinstance(payload, Mapping):
            raise EventSubWebSocketError(
                "EventSub reconnect message has "
                "no payload."
            )

        session = payload.get("session")

        if not isinstance(session, Mapping):
            raise EventSubWebSocketError(
                "EventSub reconnect message has "
                "no session."
            )

        reconnect_url = str(
            session.get("reconnect_url", "")
        ).strip()

        if not reconnect_url:
            raise EventSubWebSocketError(
                "EventSub reconnect message has "
                "no reconnect URL."
            )

        return reconnect_url

    @staticmethod
    def _log_revocation(
        envelope: Mapping[str, Any],
    ) -> None:
        payload = envelope.get("payload")

        if not isinstance(payload, Mapping):
            logger.error(
                "Twitch revoked an unknown "
                "EventSub subscription."
            )
            return

        subscription = payload.get("subscription")

        if not isinstance(subscription, Mapping):
            logger.error(
                "Twitch revoked an unknown "
                "EventSub subscription."
            )
            return

        logger.error(
            "Twitch revoked EventSub subscription "
            "%s: %s",
            subscription.get("id", "<unknown>"),
            subscription.get("status", "<unknown>"),
        )
