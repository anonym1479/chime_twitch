import argparse
import asyncio

from chimebuddy.config import load_settings
from chimebuddy.database import Database
from chimebuddy.repositories.ban_or_vip_user_settings_repository import (
    BanOrVipUserSettingsRepository,
)
from chimebuddy.twitch.runtime import create_twitch_runtime


async def configure(
    broadcaster_login: str,
    user_login: str,
    vip_chance: float,
) -> None:
    settings = load_settings()

    database = Database(settings.database_path)
    await database.initialize()

    repository = BanOrVipUserSettingsRepository(database)

    async with create_twitch_runtime(settings, database) as runtime:
        broadcaster = await runtime.helix_gateway.get_user_by_login(
            broadcaster_login
        )

        if broadcaster is None:
            raise RuntimeError(
                f"Twitch broadcaster not found: {broadcaster_login}"
            )

        user = await runtime.helix_gateway.get_user_by_login(
            user_login
        )

        if user is None:
            raise RuntimeError(
                f"Twitch user not found: {user_login}"
            )

        broadcaster_id, broadcaster_display_name = broadcaster
        user_id, user_display_name = user

        await repository.set(
            broadcaster_twitch_user_id=broadcaster_id,
            user_twitch_user_id=user_id,
            vip_chance=vip_chance,
        )

        print(
            f"Configured Ban or VIP chance for "
            f"{user_display_name} ({user_id}) "
            f"on {broadcaster_display_name} ({broadcaster_id}): "
            f"{vip_chance:.1f}% VIP."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Set a per-user Ban or VIP chance using Twitch login names."
        )
    )

    parser.add_argument(
        "broadcaster_login",
        help="Twitch login of the broadcaster.",
    )

    parser.add_argument(
        "user_login",
        help="Twitch login of the user.",
    )

    parser.add_argument(
        "vip_chance",
        type=float,
        help="VIP chance in percent (0-100).",
    )

    args = parser.parse_args()

    if not 0.0 <= args.vip_chance <= 100.0:
        parser.error("vip_chance must be between 0 and 100.")

    asyncio.run(
        configure(
            args.broadcaster_login,
            args.user_login,
            args.vip_chance,
        )
    )


if __name__ == "__main__":
    main()