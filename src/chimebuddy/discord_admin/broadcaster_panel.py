import logging

import discord

from chimebuddy.services import (
    BroadcasterLifecycleError,
    BroadcasterLifecycleService,
    BroadcasterPanelNotFoundError,
    BroadcasterPanelStatus,
    BroadcasterPanelStatusService,
    BroadcasterResumeBlockedError,
)

logger = logging.getLogger(
    "chimebuddy.discord.broadcaster_panel"
)

REFRESH_PANEL_CUSTOM_ID = (
    "chimebuddy:broadcaster:refresh"
)
LIFECYCLE_BUTTON_CUSTOM_ID = (
    "chimebuddy:broadcaster:lifecycle"
)
TITLE_TRIGGERS_BUTTON_CUSTOM_ID = (
    "chimebuddy:broadcaster:title_triggers"
)


def can_manage_broadcaster_panel(
    discord_user_id: int | str,
    status: BroadcasterPanelStatus,
    developer_discord_user_id: int | str,
) -> bool:
    user_id = str(discord_user_id)

    return user_id in {
        str(status.owner_discord_user_id),
        str(developer_discord_user_id),
    }


def build_broadcaster_management_embed(
    status: BroadcasterPanelStatus,
) -> discord.Embed:
    if status.broadcaster_enabled:
        state_text = "🟢 Active"
        state_description = (
            "ChimeBuddy is enabled for this broadcaster."
        )
        color = discord.Color.green()
    else:
        state_text = "🟠 Paused"
        state_description = (
            "ChimeBuddy is currently disabled for this "
            "broadcaster."
        )
        color = discord.Color.orange()

    if status.credential_stored:
        if status.credential_expires_at is None:
            authorization_text = "✅ Stored"
        else:
            authorization_text = (
                "✅ Stored\n"
                "Expires "
                f"<t:{status.credential_expires_at}:R>"
            )
    else:
        authorization_text = (
            "❌ Missing — Twitch authorization is required."
        )

    embed = discord.Embed(
        title=(
            f"ChimeBuddy — {status.twitch_login}"
        ),
        description=(
            "Your private ChimeBuddy administration "
            "panel.\n\n"
            "Use the button below to reload the latest "
            "status from ChimeBuddy."
        ),
        color=color,
    )

    embed.add_field(
        name="Twitch channel",
        value=(
            f"`{status.twitch_login}`\n"
            f"ID: `{status.twitch_user_id}`"
        ),
        inline=True,
    )
    embed.add_field(
        name="Discord owner",
        value=(
            f"{status.owner_discord_display_name}\n"
            f"<@{status.owner_discord_user_id}>\n"
            f"ID: `{status.owner_discord_user_id}`"
        ),
        inline=True,
    )
    embed.add_field(
        name="Broadcaster status",
        value=(
            f"{state_text}\n"
            f"{state_description}"
        ),
        inline=False,
    )
    embed.add_field(
        name="Request",
        value=(
            f"ID: `{status.request_id}`\n"
            f"Status: `{status.request_status.value}`"
        ),
        inline=True,
    )
    embed.add_field(
        name="Title triggers",
        value=(
            f"Enabled: `{status.enabled_triggers}`\n"
            f"Disabled: `{status.disabled_triggers}`\n"
            f"Total: `{status.total_triggers}`"
        ),
        inline=True,
    )
    embed.add_field(
        name="Twitch authorization",
        value=authorization_text,
        inline=False,
    )
    embed.add_field(
        name="Available controls",
        value=(
            "🔄 **Refresh status** — reload this panel.\n\n"
            "📝 **Title triggers** — privately list and "
            "manage stream-title triggers.\n\n"
            "Channel-management controls will be added "
            "here later."
        ),
        inline=False,
    )

    embed.set_footer(
        text=(
            "ChimeBuddy broadcaster panel | "
            f"request #{status.request_id}"
        )
    )

    return embed


