import logging

import discord

from chimebuddy.services import (
    BroadcasterPanelNotFoundError,
    BroadcasterPanelStatus,
    BroadcasterPanelStatusService,
)


logger = logging.getLogger(
    "chimebuddy.discord.broadcaster_panel"
)

REFRESH_PANEL_CUSTOM_ID = (
    "chimebuddy:broadcaster:refresh"
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
            "Trigger and channel-management controls "
            "will be added here next."
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
        twitch_user_id: str,
    ) -> None:
        super().__init__(timeout=None)
        self.controller = controller
        self.twitch_user_id = str(twitch_user_id)

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


class DiscordBroadcasterPanelController:
    """Restores and refreshes broadcaster dashboards."""

    def __init__(
        self,
        *,
        status_service: BroadcasterPanelStatusService,
        panel_repository,
        developer_discord_user_id: int,
    ) -> None:
        self.status_service = status_service
        self.panel_repository = panel_repository
        self.developer_discord_user_id = int(
            developer_discord_user_id
        )

    def create_view(
        self,
        twitch_user_id: str,
    ) -> BroadcasterManagementView:
        return BroadcasterManagementView(
            self,
            twitch_user_id,
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

                view = self.create_view(
                    panel.twitch_user_id
                )

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
            return
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
            return

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
            view=self.create_view(twitch_user_id),
            allowed_mentions=(
                discord.AllowedMentions.none()
            ),
        )

        await interaction.edit_original_response(
            content="The broadcaster status was refreshed."
        )