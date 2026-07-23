from dotenv import load_dotenv
from utils.refresh_token import _refresh_token_sync

load_dotenv()

print("Checking/Refreshing Twitch Token...")
_refresh_token_sync()

load_dotenv(override=True)

from bot import run_bot

if __name__ == "__main__":
    run_bot()