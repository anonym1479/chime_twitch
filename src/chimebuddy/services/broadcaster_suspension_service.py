from chimebuddy.models import (
    BroadcasterRequest,
    BroadcasterRequestStatus,
    OAuthCredentialKind,
)
from chimebuddy.repositories import (
    BroadcasterRequestRepository,
    OAuthCredentialRepository,
)


class BroadcasterSuspensionError(RuntimeError):
    """Base error for developer suspension operations."""


class BroadcasterSuspensionStateError(
    BroadcasterSuspensionError
):
    """Raised when a request cannot change suspension state."""


class BroadcasterRestorationBlockedError(
    BroadcasterSuspensionError
):
    """Raised when a suspended broadcaster cannot be restored."""


class BroadcasterSuspensionService:
    """Suspends and restores broadcasters without deleting data."""

    def __init__(
        self,
        *,
        request_repository: BroadcasterRequestRepository,
        credential_repository: OAuthCredentialRepository,
    ) -> None:
        self.request_repository = request_repository
        self.credential_repository = credential_repository

    async def suspend(
        self,
        request_id: int,
        *,
        developer_discord_user_id: str,
        internal_reason: str,
    ) -> BroadcasterRequest:
        actor_id = self._required_text(
            developer_discord_user_id,
            "developer_discord_user_id",
        )
        reason = self._required_text(
            internal_reason,
            "internal_reason",
        )
        request = await self._get_request(request_id)

        if request.status not in {
            BroadcasterRequestStatus.ACTIVE,
            BroadcasterRequestStatus.SUSPENDED,
        }:
            raise BroadcasterSuspensionStateError(
                "Only an active broadcaster can be suspended."
            )

        changed = await self.request_repository.suspend_broadcaster(
            int(request_id),
            actor_discord_user_id=actor_id,
            internal_reason=reason,
        )

        if not changed:
            raise BroadcasterSuspensionStateError(
                "The broadcaster could not be suspended because "
                "its state changed."
            )

        return await self._get_request(request_id)

    async def restore(
        self,
        request_id: int,
        *,
        developer_discord_user_id: str,
    ) -> BroadcasterRequest:
        actor_id = self._required_text(
            developer_discord_user_id,
            "developer_discord_user_id",
        )
        request = await self._get_request(request_id)

        if (
            request.status
            is not BroadcasterRequestStatus.SUSPENDED
        ):
            raise BroadcasterSuspensionStateError(
                "Only a suspended broadcaster can be restored."
            )

        credential = await self.credential_repository.get(
            request.twitch_user_id,
            OAuthCredentialKind.BROADCASTER,
        )

        if credential is None:
            raise BroadcasterRestorationBlockedError(
                "The broadcaster cannot be restored because its "
                "Twitch authorization is missing."
            )

        changed = (
            await self.request_repository
            .restore_suspended_broadcaster(
                int(request_id),
                actor_discord_user_id=actor_id,
            )
        )

        if not changed:
            raise BroadcasterSuspensionStateError(
                "The broadcaster could not be restored because "
                "its state changed or authorization became invalid."
            )

        return await self._get_request(request_id)

    async def _get_request(
        self,
        request_id: int,
    ) -> BroadcasterRequest:
        request = await self.request_repository.get(
            int(request_id)
        )

        if request is None:
            raise BroadcasterSuspensionStateError(
                "The broadcaster request does not exist."
            )

        return request

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
