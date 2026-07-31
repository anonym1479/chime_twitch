import logging

import discord
from discord import app_commands

from chimebuddy.discord_admin.broadcaster_panel import (
    DiscordBroadcasterPanelController,
)
from chimebuddy.models import BroadcasterRequestStatus
from chimebuddy.repositories import (
    BroadcasterRequestRepository,
    IdentityRepository,
)
from chimebuddy.services import (
    BroadcasterRestorationBlockedError,
    BroadcasterSuspensionError,
    BroadcasterSuspensionService,
    BroadcasterSuspensionStateError,
)


logger = logging.getLogger(
    "chimebuddy.discord.suspension"
)


class SuspensionConfirmationView(discord.ui.View):
    """Confirms one developer suspension or restoration."""

    def __init__(
        self,
        *,
        controller: "DiscordBroadcasterSuspensionController",
        twitch_user_id: str,
        twitch_login: str,
        internal_reason: str | None,
        restore: bool,
        requested_by_user_id: int,
    ) -> None:
        super().__init__(timeout=60)
        self.controller = controller
        self.twitch_user_id = twitch_user_id
        self.twitch_login = twitch_login
        self.internal_reason = internal_reason
        self.restore = restore
        self.requested_by_user_id = int(
            requested_by_user_id
        )

        if restore:
            self.confirm_button.label = (
                "Restore broadcaster"
            )
            self.confirm_button.style = (
                discord.ButtonStyle.success
            )
        else:
            self.confirm_button.label = (
                "Suspend broadcaster"
            )
            self.confirm_button.style = (
                discord.ButtonStyle.danger
            )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id == self.requested_by_user_id:
            return True

        await interaction.response.send_message(
            "Only the developer who started this action "
            "can confirm it.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(
        label="Confirm",
        style=discord.ButtonStyle.danger,
    )
    async def confirm_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.controller.execute(
            interaction,
            twitch_user_id=self.twitch_user_id,
            twitch_login=self.twitch_login,
            internal_reason=self.internal_reason,
            restore=self.restore,
        )

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content="The administration action was cancelled.",
            view=None,
        )


class BroadcasterAdminCommandGroup(app_commands.Group):
    """Developer-only broadcaster administration commands."""

    def __init__(
        self,
        controller: "DiscordBroadcasterSuspensionController",
    ) -> None:
        super().__init__(
            name="broadcaster",
            description="Developer broadcaster administration.",
            default_permissions=(
                discord.Permissions(administrator=True)
            ),
        )
        self.controller = controller

    @app_commands.command(
        name="suspend",
        description="Suspend an active ChimeBuddy broadcaster.",
    )
    @app_commands.describe(
        account="Twitch broadcaster account",
        reason="Internal reason recorded in the audit history",
    )
    async def suspend(
        self,
        interaction: discord.Interaction,
        account: str,
        reason: str,
    ) -> None:
        await self.controller.prepare_suspend(
            interaction,
            twitch_user_id=account,
            internal_reason=reason,
        )

    @suspend.autocomplete("account")
    async def suspend_account_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self.controller.autocomplete(
            interaction,
            current,
            status=BroadcasterRequestStatus.ACTIVE,
        )

    @app_commands.command(
        name="restore",
        description="Restore a suspended ChimeBuddy broadcaster.",
    )
    @app_commands.describe(
        account="Suspended Twitch broadcaster account",
    )
    async def restore(
        self,
        interaction: discord.Interaction,
        account: str,
    ) -> None:
        await self.controller.prepare_restore(
            interaction,
            twitch_user_id=account,
        )

    @restore.autocomplete("account")
    async def restore_account_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self.controller.autocomplete(
            interaction,
            current,
            status=BroadcasterRequestStatus.SUSPENDED,
        )


class DiscordBroadcasterSuspensionController:
    """Runs developer suspension commands and autocomplete."""

    def __init__(
        self,
        *,
        suspension_service: BroadcasterSuspensionService,
        request_repository: BroadcasterRequestRepository,
        identity_repository: IdentityRepository,
        panel_controller: DiscordBroadcasterPanelController,
        developer_discord_user_id: int,
    ) -> None:
        self.suspension_service = suspension_service
        self.request_repository = request_repository
        self.identity_repository = identity_repository
        self.panel_controller = panel_controller
        self.developer_discord_user_id = int(
            developer_discord_user_id
        )

    def create_command_group(
        self,
    ) -> BroadcasterAdminCommandGroup:
        return BroadcasterAdminCommandGroup(self)

    async def autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
        *,
        status: BroadcasterRequestStatus,
    ) -> list[app_commands.Choice[str]]:
        if not self._is_developer(interaction.user.id):
            return []

        needle = str(current).strip().casefold()
        choices: list[app_commands.Choice[str]] = []

        try:
            requests = (
                await self.request_repository.list_by_status(
                    (status,)
                )
            )

            for request in requests:
                account = (
                    await self.identity_repository
                    .get_twitch_account(request.twitch_user_id)
                )
                login = (
                    account.login
                    if account is not None
                    else request.twitch_user_id
                )

                if (
                    needle
                    and needle not in login.casefold()
                    and needle
                    not in request.twitch_user_id.casefold()
                ):
                    continue

                choices.append(
                    app_commands.Choice(
                        name=(
                            f"{login} "
                            f"({request.twitch_user_id})"
                        )[:100],
                        value=request.twitch_user_id,
                    )
                )
        except Exception:
            logger.exception(
                "Could not build broadcaster autocomplete "
                "choices for status %s.",
                status.value,
            )
            return []

        choices.sort(key=lambda choice: choice.name.casefold())
        return choices[:25]

    async def prepare_suspend(
        self,
        interaction: discord.Interaction,
        *,
        twitch_user_id: str,
        internal_reason: str,
    ) -> None:
        if not await self._require_developer(interaction):
            return

        reason = str(internal_reason).strip()

        if not reason or len(reason) > 500:
            await interaction.response.send_message(
                "The internal reason must contain between "
                "1 and 500 characters.",
                ephemeral=True,
            )
            return

        loaded = await self._load_target(
            interaction,
            twitch_user_id,
            expected_status=BroadcasterRequestStatus.ACTIVE,
        )

        if loaded is None:
            return

        request, login = loaded
        view = SuspensionConfirmationView(
            controller=self,
            twitch_user_id=request.twitch_user_id,
            twitch_login=login,
            internal_reason=reason,
            restore=False,
            requested_by_user_id=interaction.user.id,
        )
        await interaction.response.send_message(
            (
                f"Suspend ChimeBuddy for `{login}`?\n\n"
                "The Twitch worker will disconnect shortly. "
                "Credentials, triggers, and settings will be "
                "preserved.\n\n"
                f"Internal reason: {reason}"
            ),
            view=view,
            ephemeral=True,
        )

    async def prepare_restore(
        self,
        interaction: discord.Interaction,
        *,
        twitch_user_id: str,
    ) -> None:
        if not await self._require_developer(interaction):
            return

        loaded = await self._load_target(
            interaction,
            twitch_user_id,
            expected_status=BroadcasterRequestStatus.SUSPENDED,
        )

        if loaded is None:
            return

        request, login = loaded
        view = SuspensionConfirmationView(
            controller=self,
            twitch_user_id=request.twitch_user_id,
            twitch_login=login,
            internal_reason=None,
            restore=True,
            requested_by_user_id=interaction.user.id,
        )
        await interaction.response.send_message(
            (
                f"Restore ChimeBuddy for `{login}`?\n\n"
                "The Twitch worker will reconnect shortly."
            ),
            view=view,
            ephemeral=True,
        )

    async def execute(
        self,
        interaction: discord.Interaction,
        *,
        twitch_user_id: str,
        twitch_login: str,
        internal_reason: str | None,
        restore: bool,
    ) -> None:
        if not await self._require_developer(interaction):
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            request = (
                await self.request_repository
                .get_open_for_twitch(twitch_user_id)
            )
        except Exception:
            logger.exception(
                "Could not reload broadcaster command target %s.",
                twitch_user_id,
            )
            await interaction.edit_original_response(
                content=(
                    "ChimeBuddy could not reload the "
                    "broadcaster request."
                ),
                view=None,
            )
            return

        if request is None:
            await interaction.edit_original_response(
                content="The broadcaster request no longer exists.",
                view=None,
            )
            return

        try:
            if restore:
                await self.suspension_service.restore(
                    request.request_id,
                    developer_discord_user_id=str(
                        interaction.user.id
                    ),
                )
                action_text = "restored"
            else:
                await self.suspension_service.suspend(
                    request.request_id,
                    developer_discord_user_id=str(
                        interaction.user.id
                    ),
                    internal_reason=str(internal_reason),
                )
                action_text = "suspended"

        except BroadcasterRestorationBlockedError as exc:
            await interaction.edit_original_response(
                content=f"The broadcaster was not restored: {exc}",
                view=None,
            )
            return
        except BroadcasterSuspensionStateError as exc:
            await interaction.edit_original_response(
                content=f"The broadcaster state changed: {exc}",
                view=None,
            )
            return
        except BroadcasterSuspensionError:
            logger.exception(
                "Broadcaster suspension command failed for %s.",
                twitch_user_id,
            )
            await interaction.edit_original_response(
                content=(
                    "ChimeBuddy could not complete the "
                    "broadcaster administration action."
                ),
                view=None,
            )
            return
        except Exception:
            logger.exception(
                "Unexpected broadcaster administration "
                "failure for %s.",
                twitch_user_id,
            )
            await interaction.edit_original_response(
                content=(
                    "ChimeBuddy could not complete the "
                    "broadcaster administration action."
                ),
                view=None,
            )
            return

        panel_refreshed = True

        try:
            panel_refreshed = (
                await self.panel_controller.refresh_stored_panel(
                    interaction.client,
                    twitch_user_id,
                )
            )
        except Exception:
            panel_refreshed = False
            logger.exception(
                "Broadcaster %s changed state, but its panel "
                "could not be refreshed.",
                twitch_user_id,
            )

        panel_notice = (
            ""
            if panel_refreshed
            else (
                " The database was updated, but the private "
                "panel could not be refreshed."
            )
        )
        await interaction.edit_original_response(
            content=(
                f"`{twitch_login}` was {action_text}."
                f"{panel_notice}"
            ),
            view=None,
        )

    async def _load_target(
        self,
        interaction: discord.Interaction,
        twitch_user_id: str,
        *,
        expected_status: BroadcasterRequestStatus,
    ):
        twitch_id = str(twitch_user_id).strip()
        try:
            request = (
                await self.request_repository
                .get_open_for_twitch(twitch_id)
            )
        except Exception:
            logger.exception(
                "Could not load broadcaster command target %s.",
                twitch_id,
            )
            await interaction.response.send_message(
                "ChimeBuddy could not load the selected "
                "broadcaster.",
                ephemeral=True,
            )
            return None

        if request is None or request.status is not expected_status:
            await interaction.response.send_message(
                "The selected broadcaster is no longer in "
                "the required state. Run the command again "
                "and select an autocomplete result.",
                ephemeral=True,
            )
            return None

        try:
            account = (
                await self.identity_repository
                .get_twitch_account(twitch_id)
            )
        except Exception:
            logger.exception(
                "Could not load Twitch identity %s.",
                twitch_id,
            )
            await interaction.response.send_message(
                "ChimeBuddy could not load the selected "
                "Twitch account.",
                ephemeral=True,
            )
            return None
        login = account.login if account is not None else twitch_id
        return request, login

    async def _require_developer(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if self._is_developer(interaction.user.id):
            return True

        logger.warning(
            "Denied broadcaster administration command from "
            "Discord user %s.",
            interaction.user.id,
        )
        await interaction.response.send_message(
            "Only the ChimeBuddy developer can use this "
            "administration command.",
            ephemeral=True,
        )
        return False

    def _is_developer(
        self,
        discord_user_id: int | str,
    ) -> bool:
        return int(discord_user_id) == (
            self.developer_discord_user_id
        )
