import asyncio
import logging

import discord

from chimebuddy.repositories.panel_repository import BroadcasterPanelRepository
from chimebuddy.repositories.reward_action_log_repository import RewardActionLogRepository


logger = logging.getLogger("chimebuddy.discord.ban_or_vip_log")


class DiscordBanOrVipLogger:
    """Delivers completed reward actions to one private thread per dashboard."""

    def __init__(self, *, panel_repository: BroadcasterPanelRepository,
                 log_repository: RewardActionLogRepository) -> None:
        self.panel_repository = panel_repository
        self.log_repository = log_repository

    async def run(self, client: discord.Client) -> None:
        while not client.is_closed():
            try:
                await self.deliver_pending(client)
            except Exception:
                logger.exception("Ban or VIP Discord log delivery failed.")
            await asyncio.sleep(15)

    async def deliver_pending(self, client: discord.Client) -> None:
        for log in await self.log_repository.list_undelivered():
            thread = await self._get_or_create_thread(client, log.broadcaster_twitch_user_id)
            await thread.send(
                f"**Ban vagy VIP**\n"
                f"Twitch: `{log.user_login}`\n"
                f"Eredmény: **{log.outcome}**\n"
                f"VIP esély: `{log.vip_chance:.1f}%`\n"
                f"Időpont: {log.occurred_at}\n"
                f"Redemption ID: `{log.redemption_id}`",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await self.log_repository.mark_delivered(log.redemption_id)

    async def _get_or_create_thread(self, client: discord.Client, broadcaster_id: str):
        thread_id = await self.log_repository.get_thread_id(broadcaster_id)
        if thread_id is not None:
            try:
                channel = await client.fetch_channel(int(thread_id))
                if isinstance(channel, discord.Thread):
                    return channel
            except discord.HTTPException:
                pass
        panel = await self.panel_repository.get_for_broadcaster(broadcaster_id)
        if panel is None:
            raise RuntimeError("No Discord dashboard exists for this broadcaster.")
        parent = await client.fetch_channel(int(panel.discord_channel_id))
        if not isinstance(parent, discord.TextChannel):
            raise RuntimeError("Broadcaster dashboard is not a text channel.")
        thread = await parent.create_thread(
            name="Ban/VIP Log",
            type=discord.ChannelType.public_thread,
        )
        await self.log_repository.save_thread_id(broadcaster_id, str(thread.id))
        return thread
