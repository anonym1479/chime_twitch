import json


with open("config.json", "r", encoding="utf-8") as file:
    config = json.load(file)


CHANNEL_USERNAME = config["channel"]["username"]
CHANNEL_ID = config["channel"]["user_id"]

PIN_MESSAGE = config["pin"]["message"]

TRIGGER_ENABLED = config["trigger"]["enabled"]
TRIGGER_KEYWORDS = config["trigger"]["keywords"]