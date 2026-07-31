from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

from chimebuddy.models import (
    Broadcaster,
    BroadcasterPanel,
    BroadcasterRequest,
    BroadcasterRequestStatus,
)
from chimebuddy.repositories import (
    BroadcasterPanelRepository,
    BroadcasterRequestRepository,
    IdentityRepository,
)
from chimebuddy.services.onboarding_service import (
    OnboardingService,
)


logger = logging.getLogger(
    "chimebuddy.provisioning"
)


class BroadcasterProvisioningError(RuntimeError):
    """Base error for broadcaster provisioning."""


class BroadcasterProvisioningStateError(
    BroadcasterProvisioningError
):
    """Raised when a request cannot be provisioned."""


class BroadcasterProvisioningFailedError(
    BroadcasterProvisioningError
):
    """Raised when an external provisioning action fails."""


@dataclass(frozen=True, slots=True)
class DiscordPanelLocation:
    discord_guild_id: str
    discord_channel_id: str
    opening_message_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "discord_guild_id",
            "discord_channel_id",
            "opening_message_id",
        ):
            value = str(
                getattr(self, field_name)
            ).strip()

            if not value:
                raise ValueError(
                    f"{field_name} cannot be empty."
                )

            object.__setattr__(
                self,
                field_name,
                value,
            )


@dataclass(frozen=True, slots=True)
class BroadcasterProvisioningResult:
    request_id: int
    twitch_user_id: str
    discord_user_id: str
    discord_channel_id: str
    opening_message_id: str
    already_active: bool


class BroadcasterPanelGateway(Protocol):
    async def ensure_panel(
        self,
        *,
        request: BroadcasterRequest,
        twitch_login: str,
        existing_panel: BroadcasterPanel | None,
    ) -> DiscordPanelLocation:
        """
        Create or recover the broadcaster's Discord
        channel and opening panel.
        """

    async def activate_panel(
        self,
        twitch_user_id: str,
    ) -> bool:
        """Attach live controls after database activation."""


