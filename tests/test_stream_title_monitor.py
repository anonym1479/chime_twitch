import unittest
from types import SimpleNamespace

from chimebuddy.services import (
    StreamTitleMonitor,
    TriggerRunReport,
)
from chimebuddy.twitch import StreamInformation


class FakeIdentityRepository:
    def __init__(self, broadcaster_ids):
        self.broadcaster_ids = broadcaster_ids

    async def list_broadcasters(
        self,
        *,
        enabled_only=False,
    ):
        return [
            SimpleNamespace(
                twitch_user_id=broadcaster_id
            )
            for broadcaster_id
            in self.broadcaster_ids
        ]


class FakeStreamGateway:
    def __init__(self, results):
        self.results = results
        self.calls = []

    async def get_stream_information(
        self,
        broadcaster_twitch_user_id,
    ):
        self.calls.append(
            broadcaster_twitch_user_id
        )

        result = self.results[
            broadcaster_twitch_user_id
        ]

        if isinstance(result, Exception):
            raise result

        return result


class FakeTriggerCoordinator:
    def __init__(self):
        self.calls = []

    async def process_title(
        self,
        broadcaster_twitch_user_id,
        title,
    ):
        self.calls.append(
            (
                broadcaster_twitch_user_id,
                title,
            )
        )

        return TriggerRunReport(
            broadcaster_twitch_user_id=(
                broadcaster_twitch_user_id
            ),
            title=title,
            selected_trigger_id=None,
            activated_trigger_ids=(),
            deactivated_trigger_ids=(),
            reset_trigger_ids=(),
            errors=(),
        )


def make_stream(
    broadcaster_id,
    title,
):
    return StreamInformation(
        broadcaster_twitch_user_id=(
            broadcaster_id
        ),
        login="example_streamer",
        display_name="Example Streamer",
        title=title,
        game_id="123",
        game_name="Example Game",
        started_at="2026-07-28T10:00:00Z",
    )


class StreamTitleMonitorTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_processes_live_title(self):
        identity_repository = (
            FakeIdentityRepository(["100"])
        )
        stream_gateway = FakeStreamGateway(
            {
                "100": make_stream(
                    "100",
                    "Ranked solo gameplay",
                )
            }
        )
        coordinator = FakeTriggerCoordinator()

        monitor = StreamTitleMonitor(
            identity_repository,
            stream_gateway,
            coordinator,
        )

        report = await monitor.check_once()

        self.assertEqual(
            coordinator.calls,
            [
                (
                    "100",
                    "Ranked solo gameplay",
                )
            ],
        )
        self.assertTrue(
            report.checks[0].is_live
        )

    async def test_offline_channel_uses_empty_title(
        self,
    ):
        identity_repository = (
            FakeIdentityRepository(["100"])
        )
        stream_gateway = FakeStreamGateway(
            {
                "100": None,
            }
        )
        coordinator = FakeTriggerCoordinator()

        monitor = StreamTitleMonitor(
            identity_repository,
            stream_gateway,
            coordinator,
        )

        report = await monitor.check_once()

        self.assertEqual(
            coordinator.calls,
            [
                (
                    "100",
                    "",
                )
            ],
        )
        self.assertFalse(
            report.checks[0].is_live
        )

    async def test_one_failure_does_not_stop_others(
        self,
    ):
        identity_repository = (
            FakeIdentityRepository(
                ["100", "200"]
            )
        )
        stream_gateway = FakeStreamGateway(
            {
                "100": RuntimeError(
                    "Test failure"
                ),
                "200": make_stream(
                    "200",
                    "Solo stream",
                ),
            }
        )
        coordinator = FakeTriggerCoordinator()

        monitor = StreamTitleMonitor(
            identity_repository,
            stream_gateway,
            coordinator,
        )

        with self.assertLogs(
            "chimebuddy.twitch.title_monitor",
            level="ERROR",
        ):
            report = await monitor.check_once()

        self.assertEqual(
            report.checked_count,
            2,
        )
        self.assertEqual(
            report.error_count,
            1,
        )
        self.assertEqual(
            coordinator.calls,
            [
                (
                    "200",
                    "Solo stream",
                )
            ],
        )

    async def test_reports_each_check_to_observer(
        self,
    ) -> None:
        observed = []

        async def observe(check):
            observed.append(check)

        monitor = StreamTitleMonitor(
            FakeIdentityRepository(["100"]),
            FakeStreamGateway({"100": None}),
            FakeTriggerCoordinator(),
            check_observer=observe,
        )

        report = await monitor.check_once()

        self.assertEqual(
            observed,
            [report.checks[0]],
        )


if __name__ == "__main__":
    unittest.main()
