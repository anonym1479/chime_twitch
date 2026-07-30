import logging

import discord

from chimebuddy.models import (
    Trigger,
    TriggerMatchType,
)
from chimebuddy.services import (
    BroadcasterPanelNotFoundError,
    BroadcasterPanelStatus,
    BroadcasterPanelStatusService,
    ManagedBroadcasterNotFoundError,
    ManagedTriggerNotFoundError,
    TriggerBusyError,
    TriggerLimitReachedError,
    TriggerManagementService,
    TriggerNameConflictError,
    TriggerValidationError,
)


logger = logging.getLogger(
    "chimebuddy.discord.trigger_management"
)


def parse_match_type(
    value: str,
) -> TriggerMatchType:
    normalized = str(value).strip().casefold()

    try:
        return TriggerMatchType(normalized)
    except ValueError as exc:
        raise TriggerValidationError(
            "Match type must be `contains` or `exact`."
        ) from exc


def parse_priority(
    value: str,
) -> int:
    cleaned = str(value).strip()

    if not cleaned:
        return 100

    try:
        priority = int(cleaned)
    except ValueError as exc:
        raise TriggerValidationError(
            "Priority must be a whole number."
        ) from exc

    if not 0 <= priority <= 10000:
        raise TriggerValidationError(
            "Priority must be between 0 and 10000."
        )

    return priority


def parse_trigger_id(
    value: str,
) -> int:
    try:
        trigger_id = int(str(value).strip())
    except ValueError as exc:
        raise TriggerValidationError(
            "Trigger ID must be a whole number."
        ) from exc

    if trigger_id <= 0:
        raise TriggerValidationError(
            "Trigger ID must be greater than zero."
        )

    return trigger_id


def _short_text(
    value: str,
    maximum_length: int,
) -> str:
    text = str(value).strip()

    if len(text) <= maximum_length:
        return text

    return text[: maximum_length - 1].rstrip() + "…"


def _chunk_lines(
    lines: list[str],
    *,
    maximum_length: int = 900,
) -> list[str]:
    chunks: list[str] = []
    current_lines: list[str] = []
    current_length = 0

    for line in lines:
        added_length = len(line) + (
            1 if current_lines else 0
        )

        if (
            current_lines
            and current_length + added_length
            > maximum_length
        ):
            chunks.append("\n".join(current_lines))
            current_lines = []
            current_length = 0

        current_lines.append(line)
        current_length += len(line) + (
            1 if len(current_lines) > 1 else 0
        )

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks


def build_trigger_list_embed(
    status: BroadcasterPanelStatus,
    triggers: list[Trigger],
    *,
    selected_trigger_id: int | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=(
            f"Title triggers — {status.twitch_login}"
        ),
        description=(
            "Title triggers send a Twitch chat message "
            "when the stream title matches an expression."
            "\n\n"
            "A lower priority number wins when multiple "
            "triggers match."
        ),
        color=discord.Color.blurple(),
    )

    if not triggers:
        embed.add_field(
            name="No triggers configured",
            value=(
                "Press **Add trigger** to create the "
                "first title trigger."
            ),
            inline=False,
        )
    else:
        summary_lines: list[str] = []

        for trigger in triggers:
            state_icon = (
                "🟢" if trigger.enabled else "⚫"
            )
            match_text = (
                "contains"
                if trigger.match_type
                is TriggerMatchType.CONTAINS
                else "exact"
            )
            selected_icon = (
                "👉 "
                if trigger.trigger_id
                == selected_trigger_id
                else ""
            )

            summary_lines.append(
                f"{selected_icon}{state_icon} "
                f"`#{trigger.trigger_id}` "
                f"**{_short_text(trigger.name, 50)}** · "
                f"{match_text} "
                f"`{_short_text(trigger.expression, 60)}` · "
                f"priority `{trigger.priority}`"
            )

        for index, chunk in enumerate(
            _chunk_lines(summary_lines)
        ):
            embed.add_field(
                name=(
                    "Configured triggers"
                    if index == 0
                    else "Configured triggers continued"
                ),
                value=chunk,
                inline=False,
            )

        selected_trigger = find_trigger(
            triggers,
            selected_trigger_id,
        )

        if selected_trigger is None:
            embed.add_field(
                name="Trigger controls",
                value=(
                    "Select a trigger below to view its "
                    "full response and enable the Edit, "
                    "Enable/Disable, and Delete controls."
                ),
                inline=False,
            )
        else:
            enabled_text = (
                "🟢 Enabled"
                if selected_trigger.enabled
                else "⚫ Disabled"
            )
            match_text = (
                "contains"
                if selected_trigger.match_type
                is TriggerMatchType.CONTAINS
                else "exactly matches"
            )
            pin_text = (
                "Yes"
                if selected_trigger.pin_message
                else "No"
            )

            embed.add_field(
                name=(
                    f"Selected trigger "
                    f"#{selected_trigger.trigger_id} — "
                    f"{selected_trigger.name}"
                ),
                value=(
                    f"{enabled_text}\n"
                    f"Title {match_text}: "
                    f"`{selected_trigger.expression}`\n"
                    f"Priority: "
                    f"`{selected_trigger.priority}` · "
                    f"Pin message: `{pin_text}`\n"
                    "Response: "
                    f"{selected_trigger.response_message}"
                ),
                inline=False,
            )

    embed.set_footer(
        text=(
            f"{len(triggers)} of 25 triggers configured"
        )
    )

    return embed


