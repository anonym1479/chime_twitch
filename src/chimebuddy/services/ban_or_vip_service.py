import asyncio
import logging
import random
import time
from dataclasses import dataclass

from chimebuddy.models.ban_or_vip import (
    ChannelPointRedemption,
    RewardVipGrant,
)
from chimebuddy.models.chat import TwitchChatMessage
from chimebuddy.twitch.helix_gateway import TwitchAPIError
from chimebuddy.repositories.app_settings_repository import AppSettingsRepository
from chimebuddy.repositories.reward_vip_repository import RewardVipRepository
from chimebuddy.repositories.reward_action_log_repository import RewardActionLogRepository
from chimebuddy.repositories.ban_or_vip_user_settings_repository import BanOrVipUserSettingsRepository


logger = logging.getLogger("chimebuddy.ban_or_vip")
VIP_DURATION_SECONDS = 7 * 24 * 60 * 60
TIMEOUT_DURATION_SECONDS = 24 * 60 * 60
LAST_WORD_SECONDS = 5 * 60


@dataclass(slots=True)
class LastWordWindow:
    broadcaster_twitch_user_id: str
    user_twitch_user_id: str
    spoke: asyncio.Event


class BanOrVipService:
    """In-memory coin toss and last-word flow; only VIP grants persist."""

    def __init__(
        self,
        *,
        settings_repository: AppSettingsRepository,
        vip_repository: RewardVipRepository,
        helix_gateway,
        action_log_repository: RewardActionLogRepository,
        user_settings_repository: BanOrVipUserSettingsRepository,
        rng: random.Random | None = None
    ) -> None:
        self.settings_repository = settings_repository
        self.vip_repository = vip_repository
        self.helix_gateway = helix_gateway
        self.action_log_repository = action_log_repository
        self.user_settings_repository = user_settings_repository
        self.rng = rng or random.Random()
        self._last_word_windows: dict[tuple[str, str], LastWordWindow] = {}
        self._redemption_ids: set[str] = set()

    @staticmethod
    def reward_setting_key(broadcaster_twitch_user_id: str) -> str:
        return f"ban_or_vip.reward_id.{str(broadcaster_twitch_user_id).strip()}"

    async def handle_redemption(self, redemption: ChannelPointRedemption) -> None:

        logger.info(
            "Handling Ban/VIP redemption: broadcaster=%s, "
            "user=%s, reward_id=%s, redemption_id=%s",
            redemption.broadcaster_twitch_user_id,
            redemption.user_login,
            redemption.reward_id,
            redemption.redemption_id,
        )

        reward_id = await self.settings_repository.get(
            self.reward_setting_key(redemption.broadcaster_twitch_user_id)
        )
        if reward_id != redemption.reward_id:
            logger.warning(
                "Ignoring redemption %s: reward ID mismatch. "
                "configured=%s, received=%s",
                redemption.redemption_id,
                reward_id,
                redemption.reward_id,
            )
            return
        if redemption.redemption_id in self._redemption_ids:
            return
        self._redemption_ids.add(redemption.redemption_id)
        try:
            await self.helix_gateway.send_message(
                redemption.broadcaster_twitch_user_id,
                f"🪙 @{redemption.user_login} feldobta az érmét!",
            )
            await asyncio.sleep(self.rng.randint(3, 20))

            vip_chance = await self.user_settings_repository.get(
                redemption.broadcaster_twitch_user_id,
                redemption.user_twitch_user_id,
            )

            if self.rng.random() < vip_chance / 100.0:
                await self._award_vip(
                    redemption,
                    vip_chance=vip_chance,
                )
            else:
                await self._last_word_then_timeout(
                    redemption,
                    vip_chance=vip_chance,
                )
        except Exception:
            logger.exception("Ban or VIP failed for redemption %s.", redemption.redemption_id)
            raise

    async def observe_chat_message(self, message: TwitchChatMessage) -> None:
        window = self._last_word_windows.get((
            message.broadcaster_twitch_user_id,
            message.chatter_twitch_user_id,
        ))
        if window is not None:
            window.spoke.set()

    async def _award_vip(
        self,
        redemption: ChannelPointRedemption,
        *,
        vip_chance: float,
    ) -> None:
        try:
            await self.helix_gateway.add_vip(
                redemption.broadcaster_twitch_user_id,
                redemption.user_twitch_user_id,
            )
        except TwitchAPIError as exc:
            if (
                exc.status == 422
                and exc.message
                == "The specified user is already a VIP of this channel."
            ):
                await self.helix_gateway.send_message(
                    redemption.broadcaster_twitch_user_id,
                    f"🪙 @{redemption.user_login}, "
                    "Már VIP vagy bolond! "
                    "Megúsztad. (egyelőre ;) )",
                )

                await self.action_log_repository.create_success(
                    redemption_id=redemption.redemption_id,
                    broadcaster_twitch_user_id=(
                        redemption.broadcaster_twitch_user_id
                    ),
                    user_login=redemption.user_login,
                    outcome="already_vip",
                    vip_chance=vip_chance,
                    action="already VIP",
                )

                logger.info(
                    "Redemption %s completed as already_vip "
                    "for user %s.",
                    redemption.redemption_id,
                    redemption.user_login,
                )
                return

            raise

        await self.vip_repository.create(RewardVipGrant(
            redemption_id=redemption.redemption_id,
            broadcaster_twitch_user_id=(
                redemption.broadcaster_twitch_user_id
            ),
            user_twitch_user_id=(
                redemption.user_twitch_user_id
            ),
            expires_at=int(time.time()) + VIP_DURATION_SECONDS,
        ))

        await self.helix_gateway.send_message(
            redemption.broadcaster_twitch_user_id,
            f"🪙 FEJ! @{redemption.user_login} 7 nap VIP-et nyert! "
            f"Használd egészséggel!",
        )

        await self.action_log_repository.create_success(
            redemption_id=redemption.redemption_id,
            broadcaster_twitch_user_id=(
                redemption.broadcaster_twitch_user_id
            ),
            user_login=redemption.user_login,
            outcome="FEJ",
            vip_chance=vip_chance,
            action="added VIP",
        )

    async def _last_word_then_timeout(
            self,
            redemption: ChannelPointRedemption,
            *,
            vip_chance: float,
    ) -> None:
        await self.helix_gateway.send_message(
            redemption.broadcaster_twitch_user_id,
            f"🔨 ÍRÁS! @{redemption.user_login}, Nyertél 24óra TO-t!",
        )

        await asyncio.sleep(2)

        await self.helix_gateway.send_message(
            redemption.broadcaster_twitch_user_id,
            f"🔨 @{redemption.user_login}, Szeretnél valamit mondani az utolsó szó jogán?",
        )

        key = (
            redemption.broadcaster_twitch_user_id,
            redemption.user_twitch_user_id
        )
        window = LastWordWindow(*key, asyncio.Event())
        self._last_word_windows[key] = window
        try:
            try:
                await asyncio.wait_for(window.spoke.wait(), LAST_WORD_SECONDS)
                await asyncio.sleep(5)
            except TimeoutError:
                pass
            await self.helix_gateway.timeout_user(
                redemption.broadcaster_twitch_user_id,
                redemption.user_twitch_user_id,
                TIMEOUT_DURATION_SECONDS,
                reason="ban_or_vip",
            )
            await self.helix_gateway.send_message(
                redemption.broadcaster_twitch_user_id,
                f"🔨 @{redemption.user_login} 24óra múlva találkozunk!",
            )
            await self.action_log_repository.create_success(
                redemption_id=redemption.redemption_id,
                broadcaster_twitch_user_id=redemption.broadcaster_twitch_user_id,
                user_login=redemption.user_login,
                outcome="ÍRÁS",
                vip_chance=vip_chance,
                action="Timeout (24h)",
            )
        finally:
            self._last_word_windows.pop(key, None)

    async def expire_vips_once(self) -> None:
        for grant in await self.vip_repository.list_expired_active(int(time.time())):
            await self.helix_gateway.remove_vip(
                grant.broadcaster_twitch_user_id,
                grant.user_twitch_user_id,
            )
            await self.vip_repository.deactivate(grant.redemption_id)

    async def vip_expiry_loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.expire_vips_once()
            except Exception:
                logger.exception("Reward VIP expiry check failed.")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=60)
            except TimeoutError:
                pass
