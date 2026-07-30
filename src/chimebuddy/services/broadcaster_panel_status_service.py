from dataclasses import dataclass

from chimebuddy.models import (
    BroadcasterRequestStatus,
    OAuthCredentialKind,
)
from chimebuddy.repositories import (
    BroadcasterPanelRepository,
    BroadcasterRequestRepository,
    IdentityRepository,
    OAuthCredentialRepository,
    TriggerRepository,
)


class BroadcasterPanelStatusError(RuntimeError):
    """Base error for broadcaster panel status."""


class BroadcasterPanelNotFoundError(
    BroadcasterPanelStatusError
):
    """Raised when no stored panel exists."""


class BroadcasterPanelDataError(
    BroadcasterPanelStatusError
):
    """Raised when related panel data is incomplete."""


@dataclass(frozen=True, slots=True)
class BroadcasterPanelStatus:
    request_id: int
    request_status: BroadcasterRequestStatus

    twitch_user_id: str
    twitch_login: str
    twitch_display_name: str

    owner_discord_user_id: str
    owner_discord_username: str
    owner_discord_display_name: str

    broadcaster_enabled: bool

    total_triggers: int
    enabled_triggers: int

    credential_stored: bool
    credential_expires_at: int | None

    discord_guild_id: str
    discord_channel_id: str
    opening_message_id: str | None

    @property
    def disabled_triggers(self) -> int:
        return (
            self.total_triggers
            - self.enabled_triggers
        )


class BroadcasterPanelStatusService:
    """Builds safe broadcaster dashboard status."""

    def __init__(
        self,
        *,
        panel_repository: BroadcasterPanelRepository,
        identity_repository: IdentityRepository,
        request_repository: BroadcasterRequestRepository,
        credential_repository: OAuthCredentialRepository,
        trigger_repository: TriggerRepository,
    ) -> None:
        self.panel_repository = panel_repository
        self.identity_repository = (
            identity_repository
        )
        self.request_repository = (
            request_repository
        )
        self.credential_repository = (
            credential_repository
        )
        self.trigger_repository = (
            trigger_repository
        )

    async def get_for_broadcaster(
        self,
        twitch_user_id: str,
    ) -> BroadcasterPanelStatus:
        twitch_id = str(
            twitch_user_id
        ).strip()

        if not twitch_id:
            raise ValueError(
                "twitch_user_id cannot be empty."
            )

        panel = (
            await self.panel_repository
            .get_for_broadcaster(twitch_id)
        )

        if panel is None:
            raise BroadcasterPanelNotFoundError(
                "No management panel exists for "
                f"Twitch user {twitch_id}."
            )

        return await self._build_status(panel)

    async def get_for_channel(
        self,
        discord_channel_id: str,
    ) -> BroadcasterPanelStatus:
        channel_id = str(
            discord_channel_id
        ).strip()

        if not channel_id:
            raise ValueError(
                "discord_channel_id cannot be empty."
            )

        panel = (
            await self.panel_repository
            .get_for_channel(channel_id)
        )

        if panel is None:
            raise BroadcasterPanelNotFoundError(
                "This Discord channel is not a stored "
                "ChimeBuddy broadcaster panel."
            )

        return await self._build_status(panel)

    async def _build_status(
        self,
        panel,
    ) -> BroadcasterPanelStatus:
        broadcaster = (
            await self.identity_repository
            .get_broadcaster(
                panel.twitch_user_id
            )
        )

        if broadcaster is None:
            raise BroadcasterPanelDataError(
                "The panel's broadcaster record "
                "could not be loaded."
            )

        request = await self.request_repository.get(
            panel.request_id
        )

        if request is None:
            raise BroadcasterPanelDataError(
                "The panel's broadcaster request "
                "could not be loaded."
            )

        triggers = (
            await self.trigger_repository.list_triggers(
                panel.twitch_user_id
            )
        )

        enabled_trigger_count = sum(
            1
            for trigger in triggers
            if trigger.enabled
        )

        credential = (
            await self.credential_repository.get(
                panel.twitch_user_id,
                OAuthCredentialKind.BROADCASTER,
            )
        )

        return BroadcasterPanelStatus(
            request_id=panel.request_id,
            request_status=request.status,
            twitch_user_id=(
                broadcaster.twitch_user_id
            ),
            twitch_login=(
                broadcaster.twitch_login
            ),
            twitch_display_name=(
                broadcaster.twitch_display_name
            ),
            owner_discord_user_id=(
                broadcaster.owner_discord_user_id
            ),
            owner_discord_username=(
                broadcaster.owner_discord_username
            ),
            owner_discord_display_name=(
                broadcaster.owner_discord_display_name
            ),
            broadcaster_enabled=(
                broadcaster.enabled
            ),
            total_triggers=len(triggers),
            enabled_triggers=(
                enabled_trigger_count
            ),
            credential_stored=(
                credential is not None
            ),
            credential_expires_at=(
                credential.expires_at
                if credential is not None
                else None
            ),
            discord_guild_id=(
                panel.discord_guild_id
            ),
            discord_channel_id=(
                panel.discord_channel_id
            ),
            opening_message_id=(
                panel.opening_message_id
            ),
        )