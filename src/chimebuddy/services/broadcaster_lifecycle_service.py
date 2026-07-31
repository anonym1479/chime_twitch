from chimebuddy.models import (
    BroadcasterProfile,
    BroadcasterRequestStatus,
    OAuthCredentialKind,
)
from chimebuddy.repositories import (
    BroadcasterRequestRepository,
    IdentityRepository,
    OAuthCredentialRepository,
)


class BroadcasterLifecycleError(RuntimeError):
    """Base error for broadcaster lifecycle changes."""


class BroadcasterNotFoundError(
    BroadcasterLifecycleError
):
    """Raised when the broadcaster does not exist."""


class BroadcasterResumeBlockedError(
    BroadcasterLifecycleError
):
    """Raised when a broadcaster cannot safely resume."""


class BroadcasterLifecycleService:
    """Safely pauses and resumes a broadcaster."""

    def __init__(
        self,
        *,
        identity_repository: IdentityRepository,
        credential_repository: OAuthCredentialRepository,
        request_repository: BroadcasterRequestRepository,
    ) -> None:
        self.identity_repository = identity_repository
        self.credential_repository = (
            credential_repository
        )
        self.request_repository = request_repository

    async def pause(
        self,
        twitch_user_id: str,
    ) -> BroadcasterProfile:
        return await self._set_enabled(
            twitch_user_id,
            enabled=False,
        )

    async def resume(
        self,
        twitch_user_id: str,
    ) -> BroadcasterProfile:
        twitch_id = self._required_id(
            twitch_user_id
        )

        request = (
            await self.request_repository
            .get_open_for_twitch(twitch_id)
        )

        if (
            request is not None
            and request.status
            is BroadcasterRequestStatus.SUSPENDED
        ):
            raise BroadcasterResumeBlockedError(
                "This broadcaster was suspended by the "
                "ChimeBuddy developer and can only be "
                "restored by the developer."
            )

        credential = (
            await self.credential_repository.get(
                twitch_id,
                OAuthCredentialKind.BROADCASTER,
            )
        )

        if credential is None:
            raise BroadcasterResumeBlockedError(
                "The broadcaster cannot be resumed "
                "because its Twitch authorization is "
                "missing."
            )

        return await self._set_enabled(
            twitch_id,
            enabled=True,
        )

    async def _set_enabled(
        self,
        twitch_user_id: str,
        *,
        enabled: bool,
    ) -> BroadcasterProfile:
        twitch_id = self._required_id(
            twitch_user_id
        )

        current = (
            await self.identity_repository
            .get_broadcaster(twitch_id)
        )

        if current is None:
            raise BroadcasterNotFoundError(
                "The broadcaster does not exist."
            )

        # Repeated button presses are harmless.
        if current.enabled is enabled:
            return current

        changed = (
            await self.identity_repository
            .set_broadcaster_enabled(
                twitch_id,
                enabled,
            )
        )

        if not changed:
            raise BroadcasterLifecycleError(
                "The broadcaster status could not be "
                "updated."
            )

        updated = (
            await self.identity_repository
            .get_broadcaster(twitch_id)
        )

        if updated is None:
            raise BroadcasterLifecycleError(
                "The broadcaster disappeared after its "
                "status was updated."
            )

        return updated

    @staticmethod
    def _required_id(
        twitch_user_id: str,
    ) -> str:
        twitch_id = str(twitch_user_id).strip()

        if not twitch_id:
            raise ValueError(
                "twitch_user_id cannot be empty."
            )

        return twitch_id
