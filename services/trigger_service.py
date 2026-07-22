import json


class TriggerService:
    def __init__(self):
        with open("data/triggers.json", "r", encoding="utf-8") as f:
            self.triggers = json.load(f)

    def check(self, title):
        title = title.lower()
        for keyword, data in self.triggers.items():
            if keyword.lower() in title:
                return data

        return None