class BroadcasterManagementView(discord.ui.View):
    """Persistent controls for one broadcaster panel."""

    def __init__(
        self,
        controller: "DiscordBroadcasterPanelController",
        status: BroadcasterPanelStatus,
    ) -> None:
        super().__init__(timeout=None)
        self.controller = controller
        self.twitch_user_id = status.twitch_user_id
        self.broadcaster_enabled = (
            status.broadcaster_enabled
        )

        if self.broadcaster_enabled:
            self.lifecycle_button.label = (
                "Pause ChimeBuddy"
            )
            self.lifecycle_button.style = (
                discord.ButtonStyle.danger
            )
            self.lifecycle_button.emoji = "⏸️"
        else:
            self.lifecycle_button.label = (
                "Resume ChimeBuddy"
            )
            self.lifecycle_button.style = (
                discord.ButtonStyle.success
            )
            self.lifecycle_button.emoji = "▶️"

    @discord.ui.button(
        label="Refresh status",
        style=discord.ButtonStyle.success,
        emoji="🔄",
        custom_id=REFRESH_PANEL_CUSTOM_ID,
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.controller.handle_refresh(
            interaction,
            self.twitch_user_id,
        )

    @discord.ui.button(
        label="Pause ChimeBuddy",
        style=discord.ButtonStyle.danger,
        emoji="⏸️",
        custom_id=LIFECYCLE_BUTTON_CUSTOM_ID,
    )
    async def lifecycle_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.controller.handle_lifecycle_request(
            interaction,
            self.twitch_user_id,
            currently_enabled=(
                self.broadcaster_enabled
            ),
        )

    @discord.ui.button(
        label="Title triggers",
        style=discord.ButtonStyle.primary,
        emoji="📝",
        custom_id=TITLE_TRIGGERS_BUTTON_CUSTOM_ID,
    )
    async def title_triggers_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.controller.handle_title_triggers(
            interaction,
            self.twitch_user_id,
        )


class LifecycleConfirmationView(discord.ui.View):
    """Short-lived confirmation for pause or resume."""

    def __init__(
        self,
        *,
        controller: "DiscordBroadcasterPanelController",
        twitch_user_id: str,
        enable: bool,
        requested_by_user_id: int,
        panel_message: discord.Message,
    ) -> None:
        super().__init__(timeout=60)
        self.controller = controller
        self.twitch_user_id = twitch_user_id
        self.enable = enable
        self.requested_by_user_id = int(
            requested_by_user_id
        )
        self.panel_message = panel_message

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if (
            interaction.user.id
            == self.requested_by_user_id
        ):
            return True

        await interaction.response.send_message(
            "Only the person who started this action "
            "can confirm it.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(
        label="Confirm",
        style=discord.ButtonStyle.danger,
        emoji="✅",
    )
    async def confirm_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.controller.confirm_lifecycle_change(
            interaction,
            twitch_user_id=self.twitch_user_id,
            enable=self.enable,
            panel_message=self.panel_message,
        )

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        emoji="✖️",
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content="The status change was cancelled.",
            view=None,
        )


