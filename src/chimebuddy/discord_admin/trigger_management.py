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


def build_trigger_list_embed(
    status: BroadcasterPanelStatus,
    triggers: list[Trigger],
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
        for trigger in triggers:
            enabled_text = (
                "🟢 Enabled"
                if trigger.enabled
                else "⚫ Disabled"
            )

            match_text = (
                "contains"
                if trigger.match_type
                is TriggerMatchType.CONTAINS
                else "exactly matches"
            )

            pin_text = (
                "Yes"
                if trigger.pin_message
                else "No"
            )

            embed.add_field(
                name=(
                    f"#{trigger.trigger_id} — "
                    f"{trigger.name}"
                ),
                value=(
                    f"{enabled_text}\n"
                    f"Title {match_text}: "
                    f"`{trigger.expression}`\n"
                    f"Priority: `{trigger.priority}` · "
                    f"Pin message: `{pin_text}`\n"
                    f"Response: {trigger.response_message}"
                ),
                inline=False,
            )

    embed.set_footer(
        text=(
            f"{len(triggers)} of 25 triggers configured"
        )
    )

    return embed


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


class TriggerListView(discord.ui.View):
    """Short-lived private title-trigger controls."""

    def __init__(
        self,
        controller: "DiscordTriggerManagementController",
        status: BroadcasterPanelStatus,
    ) -> None:
        super().__init__(timeout=300)
        self.controller = controller
        self.status = status

    @discord.ui.button(
        label="Add trigger",
        style=discord.ButtonStyle.success,
        emoji="➕",
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
        label="Refresh list",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.controller.refresh_list(
            interaction,
            self.status.twitch_user_id,
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

        await interaction.edit_original_response(
            content=None,
            embed=build_trigger_list_embed(
                status,
                triggers,
            ),
            view=TriggerListView(
                self,
                status,
            ),
        )

    async def refresh_list(
        self,
        interaction: discord.Interaction,
        twitch_user_id: str,
    ) -> None:
        await interaction.response.defer()

        loaded = await self._load_authorized(
            interaction,
            twitch_user_id,
        )

        if loaded is None:
            return

        status, triggers = loaded

        await interaction.edit_original_response(
            content=None,
            embed=build_trigger_list_embed(
                status,
                triggers,
            ),
            view=TriggerListView(
                self,
                status,
            ),
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

        await interaction.edit_original_response(
            content=(
                f"Trigger **{created.name}** was created."
            ),
            embed=build_trigger_list_embed(
                status,
                triggers,
            ),
            view=TriggerListView(
                self,
                status,
            ),
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