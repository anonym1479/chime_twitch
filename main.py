from dotenv import load_dotenv
from utils.refresh_token import _refresh_token_sync

load_dotenv()

print("Checking/Refreshing Twitch Token...")
_refresh_token_sync()

load_dotenv(override=True)

from bot import bot

if __name__ == "__main__":
    bot.run()