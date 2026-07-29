import json
from dataclasses import dataclass
from enum import StrEnum


def _clean_required(
    value: str,
    field_name: str,
) -> str:
    cleaned = str(value).strip()

    if not cleaned:
        raise ValueError(
            f"{field_name} cannot be empty."
        )

    return cleaned


def _clean_optional(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()
    return cleaned or None


def _optional_positive_id(
    value: int | None,
    field_name: str,
) -> int | None:
    if value is None:
        return None

    parsed = int(value)

    if parsed <= 0:
        raise ValueError(
            f"{field_name} must be greater than zero."
        )

    return parsed


class AccountLinkSessionStatus(StrEnum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    FAILED = "failed"


class BroadcasterRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVING = "approving"
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    REJECTED = "rejected"
    BLACKLISTED = "blacklisted"
    PROVISIONING_FAILED = "provisioning_failed"
    SUSPENDED = "suspended"
    REAUTHORIZATION_REQUIRED = (
        "reauthorization_required"
    )


OPEN_BROADCASTER_REQUEST_STATUSES = frozenset(
    {
        BroadcasterRequestStatus.PENDING,
        BroadcasterRequestStatus.APPROVING,
        BroadcasterRequestStatus.PROVISIONING,
        BroadcasterRequestStatus.ACTIVE,
        BroadcasterRequestStatus.PROVISIONING_FAILED,
        BroadcasterRequestStatus.SUSPENDED,
        BroadcasterRequestStatus.REAUTHORIZATION_REQUIRED,
    }
)


@dataclass(frozen=True, slots=True)
class AccountLinkSession:
    session_id: str
    discord_user_id: str
    expires_at: int
    requested_scopes: tuple[str, ...] = ()
    twitch_user_id: str | None = None
    status: AccountLinkSessionStatus = (
        AccountLinkSessionStatus.PENDING
    )
    created_at: str | None = None
    completed_at: str | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "session_id",
            _clean_required(
                self.session_id,
                "session_id",
            ),
        )
        object.__setattr__(
            self,
            "discord_user_id",
            _clean_required(
                self.discord_user_id,
                "discord_user_id",
            ),
        )
        object.__setattr__(
            self,
            "twitch_user_id",
            _clean_optional(self.twitch_user_id),
        )

        expires_at = int(self.expires_at)

        if expires_at <= 0:
            raise ValueError(
                "expires_at must be greater than zero."
            )

        object.__setattr__(
            self,
            "expires_at",
            expires_at,
        )

        normalized_scopes = tuple(
            sorted(
                {
                    str(scope).strip()
                    for scope in self.requested_scopes
                    if str(scope).strip()
                }
            )
        )

        object.__setattr__(
            self,
            "requested_scopes",
            normalized_scopes,
        )
        object.__setattr__(
            self,
            "status",
            AccountLinkSessionStatus(self.status),
        )
        object.__setattr__(
            self,
            "created_at",
            _clean_optional(self.created_at),
        )
        object.__setattr__(
            self,
            "completed_at",
            _clean_optional(self.completed_at),
        )
        object.__setattr__(
            self,
            "last_error",
            _clean_optional(self.last_error),
        )


@dataclass(frozen=True, slots=True)
class BroadcasterRequest:
    twitch_user_id: str
    discord_user_id: str
    status: BroadcasterRequestStatus = (
        BroadcasterRequestStatus.PENDING
    )
    request_id: int | None = None

    review_guild_id: str | None = None
    review_channel_id: str | None = None
    review_message_id: str | None = None

    decision_reason: str | None = None
    requester_message: str | None = None
    decided_by_discord_user_id: str | None = None

    created_at: str | None = None
    updated_at: str | None = None
    decided_at: str | None = None
    provisioned_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "twitch_user_id",
            _clean_required(
                self.twitch_user_id,
                "twitch_user_id",
            ),
        )
        object.__setattr__(
            self,
            "discord_user_id",
            _clean_required(
                self.discord_user_id,
                "discord_user_id",
            ),
        )
        object.__setattr__(
            self,
            "status",
            BroadcasterRequestStatus(self.status),
        )
        object.__setattr__(
            self,
            "request_id",
            _optional_positive_id(
                self.request_id,
                "request_id",
            ),
        )

        optional_fields = (
            "review_guild_id",
            "review_channel_id",
            "review_message_id",
            "decision_reason",
            "requester_message",
            "decided_by_discord_user_id",
            "created_at",
            "updated_at",
            "decided_at",
            "provisioned_at",
        )

        for field_name in optional_fields:
            object.__setattr__(
                self,
                field_name,
                _clean_optional(
                    getattr(self, field_name)
                ),
            )

    @property
    def is_open(self) -> bool:
        return (
            self.status
            in OPEN_BROADCASTER_REQUEST_STATUSES
        )