def find_trigger(
    triggers: list[Trigger],
    trigger_id: int | None,
) -> Trigger | None:
    if trigger_id is None:
        return None

    for trigger in triggers:
        if trigger.trigger_id == trigger_id:
            return trigger

    return None


def build_trigger_options(
    triggers: list[Trigger],
) -> list[discord.SelectOption]:
    options = []

    for trigger in triggers:
        state = "enabled" if trigger.enabled else "disabled"
        options.append(
            discord.SelectOption(
                label=trigger.name[:100],
                value=str(trigger.trigger_id),
                description=(
                    f"#{trigger.trigger_id} · {state} · "
                    f"priority {trigger.priority}"
                )[:100],
            )
        )

    return options


class AddTriggerModal(
    discord.ui.Modal,
    title="Add title trigger",
):
    name_input = discord.ui.TextInput(
        label="Trigger name",
        placeholder="Example: Solo Mode",
        min_length=1,
        max_length=50,
    )

    expression_input = discord.ui.TextInput(
        label="Title expression",
        placeholder="Example: solo",
        min_length=1,
        max_length=200,
    )

    response_input = discord.ui.TextInput(
        label="Twitch response message",
        placeholder=(
            "The streamer is currently playing solo."
        ),
        style=discord.TextStyle.paragraph,
        min_length=1,
        max_length=450,
    )

    match_type_input = discord.ui.TextInput(
        label="Match type: contains or exact",
        default="contains",
        min_length=5,
        max_length=8,
    )

    priority_input = discord.ui.TextInput(
        label="Priority: 0-10000",
        default="100",
        required=False,
        max_length=5,
    )

    def __init__(
        self,
        controller: "DiscordTriggerManagementController",
        twitch_user_id: str,
    ) -> None:
        super().__init__(timeout=300)
        self.controller = controller
        self.twitch_user_id = twitch_user_id

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await self.controller.create_trigger(
            interaction,
            twitch_user_id=self.twitch_user_id,
            name=str(self.name_input.value),
            expression=str(
                self.expression_input.value
            ),
            response_message=str(
                self.response_input.value
            ),
            match_type_text=str(
                self.match_type_input.value
            ),
            priority_text=str(
                self.priority_input.value
            ),
        )


