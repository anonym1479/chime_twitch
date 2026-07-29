from __future__ import annotations

import logging
import re

import discord

from chimebuddy.models import (
    BroadcasterPanel,
    BroadcasterRequest,
)
from chimebuddy.repositories import (
    AppSettingsRepository,
)
from chimebuddy.services import (
    DiscordPanelLocation,
)


logger = logging.getLogger(
    "chimebuddy.discord.provisioning"
)

BROADCASTER_CATEGORY_SETTING = (
    "discord.broadcaster_category_id"
)

BROADCASTER_CATEGORY_NAME = (
    "ChimeBuddy Broadcasters"
)


def normalize_channel_name(
    twitch_login: str,
) -> str:
    normalized = (
        str(twitch_login)
        .strip()
        .casefold()
        .replace("_", "-")
    )

    normalized = re.sub(
        r"[^a-z0-9-]+",
        "-",
        normalized,
    )

    normalized = re.sub(
        r"-+",
        "-",
        normalized,
    ).strip("-")

    if not normalized:
        return "twitch-channel"

    return normalized[:90]


def opening_panel_marker(
    request_id: int,
) -> str:
    return (
        "ChimeBuddy broadcaster panel | "
        f"request #{int(request_id)}"
    )


def build_broadcaster_panel_embed(
    request: BroadcasterRequest,
    twitch_login: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"ChimeBuddy — {twitch_login}",
        description=(
            "Welcome to your private ChimeBuddy "
            "administration channel.\n\n"
            "Only you, the ChimeBuddy bot, and the "
            "server owner can access this channel."
        ),
        color=discord.Color.green(),
    )

    embed.add_field(
        name="Twitch channel",
        value=(
            f"`{twitch_login}`\n"
            f"ID: `{request.twitch_user_id}`"
        ),
        inline=True,
    )

    embed.add_field(
        name="Discord owner",
        value=(
            f"<@{request.discord_user_id}>\n"
            f"ID: `{request.discord_user_id}`"
        ),
        inline=True,
    )

    embed.add_field(
        name="Status",
        value=(
            "Your broadcaster account is being "
            "activated."
        ),
        inline=False,
    )

    embed.add_field(
        name="What happens next?",
        value=(
            "Channel-management controls, trigger "
            "settings, and other ChimeBuddy options "
            "will be added to this panel as development "
            "continues."
        ),
        inline=False,
    )

    embed.set_footer(
        text=opening_panel_marker(
            request.request_id
        )
    )

    return embed


