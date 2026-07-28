from dataclasses import dataclass
from enum import StrEnum

from chimebuddy.models import (
    Trigger,
    TriggerRuntimeState,
    TriggerRuntimeStatus,
)


class TriggerAction(StrEnum):
    NONE = "none"
    ACTIVATE = "activate"
    DEACTIVATE = "deactivate"
    RESET_ERROR = "reset_error"


@dataclass(frozen=True, slots=True)
class TriggerDecision:
    action: TriggerAction
    reason: str

    @property
    def requires_action(self) -> bool:
        return self.action is not TriggerAction.NONE


class TriggerStateMachine:
    """Decides the next action for a title trigger."""

    def decide(
        self,
        trigger: Trigger,
        state: TriggerRuntimeState,
        *,
        title_matches: bool,
    ) -> TriggerDecision:
        if trigger.trigger_id is None:
            raise ValueError(
                "A stored trigger ID is required."
            )

        if trigger.trigger_id != state.trigger_id:
            raise ValueError(
                "Trigger and runtime state IDs do not match."
            )

        if state.status in {
            TriggerRuntimeStatus.ACTIVATING,
            TriggerRuntimeStatus.DEACTIVATING,
        }:
            return TriggerDecision(
                action=TriggerAction.NONE,
                reason="A trigger operation is already running.",
            )

        if state.status is TriggerRuntimeStatus.ERROR:
            if state.message_id:
                return TriggerDecision(
                    action=TriggerAction.DEACTIVATE,
                    reason=(
                        "The failed trigger still owns a "
                        "message and needs cleanup."
                    ),
                )

            return TriggerDecision(
                action=TriggerAction.RESET_ERROR,
                reason=(
                    "The failed trigger has no message and "
                    "can return to inactive."
                ),
            )

        if state.status is TriggerRuntimeStatus.ACTIVE:
            if not trigger.enabled:
                return TriggerDecision(
                    action=TriggerAction.DEACTIVATE,
                    reason=(
                        "The active trigger was disabled."
                    ),
                )

            if not title_matches:
                return TriggerDecision(
                    action=TriggerAction.DEACTIVATE,
                    reason=(
                        "The stream title no longer matches."
                    ),
                )

            return TriggerDecision(
                action=TriggerAction.NONE,
                reason=(
                    "The trigger is already active and the "
                    "title still matches."
                ),
            )

        if state.status is TriggerRuntimeStatus.INACTIVE:
            if not trigger.enabled:
                return TriggerDecision(
                    action=TriggerAction.NONE,
                    reason="The trigger is disabled.",
                )

            if title_matches:
                return TriggerDecision(
                    action=TriggerAction.ACTIVATE,
                    reason=(
                        "The inactive trigger now matches "
                        "the stream title."
                    ),
                )

            return TriggerDecision(
                action=TriggerAction.NONE,
                reason=(
                    "The inactive trigger does not match."
                ),
            )

        return TriggerDecision(
            action=TriggerAction.NONE,
            reason="No state transition is available.",
        )