class EditTriggerModal(
    discord.ui.Modal,
    title="Edit title trigger",
):
    name_input = discord.ui.TextInput(
        label="Trigger name",
        min_length=1,
        max_length=50,
    )

    expression_input = discord.ui.TextInput(
        label="Title expression",
        min_length=1,
        max_length=200,
    )

    response_input = discord.ui.TextInput(
        label="Twitch response message",
        style=discord.TextStyle.paragraph,
        min_length=1,
        max_length=450,
    )

    match_type_input = discord.ui.TextInput(
        label="Match type: contains or exact",
        min_length=5,
        max_length=8,
    )

    priority_input = discord.ui.TextInput(
        label="Priority: 0-10000",
        required=False,
        max_length=5,
    )

    def __init__(
        self,
        controller: "DiscordTriggerManagementController",
        twitch_user_id: str,
        trigger: Trigger,
    ) -> None:
        super().__init__(timeout=300)
        self.controller = controller
        self.twitch_user_id = twitch_user_id
        self.trigger = trigger
        self.name_input.default = trigger.name
        self.expression_input.default = trigger.expression
        self.response_input.default = trigger.response_message
        self.match_type_input.default = (
            trigger.match_type.value
        )
        self.priority_input.default = str(trigger.priority)

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await self.controller.update_trigger(
            interaction,
            twitch_user_id=self.twitch_user_id,
            trigger_id=int(self.trigger.trigger_id),
            name=str(self.name_input.value),
            expression=str(
                self.expression_input.value
            ),
            response_message=str(
                self.response_input.value
            ),
            match_type_text=str(
                self.match_type_input.value
            ),
            priority_text=str(
                self.priority_input.value
            ),
            pin_message=self.trigger.pin_message,
            enabled=self.trigger.enabled,
        )


class TriggerSelect(discord.ui.Select):
    def __init__(
        self,
        controller: "DiscordTriggerManagementController",
        status: BroadcasterPanelStatus,
        triggers: list[Trigger],
        selected_trigger_id: int | None,
    ) -> None:
        super().__init__(
            placeholder="Select a trigger",
            min_values=1,
            max_values=1,
            options=build_trigger_options(triggers),
            row=0,
        )
        self.controller = controller
        self.status = status

        if selected_trigger_id is not None:
            selected_value = str(selected_trigger_id)
            for option in self.options:
                option.default = (
                    option.value == selected_value
                )

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await self.controller.select_trigger(
            interaction,
            self.status.twitch_user_id,
            parse_trigger_id(self.values[0]),
        )


