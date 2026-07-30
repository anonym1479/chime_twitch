from chimebuddy.models import (
    Trigger,
    TriggerMatchType,
    TriggerRuntimeStatus,
)
from chimebuddy.repositories import (
    DuplicateTriggerNameError,
    IdentityRepository,
    TriggerRepository,
)


DEFAULT_MAX_TRIGGERS = 25
MAX_TRIGGER_NAME_LENGTH = 50
MAX_TRIGGER_EXPRESSION_LENGTH = 200
MAX_TRIGGER_RESPONSE_LENGTH = 450
MAX_TRIGGER_PRIORITY = 10000


class TriggerManagementError(RuntimeError):
    """Base error for broadcaster trigger management."""


class ManagedTriggerNotFoundError(
    TriggerManagementError
):
    """Raised when an owned trigger cannot be found."""


class TriggerBusyError(TriggerManagementError):
    """Raised when runtime cleanup must finish first."""


class TriggerLimitReachedError(
    TriggerManagementError
):
    """Raised when a broadcaster has too many triggers."""


class TriggerValidationError(
    TriggerManagementError
):
    """Raised when trigger input is invalid."""


class TriggerNameConflictError(
    TriggerManagementError
):
    """Raised when an owned trigger name is duplicated."""


class ManagedBroadcasterNotFoundError(
    TriggerManagementError
):
    """Raised when trigger management has no broadcaster."""


