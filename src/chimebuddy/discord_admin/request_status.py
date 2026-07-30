import logging

import discord

from chimebuddy.models import (
    BroadcasterRequest,
    BroadcasterRequestStatus,
    TwitchAccount,
)
from chimebuddy.repositories import (
    BroadcasterPanelRepository,
    BroadcasterRequestRepository,
    IdentityRepository,
)


logger = logging.getLogger(
    "chimebuddy.discord.request_status"
)


def build_request_status_embed(
    request: BroadcasterRequest,
    twitch_account: TwitchAccount | None,
    *,
    panel_channel_id: str | None = None,
) -> discord.Embed:
    """Build a requester-safe view of one application."""

    status_colors = {
        BroadcasterRequestStatus.PENDING: (
            discord.Color.orange()
        ),
        BroadcasterRequestStatus.APPROVING: (
            discord.Color.blue()
        ),
        BroadcasterRequestStatus.PROVISIONING: (
            discord.Color.blue()
        ),
        BroadcasterRequestStatus.ACTIVE: (
            discord.Color.green()
        ),
        BroadcasterRequestStatus.REJECTED: (
            discord.Color.red()
        ),
        BroadcasterRequestStatus.BLACKLISTED: (
            discord.Color.dark_red()
        ),
        BroadcasterRequestStatus.PROVISIONING_FAILED: (
            discord.Color.red()
        ),
        BroadcasterRequestStatus.SUSPENDED: (
            discord.Color.orange()
        ),
        BroadcasterRequestStatus.REAUTHORIZATION_REQUIRED: (
            discord.Color.red()
        ),
    }

    twitch_name = (
        twitch_account.login
        if twitch_account is not None
        else "Unknown"
    )

    embed = discord.Embed(
        title=(
            f"ChimeBuddy request #{request.request_id}"
        ),
        description=_status_description(request.status),
        color=status_colors.get(
            request.status,
            discord.Color.light_grey(),
        ),
    )

    embed.add_field(
        name="Status",
        value=f"`{request.status.value}`",
        inline=True,
    )
    embed.add_field(
        name="Twitch channel",
        value=(
            f"`{twitch_name}`\n"
            f"ID: `{request.twitch_user_id}`"
        ),
        inline=True,
    )

    if request.created_at is not None:
        embed.add_field(
            name="Submitted",
            value=f"`{request.created_at} UTC`",
            inline=False,
        )

    if request.requester_message is not None:
        embed.add_field(
            name="Your request message",
            value=request.requester_message,
            inline=False,
        )

    if (
        request.status
        in {
            BroadcasterRequestStatus.REJECTED,
            BroadcasterRequestStatus.BLACKLISTED,
        }
        and request.decision_reason is not None
    ):
        embed.add_field(
            name="Decision message",
            value=request.decision_reason,
            inline=False,
        )

    if panel_channel_id is not None:
        embed.add_field(
            name="Private administration channel",
            value=f"<#{panel_channel_id}>",
            inline=False,
        )

    if (
        request.status
        is BroadcasterRequestStatus
        .REAUTHORIZATION_REQUIRED
    ):
        embed.add_field(
            name="Action required",
            value=(
                "Open your private administration "
                "channel, press **Refresh status**, then "
                "use **Reconnect Twitch**."
            ),
            inline=False,
        )

    embed.set_footer(
        text=(
            "This private response only shows the "
            "request linked to your Discord account."
        )
    )

    return embed


def _status_description(
    status: BroadcasterRequestStatus,
) -> str:
    descriptions = {
        BroadcasterRequestStatus.PENDING: (
            "Your request is waiting for developer review."
        ),
        BroadcasterRequestStatus.APPROVING: (
            "Your request was approved and setup is "
            "starting."
        ),
        BroadcasterRequestStatus.PROVISIONING: (
            "Your private ChimeBuddy panel is being "
            "prepared."
        ),
        BroadcasterRequestStatus.ACTIVE: (
            "ChimeBuddy is active for this broadcaster."
        ),
        BroadcasterRequestStatus.REJECTED: (
            "This request was not approved."
        ),
        BroadcasterRequestStatus.BLACKLISTED: (
            "This request was not approved and another "
            "request cannot currently be submitted."
        ),
        BroadcasterRequestStatus.PROVISIONING_FAILED: (
            "Setup could not be completed. The developer "
            "can safely retry provisioning."
        ),
        BroadcasterRequestStatus.SUSPENDED: (
            "ChimeBuddy access is currently suspended."
        ),
        BroadcasterRequestStatus.REAUTHORIZATION_REQUIRED: (
            "ChimeBuddy was paused because Twitch must "
            "be reconnected."
        ),
    }

    return descriptions.get(
        status,
        "This request has an unknown status.",
    )


class DiscordRequestStatusController:
    """Shows a Discord user only their own latest request."""

    def __init__(
        self,
        *,
        request_repository: BroadcasterRequestRepository,
        identity_repository: IdentityRepository,
        panel_repository: BroadcasterPanelRepository,
    ) -> None:
        self.request_repository = request_repository
        self.identity_repository = identity_repository
        self.panel_repository = panel_repository

    async def handle_status(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            request = (
                await self.request_repository
                .get_latest_for_discord(
                    str(interaction.user.id)
                )
            )

            if request is None:
                await interaction.edit_original_response(
                    content=(
                        "You do not have a ChimeBuddy "
                        "request yet. Use the Twitch "
                        "connection panel when you are "
                        "ready to apply."
                    ),
                    embed=None,
                )
                return

            twitch_account = (
                await self.identity_repository
                .get_twitch_account(
                    request.twitch_user_id
                )
            )

            panel = (
                await self.panel_repository
                .get_for_broadcaster(
                    request.twitch_user_id
                )
            )

            await interaction.edit_original_response(
                content=None,
                embed=build_request_status_embed(
                    request,
                    twitch_account,
                    panel_channel_id=(
                        panel.discord_channel_id
                        if panel is not None
                        else None
                    ),
                ),
            )

        except Exception:
            logger.exception(
                "Failed to load request status for "
                "Discord user %s.",
                interaction.user.id,
            )

            await interaction.edit_original_response(
                content=(
                    "ChimeBuddy could not load your "
                    "request status. Please try again."
                ),
                embed=None,
            )
