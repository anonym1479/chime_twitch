from dotenv import load_dotenv
from bot import ChimeBot

load_dotenv()

bot = ChimeBot()
bot.run()