class TriggerManagementService:
    """Safely manages broadcaster title triggers."""

    def __init__(
        self,
        *,
        trigger_repository: TriggerRepository,
        identity_repository: IdentityRepository,
        max_triggers: int = DEFAULT_MAX_TRIGGERS,
    ) -> None:
        if max_triggers <= 0:
            raise ValueError(
                "max_triggers must be positive."
            )

        self.trigger_repository = trigger_repository
        self.identity_repository = identity_repository
        self.max_triggers = int(max_triggers)

    async def list_triggers(
        self,
        broadcaster_twitch_user_id: str,
    ) -> list[Trigger]:
        broadcaster_id = (
            await self._require_broadcaster(
                broadcaster_twitch_user_id
            )
        )

        return await self.trigger_repository.list_triggers(
            broadcaster_id
        )

    async def create_trigger(
        self,
        broadcaster_twitch_user_id: str,
        *,
        name: str,
        expression: str,
        response_message: str,
        match_type: TriggerMatchType = (
            TriggerMatchType.CONTAINS
        ),
        pin_message: bool = True,
        priority: int = 100,
        enabled: bool = True,
    ) -> Trigger:
        broadcaster_id = (
            await self._require_broadcaster(
                broadcaster_twitch_user_id
            )
        )

        existing = (
            await self.trigger_repository.list_triggers(
                broadcaster_id
            )
        )

        if len(existing) >= self.max_triggers:
            raise TriggerLimitReachedError(
                "This broadcaster has reached the "
                f"limit of {self.max_triggers} triggers."
            )

        trigger = self._build_trigger(
            broadcaster_id,
            name=name,
            expression=expression,
            response_message=response_message,
            match_type=match_type,
            pin_message=pin_message,
            priority=priority,
            enabled=enabled,
        )

        try:
            return (
                await self.trigger_repository
                .create_trigger(trigger)
            )
        except DuplicateTriggerNameError as exc:
            raise TriggerNameConflictError(
                "A trigger with this name already exists."
            ) from exc

    async def update_trigger(
        self,
        broadcaster_twitch_user_id: str,
        trigger_id: int,
        *,
        name: str,
        expression: str,
        response_message: str,
        match_type: TriggerMatchType,
        pin_message: bool,
        priority: int,
        enabled: bool,
    ) -> Trigger:
        broadcaster_id = self._required_id(
            broadcaster_twitch_user_id
        )

        current = await self._get_owned_trigger(
            broadcaster_id,
            trigger_id,
        )

        state = (
            await self.trigger_repository
            .get_runtime_state(current.trigger_id)
        )

        if (
            state is None
            or state.status
            is not TriggerRuntimeStatus.INACTIVE
        ):
            raise TriggerBusyError(
                "This trigger cannot be edited until "
                "its active Twitch message has been "
                "cleaned up."
            )

        replacement = self._build_trigger(
            broadcaster_id,
            trigger_id=current.trigger_id,
            name=name,
            expression=expression,
            response_message=response_message,
            match_type=match_type,
            pin_message=pin_message,
            priority=priority,
            enabled=enabled,
        )

        try:
            changed = (
                await self.trigger_repository
                .update_inactive_trigger(replacement)
            )
        except DuplicateTriggerNameError as exc:
            raise TriggerNameConflictError(
                "A trigger with this name already exists."
            ) from exc

        if not changed:
            raise TriggerBusyError(
                "The trigger changed while it was being "
                "edited. Refresh the panel and try again."
            )

        updated = (
            await self.trigger_repository.get_trigger(
                current.trigger_id
            )
        )

        if updated is None:
            raise ManagedTriggerNotFoundError(
                "The updated trigger could not be found."
            )

        return updated

    async def set_enabled(
        self,
        broadcaster_twitch_user_id: str,
        trigger_id: int,
        enabled: bool,
    ) -> Trigger:
        broadcaster_id = self._required_id(
            broadcaster_twitch_user_id
        )

        current = await self._get_owned_trigger(
            broadcaster_id,
            trigger_id,
        )

        desired = bool(enabled)

        if current.enabled is desired:
            return current

        changed = (
            await self.trigger_repository
            .set_trigger_enabled_for_broadcaster(
                current.trigger_id,
                broadcaster_id,
                desired,
            )
        )

        if not changed:
            raise ManagedTriggerNotFoundError(
                "The trigger could not be updated."
            )

        updated = (
            await self.trigger_repository.get_trigger(
                current.trigger_id
            )
        )

        if updated is None:
            raise ManagedTriggerNotFoundError(
                "The updated trigger could not be found."
            )

        return updated

    async def delete_trigger(
        self,
        broadcaster_twitch_user_id: str,
        trigger_id: int,
    ) -> None:
        broadcaster_id = self._required_id(
            broadcaster_twitch_user_id
        )

        trigger = await self._get_owned_trigger(
            broadcaster_id,
            trigger_id,
        )

        state = (
            await self.trigger_repository
            .get_runtime_state(trigger.trigger_id)
        )

        if (
            state is None
            or state.status
            is not TriggerRuntimeStatus.INACTIVE
        ):
            raise TriggerBusyError(
                "Disable this trigger and wait for its "
                "Twitch message cleanup before deleting "
                "it."
            )

        deleted = (
            await self.trigger_repository
            .delete_inactive_trigger(
                trigger.trigger_id,
                broadcaster_id,
            )
        )

        if not deleted:
            raise TriggerBusyError(
                "The trigger changed while it was being "
                "deleted. Refresh and try again."
            )

    async def _require_broadcaster(
        self,
        broadcaster_twitch_user_id: str,
    ) -> str:
        broadcaster_id = self._required_id(
            broadcaster_twitch_user_id
        )

        broadcaster = (
            await self.identity_repository
            .get_broadcaster(broadcaster_id)
        )

        if broadcaster is None:
            raise ManagedBroadcasterNotFoundError(
                "The broadcaster does not exist."
            )

        return broadcaster_id

    async def _get_owned_trigger(
        self,
        broadcaster_twitch_user_id: str,
        trigger_id: int,
    ) -> Trigger:
        parsed_trigger_id = int(trigger_id)

        if parsed_trigger_id <= 0:
            raise TriggerValidationError(
                "trigger_id must be greater than zero."
            )

        trigger = (
            await self.trigger_repository.get_trigger(
                parsed_trigger_id
            )
        )

        if (
            trigger is None
            or trigger.broadcaster_twitch_user_id
            != broadcaster_twitch_user_id
        ):
            # Do not reveal another broadcaster's trigger.
            raise ManagedTriggerNotFoundError(
                "The trigger does not exist."
            )

        return trigger

    def _build_trigger(
        self,
        broadcaster_twitch_user_id: str,
        *,
        name: str,
        expression: str,
        response_message: str,
        match_type: TriggerMatchType,
        pin_message: bool,
        priority: int,
        enabled: bool,
        trigger_id: int | None = None,
    ) -> Trigger:
        cleaned_name = self._validated_text(
            name,
            "name",
            MAX_TRIGGER_NAME_LENGTH,
        )
        cleaned_expression = self._validated_text(
            expression,
            "expression",
            MAX_TRIGGER_EXPRESSION_LENGTH,
        )
        cleaned_response = self._validated_text(
            response_message,
            "response_message",
            MAX_TRIGGER_RESPONSE_LENGTH,
        )

        try:
            normalized_match_type = TriggerMatchType(
                match_type
            )
        except ValueError as exc:
            raise TriggerValidationError(
                "match_type must be contains or exact."
            ) from exc

        try:
            normalized_priority = int(priority)
        except (TypeError, ValueError) as exc:
            raise TriggerValidationError(
                "priority must be an integer."
            ) from exc

        if not (
            0
            <= normalized_priority
            <= MAX_TRIGGER_PRIORITY
        ):
            raise TriggerValidationError(
                "priority must be between 0 and "
                f"{MAX_TRIGGER_PRIORITY}."
            )

        return Trigger(
            trigger_id=trigger_id,
            broadcaster_twitch_user_id=(
                broadcaster_twitch_user_id
            ),
            name=cleaned_name,
            expression=cleaned_expression,
            response_message=cleaned_response,
            match_type=normalized_match_type,
            pin_message=bool(pin_message),
            priority=normalized_priority,
            enabled=bool(enabled),
        )

    @staticmethod
    def _validated_text(
        value: str,
        field_name: str,
        maximum_length: int,
    ) -> str:
        cleaned = str(value).strip()

        if not cleaned:
            raise TriggerValidationError(
                f"{field_name} cannot be empty."
            )

        if len(cleaned) > maximum_length:
            raise TriggerValidationError(
                f"{field_name} cannot exceed "
                f"{maximum_length} characters."
            )

        return cleaned

    @staticmethod
    def _required_id(
        broadcaster_twitch_user_id: str,
    ) -> str:
        broadcaster_id = str(
            broadcaster_twitch_user_id
        ).strip()

        if not broadcaster_id:
            raise TriggerValidationError(
                "broadcaster_twitch_user_id cannot be "
                "empty."
            )

        return broadcaster_id