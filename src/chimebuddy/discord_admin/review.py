import logging

import discord

from chimebuddy.models import (
    BroadcasterRequest,
    BroadcasterRequestStatus,
    DiscordAccount,
    TwitchAccount,
)
from chimebuddy.repositories import (
    ActiveBlacklistEntryError,
    AppSettingsRepository,
    BroadcasterRequestRepository,
    IdentityRepository,
)
from chimebuddy.services import (
    ReviewDecisionService,
    ReviewRequestNotFoundError,
    ReviewRequestStateError,
    BroadcasterProvisioningFailedError,
    BroadcasterProvisioningService,
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

APPROVE_BUTTON_CUSTOM_ID = (
    "chimebuddy:review:approve"
)
REJECT_BUTTON_CUSTOM_ID = (
    "chimebuddy:review:reject"
)
BLACKLIST_BUTTON_CUSTOM_ID = (
    "chimebuddy:review:blacklist"
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
            discord.Color.dark_grey()
        ),
        BroadcasterRequestStatus.REAUTHORIZATION_REQUIRED: (
            discord.Color.orange()
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

    # The two identities appear side-by-side.
    embed.add_field(
        name="Twitch account",
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
        inline=True,
    )

    # Status appears on a separate row.
    embed.add_field(
        name="Status",
        value=f"`{request.status.value}`",
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

    if request.decided_by_discord_user_id:
        embed.add_field(
            name="Decided by",
            value=(
                f"<@{request.decided_by_discord_user_id}>\n"
                f"ID: "
                f"`{request.decided_by_discord_user_id}`"
            ),
            inline=True,
        )

    if request.decision_reason:
        embed.add_field(
            name="Requester-facing decision message",
            value=request.decision_reason,
            inline=False,
        )

    footer_messages = {
        BroadcasterRequestStatus.PENDING: (
            "This request is waiting for developer review."
        ),
        BroadcasterRequestStatus.APPROVING: (
            "This request was approved and is waiting "
            "for provisioning."
        ),
        BroadcasterRequestStatus.PROVISIONING: (
            "ChimeBuddy is provisioning this broadcaster."
        ),
        BroadcasterRequestStatus.ACTIVE: (
            "This broadcaster is active."
        ),
        BroadcasterRequestStatus.REJECTED: (
            "This request was rejected."
        ),
        BroadcasterRequestStatus.BLACKLISTED: (
            "This request was rejected and both "
            "identities were blacklisted."
        ),
        BroadcasterRequestStatus.PROVISIONING_FAILED: (
            "Provisioning failed and requires attention."
        ),
        BroadcasterRequestStatus.SUSPENDED: (
            "This broadcaster is suspended."
        ),
        BroadcasterRequestStatus.REAUTHORIZATION_REQUIRED: (
            "The broadcaster must authorize Twitch again."
        ),
    }

    embed.set_footer(
        text=footer_messages.get(
            request.status,
            "ChimeBuddy broadcaster request.",
        )
    )

    return embed


class RejectRequestModal(
    discord.ui.Modal,
    title="Reject ChimeBuddy request",
):
    requester_message = discord.ui.TextInput(
        label="Reason shown to the requester",
        placeholder=(
            "Optional. Leave empty to send a generic "
            "rejection message."
        ),
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(
        self,
        *,
        controller: "DiscordReviewController",
        request_id: int,
        review_message: discord.Message | None,
    ) -> None:
        super().__init__()

        self.controller = controller
        self.request_id = request_id
        self.review_message = review_message

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        message = self.requester_message.value.strip()

        await self.controller.handle_reject(
            interaction,
            self.request_id,
            review_message=self.review_message,
            requester_message=message or None,
        )


class BlacklistRequestModal(
    discord.ui.Modal,
    title="Blacklist ChimeBuddy request",
):
    internal_reason = discord.ui.TextInput(
        label="Internal reason",
        placeholder=(
            "Required. This is visible only in "
            "ChimeBuddy's moderation records."
        ),
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000,
    )

    requester_message = discord.ui.TextInput(
        label="Message shown to the requester",
        placeholder=(
            "Optional. Do not include private "
            "moderation information."
        ),
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(
        self,
        *,
        controller: "DiscordReviewController",
        request_id: int,
        review_message: discord.Message | None,
    ) -> None:
        super().__init__()

        self.controller = controller
        self.request_id = request_id
        self.review_message = review_message

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        internal = self.internal_reason.value.strip()
        requester = (
            self.requester_message.value.strip()
        )

        await self.controller.handle_blacklist(
            interaction,
            self.request_id,
            review_message=self.review_message,
            internal_reason=internal,
            requester_message=requester or None,
        )


class ReviewDecisionView(discord.ui.View):
    """Persistent decision controls for one request."""

    def __init__(
        self,
        controller: "DiscordReviewController",
        request_id: int,
    ) -> None:
        super().__init__(timeout=None)

        self.controller = controller
        self.request_id = int(request_id)

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if self.controller.is_developer(
            interaction.user.id
        ):
            return True

        logger.warning(
            "Denied review interaction from Discord "
            "user %s.",
            interaction.user.id,
        )

        await interaction.response.send_message(
            "Only the ChimeBuddy developer can review "
            "broadcaster requests.",
            ephemeral=True,
        )

        return False

    @discord.ui.button(
        label="Approve",
        style=discord.ButtonStyle.success,
        custom_id=APPROVE_BUTTON_CUSTOM_ID,
        emoji="✅",
    )
    async def approve_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.controller.handle_approve(
            interaction,
            self.request_id,
        )

    @discord.ui.button(
        label="Reject",
        style=discord.ButtonStyle.danger,
        custom_id=REJECT_BUTTON_CUSTOM_ID,
        emoji="✖️",
    )
    async def reject_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            RejectRequestModal(
                controller=self.controller,
                request_id=self.request_id,
                review_message=interaction.message,
            )
        )

    @discord.ui.button(
        label="Blacklist",
        style=discord.ButtonStyle.secondary,
        custom_id=BLACKLIST_BUTTON_CUSTOM_ID,
        emoji="⛔",
    )
    async def blacklist_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            BlacklistRequestModal(
                controller=self.controller,
                request_id=self.request_id,
                review_message=interaction.message,
            )
        )


class DiscordReviewController:
    """Publishes and safely decides broadcaster requests."""

    def __init__(
        self,
        *,
        settings_repository: AppSettingsRepository,
        request_repository: BroadcasterRequestRepository,
        identity_repository: IdentityRepository,
        decision_service: ReviewDecisionService,
        developer_discord_user_id: int,
        provisioning_service: (
            BroadcasterProvisioningService | None
        ) = None
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
        self.decision_service = decision_service
        self.developer_discord_user_id = int(
            developer_discord_user_id
        )
        self.provisioning_service = (
            provisioning_service
        )

    def is_developer(
        self,
        discord_user_id: int,
    ) -> bool:
        return (
            int(discord_user_id)
            == self.developer_discord_user_id
        )

    def create_view(
        self,
        request_id: int,
    ) -> ReviewDecisionView:
        return ReviewDecisionView(
            self,
            request_id,
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

        channel = await self._get_channel(
            client,
            channel_id,
        )

        if channel is None:
            return False

        twitch_account, discord_account = (
            await self._load_identities(request)
        )

        view = (
            self.create_view(request.request_id)
            if request.status
            is BroadcasterRequestStatus.PENDING
            else None
        )

        try:
            message = await channel.send(
                embed=build_review_embed(
                    request,
                    twitch_account,
                    discord_account,
                ),
                view=view,
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

    async def restore_review_messages(
        self,
        client: discord.Client,
    ) -> int:
        """
        Restore buttons and refresh embeds after restart.

        This also upgrades older pending review messages
        that were originally posted without buttons.
        """

        requests = (
            await self.request_repository.list_by_status(
                tuple(BroadcasterRequestStatus)
            )
        )

        restored = 0

        for request in requests:
            if (
                request.review_channel_id is None
                or request.review_message_id is None
            ):
                continue

            try:
                channel_id = int(
                    request.review_channel_id
                )
                message_id = int(
                    request.review_message_id
                )
            except ValueError:
                logger.error(
                    "Request %s has invalid Discord "
                    "message identifiers.",
                    request.request_id,
                )
                continue

            channel = await self._get_channel(
                client,
                channel_id,
            )

            if (
                channel is None
                or not hasattr(channel, "fetch_message")
            ):
                continue

            try:
                message = await channel.fetch_message(
                    message_id
                )
            except discord.HTTPException:
                logger.exception(
                    "Could not restore review message "
                    "%s for request %s.",
                    message_id,
                    request.request_id,
                )
                continue

            view = None

            if (
                request.status
                is BroadcasterRequestStatus.PENDING
            ):
                view = self.create_view(
                    request.request_id
                )

                client.add_view(
                    view,
                    message_id=message_id,
                )

            refreshed = await self._refresh_message(
                message,
                request,
                view=view,
            )

            if refreshed:
                restored += 1

        logger.info(
            "Restored %s Discord review message(s).",
            restored,
        )

        return restored

    async def handle_approve(
        self,
        interaction: discord.Interaction,
        request_id: int,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            request = await self.decision_service.approve(
                request_id,
                actor_discord_user_id=str(
                    interaction.user.id
                ),
            )

        except ReviewRequestNotFoundError:
            await interaction.edit_original_response(
                content=(
                    "This broadcaster request no longer "
                    "exists."
                )
            )
            return

        except ReviewRequestStateError as exc:
            await self._refresh_interaction_message(
                interaction,
                exc.request,
            )

            await interaction.edit_original_response(
                content=(
                    "This request was already processed.\n"
                    "Current status: "
                    f"`{exc.request.status.value}`"
                )
            )
            return

        except Exception:
            logger.exception(
                "Failed to approve request %s.",
                request_id,
            )

            await interaction.edit_original_response(
                content=(
                    "ChimeBuddy could not approve this "
                    "request."
                )
            )
            return

        await self._refresh_interaction_message(
            interaction,
            request,
        )

        if self.provisioning_service is None:
            await interaction.edit_original_response(
                content=(
                    f"Request `{request_id}` was approved, "
                    "but automatic provisioning is not "
                    "configured."
                )
            )
            return

        try:
            result = (
                await self.provisioning_service.provision(
                    request_id,
                    actor_discord_user_id=str(
                        interaction.user.id
                    ),
                )
            )

        except BroadcasterProvisioningFailedError:
            logger.exception(
                "Provisioning failed for approved "
                "request %s.",
                request_id,
            )

            failed_request = (
                await self.request_repository.get(
                    request_id
                )
            )

            if failed_request is not None:
                await self._refresh_interaction_message(
                    interaction,
                    failed_request,
                )

            await interaction.edit_original_response(
                content=(
                    f"Request `{request_id}` was approved, "
                    "but provisioning failed.\n\n"
                    "The broadcaster remains disabled. "
                    "The failure was recorded safely."
                )
            )
            return

        except Exception:
            logger.exception(
                "Unexpected provisioning error for "
                "request %s.",
                request_id,
            )

            await interaction.edit_original_response(
                content=(
                    "An unexpected error occurred during "
                    "provisioning. Check the request "
                    "status and logs."
                )
            )
            return

        active_request = (
            await self.request_repository.get(
                request_id
            )
        )

        if active_request is not None:
            await self._refresh_interaction_message(
                interaction,
                active_request,
            )

            notified = await self._notify_approved(
                interaction.client,
                active_request,
                result.discord_channel_id,
            )
        else:
            notified = False

        notification_text = (
            "The broadcaster was notified by DM."
            if notified
            else (
                "Provisioning succeeded, but the "
                "broadcaster could not be reached by DM."
            )
        )

        await interaction.edit_original_response(
            content=(
                f"Request `{request_id}` is now active.\n\n"
                "Private broadcaster channel: "
                f"<#{result.discord_channel_id}>\n\n"
                f"{notification_text}"
            )
        )

    async def handle_reject(
        self,
        interaction: discord.Interaction,
        request_id: int,
        *,
        review_message: discord.Message | None,
        requester_message: str | None,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            request = await self.decision_service.reject(
                request_id,
                actor_discord_user_id=str(
                    interaction.user.id
                ),
                requester_message=requester_message,
            )

        except ReviewRequestNotFoundError:
            await interaction.edit_original_response(
                content=(
                    "This broadcaster request no longer "
                    "exists."
                )
            )
            return

        except ReviewRequestStateError as exc:
            await self._refresh_message(
                review_message,
                exc.request,
                view=None,
            )

            await interaction.edit_original_response(
                content=(
                    "This request was already processed.\n"
                    "Current status: "
                    f"`{exc.request.status.value}`"
                )
            )
            return

        except Exception:
            logger.exception(
                "Failed to reject request %s.",
                request_id,
            )

            await interaction.edit_original_response(
                content=(
                    "ChimeBuddy could not reject this "
                    "request."
                )
            )
            return

        await self._refresh_message(
            review_message,
            request,
            view=None,
        )

        notified = await self._notify_requester(
            interaction.client,
            request,
        )

        notification_text = (
            "The requester was notified by DM."
            if notified
            else (
                "The decision was saved, but the "
                "requester could not be reached by DM."
            )
        )

        await interaction.edit_original_response(
            content=(
                f"Request `{request_id}` was rejected.\n\n"
                f"{notification_text}"
            )
        )

    async def handle_blacklist(
        self,
        interaction: discord.Interaction,
        request_id: int,
        *,
        review_message: discord.Message | None,
        internal_reason: str,
        requester_message: str | None,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            request = (
                await self.decision_service.blacklist(
                    request_id,
                    actor_discord_user_id=str(
                        interaction.user.id
                    ),
                    internal_reason=internal_reason,
                    requester_message=(
                        requester_message
                    ),
                )
            )

        except ReviewRequestNotFoundError:
            await interaction.edit_original_response(
                content=(
                    "This broadcaster request no longer "
                    "exists."
                )
            )
            return

        except ReviewRequestStateError as exc:
            await self._refresh_message(
                review_message,
                exc.request,
                view=None,
            )

            await interaction.edit_original_response(
                content=(
                    "This request was already processed.\n"
                    "Current status: "
                    f"`{exc.request.status.value}`"
                )
            )
            return

        except ActiveBlacklistEntryError:
            await interaction.edit_original_response(
                content=(
                    "This Discord or Twitch identity is "
                    "already actively blacklisted."
                )
            )
            return

        except Exception:
            logger.exception(
                "Failed to blacklist request %s.",
                request_id,
            )

            await interaction.edit_original_response(
                content=(
                    "ChimeBuddy could not blacklist this "
                    "request. No partial decision was saved."
                )
            )
            return

        await self._refresh_message(
            review_message,
            request,
            view=None,
        )

        notified = await self._notify_requester(
            interaction.client,
            request,
        )

        notification_text = (
            "The requester was notified by DM."
            if notified
            else (
                "The decision was saved, but the "
                "requester could not be reached by DM."
            )
        )

        await interaction.edit_original_response(
            content=(
                f"Request `{request_id}` was blacklisted.\n\n"
                "Both the Discord and Twitch identities "
                "are now blocked from new requests.\n\n"
                f"{notification_text}"
            )
        )

    async def _notify_approved(
        self,
        client: discord.Client,
        request: BroadcasterRequest,
        discord_channel_id: str,
    ) -> bool:
        try:
            discord_user_id = int(
                request.discord_user_id
            )
        except ValueError:
            return False

        user = client.get_user(discord_user_id)

        if user is None:
            try:
                user = await client.fetch_user(
                    discord_user_id
                )
            except discord.HTTPException:
                logger.exception(
                    "Could not load approved Discord "
                    "user %s.",
                    discord_user_id,
                )
                return False

        try:
            await user.send(
                (
                    "**Your ChimeBuddy request was "
                    "approved!**\n\n"
                    f"Request ID: `{request.request_id}`\n"
                    "Status: `active`\n\n"
                    "Your private administration channel "
                    "is ready:\n"
                    f"<#{discord_channel_id}>"
                ),
                allowed_mentions=(
                    discord.AllowedMentions.none()
                ),
            )
        except discord.HTTPException:
            logger.warning(
                "Approved Discord user %s could not "
                "be notified.",
                discord_user_id,
            )
            return False

        return True

    async def _notify_requester(
        self,
        client: discord.Client,
        request: BroadcasterRequest,
    ) -> bool:
        try:
            discord_user_id = int(
                request.discord_user_id
            )
        except ValueError:
            logger.error(
                "Request %s has an invalid Discord "
                "user ID.",
                request.request_id,
            )
            return False

        user = client.get_user(discord_user_id)

        if user is None:
            try:
                user = await client.fetch_user(
                    discord_user_id
                )
            except discord.HTTPException:
                logger.exception(
                    "Could not load Discord user %s "
                    "for request notification.",
                    discord_user_id,
                )
                return False

        if (
            request.status
            is BroadcasterRequestStatus.REJECTED
        ):
            reason = (
                request.decision_reason
                or (
                    "Your request could not be approved "
                    "at this time."
                )
            )

            content = (
                "**ChimeBuddy request update**\n\n"
                f"Request ID: `{request.request_id}`\n"
                "Decision: `rejected`\n\n"
                f"{reason}"
            )

        elif (
            request.status
            is BroadcasterRequestStatus.BLACKLISTED
        ):
            message = (
                request.decision_reason
                or (
                    "Your request cannot be approved, "
                    "and this account cannot submit "
                    "another ChimeBuddy request."
                )
            )

            content = (
                "**ChimeBuddy request update**\n\n"
                f"Request ID: `{request.request_id}`\n"
                "Decision: `not approved`\n\n"
                f"{message}"
            )

        else:
            return False

        try:
            await user.send(
                content,
                allowed_mentions=(
                    discord.AllowedMentions.none()
                ),
            )
        except discord.HTTPException:
            logger.warning(
                "Discord user %s could not be notified "
                "about request %s.",
                discord_user_id,
                request.request_id,
            )
            return False

        return True

    async def _refresh_interaction_message(
        self,
        interaction: discord.Interaction,
        request: BroadcasterRequest,
    ) -> bool:
        return await self._refresh_message(
            interaction.message,
            request,
            view=None,
        )

    async def _refresh_message(
        self,
        message,
        request: BroadcasterRequest,
        *,
        view: discord.ui.View | None,
    ) -> bool:
        if message is None:
            logger.warning(
                "Request %s was decided, but its review "
                "message was unavailable.",
                request.request_id,
            )
            return False

        twitch_account, discord_account = (
            await self._load_identities(request)
        )

        try:
            await message.edit(
                embed=build_review_embed(
                    request,
                    twitch_account,
                    discord_account,
                ),
                view=view,
                allowed_mentions=(
                    discord.AllowedMentions.none()
                ),
            )
        except discord.HTTPException:
            logger.exception(
                "Could not refresh the Discord review "
                "message for request %s.",
                request.request_id,
            )
            return False

        return True

    async def _load_identities(
        self,
        request: BroadcasterRequest,
    ) -> tuple[
        TwitchAccount | None,
        DiscordAccount | None,
    ]:
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

        return twitch_account, discord_account

    @staticmethod
    async def _get_channel(
        client: discord.Client,
        channel_id: int,
    ):
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
                return None

        if not hasattr(channel, "send"):
            logger.error(
                "Configured review channel %s cannot "
                "receive messages.",
                channel_id,
            )
            return None

        return channel