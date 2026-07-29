import unittest

from chimebuddy.models import (
    AccountLinkSession,
    AccountLinkSessionStatus,
    BroadcasterBlacklistEntry,
    BroadcasterPanel,
    BroadcasterRequest,
    BroadcasterRequestStatus,
    OnboardingRequestEvent,
)


class OnboardingModelTests(unittest.TestCase):
    def test_link_session_normalizes_values(self):
        session = AccountLinkSession(
            session_id=" session-1 ",
            discord_user_id=" 123 ",
            twitch_user_id=" 456 ",
            expires_at=1000,
            requested_scopes=(
                "channel:bot",
                " channel:bot ",
                "",
            ),
            status="authorized",
        )

        self.assertEqual(
            session.session_id,
            "session-1",
        )
        self.assertEqual(
            session.discord_user_id,
            "123",
        )
        self.assertEqual(
            session.twitch_user_id,
            "456",
        )
        self.assertEqual(
            session.requested_scopes,
            ("channel:bot",),
        )
        self.assertEqual(
            session.status,
            AccountLinkSessionStatus.AUTHORIZED,
        )

    def test_link_session_rejects_invalid_expiry(self):
        with self.assertRaisesRegex(
            ValueError,
            "expires_at",
        ):
            AccountLinkSession(
                session_id="session-1",
                discord_user_id="123",
                expires_at=0,
            )

    def test_request_reports_open_status(self):
        pending = BroadcasterRequest(
            twitch_user_id="456",
            discord_user_id="123",
        )

        rejected = BroadcasterRequest(
            twitch_user_id="456",
            discord_user_id="123",
            status=BroadcasterRequestStatus.REJECTED,
        )

        self.assertTrue(pending.is_open)
        self.assertFalse(rejected.is_open)

    def test_panel_requires_positive_request_id(self):
        with self.assertRaisesRegex(
            ValueError,
            "request_id",
        ):
            BroadcasterPanel(
                twitch_user_id="456",
                request_id=0,
                discord_guild_id="100",
                discord_channel_id="200",
            )

    def test_blacklist_requires_an_identity(self):
        with self.assertRaisesRegex(
            ValueError,
            "requires a Discord user ID",
        ):
            BroadcasterBlacklistEntry(
                internal_reason="Test reason",
                created_by_discord_user_id="999",
            )

    def test_blacklist_accepts_both_identities(self):
        entry = BroadcasterBlacklistEntry(
            discord_user_id="123",
            twitch_user_id="456",
            internal_reason=" Test reason ",
            created_by_discord_user_id="999",
        )

        self.assertEqual(
            entry.internal_reason,
            "Test reason",
        )
        self.assertTrue(entry.active)

    def test_event_validates_and_normalizes_json(self):
        event = OnboardingRequestEvent(
            request_id=1,
            event_type=" request_created ",
            from_status=None,
            to_status="pending",
            details_json='{"source": "test"}',
        )

        self.assertEqual(
            event.event_type,
            "request_created",
        )
        self.assertEqual(
            event.to_status,
            BroadcasterRequestStatus.PENDING,
        )
        self.assertEqual(
            event.details_json,
            '{"source":"test"}',
        )

    def test_event_rejects_non_object_json(self):
        with self.assertRaisesRegex(
            ValueError,
            "JSON object",
        ):
            OnboardingRequestEvent(
                request_id=1,
                event_type="test",
                details_json='["not", "an", "object"]',
            )


if __name__ == "__main__":
    unittest.main()