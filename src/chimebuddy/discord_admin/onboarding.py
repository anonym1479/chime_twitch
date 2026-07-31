import logging
import time

import discord

from chimebuddy.discord_admin.review import (
    DiscordReviewController,
)
from chimebuddy.models import DiscordAccount
from chimebuddy.repositories import (
    AccountLinkIdentityConflictError,
    OpenBroadcasterRequestError,
    PendingAccountLinkSessionError,
)
from chimebuddy.services import (
    AccountLinkAuthorization,
    AccountLinkChallenge,
    AccountLinkingService,
    BlacklistedIdentityError,
    ExistingBroadcasterRequestError,
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

CONFIRM_BUTTON_CUSTOM_ID = (
    "chimebuddy:onboarding:confirm"
)

CANCEL_BUTTON_CUSTOM_ID = (
    "chimebuddy:onboarding:different-account"
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
            "• You can verify the connected account "
            "before submitting your request.\n"
            "• Your request requires developer approval."
        ),
        color=discord.Color.orange(),
    )

    embed.set_footer(
        text="Press the button below when you are ready."
    )

    return embed


def build_confirmation_embed(
    authorization: AccountLinkAuthorization,
    discord_user: discord.abc.User,
) -> discord.Embed:
    is_reauthorization = (
        authorization.existing_request is not None
    )

    embed = discord.Embed(
        title=(
            "Confirm Twitch reconnection"
            if is_reauthorization
            else "Check your account information"
        ),
        description=(
            "Twitch authorization was successful.\n\n"
            "Please confirm that these are the accounts "
            "you want to connect."
        ),
        color=discord.Color.orange(),
    )

    embed.add_field(
        name="Twitch account",
        value=(
            f"Channel: `{authorization.twitch_login}`\n"
            f"ID: `{authorization.twitch_user_id}`"
        ),
        inline=True,
    )

    embed.add_field(
        name="Discord account",
        value=(
            f"{discord_user.mention}\n"
            f"ID: `{authorization.discord_user_id}`"
        ),
        inline=True,
    )

    embed.add_field(
        name="Next step",
        value=(
            (
                "Press **Reconnect Twitch** to restore "
                "your existing ChimeBuddy access.\n\n"
                if is_reauthorization
                else (
                    "Press **Continue to request** to add "
                    "an optional message and submit your "
                    "request.\n\n"
                )
            )
            + "If the Twitch account is incorrect, choose "
            "**Use another Twitch account**."
        ),
        inline=False,
    )

    embed.set_footer(
        text=(
            (
                "Your existing request will keep the "
                "same request ID and private panel."
                if is_reauthorization
                else (
                    "Your Twitch credential and "
                    "ChimeBuddy request have not been "
                    "saved yet."
                )
            )
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


class RequestMessageModal(
    discord.ui.Modal,
    title="Request ChimeBuddy",
):
    requester_message = discord.ui.TextInput(
        label="Optional message",
        placeholder=(
            "Tell us something about your channel or "
            "why you would like to use ChimeBuddy."
        ),
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(
        self,
        *,
        controller: "DiscordOnboardingController",
        authorization: AccountLinkAuthorization,
        confirmation_view: "AccountConfirmationView",
        confirmation_interaction: discord.Interaction,
    ) -> None:
        super().__init__()

        self.controller = controller
        self.authorization = authorization
        self.confirmation_view = confirmation_view
        self.confirmation_interaction = (
            confirmation_interaction
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not self.confirmation_view.claim():
            await interaction.response.send_message(
                "This request is already being submitted.",
                ephemeral=True,
            )
            return

        message = self.requester_message.value.strip()

        succeeded = await self.controller.finalize_request(
            interaction,
            self.authorization,
            requester_message=message or None,
        )

        if not succeeded:
            self.confirmation_view.release()
            return

        self.confirmation_view.stop()

        try:
            await (
                self.confirmation_interaction
                .edit_original_response(
                    content=(
                        "**Request submitted successfully.**\n\n"
                        "You can see the final information "
                        "in the confirmation message below."
                    ),
                    embed=None,
                    view=None,
                )
            )
        except discord.HTTPException:
            logger.warning(
                "Could not update the account "
                "confirmation message after submission."
            )


class AccountConfirmationView(discord.ui.View):
    """Temporary confirmation buttons after Twitch auth."""

    def __init__(
        self,
        *,
        controller: "DiscordOnboardingController",
        authorization: AccountLinkAuthorization,
    ) -> None:
        remaining_seconds = max(
            1,
            authorization.confirmation_expires_at
            - int(time.time()),
        )

        super().__init__(
            timeout=float(remaining_seconds)
        )

        self.controller = controller
        self.authorization = authorization
        self.expected_discord_user_id = (
            authorization.discord_user_id
        )
        self._claimed = False

        if authorization.existing_request is not None:
            self.continue_button.label = "Reconnect Twitch"

    def claim(self) -> bool:
        """Claim the confirmation for one final operation."""

        if self._claimed:
            return False

        self._claimed = True
        return True

    def release(self) -> None:
        """Allow another submission after a recoverable error."""

        self._claimed = False

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if (
            str(interaction.user.id)
            == self.expected_discord_user_id
        ):
            return True

        await interaction.response.send_message(
            "This account confirmation belongs to "
            "another Discord user.",
            ephemeral=True,
        )

        return False

    @discord.ui.button(
        label="Continue to request",
        style=discord.ButtonStyle.success,
        custom_id=CONFIRM_BUTTON_CUSTOM_ID,
        emoji="✅",
    )
    async def continue_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self._claimed:
            await interaction.response.send_message(
                "This request is already being submitted.",
                ephemeral=True,
            )
            return

        if self.authorization.existing_request is not None:
            self.claim()

            succeeded = await self.controller.finalize_request(
                interaction,
                self.authorization,
                requester_message=None,
            )

            if succeeded:
                self.stop()
            else:
                self.release()

            return

        await interaction.response.send_modal(
            RequestMessageModal(
                controller=self.controller,
                authorization=self.authorization,
                confirmation_view=self,
                confirmation_interaction=interaction,
            )
        )

    @discord.ui.button(
        label="Use another Twitch account",
        style=discord.ButtonStyle.secondary,
        custom_id=CANCEL_BUTTON_CUSTOM_ID,
        emoji="↩️",
    )
    async def different_account_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self._claimed:
            await interaction.response.send_message(
                "This request is already being submitted.",
                ephemeral=True,
            )
            return

        self.claim()

        try:
            await (
                self.controller.account_linking_service
                .cancel_authorization(
                    self.authorization
                )
            )
        except Exception:
            self._claimed = False

            logger.exception(
                "Failed to cancel account authorization "
                "for Discord user %s.",
                interaction.user.id,
            )

            await interaction.response.send_message(
                "ChimeBuddy could not cancel this "
                "authorization. Please try again.",
                ephemeral=True,
            )
            return

        self.stop()

        await interaction.response.edit_message(
            content=(
                "The Twitch authorization was cancelled.\n\n"
                "Press the button on the onboarding panel "
                "when you are ready to connect another "
                "Twitch account."
            ),
            embed=None,
            view=None,
        )

    async def on_timeout(self) -> None:
        if self._claimed:
            return

        try:
            await (
                self.controller.account_linking_service
                .cancel_authorization(
                    self.authorization
                )
            )
        except Exception:
            logger.exception(
                "Failed to expire an unused account "
                "confirmation for Discord user %s.",
                self.expected_discord_user_id,
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
        style=discord.ButtonStyle.success,
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
        review_controller: (
            DiscordReviewController | None
        ) = None,
    ) -> None:
        self.account_linking_service = (
            account_linking_service
        )
        self.review_controller = review_controller

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

        except ExistingBroadcasterRequestError as exc:
            request = exc.request

            await interaction.edit_original_response(
                content=(
                    "You already have a ChimeBuddy "
                    "request.\n\n"
                    f"Request ID: `{request.request_id}`\n"
                    "Current status: "
                    f"`{request.status.value}`\n\n"
                    "You do not need to authorize "
                    "Twitch again."
                )
            )
            return

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
            content=render_challenge(challenge),
            embed=None,
            view=None,
        )

        try:
            authorization = (
                await self.account_linking_service
                .authenticate(challenge)
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

        except BlacklistedIdentityError:
            await interaction.edit_original_response(
                content=(
                    "This Discord or Twitch account "
                    "cannot submit a ChimeBuddy request."
                )
            )
            return

        except Exception:
            logger.exception(
                "Twitch authentication failed for "
                "Discord user %s.",
                interaction.user.id,
            )

            await interaction.edit_original_response(
                content=(
                    "Twitch authorization could not be "
                    "completed. Please try again later."
                )
            )
            return

        confirmation_view = AccountConfirmationView(
            controller=self,
            authorization=authorization,
        )

        await interaction.edit_original_response(
            content=None,
            embed=build_confirmation_embed(
                authorization,
                interaction.user,
            ),
            view=confirmation_view,
        )

    async def finalize_request(
        self,
        interaction: discord.Interaction,
        authorization: AccountLinkAuthorization,
        *,
        requester_message: str | None,
    ) -> bool:
        if (
            str(interaction.user.id)
            != authorization.discord_user_id
        ):
            await interaction.response.send_message(
                "This Twitch authorization belongs to "
                "another Discord user.",
                ephemeral=True,
            )
            return False

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            result = (
                await self.account_linking_service
                .confirm_and_create_request(
                    authorization,
                    requester_message=requester_message,
                )
            )

        except AccountLinkIdentityConflictError as exc:
            await interaction.edit_original_response(
                content=(
                    "These accounts cannot be linked: "
                    f"{exc}"
                )
            )
            return False

        except BlacklistedIdentityError:
            await interaction.edit_original_response(
                content=(
                    "This account cannot submit a "
                    "ChimeBuddy request."
                )
            )
            return False

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
            return True

        except Exception:
            logger.exception(
                "Request creation failed for Discord "
                "user %s.",
                interaction.user.id,
            )

            await interaction.edit_original_response(
                content=(
                    "ChimeBuddy could not submit your "
                    "request. Please try again."
                )
            )
            return False

        if (
            self.review_controller is not None
            and not result.was_reauthorization
        ):
            try:
                await self.review_controller.publish_request(
                    interaction.client,
                    result.request,
                )
            except Exception:
                logger.exception(
                    "Request %s was saved, but its "
                    "Discord review message failed.",
                    result.request.request_id,
                )

        linked_role = await self._assign_linked_role(
            interaction
        )

        if linked_role is not None:
            role_message = (
                f"The {linked_role.mention} role was added."
            )
        else:
            role_message = (
                "Your accounts are linked, but Discord "
                "could not add the **Twitch Linked** role. "
                "The developer has been notified."
            )

        if result.was_reauthorization:
            await interaction.edit_original_response(
                content=(
                    "**Twitch reconnected successfully!**"
                    "\n\n"
                    f"Twitch channel: "
                    f"`{result.twitch_login}`\n"
                    f"Request ID: "
                    f"`{result.request.request_id}`\n"
                    "Request status: `active`\n\n"
                    f"{role_message}\n\n"
                    "ChimeBuddy has been resumed. The "
                    "Twitch worker will reconnect this "
                    "channel during its next broadcaster "
                    "synchronization."
                )
            )
            return True

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

        return True

    async def _assign_linked_role(
        self,
        interaction: discord.Interaction,
    ) -> discord.Role | None:
        if (
            interaction.guild is None
            or not isinstance(
                interaction.user,
                discord.Member,
            )
        ):
            return None

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

            return role

        except discord.HTTPException:
            logger.exception(
                "Failed to assign Twitch Linked role "
                "to Discord user %s.",
                interaction.user.id,
            )
            return None

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
