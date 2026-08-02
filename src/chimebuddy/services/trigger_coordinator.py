import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

from chimebuddy.models import (
    Trigger,
    TriggerRuntimeState,
)
from chimebuddy.repositories import TriggerRepository
from chimebuddy.services.trigger_matcher import (
    TitleTriggerMatcher,
)
from chimebuddy.services.trigger_state_machine import (
    TriggerAction,
    TriggerStateMachine,
)


logger = logging.getLogger(
    "chimebuddy.twitch.triggers"
)


class ChatGateway(Protocol):
    async def send_message(
        self,
        broadcaster_twitch_user_id: str,
        message: str,
    ) -> str:
        """Send a message and return its Twitch message ID."""


class PinGateway(Protocol):
    async def pin_message(
        self,
        broadcaster_twitch_user_id: str,
        message_id: str,
    ) -> None:
        """Pin a previously sent Twitch message."""

    async def unpin_message(
        self,
        broadcaster_twitch_user_id: str,
        message_id: str,
    ) -> None:
        """Unpin a previously sent Twitch message."""


@dataclass(frozen=True, slots=True)
class TriggerRunReport:
    broadcaster_twitch_user_id: str
    title: str
    selected_trigger_id: int | None
    activated_trigger_ids: tuple[int, ...]
    deactivated_trigger_ids: tuple[int, ...]
    reset_trigger_ids: tuple[int, ...]
    errors: tuple[str, ...]

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


