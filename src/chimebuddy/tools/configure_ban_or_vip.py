import argparse
import asyncio

from chimebuddy.config import load_settings
from chimebuddy.database import Database
from chimebuddy.repositories.app_settings_repository import AppSettingsRepository
from chimebuddy.services.ban_or_vip_service import BanOrVipService


async def configure(broadcaster_id: str, reward_id: str) -> None:
    settings = load_settings()
    database = Database(settings.database_path)
    await database.initialize()
    key = BanOrVipService.reward_setting_key(broadcaster_id)
    await AppSettingsRepository(database).set(key, reward_id)
    print(f"Configured Ban or VIP reward for broadcaster {broadcaster_id}.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bind a Twitch Channel Points reward to Ban or VIP."
    )
    parser.add_argument("broadcaster_id")
    parser.add_argument("reward_id")
    args = parser.parse_args()
    asyncio.run(configure(args.broadcaster_id, args.reward_id))


if __name__ == "__main__":
    main()
