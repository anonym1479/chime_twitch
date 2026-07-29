import logging

import discord

from chimebuddy.models import DiscordAccount
from chimebuddy.repositories import (
    AccountLinkIdentityConflictError,
    OpenBroadcasterRequestError,
    PendingAccountLinkSessionError,
)
from chimebuddy.services import (
    AccountLinkChallenge,
    AccountLinkingService,
    BlacklistedIdentityError,
)
from chimebuddy.twitch.device_authorization import (
    DeviceAuthorizationDeniedError,
    DeviceAuthorizationExpiredError,
)


logger = logging.getLogger(
    "chimebuddy.discord.onboarding"
)

LINKED_ROLE_NAME = "Twitch Linked"
CONNECT_BUTTON_CUSTOM_ID = (
    "chimebuddy:onboarding:connect"
)


def build_onboarding_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Connect Twitch & Request ChimeBuddy",
        description=(
            "Connect your Discord account to your Twitch "
            "account and submit a request to use "
            "ChimeBuddy.\n\n"
            "**Before you begin:**\n"
            "• Sign in with your broadcaster account.\n"
            "• Twitch will ask for the `channel:bot` "
            "permission.\n"
            "• Your authorization code will only be "
            "shown to you.\n"
            "• Your request will require developer "
            "approval."
        ),
        color=discord.Color.purple(),
    )

    embed.set_footer(
        text=(
            "Press the button below when you are ready."
        )
    )

    return embed


def render_challenge(
    challenge: AccountLinkChallenge,
) -> str:
    return (
        "**Twitch authorization started**\n\n"
        "1. Open this private Twitch activation page:\n"
        f"{challenge.verification_uri}\n\n"
        "2. Enter this code if Twitch asks for it:\n"
        f"`{challenge.user_code}`\n\n"
        "3. Sign in using the Twitch broadcaster "
        "account you want to connect.\n\n"
        f"This authorization expires "
        f"<t:{challenge.expires_at}:R>.\n\n"
        "ChimeBuddy is waiting for Twitch. You do not "
        "need to press the Discord button again."
    )


class OnboardingView(discord.ui.View):
    """Persistent public onboarding buttons."""

    def __init__(
        self,
        controller: "DiscordOnboardingController",
    ) -> None:
        super().__init__(timeout=None)
        self.controller = controller

    @discord.ui.button(
        label="Connect Twitch & Request ChimeBuddy",
        style=discord.ButtonStyle.primary,
        custom_id=CONNECT_BUTTON_CUSTOM_ID,
        emoji="🔗",
    )
    async def connect_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.controller.handle_connect(
            interaction
        )