class TriggerCoordinator:
    """Coordinates trigger decisions and external actions."""

    def __init__(
        self,
        repository: TriggerRepository,
        matcher: TitleTriggerMatcher,
        state_machine: TriggerStateMachine,
        chat_gateway: ChatGateway,
        pin_gateway: PinGateway,
    ) -> None:
        self.repository = repository
        self.matcher = matcher
        self.state_machine = state_machine
        self.chat_gateway = chat_gateway
        self.pin_gateway = pin_gateway

        # Only one title evaluation may run per broadcaster at once.
        self._broadcaster_locks: dict[str, asyncio.Lock] = {}

    async def process_title(
        self,
        broadcaster_twitch_user_id: str,
        title: str,
    ) -> TriggerRunReport:
        broadcaster_id = str(
            broadcaster_twitch_user_id
        ).strip()

        if not broadcaster_id:
            raise ValueError(
                "broadcaster_twitch_user_id cannot be empty."
            )

        lock = self._broadcaster_locks.setdefault(
            broadcaster_id,
            asyncio.Lock(),
        )

        async with lock:
            return await self._process_title_locked(
                broadcaster_id,
                str(title),
            )

    async def _process_title_locked(
        self,
        broadcaster_id: str,
        title: str,
    ) -> TriggerRunReport:
        triggers = await self.repository.list_triggers(
            broadcaster_id
        )

        evaluation = self.matcher.evaluate(
            title,
            triggers,
        )

        selected_trigger = evaluation.selected_trigger
        selected_trigger_id = (
            selected_trigger.trigger_id
            if selected_trigger is not None
            else None
        )

        activated: list[int] = []
        deactivated: list[int] = []
        reset: list[int] = []
        errors: list[str] = []

        cleanup_failed = False

        # First, deactivate triggers that should no longer own
        # the active pinned message.
        for trigger in triggers:
            if trigger.trigger_id == selected_trigger_id:
                continue

            state = await self.repository.get_runtime_state(
                trigger.trigger_id
            )

            if state is None:
                error = (
                    f"Trigger {trigger.trigger_id} has no "
                    "runtime state."
                )
                errors.append(error)
                logger.error(
                    "Trigger runtime state is missing: "
                    "broadcaster=%s, trigger=%s, name=%r.",
                    broadcaster_id,
                    trigger.trigger_id,
                    trigger.name,
                )
                cleanup_failed = True
                continue

            decision = self.state_machine.decide(
                trigger,
                state,
                title_matches=False,
            )

            if decision.action is TriggerAction.DEACTIVATE:
                success, error = await self._deactivate(
                    trigger,
                    state,
                )

                if success:
                    deactivated.append(trigger.trigger_id)
                    logger.info(
                        "Trigger deactivated: broadcaster=%s, "
                        "trigger=%s, name=%r, reason=%s.",
                        broadcaster_id,
                        trigger.trigger_id,
                        trigger.name,
                        self._deactivation_reason(trigger),
                    )

                if error:
                    errors.append(error)
                    cleanup_failed = True

            elif decision.action is TriggerAction.RESET_ERROR:
                was_reset = await self.repository.reset_error(
                    trigger.trigger_id
                )

                if was_reset:
                    reset.append(trigger.trigger_id)
                    logger.info(
                        "Trigger error reset: broadcaster=%s, "
                        "trigger=%s, name=%r.",
                        broadcaster_id,
                        trigger.trigger_id,
                        trigger.name,
                    )

        # Only activate the selected trigger after old trigger
        # cleanup has completed successfully.
        if selected_trigger is not None and not cleanup_failed:
            state = await self.repository.get_runtime_state(
                selected_trigger.trigger_id
            )

            if state is None:
                error = (
                    f"Trigger {selected_trigger.trigger_id} "
                    "has no runtime state."
                )
                errors.append(error)
                logger.error(
                    "Trigger runtime state is missing: "
                    "broadcaster=%s, trigger=%s, name=%r.",
                    broadcaster_id,
                    selected_trigger.trigger_id,
                    selected_trigger.name,
                )
            else:
                decision = self.state_machine.decide(
                    selected_trigger,
                    state,
                    title_matches=True,
                )

                if decision.action is TriggerAction.ACTIVATE:
                    logger.info(
                        "Title trigger matched: broadcaster=%s, "
                        "trigger=%s, name=%r.",
                        broadcaster_id,
                        selected_trigger.trigger_id,
                        selected_trigger.name,
                    )
                    success, error = await self._activate(
                        selected_trigger,
                        title,
                    )

                    if success:
                        activated.append(
                            selected_trigger.trigger_id
                        )

                    if error:
                        errors.append(error)

                elif (
                    decision.action
                    is TriggerAction.DEACTIVATE
                ):
                    success, error = await self._deactivate(
                        selected_trigger,
                        state,
                    )

                    if success:
                        deactivated.append(
                            selected_trigger.trigger_id
                        )
                        logger.info(
                            "Trigger deactivated: broadcaster=%s, "
                            "trigger=%s, name=%r, reason=%s.",
                            broadcaster_id,
                            selected_trigger.trigger_id,
                            selected_trigger.name,
                            self._deactivation_reason(
                                selected_trigger
                            ),
                        )

                    if error:
                        errors.append(error)

                elif (
                    decision.action
                    is TriggerAction.RESET_ERROR
                ):
                    was_reset = (
                        await self.repository.reset_error(
                            selected_trigger.trigger_id
                        )
                    )

                    if was_reset:
                        reset.append(
                            selected_trigger.trigger_id
                        )
                        logger.info(
                            "Trigger error reset: "
                            "broadcaster=%s, trigger=%s, "
                            "name=%r.",
                            broadcaster_id,
                            selected_trigger.trigger_id,
                            selected_trigger.name,
                        )

        return TriggerRunReport(
            broadcaster_twitch_user_id=broadcaster_id,
            title=title,
            selected_trigger_id=selected_trigger_id,
            activated_trigger_ids=tuple(activated),
            deactivated_trigger_ids=tuple(deactivated),
            reset_trigger_ids=tuple(reset),
            errors=tuple(errors),
        )

    async def _activate(
        self,
        trigger: Trigger,
        title: str,
    ) -> tuple[bool, str | None]:
        claimed = await self.repository.claim_activation(
            trigger.trigger_id,
            title,
        )

        if not claimed:
            return False, None

        try:
            message_id = await self.chat_gateway.send_message(
                trigger.broadcaster_twitch_user_id,
                trigger.response_message,
            )
        except Exception as exc:
            await self.repository.mark_operation_error(
                trigger.trigger_id,
                "Twitch chat message sending failed.",
            )

            logger.error(
                "Trigger activation failed: broadcaster=%s, "
                "trigger=%s, name=%r, operation=send_message, "
                "error_type=%s.",
                trigger.broadcaster_twitch_user_id,
                trigger.trigger_id,
                trigger.name,
                type(exc).__name__,
            )

            return (
                False,
                f"Failed to send the message for trigger "
                f"{trigger.trigger_id}.",
            )

        was_pinned = False
        pin_error: str | None = None

        if trigger.pin_message:
            try:
                await self.pin_gateway.pin_message(
                    trigger.broadcaster_twitch_user_id,
                    message_id,
                )
                was_pinned = True
            except Exception as exc:
                # The chat message was sent successfully. Keep the
                # trigger active so it is not sent repeatedly.
                pin_error = (
                    f"Trigger {trigger.trigger_id} sent its "
                    "message, but pinning failed."
                )
                logger.warning(
                    "Trigger pinning failed: broadcaster=%s, "
                    "trigger=%s, name=%r, error_type=%s.",
                    trigger.broadcaster_twitch_user_id,
                    trigger.trigger_id,
                    trigger.name,
                    type(exc).__name__,
                )

        completed = (
            await self.repository.complete_activation(
                trigger.trigger_id,
                message_id,
                is_pinned=was_pinned,
            )
        )

        if not completed:
            await self.repository.mark_operation_error(
                trigger.trigger_id,
                "Activation state could not be completed.",
                message_id=message_id,
                is_pinned=was_pinned,
            )

            logger.error(
                "Trigger activation failed: broadcaster=%s, "
                "trigger=%s, name=%r, "
                "operation=complete_state.",
                trigger.broadcaster_twitch_user_id,
                trigger.trigger_id,
                trigger.name,
            )

            return (
                False,
                f"Trigger {trigger.trigger_id} could not "
                "complete activation.",
            )

        logger.info(
            "Trigger activated: broadcaster=%s, trigger=%s, "
            "name=%r, pinned=%s.",
            trigger.broadcaster_twitch_user_id,
            trigger.trigger_id,
            trigger.name,
            was_pinned,
        )

        return True, pin_error

    async def _deactivate(
        self,
        trigger: Trigger,
        state: TriggerRuntimeState,
    ) -> tuple[bool, str | None]:
        claimed = await self.repository.claim_deactivation(
            trigger.trigger_id
        )

        if not claimed:
            return False, None

        if state.message_id and state.is_pinned:
            try:
                await self.pin_gateway.unpin_message(
                    trigger.broadcaster_twitch_user_id,
                    state.message_id,
                )
            except Exception as exc:
                await self.repository.mark_operation_error(
                    trigger.trigger_id,
                    "Twitch message unpinning failed.",
                )

                logger.error(
                    "Trigger deactivation failed: "
                    "broadcaster=%s, trigger=%s, name=%r, "
                    "operation=unpin_message, error_type=%s.",
                    trigger.broadcaster_twitch_user_id,
                    trigger.trigger_id,
                    trigger.name,
                    type(exc).__name__,
                )

                return (
                    False,
                    f"Failed to unpin the message for "
                    f"trigger {trigger.trigger_id}.",
                )

        completed = (
            await self.repository.complete_deactivation(
                trigger.trigger_id
            )
        )

        if not completed:
            await self.repository.mark_operation_error(
                trigger.trigger_id,
                "Deactivation state could not be completed.",
            )

            logger.error(
                "Trigger deactivation failed: broadcaster=%s, "
                "trigger=%s, name=%r, "
                "operation=complete_state.",
                trigger.broadcaster_twitch_user_id,
                trigger.trigger_id,
                trigger.name,
            )

            return (
                False,
                f"Trigger {trigger.trigger_id} could not "
                "complete deactivation.",
            )

        return True, None

    @staticmethod
    def _deactivation_reason(trigger: Trigger) -> str:
        if not trigger.enabled:
            return "trigger_disabled"

        return "title_no_longer_matches"