class TriggerListView(discord.ui.View):
    """Short-lived private title-trigger controls."""

    def __init__(
        self,
        controller: "DiscordTriggerManagementController",
        status: BroadcasterPanelStatus,
        triggers: list[Trigger],
        *,
        selected_trigger_id: int | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self.controller = controller
        self.status = status
        self.triggers = triggers
        self.selected_trigger_id = selected_trigger_id

        if triggers:
            self.add_item(
                TriggerSelect(
                    controller,
                    status,
                    triggers,
                    selected_trigger_id,
                )
            )

        selected_trigger = find_trigger(
            triggers,
            selected_trigger_id,
        )
        has_selection = selected_trigger is not None

        self.edit_button.disabled = not has_selection
        self.toggle_button.disabled = not has_selection
        self.delete_button.disabled = not has_selection

        if selected_trigger is not None:
            if selected_trigger.enabled:
                self.toggle_button.label = "Disable"
                self.toggle_button.style = (
                    discord.ButtonStyle.secondary
                )
                self.toggle_button.emoji = "⏸️"
            else:
                self.toggle_button.label = "Enable"
                self.toggle_button.style = (
                    discord.ButtonStyle.success
                )
                self.toggle_button.emoji = "▶️"

    @discord.ui.button(
        label="Add trigger",
        style=discord.ButtonStyle.success,
        emoji="➕",
        row=1,
    )
    async def add_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self.controller.can_manage(
            interaction.user.id,
            self.status,
        ):
            await interaction.response.send_message(
                "You cannot manage this broadcaster's "
                "triggers.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            AddTriggerModal(
                self.controller,
                self.status.twitch_user_id,
            )
        )

    @discord.ui.button(
        label="Edit",
        style=discord.ButtonStyle.primary,
        emoji="✏️",
        row=1,
    )
    async def edit_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.controller.request_edit(
            interaction,
            self.status.twitch_user_id,
            self.selected_trigger_id,
        )

    @discord.ui.button(
        label="Disable",
        style=discord.ButtonStyle.secondary,
        emoji="⏸️",
        row=1,
    )
    async def toggle_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.controller.toggle_trigger(
            interaction,
            self.status.twitch_user_id,
            self.selected_trigger_id,
        )

    @discord.ui.button(
        label="Delete",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
        row=1,
    )
    async def delete_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.controller.request_delete(
            interaction,
            self.status.twitch_user_id,
            self.selected_trigger_id,
        )

    @discord.ui.button(
        label="Refresh list",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        row=2,
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.controller.refresh_list(
            interaction,
            self.status.twitch_user_id,
            selected_trigger_id=self.selected_trigger_id,
        )


class DeleteTriggerConfirmationView(discord.ui.View):
    """Short-lived confirmation for trigger deletion."""

    def __init__(
        self,
        *,
        controller: "DiscordTriggerManagementController",
        twitch_user_id: str,
        trigger_id: int,
        trigger_name: str,
        requested_by_user_id: int,
    ) -> None:
        super().__init__(timeout=60)
        self.controller = controller
        self.twitch_user_id = twitch_user_id
        self.trigger_id = trigger_id
        self.trigger_name = trigger_name
        self.requested_by_user_id = int(
            requested_by_user_id
        )

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
            "Only the person who started this deletion "
            "can confirm it.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(
        label="Delete trigger",
        style=discord.ButtonStyle.danger,
        emoji="✅",
    )
    async def confirm_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.controller.confirm_delete(
            interaction,
            twitch_user_id=self.twitch_user_id,
            trigger_id=self.trigger_id,
            trigger_name=self.trigger_name,
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
            content="Trigger deletion was cancelled.",
            view=None,
        )