class DiscordBroadcasterPanelController:
    """Restores and controls broadcaster dashboards."""

    def __init__(
        self,
        *,
        status_service: BroadcasterPanelStatusService,
        lifecycle_service: BroadcasterLifecycleService,
        panel_repository,
        developer_discord_user_id: int,
        trigger_management_controller=None,
    ) -> None:
        self.status_service = status_service
        self.lifecycle_service = lifecycle_service
        self.panel_repository = panel_repository
        self.trigger_management_controller = (
            trigger_management_controller
        )
        self.developer_discord_user_id = int(
            developer_discord_user_id
        )

    def create_view(
        self,
        status: BroadcasterPanelStatus,
    ) -> BroadcasterManagementView:
        return BroadcasterManagementView(
            self,
            status,
        )

    async def restore_panels(
        self,
        client: discord.Client,
    ) -> int:
        panels = await self.panel_repository.list_all()
        restored = 0

        for panel in panels:
            if panel.opening_message_id is None:
                continue

            try:
                channel = client.get_channel(
                    int(panel.discord_channel_id)
                )

                if channel is None:
                    channel = await client.fetch_channel(
                        int(panel.discord_channel_id)
                    )

                if not hasattr(channel, "fetch_message"):
                    logger.error(
                        "Broadcaster panel channel %s "
                        "cannot load messages.",
                        panel.discord_channel_id,
                    )
                    continue

                message = await channel.fetch_message(
                    int(panel.opening_message_id)
                )

                status = (
                    await self.status_service
                    .get_for_broadcaster(
                        panel.twitch_user_id
                    )
                )

                view = self.create_view(status)

                client.add_view(
                    view,
                    message_id=int(
                        panel.opening_message_id
                    ),
                )

                await message.edit(
                    embed=(
                        build_broadcaster_management_embed(
                            status
                        )
                    ),
                    view=view,
                    allowed_mentions=(
                        discord.AllowedMentions.none()
                    ),
                )

                restored += 1

            except BroadcasterPanelNotFoundError:
                logger.exception(
                    "Stored broadcaster panel for %s "
                    "could not be loaded.",
                    panel.twitch_user_id,
                )

            except discord.HTTPException:
                logger.exception(
                    "Discord broadcaster panel for %s "
                    "could not be restored.",
                    panel.twitch_user_id,
                )

            except Exception:
                logger.exception(
                    "Unexpected failure while restoring "
                    "broadcaster panel for %s.",
                    panel.twitch_user_id,
                )

        logger.info(
            "Restored %s Discord broadcaster panel(s).",
            restored,
        )

        return restored

    async def handle_refresh(
        self,
        interaction: discord.Interaction,
        twitch_user_id: str,
    ) -> None:
        status = await self._load_authorized_status(
            interaction,
            twitch_user_id,
        )

        if status is None:
            return

        if interaction.message is None:
            await interaction.response.send_message(
                "The broadcaster panel message could not "
                "be found.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await interaction.message.edit(
            embed=build_broadcaster_management_embed(
                status
            ),
            view=self.create_view(status),
            allowed_mentions=(
                discord.AllowedMentions.none()
            ),
        )

        await interaction.edit_original_response(
            content="The broadcaster status was refreshed."
        )

    async def handle_lifecycle_request(
        self,
        interaction: discord.Interaction,
        twitch_user_id: str,
        *,
        currently_enabled: bool,
    ) -> None:
        status = await self._load_authorized_status(
            interaction,
            twitch_user_id,
        )

        if status is None:
            return

        if interaction.message is None:
            await interaction.response.send_message(
                "The broadcaster panel message could not "
                "be found.",
                ephemeral=True,
            )
            return

        # Use the fresh database value, not only the
        # value stored by the button when it was created.
        enable = not status.broadcaster_enabled

        if enable:
            action_text = "resume"
            explanation = (
                "ChimeBuddy will reconnect to this Twitch "
                "channel shortly."
            )
        else:
            action_text = "pause"
            explanation = (
                "ChimeBuddy will stop receiving this "
                "channel's Twitch events shortly. "
                "Credentials, triggers, and settings will "
                "be preserved."
            )

        confirmation_view = LifecycleConfirmationView(
            controller=self,
            twitch_user_id=twitch_user_id,
            enable=enable,
            requested_by_user_id=(
                interaction.user.id
            ),
            panel_message=interaction.message,
        )

        await interaction.response.send_message(
            (
                f"Are you sure you want to **{action_text} "
                "ChimeBuddy** for "
                f"`{status.twitch_login}`?\n\n"
                f"{explanation}"
            ),
            view=confirmation_view,
            ephemeral=True,
        )

    async def confirm_lifecycle_change(
        self,
        interaction: discord.Interaction,
        *,
        twitch_user_id: str,
        enable: bool,
        panel_message: discord.Message,
    ) -> None:
        status = await self._load_authorized_status(
            interaction,
            twitch_user_id,
        )

        if status is None:
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            if enable:
                await self.lifecycle_service.resume(
                    twitch_user_id
                )
                result_text = (
                    "ChimeBuddy was resumed. Twitch "
                    "reconnection may take up to the "
                    "broadcaster synchronization interval."
                )
            else:
                await self.lifecycle_service.pause(
                    twitch_user_id
                )
                result_text = (
                    "ChimeBuddy was paused. Its settings "
                    "and Twitch authorization were kept."
                )

            updated_status = (
                await self.status_service
                .get_for_broadcaster(twitch_user_id)
            )

            await panel_message.edit(
                embed=(
                    build_broadcaster_management_embed(
                        updated_status
                    )
                ),
                view=self.create_view(updated_status),
                allowed_mentions=(
                    discord.AllowedMentions.none()
                ),
            )

        except BroadcasterResumeBlockedError as exc:
            await interaction.edit_original_response(
                content=(
                    "ChimeBuddy could not be resumed:\n"
                    f"{exc}"
                ),
                view=None,
            )
            return

        except BroadcasterLifecycleError:
            logger.exception(
                "Broadcaster lifecycle change failed "
                "for Twitch user %s.",
                twitch_user_id,
            )

            await interaction.edit_original_response(
                content=(
                    "ChimeBuddy could not change the "
                    "broadcaster status."
                ),
                view=None,
            )
            return

        except discord.HTTPException:
            logger.exception(
                "The broadcaster changed status, but its "
                "Discord panel could not be updated."
            )

            await interaction.edit_original_response(
                content=(
                    "The broadcaster status changed, but "
                    "Discord could not refresh the panel. "
                    "Press **Refresh status**."
                ),
                view=None,
            )
            return

        await interaction.edit_original_response(
            content=result_text,
            view=None,
        )

    async def handle_title_triggers(
        self,
        interaction: discord.Interaction,
        twitch_user_id: str,
    ) -> None:
        status = await self._load_authorized_status(
            interaction,
            twitch_user_id,
        )

        if status is None:
            return

        if self.trigger_management_controller is None:
            await interaction.response.send_message(
                "Title trigger management is not "
                "configured.",
                ephemeral=True,
            )
            return

        await (
            self.trigger_management_controller
            .show_triggers(
                interaction,
                twitch_user_id,
            )
        )

    async def _load_authorized_status(
        self,
        interaction: discord.Interaction,
        twitch_user_id: str,
    ) -> BroadcasterPanelStatus | None:
        try:
            status = (
                await self.status_service
                .get_for_broadcaster(twitch_user_id)
            )
        except BroadcasterPanelNotFoundError:
            await interaction.response.send_message(
                "This broadcaster panel is no longer "
                "registered.",
                ephemeral=True,
            )
            return None
        except Exception:
            logger.exception(
                "Could not load broadcaster panel status "
                "for %s.",
                twitch_user_id,
            )

            await interaction.response.send_message(
                "ChimeBuddy could not load this panel's "
                "status.",
                ephemeral=True,
            )
            return None

        if not can_manage_broadcaster_panel(
            interaction.user.id,
            status,
            self.developer_discord_user_id,
        ):
            logger.warning(
                "Denied broadcaster panel access to "
                "Discord user %s for Twitch user %s.",
                interaction.user.id,
                twitch_user_id,
            )

            await interaction.response.send_message(
                "Only this broadcaster or the ChimeBuddy "
                "developer can use these controls.",
                ephemeral=True,
            )
            return None

        return status