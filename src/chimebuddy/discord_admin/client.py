import logging

import discord
from discord import app_commands

from chimebuddy.discord_admin.onboarding import (
    DiscordOnboardingController,
)
from chimebuddy.discord_admin.status_service import (
    DiscordAdminStatusService,
)
from chimebuddy.discord_admin.review import (
    DiscordReviewController,
)
from chimebuddy.discord_admin.request_status import (
    DiscordRequestStatusController,
)
from chimebuddy.discord_admin.broadcaster_panel import (
    DiscordBroadcasterPanelController,
)
from chimebuddy.discord_admin.suspension import (
    DiscordBroadcasterSuspensionController,
)
from chimebuddy.discord_admin.help import (
    DiscordHelpController,
)


logger = logging.getLogger(
    "chimebuddy.discord.client"
)


def is_developer(
    discord_user_id: int,
    developer_discord_user_id: int,
) -> bool:
    return (
        int(discord_user_id)
        == int(developer_discord_user_id)
    )


class ChimeBuddyDiscordClient(discord.Client):
    """Private Discord administration client."""

    def __init__(
        self,
        *,
        developer_discord_user_id: int,
        discord_guild_id: int,
        status_service: DiscordAdminStatusService,
        onboarding_controller: (
            DiscordOnboardingController | None
        ) = None,
        review_controller:(
            DiscordReviewController | None
        ) = None,
        broadcaster_panel_controller: (
            DiscordBroadcasterPanelController | None
        ) = None,
        request_status_controller: (
            DiscordRequestStatusController | None
        ) = None,
        suspension_controller: (
            DiscordBroadcasterSuspensionController | None
        ) = None,
        help_controller: (
            DiscordHelpController | None
        ) = None,
    ) -> None:
        intents = discord.Intents.none()
        intents.guilds = True

        super().__init__(
            intents=intents,
            max_messages=None,
            allowed_mentions=(
                discord.AllowedMentions.none()
            ),
        )

        self.developer_discord_user_id = (
            developer_discord_user_id
        )
        self.discord_guild_id = discord_guild_id
        self.status_service = status_service
        self.onboarding_controller = (
            onboarding_controller
        )
        self.review_controller = review_controller
        self.broadcaster_panel_controller = (
            broadcaster_panel_controller
        )
        self.request_status_controller = (
            request_status_controller
        )
        self.suspension_controller = suspension_controller
        self.help_controller = help_controller

        self.command_tree = app_commands.CommandTree(
            self,
            fallback_to_global=False,
        )

        self.guild_object = discord.Object(
            id=discord_guild_id
        )

        async def status_command(
            interaction: discord.Interaction,
        ) -> None:
            await self._handle_status(interaction)

        self.command_tree.add_command(
            app_commands.Command(
                name="status",
                description=(
                    "Show ChimeBuddy's administration "
                    "status."
                ),
                callback=status_command,
            ),
            guild=self.guild_object,
        )

        if self.help_controller is not None:
            async def help_command(
                interaction: discord.Interaction,
            ) -> None:
                await self.help_controller.show_help(
                    interaction
                )

            self.command_tree.add_command(
                app_commands.Command(
                    name="help",
                    description=(
                        "Privately show the bilingual "
                        "ChimeBuddy guide."
                    ),
                    callback=help_command,
                ),
                guild=self.guild_object,
            )

        if self.request_status_controller is not None:
            async def request_status_command(
                interaction: discord.Interaction,
            ) -> None:
                await (
                    self.request_status_controller
                    .handle_status(interaction)
                )

            self.command_tree.add_command(
                app_commands.Command(
                    name="request-status",
                    description=(
                        "Privately show your latest "
                        "ChimeBuddy request."
                    ),
                    callback=request_status_command,
                ),
                guild=self.guild_object,
            )

        if self.onboarding_controller is not None:
            async def setup_onboarding_command(
                interaction: discord.Interaction,
            ) -> None:
                await self._handle_setup_onboarding(
                    interaction
                )

            self.command_tree.add_command(
                app_commands.Command(
                    name="setup-onboarding",
                    description=(
                        "Post ChimeBuddy's Twitch "
                        "onboarding panel here."
                    ),
                    callback=(
                        setup_onboarding_command
                    ),
                ),
                guild=self.guild_object,
            )

        if self.review_controller is not None:
            async def setup_review_command(
                interaction: discord.Interaction,
            ) -> None:
                await self._handle_setup_review(
                    interaction
                )

            self.command_tree.add_command(
                app_commands.Command(
                    name="setup-review",
                    description=(
                        "Use this channel for reviewing "
                        "ChimeBuddy requests."
                    ),
                    callback=setup_review_command,
                ),
                guild=self.guild_object,
            )

        if self.suspension_controller is not None:
            self.command_tree.add_command(
                self.suspension_controller
                .create_command_group(),
                guild=self.guild_object,
            )

    async def setup_hook(self) -> None:
        if self.onboarding_controller is not None:
            # Register the stable custom ID so buttons on
            # older panel messages survive restarts.
            self.add_view(
                self.onboarding_controller.create_view()
            )
            
        if self.review_controller is not None:
                    await (
                        self.review_controller
                        .restore_review_messages(self)
                    )
        if (
            self.broadcaster_panel_controller
            is not None
        ):
            await (
                self.broadcaster_panel_controller
                .restore_panels(self)
            )

        commands = await self.command_tree.sync(
            guild=self.guild_object
        )

        logger.info(
            "Synchronized %s Discord command(s) "
            "to guild %s.",
            len(commands),
            self.discord_guild_id,
        )

    async def on_ready(self) -> None:
        if self.user is None:
            logger.warning(
                "Discord connected without a user."
            )
            return

        logger.info(
            "Discord admin connected as %s "
            "(user ID %s).",
            self.user,
            self.user.id,
        )

    async def _handle_status(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not self._is_developer_interaction(
            interaction
        ):
            logger.warning(
                "Denied Discord /status request "
                "from user %s.",
                interaction.user.id,
            )

            await interaction.response.send_message(
                "You do not have permission to use "
                "this administration command.",
                ephemeral=True,
            )
            return

        try:
            status = await self.status_service.get_status()
        except Exception:
            logger.exception(
                "Failed to build Discord admin status."
            )

            await interaction.response.send_message(
                "ChimeBuddy could not read its status.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            status.render(),
            ephemeral=True,
        )

    async def _handle_setup_review(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not self._is_developer_interaction(
            interaction
        ):
            logger.warning(
                "Denied Discord /setup-review request "
                "from user %s.",
                interaction.user.id,
            )

            await interaction.response.send_message(
                "Only the ChimeBuddy developer can "
                "configure the review channel.",
                ephemeral=True,
            )
            return

        if self.review_controller is None:
            await interaction.response.send_message(
                "The request review system is not "
                "configured.",
                ephemeral=True,
            )
            return

        await self.review_controller.configure_channel(
            interaction
        )

    async def _handle_setup_onboarding(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not self._is_developer_interaction(
            interaction
        ):
            logger.warning(
                "Denied Discord /setup-onboarding "
                "request from user %s.",
                interaction.user.id,
            )

            await interaction.response.send_message(
                "Only the ChimeBuddy developer can "
                "set up the onboarding panel.",
                ephemeral=True,
            )
            return

        if self.onboarding_controller is None:
            await interaction.response.send_message(
                "Discord onboarding is not configured.",
                ephemeral=True,
            )
            return

        await self.onboarding_controller.post_panel(
            interaction
        )

    def _is_developer_interaction(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        return is_developer(
            interaction.user.id,
            self.developer_discord_user_id,
        )