class DiscordTriggerManagementController:
    """Connects private Discord controls to triggers."""

    def __init__(
        self,
        *,
        management_service: TriggerManagementService,
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
        user_id = str(discord_user_id)

        return user_id in {
            str(status.owner_discord_user_id),
            str(self.developer_discord_user_id),
        }

    async def show_triggers(
        self,
        interaction: discord.Interaction,
        twitch_user_id: str,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        loaded = await self._load_authorized(
            interaction,
            twitch_user_id,
        )

        if loaded is None:
            return

        status, triggers = loaded

        await self._edit_trigger_list_response(
            interaction,
            status,
            triggers,
            content=None,
        )

    async def refresh_list(
        self,
        interaction: discord.Interaction,
        twitch_user_id: str,
        *,
        selected_trigger_id: int | None = None,
    ) -> None:
        await interaction.response.defer()

        loaded = await self._load_authorized(
            interaction,
            twitch_user_id,
        )

        if loaded is None:
            return

        status, triggers = loaded

        if (
            selected_trigger_id is not None
            and find_trigger(triggers, selected_trigger_id)
            is None
        ):
            selected_trigger_id = None

        await self._edit_trigger_list_response(
            interaction,
            status,
            triggers,
            content=None,
            selected_trigger_id=selected_trigger_id,
        )

    async def select_trigger(
        self,
        interaction: discord.Interaction,
        twitch_user_id: str,
        trigger_id: int,
    ) -> None:
        await interaction.response.defer()

        loaded = await self._load_authorized(
            interaction,
            twitch_user_id,
        )

        if loaded is None:
            return

        status, triggers = loaded

        if find_trigger(triggers, trigger_id) is None:
            await interaction.edit_original_response(
                content=(
                    "That trigger is no longer available. "
                    "Refresh the list and try again."
                ),
                embed=build_trigger_list_embed(
                    status,
                    triggers,
                ),
                view=TriggerListView(
                    self,
                    status,
                    triggers,
                ),
            )
            return

        await self._edit_trigger_list_response(
            interaction,
            status,
            triggers,
            content=None,
            selected_trigger_id=trigger_id,
        )

    async def request_edit(
        self,
        interaction: discord.Interaction,
        twitch_user_id: str,
        selected_trigger_id: int | None,
    ) -> None:
        if selected_trigger_id is None:
            await interaction.response.send_message(
                "Select a trigger before editing.",
                ephemeral=True,
            )
            return

        try:
            status = (
                await self.status_service
                .get_for_broadcaster(twitch_user_id)
            )

            if not self.can_manage(
                interaction.user.id,
                status,
            ):
                await interaction.response.send_message(
                    "You cannot manage this broadcaster's "
                    "triggers.",
                    ephemeral=True,
                )
                return

            triggers = (
                await self.management_service
                .list_triggers(twitch_user_id)
            )
            trigger = find_trigger(
                triggers,
                selected_trigger_id,
            )

            if trigger is None:
                await interaction.response.send_message(
                    "That trigger is no longer available. "
                    "Refresh the list and try again.",
                    ephemeral=True,
                )
                return

            await interaction.response.send_modal(
                EditTriggerModal(
                    self,
                    twitch_user_id,
                    trigger,
                )
            )

        except Exception:
            logger.exception(
                "Failed to open title trigger edit modal "
                "for Twitch user %s.",
                twitch_user_id,
            )
            await interaction.response.send_message(
                "ChimeBuddy could not open this trigger "
                "for editing.",
                ephemeral=True,
            )

    async def create_trigger(
        self,
        interaction: discord.Interaction,
        *,
        twitch_user_id: str,
        name: str,
        expression: str,
        response_message: str,
        match_type_text: str,
        priority_text: str,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            status = (
                await self.status_service
                .get_for_broadcaster(twitch_user_id)
            )

            if not self.can_manage(
                interaction.user.id,
                status,
            ):
                await interaction.edit_original_response(
                    content=(
                        "You cannot manage this "
                        "broadcaster's triggers."
                    ),
                    embed=None,
                    view=None,
                )
                return

            match_type = parse_match_type(
                match_type_text
            )
            priority = parse_priority(
                priority_text
            )

            created = (
                await self.management_service
                .create_trigger(
                    twitch_user_id,
                    name=name,
                    expression=expression,
                    response_message=response_message,
                    match_type=match_type,
                    priority=priority,
                    pin_message=True,
                    enabled=True,
                )
            )

            triggers = (
                await self.management_service
                .list_triggers(twitch_user_id)
            )

        except (
            ManagedBroadcasterNotFoundError,
            TriggerValidationError,
            TriggerNameConflictError,
            TriggerLimitReachedError,
        ) as exc:
            await interaction.edit_original_response(
                content=f"Trigger not created: {exc}",
                embed=None,
                view=None,
            )
            return

        except Exception:
            logger.exception(
                "Failed to create title trigger for "
                "Twitch user %s.",
                twitch_user_id,
            )

            await interaction.edit_original_response(
                content=(
                    "ChimeBuddy could not create the "
                    "trigger."
                ),
                embed=None,
                view=None,
            )
            return

        await self._edit_trigger_list_response(
            interaction,
            status,
            triggers,
            content=(
                f"Trigger **{created.name}** was created."
            ),
            selected_trigger_id=created.trigger_id,
        )

    async def update_trigger(
        self,
        interaction: discord.Interaction,
        *,
        twitch_user_id: str,
        trigger_id: int,
        name: str,
        expression: str,
        response_message: str,
        match_type_text: str,
        priority_text: str,
        pin_message: bool,
        enabled: bool,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            status = (
                await self.status_service
                .get_for_broadcaster(twitch_user_id)
            )

            if not self.can_manage(
                interaction.user.id,
                status,
            ):
                await interaction.edit_original_response(
                    content=(
                        "You cannot manage this "
                        "broadcaster's triggers."
                    ),
                    embed=None,
                    view=None,
                )
                return

            updated = (
                await self.management_service
                .update_trigger(
                    twitch_user_id,
                    trigger_id,
                    name=name,
                    expression=expression,
                    response_message=response_message,
                    match_type=parse_match_type(
                        match_type_text
                    ),
                    pin_message=pin_message,
                    priority=parse_priority(
                        priority_text
                    ),
                    enabled=enabled,
                )
            )
            triggers = (
                await self.management_service
                .list_triggers(twitch_user_id)
            )

        except (
            ManagedTriggerNotFoundError,
            TriggerBusyError,
            TriggerValidationError,
            TriggerNameConflictError,
        ) as exc:
            await interaction.edit_original_response(
                content=f"Trigger not updated: {exc}",
                embed=None,
                view=None,
            )
            return

        except Exception:
            logger.exception(
                "Failed to update title trigger %s for "
                "Twitch user %s.",
                trigger_id,
                twitch_user_id,
            )
            await interaction.edit_original_response(
                content=(
                    "ChimeBuddy could not update the "
                    "trigger."
                ),
                embed=None,
                view=None,
            )
            return

        await self._edit_trigger_list_response(
            interaction,
            status,
            triggers,
            content=(
                f"Trigger **{updated.name}** was updated."
            ),
            selected_trigger_id=updated.trigger_id,
        )

    async def toggle_trigger(
        self,
        interaction: discord.Interaction,
        twitch_user_id: str,
        selected_trigger_id: int | None,
    ) -> None:
        if selected_trigger_id is None:
            await interaction.response.send_message(
                "Select a trigger before changing it.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            status = (
                await self.status_service
                .get_for_broadcaster(twitch_user_id)
            )

            if not self.can_manage(
                interaction.user.id,
                status,
            ):
                await interaction.edit_original_response(
                    content=(
                        "You cannot manage this "
                        "broadcaster's triggers."
                    ),
                    embed=None,
                    view=None,
                )
                return

            triggers = (
                await self.management_service
                .list_triggers(twitch_user_id)
            )
            current = find_trigger(
                triggers,
                selected_trigger_id,
            )

            if current is None:
                raise ManagedTriggerNotFoundError(
                    "The trigger does not exist."
                )

            updated = (
                await self.management_service
                .set_enabled(
                    twitch_user_id,
                    current.trigger_id,
                    not current.enabled,
                )
            )
            triggers = (
                await self.management_service
                .list_triggers(twitch_user_id)
            )

        except (
            ManagedTriggerNotFoundError,
            TriggerValidationError,
        ) as exc:
            await interaction.edit_original_response(
                content=f"Trigger not changed: {exc}",
                embed=None,
                view=None,
            )
            return

        except Exception:
            logger.exception(
                "Failed to toggle title trigger %s for "
                "Twitch user %s.",
                selected_trigger_id,
                twitch_user_id,
            )
            await interaction.edit_original_response(
                content=(
                    "ChimeBuddy could not change the "
                    "trigger."
                ),
                embed=None,
                view=None,
            )
            return

        state_text = (
            "enabled" if updated.enabled else "disabled"
        )
        await self._edit_trigger_list_response(
            interaction,
            status,
            triggers,
            content=(
                f"Trigger **{updated.name}** was "
                f"{state_text}."
            ),
            selected_trigger_id=updated.trigger_id,
        )

    async def request_delete(
        self,
        interaction: discord.Interaction,
        twitch_user_id: str,
        selected_trigger_id: int | None,
    ) -> None:
        if selected_trigger_id is None:
            await interaction.response.send_message(
                "Select a trigger before deleting.",
                ephemeral=True,
            )
            return

        try:
            status = (
                await self.status_service
                .get_for_broadcaster(twitch_user_id)
            )

            if not self.can_manage(
                interaction.user.id,
                status,
            ):
                await interaction.response.send_message(
                    "You cannot manage this broadcaster's "
                    "triggers.",
                    ephemeral=True,
                )
                return

            triggers = (
                await self.management_service
                .list_triggers(twitch_user_id)
            )
            trigger = find_trigger(
                triggers,
                selected_trigger_id,
            )

            if trigger is None:
                await interaction.response.send_message(
                    "That trigger is no longer available. "
                    "Refresh the list and try again.",
                    ephemeral=True,
                )
                return

            await interaction.response.send_message(
                (
                    "Delete title trigger "
                    f"**{trigger.name}**? This cannot be "
                    "undone. Active triggers must finish "
                    "cleanup before deletion can succeed."
                ),
                view=DeleteTriggerConfirmationView(
                    controller=self,
                    twitch_user_id=twitch_user_id,
                    trigger_id=int(trigger.trigger_id),
                    trigger_name=trigger.name,
                    requested_by_user_id=(
                        interaction.user.id
                    ),
                ),
                ephemeral=True,
            )

        except Exception:
            logger.exception(
                "Failed to request deletion for title "
                "trigger %s on Twitch user %s.",
                selected_trigger_id,
                twitch_user_id,
            )
            await interaction.response.send_message(
                "ChimeBuddy could not prepare that "
                "deletion.",
                ephemeral=True,
            )

    async def confirm_delete(
        self,
        interaction: discord.Interaction,
        *,
        twitch_user_id: str,
        trigger_id: int,
        trigger_name: str,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            status = (
                await self.status_service
                .get_for_broadcaster(twitch_user_id)
            )

            if not self.can_manage(
                interaction.user.id,
                status,
            ):
                await interaction.edit_original_response(
                    content=(
                        "You cannot manage this "
                        "broadcaster's triggers."
                    ),
                    view=None,
                )
                return

            await self.management_service.delete_trigger(
                twitch_user_id,
                trigger_id,
            )

        except (
            ManagedTriggerNotFoundError,
            TriggerBusyError,
            TriggerValidationError,
        ) as exc:
            await interaction.edit_original_response(
                content=f"Trigger not deleted: {exc}",
                view=None,
            )
            return

        except Exception:
            logger.exception(
                "Failed to delete title trigger %s for "
                "Twitch user %s.",
                trigger_id,
                twitch_user_id,
            )
            await interaction.edit_original_response(
                content=(
                    "ChimeBuddy could not delete the "
                    "trigger."
                ),
                view=None,
            )
            return

        await interaction.edit_original_response(
            content=(
                f"Trigger **{trigger_name}** was deleted. "
                "Press **Refresh list** in the trigger "
                "panel to reload."
            ),
            view=None,
        )

    async def _load_authorized(
        self,
        interaction: discord.Interaction,
        twitch_user_id: str,
    ) -> tuple[
        BroadcasterPanelStatus,
        list[Trigger],
    ] | None:
        try:
            status = (
                await self.status_service
                .get_for_broadcaster(twitch_user_id)
            )

            if not self.can_manage(
                interaction.user.id,
                status,
            ):
                await interaction.edit_original_response(
                    content=(
                        "You cannot manage this "
                        "broadcaster's triggers."
                    ),
                    embed=None,
                    view=None,
                )
                return None

            triggers = (
                await self.management_service
                .list_triggers(twitch_user_id)
            )

            return status, triggers

        except BroadcasterPanelNotFoundError:
            await interaction.edit_original_response(
                content=(
                    "This broadcaster panel is no longer "
                    "registered."
                ),
                embed=None,
                view=None,
            )
            return None

        except Exception:
            logger.exception(
                "Failed to load title triggers for "
                "Twitch user %s.",
                twitch_user_id,
            )

            await interaction.edit_original_response(
                content=(
                    "ChimeBuddy could not load the title "
                    "triggers."
                ),
                embed=None,
                view=None,
            )
            return None

    async def _edit_trigger_list_response(
        self,
        interaction: discord.Interaction,
        status: BroadcasterPanelStatus,
        triggers: list[Trigger],
        *,
        content: str | None,
        selected_trigger_id: int | None = None,
    ) -> None:
        await interaction.edit_original_response(
            content=content,
            embed=build_trigger_list_embed(
                status,
                triggers,
                selected_trigger_id=selected_trigger_id,
            ),
            view=TriggerListView(
                self,
                status,
                triggers,
                selected_trigger_id=selected_trigger_id,
            ),
        )