@dataclass(frozen=True, slots=True)
class BroadcasterPanel:
    twitch_user_id: str
    request_id: int
    discord_guild_id: str
    discord_channel_id: str
    opening_message_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "twitch_user_id",
            _clean_required(
                self.twitch_user_id,
                "twitch_user_id",
            ),
        )

        request_id = int(self.request_id)

        if request_id <= 0:
            raise ValueError(
                "request_id must be greater than zero."
            )

        object.__setattr__(
            self,
            "request_id",
            request_id,
        )
        object.__setattr__(
            self,
            "discord_guild_id",
            _clean_required(
                self.discord_guild_id,
                "discord_guild_id",
            ),
        )
        object.__setattr__(
            self,
            "discord_channel_id",
            _clean_required(
                self.discord_channel_id,
                "discord_channel_id",
            ),
        )
        object.__setattr__(
            self,
            "opening_message_id",
            _clean_optional(
                self.opening_message_id
            ),
        )
        object.__setattr__(
            self,
            "created_at",
            _clean_optional(self.created_at),
        )
        object.__setattr__(
            self,
            "updated_at",
            _clean_optional(self.updated_at),
        )


@dataclass(frozen=True, slots=True)
class BroadcasterBlacklistEntry:
    internal_reason: str
    created_by_discord_user_id: str
    discord_user_id: str | None = None
    twitch_user_id: str | None = None
    requester_message: str | None = None
    active: bool = True
    blacklist_id: int | None = None
    created_at: str | None = None
    revoked_at: str | None = None
    revoked_by_discord_user_id: str | None = None
    revocation_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "internal_reason",
            _clean_required(
                self.internal_reason,
                "internal_reason",
            ),
        )
        object.__setattr__(
            self,
            "created_by_discord_user_id",
            _clean_required(
                self.created_by_discord_user_id,
                "created_by_discord_user_id",
            ),
        )
        object.__setattr__(
            self,
            "discord_user_id",
            _clean_optional(self.discord_user_id),
        )
        object.__setattr__(
            self,
            "twitch_user_id",
            _clean_optional(self.twitch_user_id),
        )

        if (
            self.discord_user_id is None
            and self.twitch_user_id is None
        ):
            raise ValueError(
                "A blacklist entry requires a Discord "
                "user ID, Twitch user ID, or both."
            )

        object.__setattr__(
            self,
            "blacklist_id",
            _optional_positive_id(
                self.blacklist_id,
                "blacklist_id",
            ),
        )
        object.__setattr__(
            self,
            "active",
            bool(self.active),
        )

        optional_fields = (
            "requester_message",
            "created_at",
            "revoked_at",
            "revoked_by_discord_user_id",
            "revocation_reason",
        )

        for field_name in optional_fields:
            object.__setattr__(
                self,
                field_name,
                _clean_optional(
                    getattr(self, field_name)
                ),
            )


@dataclass(frozen=True, slots=True)
class OnboardingRequestEvent:
    request_id: int
    event_type: str
    from_status: BroadcasterRequestStatus | None = None
    to_status: BroadcasterRequestStatus | None = None
    actor_discord_user_id: str | None = None
    details_json: str = "{}"
    event_id: int | None = None
    created_at: str | None = None

    def __post_init__(self) -> None:
        request_id = int(self.request_id)

        if request_id <= 0:
            raise ValueError(
                "request_id must be greater than zero."
            )

        object.__setattr__(
            self,
            "request_id",
            request_id,
        )
        object.__setattr__(
            self,
            "event_type",
            _clean_required(
                self.event_type,
                "event_type",
            ),
        )
        object.__setattr__(
            self,
            "event_id",
            _optional_positive_id(
                self.event_id,
                "event_id",
            ),
        )

        if self.from_status is not None:
            object.__setattr__(
                self,
                "from_status",
                BroadcasterRequestStatus(
                    self.from_status
                ),
            )

        if self.to_status is not None:
            object.__setattr__(
                self,
                "to_status",
                BroadcasterRequestStatus(
                    self.to_status
                ),
            )

        object.__setattr__(
            self,
            "actor_discord_user_id",
            _clean_optional(
                self.actor_discord_user_id
            ),
        )
        object.__setattr__(
            self,
            "created_at",
            _clean_optional(self.created_at),
        )

        try:
            details = json.loads(self.details_json)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "details_json must contain valid JSON."
            ) from exc

        if not isinstance(details, dict):
            raise ValueError(
                "details_json must contain a JSON object."
            )

        object.__setattr__(
            self,
            "details_json",
            json.dumps(
                details,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )