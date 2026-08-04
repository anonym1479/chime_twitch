import logging
import math

import discord

from chimebuddy.models import (
    CustomCommand,
    CustomCommandPermission,
)
from chimebuddy.services import (
    BroadcasterPanelNotFoundError,
    BroadcasterPanelStatus,
    BroadcasterPanelStatusService,
    CustomCommandLimitReachedError,
    CustomCommandManagementService,
    CustomCommandNameConflictError,
    CustomCommandValidationError,
    ManagedCustomCommandBroadcasterNotFoundError,
    ManagedCustomCommandNotFoundError,
    ReservedCustomCommandNameError,
)


logger = logging.getLogger(
    "chimebuddy.discord.custom_commands"
)

COMMANDS_PER_PAGE = 25


def parse_permission(
    value: str,
) -> CustomCommandPermission:
    normalized = str(value).strip().casefold()

    try:
        return CustomCommandPermission(normalized)
    except ValueError as exc:
        raise CustomCommandValidationError(
            "Permission must be `everyone`, `subscriber`, "
            "`vip`, `moderator`, or `broadcaster`."
        ) from exc


def parse_cooldown(value: str) -> int:
    try:
        cooldown = int(str(value).strip())
    except ValueError as exc:
        raise CustomCommandValidationError(
            "Cooldown must be a whole number of seconds."
        ) from exc

    return cooldown


def parse_command_id(value: str) -> int:
    try:
        command_id = int(str(value).strip())
    except ValueError as exc:
        raise CustomCommandValidationError(
            "Command ID must be a whole number."
        ) from exc

    if command_id <= 0:
        raise CustomCommandValidationError(
            "Command ID must be greater than zero."
        )

    return command_id


def find_command(
    commands: list[CustomCommand],
    command_id: int | None,
) -> CustomCommand | None:
    if command_id is None:
        return None

    for command in commands:
        if command.command_id == command_id:
            return command

    return None


def _short_text(value: str, maximum_length: int) -> str:
    text = str(value).strip()

    if len(text) <= maximum_length:
        return text

    return text[: maximum_length - 1].rstrip() + "..."


def _chunk_lines(
    lines: list[str],
    *,
    maximum_length: int = 900,
) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []

    for line in lines:
        candidate = "\n".join([*current, line])

        if current and len(candidate) > maximum_length:
            chunks.append("\n".join(current))
            current = [line]
        else:
            current.append(line)

    if current:
        chunks.append("\n".join(current))

    return chunks


def _page_count(commands: list[CustomCommand]) -> int:
    return max(1, math.ceil(len(commands) / COMMANDS_PER_PAGE))


def _normalized_page(
    commands: list[CustomCommand],
    page: int,
) -> int:
    return min(max(int(page), 0), _page_count(commands) - 1)


def commands_for_page(
    commands: list[CustomCommand],
    page: int,
) -> list[CustomCommand]:
    normalized_page = _normalized_page(commands, page)
    start = normalized_page * COMMANDS_PER_PAGE
    return commands[start : start + COMMANDS_PER_PAGE]


def build_command_list_embed(
    status: BroadcasterPanelStatus,
    commands: list[CustomCommand],
    *,
    selected_command_id: int | None = None,
    page: int = 0,
) -> discord.Embed:
    page = _normalized_page(commands, page)
    pages = _page_count(commands)
    visible_commands = commands_for_page(commands, page)

    embed = discord.Embed(
        title=f"Custom commands - {status.twitch_login}",
        description=(
            "Custom commands respond in Twitch chat. "
            "Viewers invoke them with an underscore, "
            "for example `_rules`."
        ),
        color=discord.Color.blurple(),
    )

    if not commands:
        embed.add_field(
            name="No custom commands configured",
            value=(
                "Press **Add command** to create the "
                "first custom Twitch command."
            ),
            inline=False,
        )
    else:
        lines = []

        for command in visible_commands:
            state = "Enabled" if command.enabled else "Disabled"
            selected = (
                "> "
                if command.command_id == selected_command_id
                else ""
            )
            lines.append(
                f"{selected}`#{command.command_id}` "
                f"**_{command.name}** - {state} - "
                f"{command.permission.value} - "
                f"{command.cooldown_seconds}s cooldown"
            )

        for index, chunk in enumerate(_chunk_lines(lines)):
            embed.add_field(
                name=(
                    f"Configured commands - page {page + 1}/{pages}"
                    if index == 0
                    else "Configured commands continued"
                ),
                value=chunk,
                inline=False,
            )

        selected = find_command(
            commands,
            selected_command_id,
        )

        if selected is None:
            embed.add_field(
                name="Command controls",
                value=(
                    "Select a command below to view its "
                    "response and enable Edit, "
                    "Enable/Disable, and Delete."
                ),
                inline=False,
            )
        else:
            embed.add_field(
                name=(
                    f"Selected command #{selected.command_id} "
                    f"- _{selected.name}"
                ),
                value=(
                    f"Status: `{'enabled' if selected.enabled else 'disabled'}`\n"
                    f"Permission: `{selected.permission.value}`\n"
                    f"Cooldown: `{selected.cooldown_seconds} seconds`\n"
                    f"Response: {_short_text(selected.response_message, 900)}"
                ),
                inline=False,
            )

    embed.set_footer(
        text=f"{len(commands)} of 50 custom commands configured"
    )
    return embed


def build_command_options(
    commands: list[CustomCommand],
) -> list[discord.SelectOption]:
    return [
        discord.SelectOption(
            label=("_" + command.name)[:100],
            value=str(command.command_id),
            description=(
                f"#{command.command_id} - "
                f"{'enabled' if command.enabled else 'disabled'} - "
                f"{command.permission.value}"
            )[:100],
        )
        for command in commands
    ]


class AddCustomCommandModal(
    discord.ui.Modal,
    title="Add custom command",
):
    name_input = discord.ui.TextInput(
        label="Command name (without _)",
        placeholder="Example: rules",
        min_length=1,
        max_length=25,
    )
    response_input = discord.ui.TextInput(
        label="Twitch response message",
        placeholder="Please read the channel rules.",
        style=discord.TextStyle.paragraph,
        min_length=1,
        max_length=450,
    )
    permission_input = discord.ui.TextInput(
        label="Who can use it?",
        placeholder=(
            "everyone / subscriber / vip / moderator / broadcaster"
        ),
        default="everyone",
        min_length=3,
        max_length=11,
    )
    cooldown_input = discord.ui.TextInput(
        label="Cooldown in seconds (5-3600)",
        default="30",
        min_length=1,
        max_length=4,
    )

    def __init__(
        self,
        controller: "DiscordCustomCommandManagementController",
        twitch_user_id: str,
    ) -> None:
        super().__init__(timeout=300)
        self.controller = controller
        self.twitch_user_id = twitch_user_id

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await self.controller.create_command(
            interaction,
            twitch_user_id=self.twitch_user_id,
            name=str(self.name_input.value),
            response_message=str(self.response_input.value),
            permission_text=str(self.permission_input.value),
            cooldown_text=str(self.cooldown_input.value),
        )


class EditCustomCommandModal(
    discord.ui.Modal,
    title="Edit custom command",
):
    name_input = discord.ui.TextInput(
        label="Command name (without _)",
        min_length=1,
        max_length=25,
    )
    response_input = discord.ui.TextInput(
        label="Twitch response message",
        style=discord.TextStyle.paragraph,
        min_length=1,
        max_length=450,
    )
    permission_input = discord.ui.TextInput(
        label="Who can use it?",
        min_length=3,
        max_length=11,
    )
    cooldown_input = discord.ui.TextInput(
        label="Cooldown in seconds (5-3600)",
        min_length=1,
        max_length=4,
    )

    def __init__(
        self,
        controller: "DiscordCustomCommandManagementController",
        twitch_user_id: str,
        command: CustomCommand,
    ) -> None:
        super().__init__(timeout=300)
        self.controller = controller
        self.twitch_user_id = twitch_user_id
        self.command = command
        self.name_input.default = command.name
        self.response_input.default = command.response_message
        self.permission_input.default = command.permission.value
        self.cooldown_input.default = str(command.cooldown_seconds)

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await self.controller.update_command(
            interaction,
            twitch_user_id=self.twitch_user_id,
            command_id=int(self.command.command_id),
            name=str(self.name_input.value),
            response_message=str(self.response_input.value),
            permission_text=str(self.permission_input.value),
            cooldown_text=str(self.cooldown_input.value),
            enabled=self.command.enabled,
        )


