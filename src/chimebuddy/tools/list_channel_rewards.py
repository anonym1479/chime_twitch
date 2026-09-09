import argparse
import asyncio

from chimebuddy.config import load_settings
from chimebuddy.database import Database
from chimebuddy.twitch.runtime import create_twitch_runtime


async def list_rewards(broadcaster_id: str) -> None:
    settings = load_settings()
    database = Database(settings.database_path)
    await database.initialize()
    async with create_twitch_runtime(settings, database) as runtime:
        rewards = await runtime.helix_gateway.list_custom_rewards(broadcaster_id)
    if not rewards:
        print("No Channel Points custom rewards found.")
        return
    for reward in rewards:
        print(f"{reward['id']}  |  {reward['title']}  |  {reward['cost']} points")


def main() -> None:
    parser = argparse.ArgumentParser(description="List Twitch Channel Points rewards.")
    parser.add_argument("broadcaster_id")
    args = parser.parse_args()
    asyncio.run(list_rewards(args.broadcaster_id))


if __name__ == "__main__":
    main()