class DiscordOnboardingController:
    """Connects Discord interactions to onboarding services."""

    def __init__(
        self,
        account_linking_service: AccountLinkingService,
    ) -> None:
        self.account_linking_service = (
            account_linking_service
        )

    def create_view(self) -> OnboardingView:
        return OnboardingView(self)

    async def post_panel(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if (
            interaction.guild is None
            or interaction.channel is None
        ):
            await interaction.response.send_message(
                "The onboarding panel can only be "
                "created inside the configured server.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            await self._get_or_create_linked_role(
                interaction.guild
            )

            await interaction.channel.send(
                embed=build_onboarding_embed(),
                view=self.create_view(),
                allowed_mentions=(
                    discord.AllowedMentions.none()
                ),
            )

        except discord.Forbidden:
            logger.exception(
                "Discord denied onboarding panel setup."
            )

            await interaction.edit_original_response(
                content=(
                    "I could not create the onboarding "
                    "panel or the Twitch Linked role. "
                    "Check my Manage Roles and Send "
                    "Messages permissions."
                )
            )
            return

        except discord.HTTPException:
            logger.exception(
                "Discord onboarding panel setup failed."
            )

            await interaction.edit_original_response(
                content=(
                    "Discord could not create the "
                    "onboarding panel. Please try again."
                )
            )
            return

        await interaction.edit_original_response(
            content=(
                "The onboarding panel is ready in "
                f"{interaction.channel.mention}."
            )
        )

    async def handle_connect(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Account linking can only be started "
                "inside the ChimeBuddy server.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        discord_account = DiscordAccount(
            discord_user_id=str(interaction.user.id),
            username=interaction.user.name,
            display_name=(
                interaction.user.display_name
            ),
        )

        try:
            challenge = (
                await self.account_linking_service.start(
                    discord_account
                )
            )

        except PendingAccountLinkSessionError:
            await interaction.edit_original_response(
                content=(
                    "You already have a Twitch "
                    "authorization in progress. Finish "
                    "that authorization or wait for it "
                    "to expire before trying again."
                )
            )
            return

        except BlacklistedIdentityError:
            await interaction.edit_original_response(
                content=(
                    "This account cannot submit a "
                    "ChimeBuddy request."
                )
            )
            return

        except Exception:
            logger.exception(
                "Failed to start Discord account linking "
                "for user %s.",
                interaction.user.id,
            )

            await interaction.edit_original_response(
                content=(
                    "ChimeBuddy could not start Twitch "
                    "authorization. Please try again later."
                )
            )
            return

        await interaction.edit_original_response(
            content=render_challenge(challenge)
        )

        try:
            result = (
                await self.account_linking_service.complete(
                    challenge
                )
            )

        except DeviceAuthorizationDeniedError:
            await interaction.edit_original_response(
                content=(
                    "Twitch authorization was denied. "
                    "Nothing was linked."
                )
            )
            return

        except DeviceAuthorizationExpiredError:
            await interaction.edit_original_response(
                content=(
                    "The Twitch authorization code "
                    "expired. Press the button to start "
                    "again."
                )
            )
            return

        except AccountLinkIdentityConflictError as exc:
            await interaction.edit_original_response(
                content=(
                    "These accounts cannot be linked: "
                    f"{exc}"
                )
            )
            return

        except BlacklistedIdentityError:
            await interaction.edit_original_response(
                content=(
                    "This account cannot submit a "
                    "ChimeBuddy request."
                )
            )
            return

        except OpenBroadcasterRequestError:
            await self._assign_linked_role(
                interaction
            )

            await interaction.edit_original_response(
                content=(
                    "Your Twitch account is linked, but "
                    "you already have an active or pending "
                    "ChimeBuddy request."
                )
            )
            return

        except Exception:
            logger.exception(
                "Discord account linking failed for "
                "user %s.",
                interaction.user.id,
            )

            await interaction.edit_original_response(
                content=(
                    "Twitch authorization could not be "
                    "completed. Please try again later."
                )
            )
            return

        role_assigned = await self._assign_linked_role(
            interaction
        )

        role_message = (
            "The **Twitch Linked** role was added."
            if role_assigned
            else (
                "Your accounts are linked, but Discord "
                "could not add the Twitch Linked role. "
                "The developer has been notified."
            )
        )

        await interaction.edit_original_response(
            content=(
                "**Twitch account connected "
                "successfully!**\n\n"
                f"Twitch channel: `{result.twitch_login}`\n"
                f"Request ID: `{result.request.request_id}`\n"
                "Request status: `pending`\n\n"
                f"{role_message}\n\n"
                "You will be notified after your request "
                "has been reviewed."
            )
        )

    async def _assign_linked_role(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if (
            interaction.guild is None
            or not isinstance(
                interaction.user,
                discord.Member,
            )
        ):
            return False

        try:
            role = await self._get_or_create_linked_role(
                interaction.guild
            )

            await interaction.user.add_roles(
                role,
                reason=(
                    "ChimeBuddy Twitch account linked."
                ),
            )

            return True

        except discord.HTTPException:
            logger.exception(
                "Failed to assign Twitch Linked role "
                "to Discord user %s.",
                interaction.user.id,
            )
            return False

    @staticmethod
    async def _get_or_create_linked_role(
        guild: discord.Guild,
    ) -> discord.Role:
        existing_role = discord.utils.get(
            guild.roles,
            name=LINKED_ROLE_NAME,
        )

        if existing_role is not None:
            return existing_role

        return await guild.create_role(
            name=LINKED_ROLE_NAME,
            reason=(
                "ChimeBuddy Discord onboarding setup."
            ),
        )