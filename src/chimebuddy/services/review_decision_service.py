from chimebuddy.models import (
    BroadcasterRequest,
    BroadcasterRequestStatus,
)
from chimebuddy.repositories import (
    BroadcasterRequestRepository,
)


class ReviewDecisionError(RuntimeError):
    """Base error for request review decisions."""


class ReviewRequestNotFoundError(
    ReviewDecisionError
):
    """Raised when a reviewed request does not exist."""


class ReviewRequestStateError(
    ReviewDecisionError
):
    """Raised when a request was already decided."""

    def __init__(
        self,
        request: BroadcasterRequest,
    ) -> None:
        self.request = request

        super().__init__(
            f"Request {request.request_id} cannot be "
            "reviewed while its status is "
            f"{request.status.value}."
        )


class ReviewDecisionService:
    """Applies safe broadcaster request decisions."""

    def __init__(
        self,
        request_repository: (
            BroadcasterRequestRepository
        ),
    ) -> None:
        self.request_repository = request_repository

    async def approve(
        self,
        request_id: int,
        *,
        actor_discord_user_id: str,
    ) -> BroadcasterRequest:
        actor_id = self._required_text(
            actor_discord_user_id,
            "actor_discord_user_id",
        )

        changed = (
            await self.request_repository.transition(
                request_id,
                expected_statuses=(
                    BroadcasterRequestStatus.PENDING,
                ),
                new_status=(
                    BroadcasterRequestStatus.APPROVING
                ),
                event_type="request_approved",
                actor_discord_user_id=actor_id,
            )
        )

        return await self._load_result(
            request_id,
            changed,
        )

    async def reject(
        self,
        request_id: int,
        *,
        actor_discord_user_id: str,
        requester_message: str | None = None,
    ) -> BroadcasterRequest:
        actor_id = self._required_text(
            actor_discord_user_id,
            "actor_discord_user_id",
        )

        message = self._optional_text(
            requester_message
        )

        changed = (
            await self.request_repository.transition(
                request_id,
                expected_statuses=(
                    BroadcasterRequestStatus.PENDING,
                ),
                new_status=(
                    BroadcasterRequestStatus.REJECTED
                ),
                event_type="request_rejected",
                actor_discord_user_id=actor_id,
                decision_reason=message,
            )
        )

        return await self._load_result(
            request_id,
            changed,
        )

    async def blacklist(
        self,
        request_id: int,
        *,
        actor_discord_user_id: str,
        internal_reason: str,
        requester_message: str | None = None,
    ) -> BroadcasterRequest:
        actor_id = self._required_text(
            actor_discord_user_id,
            "actor_discord_user_id",
        )

        internal = self._required_text(
            internal_reason,
            "internal_reason",
        )

        message = self._optional_text(
            requester_message
        )

        changed = (
            await self.request_repository
            .blacklist_pending(
                request_id,
                actor_discord_user_id=actor_id,
                internal_reason=internal,
                requester_message=message,
            )
        )

        return await self._load_result(
            request_id,
            changed,
        )

    async def _load_result(
        self,
        request_id: int,
        changed: bool,
    ) -> BroadcasterRequest:
        request = await self.request_repository.get(
            request_id
        )

        if request is None:
            raise ReviewRequestNotFoundError(
                f"Broadcaster request {request_id} "
                "does not exist."
            )

        if not changed:
            raise ReviewRequestStateError(request)

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

    @staticmethod
    def _optional_text(
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        cleaned = str(value).strip()
        return cleaned or None