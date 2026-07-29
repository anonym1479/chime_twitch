from collections.abc import Iterable

from chimebuddy.models import (
    AccountLinkStatus,
    BroadcasterRequest,
    BroadcasterRequestStatus,
    OAuthCredentialKind,
)
from chimebuddy.repositories import (
    BroadcasterBlacklistRepository,
    BroadcasterRequestRepository,
    IdentityRepository,
    OAuthCredentialRepository,
)


class OnboardingError(RuntimeError):
    """Base error for onboarding operations."""


class AccountLinkRequiredError(OnboardingError):
    """Raised when Discord and Twitch are not verified together."""


class BroadcasterAuthorizationRequiredError(
    OnboardingError
):
    """Raised when broadcaster OAuth authorization is missing."""


class BlacklistedIdentityError(OnboardingError):
    """Raised when Discord or Twitch is blacklisted."""


class RequestStateConflictError(OnboardingError):
    """Raised when a request is no longer in the expected state."""


class OnboardingService:
    """Coordinates broadcaster applications and decisions."""

    def __init__(
        self,
        identity_repository: IdentityRepository,
        credential_repository: OAuthCredentialRepository,
        request_repository: BroadcasterRequestRepository,
        blacklist_repository: (
            BroadcasterBlacklistRepository
        ),
    ) -> None:
        self.identity_repository = identity_repository
        self.credential_repository = (
            credential_repository
        )
        self.request_repository = request_repository
        self.blacklist_repository = (
            blacklist_repository
        )

    async def create_request(
        self,
        *,
        twitch_user_id: str,
        discord_user_id: str,
        requester_message: str | None = None,
    ) -> BroadcasterRequest:
        twitch_id = self._required_text(
            twitch_user_id,
            "twitch_user_id",
        )
        discord_id = self._required_text(
            discord_user_id,
            "discord_user_id",
        )
        message = self._optional_text(
            requester_message
        )

        blacklist_entry = (
            await self.blacklist_repository.find_active(
                discord_user_id=discord_id,
                twitch_user_id=twitch_id,
            )
        )

        if blacklist_entry is not None:
            raise BlacklistedIdentityError(
                "This Discord or Twitch account cannot "
                "request ChimeBuddy access."
            )

        link = (
            await self.identity_repository
            .get_account_link(twitch_id)
        )

        if (
            link is None
            or link.discord_user_id != discord_id
            or link.status
            is not AccountLinkStatus.VERIFIED
        ):
            raise AccountLinkRequiredError(
                "The Discord and Twitch accounts must be "
                "linked and verified first."
            )

        credential = (
            await self.credential_repository.get(
                twitch_id,
                OAuthCredentialKind.BROADCASTER,
            )
        )

        if credential is None:
            raise BroadcasterAuthorizationRequiredError(
                "The broadcaster must authorize "
                "ChimeBuddy before requesting access."
            )

        return await self.request_repository.create(
            BroadcasterRequest(
                twitch_user_id=twitch_id,
                discord_user_id=discord_id,
                requester_message=message,
            )
        )

    async def begin_approval(
        self,
        request_id: int,
        *,
        developer_discord_user_id: str,
        note: str | None = None,
    ) -> BroadcasterRequest:
        return await self._transition(
            request_id,
            expected_statuses=(
                BroadcasterRequestStatus.PENDING,
            ),
            new_status=(
                BroadcasterRequestStatus.APPROVING
            ),
            event_type="request_approved",
            actor_discord_user_id=(
                developer_discord_user_id
            ),
            decision_reason=note,
        )

    async def reject_request(
        self,
        request_id: int,
        *,
        developer_discord_user_id: str,
        reason: str,
    ) -> BroadcasterRequest:
        rejection_reason = self._required_text(
            reason,
            "reason",
        )

        return await self._transition(
            request_id,
            expected_statuses=(
                BroadcasterRequestStatus.PENDING,
                BroadcasterRequestStatus.APPROVING,
            ),
            new_status=(
                BroadcasterRequestStatus.REJECTED
            ),
            event_type="request_rejected",
            actor_discord_user_id=(
                developer_discord_user_id
            ),
            decision_reason=rejection_reason,
        )

    async def begin_provisioning(
        self,
        request_id: int,
        *,
        actor_discord_user_id: str,
    ) -> BroadcasterRequest:
        return await self._transition(
            request_id,
            expected_statuses=(
                BroadcasterRequestStatus.APPROVING,
                BroadcasterRequestStatus.PROVISIONING_FAILED,
            ),
            new_status=(
                BroadcasterRequestStatus.PROVISIONING
            ),
            event_type="provisioning_started",
            actor_discord_user_id=(
                actor_discord_user_id
            ),
        )

    async def mark_active(
        self,
        request_id: int,
        *,
        actor_discord_user_id: str,
    ) -> BroadcasterRequest:
        return await self._transition(
            request_id,
            expected_statuses=(
                BroadcasterRequestStatus.PROVISIONING,
            ),
            new_status=(
                BroadcasterRequestStatus.ACTIVE
            ),
            event_type="provisioning_completed",
            actor_discord_user_id=(
                actor_discord_user_id
            ),
        )

    async def mark_provisioning_failed(
        self,
        request_id: int,
        *,
        reason: str,
        actor_discord_user_id: str | None = None,
    ) -> BroadcasterRequest:
        failure_reason = self._required_text(
            reason,
            "reason",
        )

        return await self._transition(
            request_id,
            expected_statuses=(
                BroadcasterRequestStatus.PROVISIONING,
            ),
            new_status=(
                BroadcasterRequestStatus.PROVISIONING_FAILED
            ),
            event_type="provisioning_failed",
            actor_discord_user_id=(
                actor_discord_user_id
            ),
            decision_reason=failure_reason,
        )

    async def _transition(
        self,
        request_id: int,
        *,
        expected_statuses: Iterable[
            BroadcasterRequestStatus
        ],
        new_status: BroadcasterRequestStatus,
        event_type: str,
        actor_discord_user_id: str | None,
        decision_reason: str | None = None,
    ) -> BroadcasterRequest:
        actor_id = self._optional_text(
            actor_discord_user_id
        )

        changed = await self.request_repository.transition(
            int(request_id),
            expected_statuses=expected_statuses,
            new_status=new_status,
            event_type=event_type,
            actor_discord_user_id=actor_id,
            decision_reason=decision_reason,
        )

        if not changed:
            raise RequestStateConflictError(
                "The broadcaster request no longer has "
                "the expected status. It may already have "
                "been handled."
            )

        updated = await self.request_repository.get(
            int(request_id)
        )

        if updated is None:
            raise OnboardingError(
                "The broadcaster request disappeared "
                "after its status was updated."
            )

        return updated

    @staticmethod
    def _required_text(
        value: str,
        field_name: str,
    ) -> str:
        cleaned = str(value).strip()

        if not cleaned:
            raise ValueError(
                f"{field_name} cannot be empty."
            )

        return cleaned

    @staticmethod
    def _optional_text(
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        cleaned = str(value).strip()
        return cleaned or None