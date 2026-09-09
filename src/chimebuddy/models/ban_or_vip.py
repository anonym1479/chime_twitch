from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChannelPointRedemption:
    redemption_id: str
    broadcaster_twitch_user_id: str
    broadcaster_login: str
    user_twitch_user_id: str
    user_login: str
    user_display_name: str
    reward_id: str
    reward_title: str


@dataclass(frozen=True, slots=True)
class RewardVipGrant:
    redemption_id: str
    broadcaster_twitch_user_id: str
    user_twitch_user_id: str
    expires_at: int
    active: bool = True
