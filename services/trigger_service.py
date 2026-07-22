import json


class TriggerService:
    def __init__(self):
        with open("data/triggers.json", "r", encoding="utf-8") as f:
            self.triggers_data = json.load(f)

    def check(self, channel_username, title):
        """Checks if a title contains any trigger keyword specific to the given channel."""
        channel_triggers = self.triggers_data.get(channel_username.lower(), {})
        title_lower = title.lower()

        for keyword, data in channel_triggers.items():
            if keyword.lower() in title_lower:
                return data

        return None