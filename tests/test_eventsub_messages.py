import unittest

from chimebuddy.twitch.eventsub_messages import (
    EventSubMessageError,
    parse_channel_chat_message,
)


def create_notification() -> dict:
    return {
        "metadata": {
            "message_id": "event-message-1",
            "message_type": "notification",
            "subscription_type": "channel.chat.message",
            "subscription_version": "1",
        },
        "payload": {
            "subscription": {
                "type": "channel.chat.message",
            },
            "event": {
                "broadcaster_user_id": "211164044",
                "broadcaster_user_login": "anonym_poal",
                "broadcaster_user_name": "Anonym_Poal",
                "chatter_user_id": "123456789",
                "chatter_user_login": "example_mod",
                "chatter_user_name": "Example_Mod",
                "message_id": "chat-message-1",
                "message": {
                    "text": "_test",
                    "fragments": [],
                },
                "message_type": "text",
                "badges": [
                    {
                        "set_id": "moderator",
                        "id": "1",
                        "info": "",
                    }
                ],
            },
        },
    }


class EventSubMessageTests(unittest.TestCase):
    def test_parses_chat_notification(self) -> None:
        message = parse_channel_chat_message(
            create_notification()
        )

        self.assertEqual(
            message.broadcaster_twitch_user_id,
            "211164044",
        )
        self.assertEqual(
            message.chatter_twitch_user_id,
            "123456789",
        )
        self.assertEqual(message.text, "_test")
        self.assertTrue(message.is_moderator)
        self.assertFalse(message.is_vip)
        self.assertFalse(message.is_broadcaster)

    def test_detects_broadcaster_by_id(self) -> None:
        notification = create_notification()
        event = notification["payload"]["event"]

        event["chatter_user_id"] = "211164044"
        event["badges"] = []

        message = parse_channel_chat_message(
            notification
        )

        self.assertTrue(message.is_broadcaster)
        self.assertFalse(message.is_moderator)

    def test_rejects_wrong_subscription_type(self) -> None:
        notification = create_notification()
        notification["metadata"][
            "subscription_type"
        ] = "stream.online"

        with self.assertRaises(EventSubMessageError):
            parse_channel_chat_message(notification)


if __name__ == "__main__":
    unittest.main()