class BroadcasterProvisioningService:
    """
    Coordinates database and Discord provisioning.

    Discord operations are delegated to a gateway so
    failures and retries can be tested safely.
    """

    def __init__(
        self,
        *,
        onboarding_service: OnboardingService,
        identity_repository: IdentityRepository,
        request_repository: BroadcasterRequestRepository,
        panel_repository: BroadcasterPanelRepository,
        panel_gateway: BroadcasterPanelGateway,
    ) -> None:
        self.onboarding_service = onboarding_service
        self.identity_repository = (
            identity_repository
        )
        self.request_repository = (
            request_repository
        )
        self.panel_repository = panel_repository
        self.panel_gateway = panel_gateway

        self._request_locks: dict[
            int,
            asyncio.Lock,
        ] = {}

    async def provision(
        self,
        request_id: int,
        *,
        actor_discord_user_id: str,
    ) -> BroadcasterProvisioningResult:
        parsed_request_id = int(request_id)

        if parsed_request_id <= 0:
            raise ValueError(
                "request_id must be greater than zero."
            )

        actor_id = str(
            actor_discord_user_id
        ).strip()

        if not actor_id:
            raise ValueError(
                "actor_discord_user_id cannot be empty."
            )

        lock = self._request_locks.setdefault(
            parsed_request_id,
            asyncio.Lock(),
        )

        async with lock:
            return await self._provision_locked(
                parsed_request_id,
                actor_id,
            )

    async def _provision_locked(
        self,
        request_id: int,
        actor_id: str,
    ) -> BroadcasterProvisioningResult:
        request = await self.request_repository.get(
            request_id
        )

        if request is None:
            raise BroadcasterProvisioningStateError(
                f"Broadcaster request {request_id} "
                "does not exist."
            )

        if (
            request.status
            is BroadcasterRequestStatus.ACTIVE
        ):
            return await self._active_result(request)

        if request.status in {
            BroadcasterRequestStatus.APPROVING,
            BroadcasterRequestStatus.PROVISIONING_FAILED,
        }:
            request = (
                await self.onboarding_service
                .begin_provisioning(
                    request_id,
                    actor_discord_user_id=actor_id,
                )
            )

        elif (
            request.status
            is not BroadcasterRequestStatus.PROVISIONING
        ):
            raise BroadcasterProvisioningStateError(
                f"Request {request_id} cannot be "
                "provisioned while its status is "
                f"{request.status.value}."
            )

        # The broadcaster exists while provisioning, but
        # remains disabled until every required step passes.
        await self.identity_repository.save_broadcaster(
            Broadcaster(
                twitch_user_id=request.twitch_user_id,
                owner_discord_user_id=(
                    request.discord_user_id
                ),
                enabled=False,
            )
        )

        try:
            twitch_account = (
                await self.identity_repository
                .get_twitch_account(
                    request.twitch_user_id
                )
            )

            if twitch_account is None:
                raise RuntimeError(
                    "The request's Twitch account "
                    "could not be loaded."
                )

            panel = (
                await self.panel_repository
                .get_for_broadcaster(
                    request.twitch_user_id
                )
            )

            if (
                panel is None
                or panel.opening_message_id is None
            ):
                location = (
                    await self.panel_gateway.ensure_panel(
                        request=request,
                        twitch_login=(
                            twitch_account.login
                        ),
                        existing_panel=panel,
                    )
                )

                if panel is None:
                    panel = (
                        await self.panel_repository.create(
                            BroadcasterPanel(
                                twitch_user_id=(
                                    request.twitch_user_id
                                ),
                                request_id=request_id,
                                discord_guild_id=(
                                    location.discord_guild_id
                                ),
                                discord_channel_id=(
                                    location.discord_channel_id
                                ),
                                opening_message_id=(
                                    location.opening_message_id
                                ),
                            )
                        )
                    )

                else:
                    if (
                        panel.discord_guild_id
                        != location.discord_guild_id
                        or panel.discord_channel_id
                        != location.discord_channel_id
                    ):
                        raise RuntimeError(
                            "Discord returned a different "
                            "channel for an existing "
                            "broadcaster panel."
                        )

                    changed = (
                        await self.panel_repository
                        .set_opening_message(
                            request.twitch_user_id,
                            location.opening_message_id,
                        )
                    )

                    if not changed:
                        raise RuntimeError(
                            "The opening panel message "
                            "could not be stored."
                        )

                    panel = (
                        await self.panel_repository
                        .get_for_broadcaster(
                            request.twitch_user_id
                        )
                    )

            if (
                panel is None
                or panel.opening_message_id is None
            ):
                raise RuntimeError(
                    "Broadcaster panel provisioning "
                    "did not produce a complete panel."
                )

            enabled = (
                await self.identity_repository
                .set_broadcaster_enabled(
                    request.twitch_user_id,
                    True,
                )
            )

            if not enabled:
                raise RuntimeError(
                    "The broadcaster could not be enabled."
                )

            await self.onboarding_service.mark_active(
                request_id,
                actor_discord_user_id=actor_id,
            )

            try:
                panel_activated = (
                    await self.panel_gateway.activate_panel(
                        request.twitch_user_id
                    )
                )

                if not panel_activated:
                    logger.warning(
                        "Broadcaster %s became active, but "
                        "its Discord controls were not "
                        "attached immediately.",
                        request.twitch_user_id,
                    )
            except Exception:
                # Core provisioning is already complete. A bot
                # restart can safely restore this panel later.
                logger.exception(
                    "Broadcaster %s became active, but its "
                    "Discord panel could not be refreshed.",
                    request.twitch_user_id,
                )

        except Exception as exc:
            await self._record_failure(
                request,
                actor_id,
            )

            raise BroadcasterProvisioningFailedError(
                f"Provisioning request {request_id} failed."
            ) from exc

        return BroadcasterProvisioningResult(
            request_id=request_id,
            twitch_user_id=request.twitch_user_id,
            discord_user_id=request.discord_user_id,
            discord_channel_id=(
                panel.discord_channel_id
            ),
            opening_message_id=(
                panel.opening_message_id
            ),
            already_active=False,
        )

    async def _active_result(
        self,
        request: BroadcasterRequest,
    ) -> BroadcasterProvisioningResult:
        broadcaster = (
            await self.identity_repository
            .get_broadcaster(
                request.twitch_user_id
            )
        )

        panel = (
            await self.panel_repository
            .get_for_broadcaster(
                request.twitch_user_id
            )
        )

        if (
            broadcaster is None
            or not broadcaster.enabled
            or panel is None
            or panel.opening_message_id is None
        ):
            raise BroadcasterProvisioningStateError(
                "The request is active, but its "
                "broadcaster records are incomplete."
            )

        return BroadcasterProvisioningResult(
            request_id=request.request_id,
            twitch_user_id=request.twitch_user_id,
            discord_user_id=request.discord_user_id,
            discord_channel_id=(
                panel.discord_channel_id
            ),
            opening_message_id=(
                panel.opening_message_id
            ),
            already_active=True,
        )

    async def _record_failure(
        self,
        request: BroadcasterRequest,
        actor_id: str,
    ) -> None:
        try:
            await self.identity_repository.set_broadcaster_enabled(
                request.twitch_user_id,
                False,
            )
        except Exception:
            logger.exception(
                "Failed to disable broadcaster %s "
                "after a provisioning error.",
                request.twitch_user_id,
            )

        try:
            current_request = (
                await self.request_repository.get(
                    request.request_id
                )
            )

            if (
                current_request is not None
                and current_request.status
                is BroadcasterRequestStatus.PROVISIONING
            ):
                await (
                    self.onboarding_service
                    .mark_provisioning_failed(
                        request.request_id,
                        reason=(
                            "Discord broadcaster "
                            "provisioning failed."
                        ),
                        actor_discord_user_id=actor_id,
                    )
                )

        except Exception:
            logger.exception(
                "Failed to record provisioning failure "
                "for request %s.",
                request.request_id,
            )
