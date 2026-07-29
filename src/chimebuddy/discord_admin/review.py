import logging

import discord

from chimebuddy.models import (
    BroadcasterRequest,
    BroadcasterRequestStatus,
    DiscordAccount,
    TwitchAccount,
)
from chimebuddy.repositories import (
    AppSettingsRepository,
    BroadcasterRequestRepository,
    IdentityRepository,
)


logger = logging.getLogger(
    "chimebuddy.discord.review"
)

REVIEW_CHANNEL_SETTING = (
    "discord.review_channel_id"
)

REVIEWABLE_STATUSES = (
    BroadcasterRequestStatus.PENDING,
    BroadcasterRequestStatus.APPROVING,
    BroadcasterRequestStatus.PROVISIONING,
    BroadcasterRequestStatus.PROVISIONING_FAILED,
)


def build_review_embed(
    request: BroadcasterRequest,
    twitch_account: TwitchAccount | None,
    discord_account: DiscordAccount | None,
) -> discord.Embed:
    twitch_name = (
        twitch_account.login
        if twitch_account is not None
        else "Unknown"
    )

    discord_name = (
        discord_account.display_name
        if discord_account is not None
        else "Unknown"
    )

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
        BroadcasterRequestStatus.PROVISIONING_FAILED: (
            discord.Color.red()
        ),
    }

    embed = discord.Embed(
        title=(
            f"ChimeBuddy request #{request.request_id}"
        ),
        description=(
            "A broadcaster has requested access "
            "to ChimeBuddy."
        ),
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
    embed.add_field(
        name="Discord account",
        value=(
            f"{discord_name}\n"
            f"<@{request.discord_user_id}>\n"
            f"ID: `{request.discord_user_id}`"
        ),
        inline=False,
    )
    embed.add_field(
        name="Requester message",
        value=(
            request.requester_message
            or "No message was provided."
        ),
        inline=False,
    )

    embed.set_footer(
        text=(
            "This request is waiting for "
            "developer review."
        )
    )

    return embed


class DiscordReviewController:
    """Publishes broadcaster requests to a review channel."""

    def __init__(
        self,
        *,
        settings_repository: AppSettingsRepository,
        request_repository: BroadcasterRequestRepository,
        identity_repository: IdentityRepository,
    ) -> None:
        self.settings_repository = (
            settings_repository
        )
        self.request_repository = (
            request_repository
        )
        self.identity_repository = (
            identity_repository
        )

    async def configure_channel(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if (
            interaction.guild is None
            or interaction.channel is None
        ):
            await interaction.response.send_message(
                "The review channel can only be "
                "configured inside the ChimeBuddy server.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await self.settings_repository.set(
            REVIEW_CHANNEL_SETTING,
            str(interaction.channel.id),
        )

        requests = (
            await self.request_repository.list_by_status(
                REVIEWABLE_STATUSES
            )
        )

        posted = 0

        for request in requests:
            if request.review_message_id is not None:
                continue

            was_posted = await self.publish_request(
                interaction.client,
                request,
            )

            if was_posted:
                posted += 1

        await interaction.edit_original_response(
            content=(
                "This channel is now ChimeBuddy's "
                "request review channel.\n\n"
                f"Existing requests posted: `{posted}`"
            )
        )

    async def publish_request(
        self,
        client: discord.Client,
        request: BroadcasterRequest,
    ) -> bool:
        if request.review_message_id is not None:
            return False

        channel_id = (
            await self.settings_repository
            .get_positive_int(
                REVIEW_CHANNEL_SETTING
            )
        )

        if channel_id is None:
            logger.warning(
                "A broadcaster request was created, "
                "but no Discord review channel is "
                "configured."
            )
            return False

        channel = client.get_channel(channel_id)

        if channel is None:
            try:
                channel = await client.fetch_channel(
                    channel_id
                )
            except discord.HTTPException:
                logger.exception(
                    "Failed to load Discord review "
                    "channel %s.",
                    channel_id,
                )
                return False

        if not hasattr(channel, "send"):
            logger.error(
                "Configured review channel %s cannot "
                "receive messages.",
                channel_id,
            )
            return False

        twitch_account = (
            await self.identity_repository
            .get_twitch_account(
                request.twitch_user_id
            )
        )
        discord_account = (
            await self.identity_repository
            .get_discord_account(
                request.discord_user_id
            )
        )

        try:
            message = await channel.send(
                embed=build_review_embed(
                    request,
                    twitch_account,
                    discord_account,
                ),
                allowed_mentions=(
                    discord.AllowedMentions.none()
                ),
            )
        except discord.HTTPException:
            logger.exception(
                "Failed to post broadcaster request "
                "%s to Discord.",
                request.request_id,
            )
            return False

        guild = getattr(channel, "guild", None)

        if guild is None:
            logger.error(
                "Review channel %s has no guild.",
                channel_id,
            )
            return False

        saved = (
            await self.request_repository
            .set_review_message(
                request.request_id,
                guild_id=str(guild.id),
                channel_id=str(channel.id),
                message_id=str(message.id),
            )
        )

        if not saved:
            logger.error(
                "Request %s was posted but its Discord "
                "message location could not be saved.",
                request.request_id,
            )
            return False

        logger.info(
            "Posted broadcaster request %s to "
            "Discord channel %s.",
            request.request_id,
            channel.id,
        )

        return True