class CustomCommandSelect(discord.ui.Select):
    def __init__(
        self,
        controller: "DiscordCustomCommandManagementController",
        status: BroadcasterPanelStatus,
        commands: list[CustomCommand],
        selected_command_id: int | None,
        page: int,
    ) -> None:
        visible_commands = commands_for_page(commands, page)
        super().__init__(
            placeholder="Select a custom command",
            min_values=1,
            max_values=1,
            options=build_command_options(visible_commands),
            row=0,
        )
        self.controller = controller
        self.status = status
        self.page = page

        for option in self.options:
            option.default = (
                option.value == str(selected_command_id)
            )

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await self.controller.select_command(
            interaction,
            self.status.twitch_user_id,
            parse_command_id(self.values[0]),
            page=self.page,
        )


class CustomCommandListView(discord.ui.View):
    """Short-lived private custom-command controls."""

    def __init__(
        self,
        controller: "DiscordCustomCommandManagementController",
        status: BroadcasterPanelStatus,
        commands: list[CustomCommand],
        *,
        selected_command_id: int | None = None,
        page: int = 0,
    ) -> None:
        super().__init__(timeout=300)
        self.controller = controller
        self.status = status
        self.commands = commands
        self.page = _normalized_page(commands, page)
        self.selected_command_id = selected_command_id

        if commands:
            self.add_item(
                CustomCommandSelect(
                    controller,
                    status,
                    commands,
                    selected_command_id,
                    self.page,
                )
            )

        selected = find_command(commands, selected_command_id)
        has_selection = selected is not None
        self.edit_button.disabled = not has_selection
        self.toggle_button.disabled = not has_selection
        self.delete_button.disabled = not has_selection
        self.previous_button.disabled = self.page == 0
        self.next_button.disabled = (
            self.page >= _page_count(commands) - 1
        )

        if selected is not None and not selected.enabled:
            self.toggle_button.label = "Enable"
            self.toggle_button.style = discord.ButtonStyle.success

    @discord.ui.button(
        label="Add command",
        style=discord.ButtonStyle.success,
        row=1,
    )
    async def add_button(self, interaction, button) -> None:
        if not self.controller.can_manage(
            interaction.user.id,
            self.status,
        ):
            await interaction.response.send_message(
                "You cannot manage this broadcaster's commands.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            AddCustomCommandModal(
                self.controller,
                self.status.twitch_user_id,
            )
        )

    @discord.ui.button(
        label="Edit",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def edit_button(self, interaction, button) -> None:
        await self.controller.request_edit(
            interaction,
            self.status.twitch_user_id,
            self.selected_command_id,
        )

    @discord.ui.button(
        label="Disable",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def toggle_button(self, interaction, button) -> None:
        await self.controller.toggle_command(
            interaction,
            self.status.twitch_user_id,
            self.selected_command_id,
            page=self.page,
        )

    @discord.ui.button(
        label="Delete",
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def delete_button(self, interaction, button) -> None:
        await self.controller.request_delete(
            interaction,
            self.status.twitch_user_id,
            self.selected_command_id,
        )

    @discord.ui.button(
        label="Previous",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def previous_button(self, interaction, button) -> None:
        await self.controller.change_page(
            interaction,
            self.status.twitch_user_id,
            self.page - 1,
        )

    @discord.ui.button(
        label="Next",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def next_button(self, interaction, button) -> None:
        await self.controller.change_page(
            interaction,
            self.status.twitch_user_id,
            self.page + 1,
        )

    @discord.ui.button(
        label="Refresh list",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def refresh_button(self, interaction, button) -> None:
        await self.controller.refresh_list(
            interaction,
            self.status.twitch_user_id,
            selected_command_id=self.selected_command_id,
            page=self.page,
        )


class DeleteCustomCommandConfirmationView(discord.ui.View):
    def __init__(
        self,
        *,
        controller: "DiscordCustomCommandManagementController",
        twitch_user_id: str,
        command_id: int,
        command_name: str,
        requested_by_user_id: int,
    ) -> None:
        super().__init__(timeout=60)
        self.controller = controller
        self.twitch_user_id = twitch_user_id
        self.command_id = command_id
        self.command_name = command_name
        self.requested_by_user_id = int(requested_by_user_id)

    async def interaction_check(self, interaction) -> bool:
        if interaction.user.id == self.requested_by_user_id:
            return True

        await interaction.response.send_message(
            "Only the person who started this deletion can confirm it.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(
        label="Delete command",
        style=discord.ButtonStyle.danger,
    )
    async def confirm_button(self, interaction, button) -> None:
        await self.controller.confirm_delete(
            interaction,
            twitch_user_id=self.twitch_user_id,
            command_id=self.command_id,
            command_name=self.command_name,
        )

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel_button(self, interaction, button) -> None:
        await interaction.response.edit_message(
            content="Command deletion was cancelled.",
            view=None,
        )


class DiscordCustomCommandManagementController:
    """Connects private Discord controls to custom commands."""

    def __init__(
        self,
        *,
        management_service: CustomCommandManagementService,
        status_service: BroadcasterPanelStatusService,
        developer_discord_user_id: int,
    ) -> None:
        self.management_service = management_service
        self.status_service = status_service
        self.developer_discord_user_id = int(
            developer_discord_user_id
        )

    def can_manage(
        self,
        discord_user_id: int | str,
        status: BroadcasterPanelStatus,
    ) -> bool:
        return str(discord_user_id) in {
            str(status.owner_discord_user_id),
            str(self.developer_discord_user_id),
        }

    async def show_commands(self, interaction, twitch_user_id) -> None:
        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )
        loaded = await self._load_authorized(
            interaction,
            twitch_user_id,
        )
        if loaded is not None:
            await self._edit_list(interaction, *loaded)

    async def refresh_list(
        self,
        interaction,
        twitch_user_id,
        *,
        selected_command_id=None,
        page=0,
    ) -> None:
        await interaction.response.defer()
        loaded = await self._load_authorized(
            interaction,
            twitch_user_id,
        )
        if loaded is None:
            return
        status, commands = loaded
        if find_command(commands, selected_command_id) is None:
            selected_command_id = None
        await self._edit_list(
            interaction,
            status,
            commands,
            selected_command_id=selected_command_id,
            page=page,
        )

    async def change_page(
        self,
        interaction,
        twitch_user_id,
        page,
    ) -> None:
        await self.refresh_list(
            interaction,
            twitch_user_id,
            page=page,
        )

    async def select_command(
        self,
        interaction,
        twitch_user_id,
        command_id,
        *,
        page=0,
    ) -> None:
        await interaction.response.defer()
        loaded = await self._load_authorized(
            interaction,
            twitch_user_id,
        )
        if loaded is None:
            return
        status, commands = loaded
        if find_command(commands, command_id) is None:
            command_id = None
        await self._edit_list(
            interaction,
            status,
            commands,
            selected_command_id=command_id,
            page=page,
        )

    async def request_edit(
        self,
        interaction,
        twitch_user_id,
        selected_command_id,
    ) -> None:
        if selected_command_id is None:
            await interaction.response.send_message(
                "Select a command before editing.",
                ephemeral=True,
            )
            return

        try:
            status = await self.status_service.get_for_broadcaster(
                twitch_user_id
            )
            commands = await self.management_service.list_commands(
                twitch_user_id
            )
            command = find_command(commands, selected_command_id)
            if not self.can_manage(interaction.user.id, status):
                raise PermissionError
            if command is None:
                raise ManagedCustomCommandNotFoundError(
                    "The custom command does not exist."
                )
            await interaction.response.send_modal(
                EditCustomCommandModal(
                    self,
                    twitch_user_id,
                    command,
                )
            )
        except PermissionError:
            await interaction.response.send_message(
                "You cannot manage this broadcaster's commands.",
                ephemeral=True,
            )
        except Exception:
            logger.exception(
                "Failed to open custom command edit modal for %s.",
                twitch_user_id,
            )
            await interaction.response.send_message(
                "ChimeBuddy could not open this command for editing.",
                ephemeral=True,
            )

    async def create_command(
        self,
        interaction,
        *,
        twitch_user_id,
        name,
        response_message,
        permission_text,
        cooldown_text,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )
        try:
            status = await self.status_service.get_for_broadcaster(
                twitch_user_id
            )
            if not self.can_manage(interaction.user.id, status):
                raise PermissionError
            created = await self.management_service.create_command(
                twitch_user_id,
                name=name,
                response_message=response_message,
                permission=parse_permission(permission_text),
                cooldown_seconds=parse_cooldown(cooldown_text),
                enabled=True,
            )
            commands = await self.management_service.list_commands(
                twitch_user_id
            )
        except PermissionError:
            await self._error(
                interaction,
                "You cannot manage this broadcaster's commands.",
            )
            return
        except self._expected_errors() as exc:
            await self._error(interaction, f"Command not created: {exc}")
            return
        except Exception:
            logger.exception(
                "Failed to create custom command for %s.",
                twitch_user_id,
            )
            await self._error(
                interaction,
                "ChimeBuddy could not create the command.",
            )
            return

        await self._edit_list(
            interaction,
            status,
            commands,
            content=f"Command **_{created.name}** was created.",
            selected_command_id=created.command_id,
            page=self._page_for(commands, created.command_id),
        )

    async def update_command(
        self,
        interaction,
        *,
        twitch_user_id,
        command_id,
        name,
        response_message,
        permission_text,
        cooldown_text,
        enabled,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )
        try:
            status = await self.status_service.get_for_broadcaster(
                twitch_user_id
            )
            if not self.can_manage(interaction.user.id, status):
                raise PermissionError
            updated = await self.management_service.update_command(
                twitch_user_id,
                command_id,
                name=name,
                response_message=response_message,
                permission=parse_permission(permission_text),
                cooldown_seconds=parse_cooldown(cooldown_text),
                enabled=enabled,
            )
            commands = await self.management_service.list_commands(
                twitch_user_id
            )
        except PermissionError:
            await self._error(
                interaction,
                "You cannot manage this broadcaster's commands.",
            )
            return
        except self._expected_errors() as exc:
            await self._error(interaction, f"Command not updated: {exc}")
            return
        except Exception:
            logger.exception(
                "Failed to update custom command %s for %s.",
                command_id,
                twitch_user_id,
            )
            await self._error(
                interaction,
                "ChimeBuddy could not update the command.",
            )
            return
        await self._edit_list(
            interaction,
            status,
            commands,
            content=f"Command **_{updated.name}** was updated.",
            selected_command_id=updated.command_id,
            page=self._page_for(commands, updated.command_id),
        )

    async def toggle_command(
        self,
        interaction,
        twitch_user_id,
        selected_command_id,
        *,
        page=0,
    ) -> None:
        if selected_command_id is None:
            await interaction.response.send_message(
                "Select a command before changing it.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )
        try:
            status = await self.status_service.get_for_broadcaster(
                twitch_user_id
            )
            if not self.can_manage(interaction.user.id, status):
                raise PermissionError
            commands = await self.management_service.list_commands(
                twitch_user_id
            )
            current = find_command(commands, selected_command_id)
            if current is None:
                raise ManagedCustomCommandNotFoundError(
                    "The custom command does not exist."
                )
            updated = await self.management_service.set_enabled(
                twitch_user_id,
                current.command_id,
                not current.enabled,
            )
            commands = await self.management_service.list_commands(
                twitch_user_id
            )
        except PermissionError:
            await self._error(
                interaction,
                "You cannot manage this broadcaster's commands.",
            )
            return
        except self._expected_errors() as exc:
            await self._error(interaction, f"Command not changed: {exc}")
            return
        except Exception:
            logger.exception(
                "Failed to toggle custom command %s for %s.",
                selected_command_id,
                twitch_user_id,
            )
            await self._error(
                interaction,
                "ChimeBuddy could not change the command.",
            )
            return
        await self._edit_list(
            interaction,
            status,
            commands,
            content=(
                f"Command **_{updated.name}** was "
                f"{'enabled' if updated.enabled else 'disabled'}."
            ),
            selected_command_id=updated.command_id,
            page=page,
        )

    async def request_delete(
        self,
        interaction,
        twitch_user_id,
        selected_command_id,
    ) -> None:
        if selected_command_id is None:
            await interaction.response.send_message(
                "Select a command before deleting.",
                ephemeral=True,
            )
            return
        try:
            status = await self.status_service.get_for_broadcaster(
                twitch_user_id
            )
            commands = await self.management_service.list_commands(
                twitch_user_id
            )
            command = find_command(commands, selected_command_id)
            if not self.can_manage(interaction.user.id, status):
                raise PermissionError
            if command is None:
                raise ManagedCustomCommandNotFoundError
            await interaction.response.send_message(
                f"Delete custom command **_{command.name}**? "
                "This cannot be undone.",
                view=DeleteCustomCommandConfirmationView(
                    controller=self,
                    twitch_user_id=twitch_user_id,
                    command_id=int(command.command_id),
                    command_name=command.name,
                    requested_by_user_id=interaction.user.id,
                ),
                ephemeral=True,
            )
        except PermissionError:
            await interaction.response.send_message(
                "You cannot manage this broadcaster's commands.",
                ephemeral=True,
            )
        except Exception:
            logger.exception(
                "Failed to request custom command deletion for %s.",
                twitch_user_id,
            )
            await interaction.response.send_message(
                "ChimeBuddy could not prepare that deletion.",
                ephemeral=True,
            )

    async def confirm_delete(
        self,
        interaction,
        *,
        twitch_user_id,
        command_id,
        command_name,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )
        try:
            status = await self.status_service.get_for_broadcaster(
                twitch_user_id
            )
            if not self.can_manage(interaction.user.id, status):
                raise PermissionError
            await self.management_service.delete_command(
                twitch_user_id,
                command_id,
            )
        except PermissionError:
            await interaction.edit_original_response(
                content="You cannot manage this broadcaster's commands.",
                view=None,
            )
            return
        except self._expected_errors() as exc:
            await interaction.edit_original_response(
                content=f"Command not deleted: {exc}",
                view=None,
            )
            return
        except Exception:
            logger.exception(
                "Failed to delete custom command %s for %s.",
                command_id,
                twitch_user_id,
            )
            await interaction.edit_original_response(
                content="ChimeBuddy could not delete the command.",
                view=None,
            )
            return
        await interaction.edit_original_response(
            content=(
                f"Command **_{command_name}** was deleted. "
                "Press **Refresh list** in the command panel to reload."
            ),
            view=None,
        )

    async def _load_authorized(
        self,
        interaction,
        twitch_user_id,
    ) -> tuple[BroadcasterPanelStatus, list[CustomCommand]] | None:
        try:
            status = await self.status_service.get_for_broadcaster(
                twitch_user_id
            )
            if not self.can_manage(interaction.user.id, status):
                await self._error(
                    interaction,
                    "You cannot manage this broadcaster's commands.",
                )
                return None
            commands = await self.management_service.list_commands(
                twitch_user_id
            )
            return status, commands
        except BroadcasterPanelNotFoundError:
            await self._error(
                interaction,
                "This broadcaster panel is no longer registered.",
            )
            return None
        except (
            ManagedCustomCommandBroadcasterNotFoundError,
        ) as exc:
            await self._error(interaction, str(exc))
            return None
        except Exception:
            logger.exception(
                "Failed to load custom commands for %s.",
                twitch_user_id,
            )
            await self._error(
                interaction,
                "ChimeBuddy could not load the custom commands.",
            )
            return None

    async def _edit_list(
        self,
        interaction,
        status,
        commands,
        *,
        content=None,
        selected_command_id=None,
        page=0,
    ) -> None:
        await interaction.edit_original_response(
            content=content,
            embed=build_command_list_embed(
                status,
                commands,
                selected_command_id=selected_command_id,
                page=page,
            ),
            view=CustomCommandListView(
                self,
                status,
                commands,
                selected_command_id=selected_command_id,
                page=page,
            ),
        )

    @staticmethod
    async def _error(interaction, content) -> None:
        await interaction.edit_original_response(
            content=content,
            embed=None,
            view=None,
        )

    @staticmethod
    def _page_for(commands, command_id) -> int:
        for index, command in enumerate(commands):
            if command.command_id == command_id:
                return index // COMMANDS_PER_PAGE
        return 0

    @staticmethod
    def _expected_errors():
        return (
            CustomCommandValidationError,
            CustomCommandNameConflictError,
            CustomCommandLimitReachedError,
            ReservedCustomCommandNameError,
            ManagedCustomCommandNotFoundError,
            ManagedCustomCommandBroadcasterNotFoundError,
        )
