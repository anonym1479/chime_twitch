from dataclasses import dataclass
from enum import StrEnum


def _clean_required(value: str, field_name: str) -> str:
    cleaned = str(value).strip()

    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty.")

    return cleaned


class TriggerSource(StrEnum):
    STREAM_TITLE = "stream_title"


class TriggerMatchType(StrEnum):
    CONTAINS = "contains"
    EXACT = "exact"


class TriggerRuntimeStatus(StrEnum):
    INACTIVE = "inactive"
    ACTIVATING = "activating"
    ACTIVE = "active"
    DEACTIVATING = "deactivating"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Trigger:
    broadcaster_twitch_user_id: str
    name: str
    expression: str
    response_message: str
    source: TriggerSource = TriggerSource.STREAM_TITLE
    match_type: TriggerMatchType = TriggerMatchType.CONTAINS
    pin_message: bool = True
    priority: int = 100
    enabled: bool = True
    trigger_id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "broadcaster_twitch_user_id",
            _clean_required(
                self.broadcaster_twitch_user_id,
                "broadcaster_twitch_user_id",
            ),
        )
        object.__setattr__(
            self,
            "name",
            _clean_required(self.name, "name"),
        )
        object.__setattr__(
            self,
            "expression",
            _clean_required(
                self.expression,
                "expression",
            ),
        )
        object.__setattr__(
            self,
            "response_message",
            _clean_required(
                self.response_message,
                "response_message",
            ),
        )

        if self.priority < 0:
            raise ValueError("priority cannot be negative.")

        if self.trigger_id is not None and self.trigger_id <= 0:
            raise ValueError(
                "trigger_id must be greater than zero."
            )


@dataclass(frozen=True, slots=True)
class TriggerRuntimeState:
    trigger_id: int
    status: TriggerRuntimeStatus
    last_title: str | None
    message_id: str | None
    is_pinned: bool
    activated_at: str | None
    operation_started_at: str | None
    updated_at: str
    last_error: str | None