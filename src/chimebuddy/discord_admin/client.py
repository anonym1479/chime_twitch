import logging

import discord
from discord import app_commands

from chimebuddy.discord_admin.onboarding import (
    DiscordOnboardingController,
)
from chimebuddy.discord_admin.status_service import (
    DiscordAdminStatusService,
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

    async def setup_hook(self) -> None:
        if self.onboarding_controller is not None:
            # Register the stable custom ID so buttons on
            # older panel messages survive restarts.
            self.add_view(
                self.onboarding_controller.create_view()
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