class DiscordBroadcasterPanelGateway:
    """Creates recoverable private broadcaster channels."""

    def __init__(
        self,
        *,
        settings_repository: AppSettingsRepository,
        discord_guild_id: int,
    ) -> None:
        self.settings_repository = (
            settings_repository
        )
        self.discord_guild_id = int(
            discord_guild_id
        )
        self.client: discord.Client | None = None

    def bind_client(
        self,
        client: discord.Client,
    ) -> None:
        self.client = client

    async def ensure_panel(
        self,
        *,
        request: BroadcasterRequest,
        twitch_login: str,
        existing_panel: BroadcasterPanel | None,
    ) -> DiscordPanelLocation:
        client = self._require_client()

        guild = client.get_guild(
            self.discord_guild_id
        )

        if guild is None:
            raise RuntimeError(
                "The configured Discord guild is not "
                "available in the bot cache."
            )

        member = guild.get_member(
            int(request.discord_user_id)
        )

        if member is None:
            member = await guild.fetch_member(
                int(request.discord_user_id)
            )

        bot_member = guild.me

        if bot_member is None:
            if client.user is None:
                raise RuntimeError(
                    "The Discord bot user is unavailable."
                )

            bot_member = await guild.fetch_member(
                client.user.id
            )

        category = await self._ensure_category(
            guild,
            bot_member,
        )

        channel = await self._ensure_channel(
            guild=guild,
            category=category,
            member=member,
            bot_member=bot_member,
            request=request,
            twitch_login=twitch_login,
            existing_panel=existing_panel,
        )

        message = await self._ensure_opening_message(
            channel=channel,
            request=request,
            twitch_login=twitch_login,
        )

        return DiscordPanelLocation(
            discord_guild_id=str(guild.id),
            discord_channel_id=str(channel.id),
            opening_message_id=str(message.id),
        )

    async def _ensure_category(
        self,
        guild: discord.Guild,
        bot_member: discord.Member,
    ) -> discord.CategoryChannel:
        configured_category_id = (
            await self.settings_repository
            .get_positive_int(
                BROADCASTER_CATEGORY_SETTING
            )
        )

        if configured_category_id is not None:
            configured_category = guild.get_channel(
                configured_category_id
            )

            if isinstance(
                configured_category,
                discord.CategoryChannel,
            ):
                return configured_category

        existing_category = discord.utils.get(
            guild.categories,
            name=BROADCASTER_CATEGORY_NAME,
        )

        if existing_category is not None:
            await self.settings_repository.set(
                BROADCASTER_CATEGORY_SETTING,
                str(existing_category.id),
            )

            return existing_category

        overwrites = {
            guild.default_role: (
                discord.PermissionOverwrite(
                    view_channel=False,
                )
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                manage_channels=True,
            ),
        }

        category = await guild.create_category(
            BROADCASTER_CATEGORY_NAME,
            overwrites=overwrites,
            reason=(
                "ChimeBuddy broadcaster provisioning."
            ),
        )

        await self.settings_repository.set(
            BROADCASTER_CATEGORY_SETTING,
            str(category.id),
        )

        logger.info(
            "Created Discord broadcaster category %s.",
            category.id,
        )

        return category

    async def _ensure_channel(
        self,
        *,
        guild: discord.Guild,
        category: discord.CategoryChannel,
        member: discord.Member,
        bot_member: discord.Member,
        request: BroadcasterRequest,
        twitch_login: str,
        existing_panel: BroadcasterPanel | None,
    ) -> discord.TextChannel:
        topic = self._channel_topic(request)
        channel = None

        if existing_panel is not None:
            existing_channel_id = int(
                existing_panel.discord_channel_id
            )

            cached_channel = guild.get_channel(
                existing_channel_id
            )

            if cached_channel is None:
                fetched_channel = (
                    await self._require_client()
                    .fetch_channel(
                        existing_channel_id
                    )
                )
                cached_channel = fetched_channel

            if not isinstance(
                cached_channel,
                discord.TextChannel,
            ):
                raise RuntimeError(
                    "The stored broadcaster channel "
                    "is not a Discord text channel."
                )

            if cached_channel.guild.id != guild.id:
                raise RuntimeError(
                    "The stored broadcaster channel "
                    "belongs to another Discord guild."
                )

            channel = cached_channel

        if channel is None:
            channel = discord.utils.find(
                lambda candidate: (
                    isinstance(
                        candidate,
                        discord.TextChannel,
                    )
                    and candidate.topic is not None
                    and topic in candidate.topic
                ),
                guild.text_channels,
            )

        overwrites = {
            guild.default_role: (
                discord.PermissionOverwrite(
                    view_channel=False,
                )
            ),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                embed_links=True,
                attach_files=True,
                use_application_commands=True,
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                manage_channels=True,
            ),
        }

        if channel is None:
            channel = await guild.create_text_channel(
                normalize_channel_name(
                    twitch_login
                ),
                category=category,
                topic=topic,
                overwrites=overwrites,
                reason=(
                    "Approved ChimeBuddy broadcaster "
                    f"request #{request.request_id}."
                ),
            )

            logger.info(
                "Created private Discord channel %s "
                "for broadcaster request %s.",
                channel.id,
                request.request_id,
            )

        else:
            await channel.edit(
                category=category,
                topic=topic,
                overwrites=overwrites,
                reason=(
                    "Recovering ChimeBuddy broadcaster "
                    f"request #{request.request_id}."
                ),
            )

        return channel

    async def _ensure_opening_message(
        self,
        *,
        channel: discord.TextChannel,
        request: BroadcasterRequest,
        twitch_login: str,
    ) -> discord.Message:
        marker = opening_panel_marker(
            request.request_id
        )

        async for message in channel.history(
            limit=50
        ):
            if not message.embeds:
                continue

            for embed in message.embeds:
                footer = embed.footer

                if (
                    footer is not None
                    and footer.text == marker
                ):
                    return message

        message = await channel.send(
            embed=build_broadcaster_panel_embed(
                request,
                twitch_login,
            ),
            allowed_mentions=(
                discord.AllowedMentions.none()
            ),
        )

        logger.info(
            "Posted opening panel message %s for "
            "broadcaster request %s.",
            message.id,
            request.request_id,
        )

        return message

    @staticmethod
    def _channel_topic(
        request: BroadcasterRequest,
    ) -> str:
        return (
            "ChimeBuddy broadcaster request "
            f"#{request.request_id} | "
            f"Twitch ID {request.twitch_user_id}"
        )

    def _require_client(
        self,
    ) -> discord.Client:
        if self.client is None:
            raise RuntimeError(
                "The Discord provisioning gateway "
                "has not been connected to a client."
            )

        return self.client