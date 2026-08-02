import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from chimebuddy.database import Database
from chimebuddy.models import (
    AccountLink,
    AccountLinkStatus,
    Broadcaster,
    DiscordAccount,
    Trigger,
    TwitchAccount,
)
from chimebuddy.repositories import (
    IdentityRepository,
    TriggerRepository,
)
from chimebuddy.twitch import StreamInformation
from chimebuddy.twitch.worker import (
    create_title_monitor,
    eventsub_supervisor_loop,
    token_validation_loop,
    validate_enabled_broadcaster_credentials,
)
from chimebuddy.twitch.token_manager import (
    ReauthorizationRequiredError,
)


class FakeTokenManager:
    def __init__(self):
        self.calls = 0
        self.called_event = asyncio.Event()
        self.validation_errors = {}

    async def validate_now(
        self,
        twitch_user_id,
        credential_kind,
        required_scopes=(),
    ):
        self.calls += 1
        self.called_event.set()

        error = self.validation_errors.get(
            str(twitch_user_id)
        )

        if error is not None:
            raise error

        return "access-token"


class FakeRuntime:
    def __init__(self, token_manager) -> None:
        self.token_manager = token_manager
        self.bot_twitch_user_id = "bot-1"
        self.bot_validation_calls = 0
        self.bot_called_event = asyncio.Event()

    async def validate_bot_token(self):
        self.bot_validation_calls += 1
        self.bot_called_event.set()
        return "bot-access-token"


class FakeIdentityRepository:
    def __init__(
        self,
        broadcaster_ids=(),
    ) -> None:
        self.broadcaster_ids = tuple(
            broadcaster_ids
        )

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


class FakeEventSubService:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()

    async def run(
        self,
        stop_event: asyncio.Event,
    ) -> None:
        self.started.set()
        await stop_event.wait()
        self.stopped.set()


class FakeEventSubFactory:
    def __init__(self) -> None:
        self.calls = []
        self.services = []
        self.call_queue = asyncio.Queue()

    def __call__(
        self,
        broadcaster_ids,
    ) -> FakeEventSubService:
        ids = tuple(broadcaster_ids)
        service = FakeEventSubService()

        self.calls.append(ids)
        self.services.append(service)
        self.call_queue.put_nowait(ids)

        return service

class FakeBroadcasterCleanup:
    def __init__(self) -> None:
        self.calls = []
        self.called = asyncio.Event()

    async def __call__(
        self,
        broadcaster_ids,
    ) -> None:
        self.calls.append(
            tuple(broadcaster_ids)
        )
        self.called.set()


class FakeHealthRepository:
    def __init__(self) -> None:
        self.successes = []
        self.failures = []

    async def mark_success(
        self,
        component,
        subject_id="",
        **kwargs,
    ):
        self.successes.append(
            (component, subject_id, kwargs)
        )

    async def mark_failure(
        self,
        component,
        subject_id="",
        **kwargs,
    ):
        self.failures.append(
            (component, subject_id, kwargs)
        )


class PinFailingTitleGateway:
    async def get_stream_information(
        self,
        broadcaster_twitch_user_id,
    ):
        return StreamInformation(
            broadcaster_twitch_user_id=(
                broadcaster_twitch_user_id
            ),
            login="example_streamer",
            display_name="Example Streamer",
            title="Solo test stream",
            game_id="1",
            game_name="Example Game",
            started_at="2026-08-02T10:00:00Z",
        )

    async def send_message(
        self,
        broadcaster_twitch_user_id,
        message,
    ):
        return "message-1"

    async def pin_message(
        self,
        broadcaster_twitch_user_id,
        message_id,
    ):
        raise RuntimeError("Simulated pin failure.")

    async def unpin_message(
        self,
        broadcaster_twitch_user_id,
        message_id,
    ):
        return None


class TwitchWorkerTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_periodic_token_validation(self):
        token_manager = FakeTokenManager()

        runtime = FakeRuntime(token_manager)
        repository = FakeIdentityRepository()

        async def handle_reauthorization(
            broadcaster_id,
            reason,
        ):
            raise AssertionError(
                "No broadcaster should need reauthorization."
            )

        stop_event = asyncio.Event()

        task = asyncio.create_task(
            token_validation_loop(
                runtime,
                repository,
                handle_reauthorization,
                stop_event,
                validation_interval_seconds=0.01,
            )
        )

        await asyncio.wait_for(
            runtime.bot_called_event.wait(),
            timeout=1,
        )

        stop_event.set()

        await asyncio.wait_for(
            task,
            timeout=1,
        )

        self.assertGreaterEqual(
            runtime.bot_validation_calls,
            1,
        )

    async def test_trigger_errors_degrade_title_health(
        self,
    ) -> None:
        temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temp_directory.cleanup)
        database = Database(
            Path(temp_directory.name) / "test.db"
        )
        await database.initialize()

        identity_repository = IdentityRepository(database)
        await identity_repository.save_twitch_account(
            TwitchAccount(
                twitch_user_id="100",
                login="example_streamer",
                display_name="Example Streamer",
            )
        )
        await identity_repository.save_discord_account(
            DiscordAccount(
                discord_user_id="200",
                username="example_user",
                display_name="Example User",
            )
        )
        await identity_repository.save_account_link(
            AccountLink(
                twitch_user_id="100",
                discord_user_id="200",
                status=AccountLinkStatus.VERIFIED,
                verification_method="test",
            )
        )
        await identity_repository.save_broadcaster(
            Broadcaster(
                twitch_user_id="100",
                owner_discord_user_id="200",
            )
        )
        await TriggerRepository(database).create_trigger(
            Trigger(
                broadcaster_twitch_user_id="100",
                name="Solo",
                expression="solo",
                response_message="Solo mode is active.",
            )
        )

        health_repository = FakeHealthRepository()
        monitor = create_title_monitor(
            database,
            SimpleNamespace(
                helix_gateway=PinFailingTitleGateway()
            ),
            health_repository,
        )

        with self.assertLogs(
            "chimebuddy.twitch.triggers",
            level="WARNING",
        ):
            report = await monitor.check_once()

        self.assertEqual(report.error_count, 1)
        self.assertEqual(
            health_repository.failures[0][:2],
            ("title_monitor", "100"),
        )
        self.assertEqual(
            health_repository.failures[0][2][
                "error_code"
            ],
            "title_trigger_failed",
        )

    async def test_rejects_invalid_token_interval(self):
        runtime = FakeRuntime(FakeTokenManager())

        with self.assertRaises(ValueError):
            await token_validation_loop(
                runtime,
                FakeIdentityRepository(),
                lambda broadcaster_id, reason: None,
                asyncio.Event(),
                validation_interval_seconds=0,
            )

    async def test_broadcaster_reauthorization_is_isolated(
        self,
    ) -> None:
        token_manager = FakeTokenManager()
        token_manager.validation_errors["100"] = (
            ReauthorizationRequiredError(
                "Refresh token rejected."
            )
        )

        runtime = FakeRuntime(token_manager)
        repository = FakeIdentityRepository(
            ("100", "200")
        )
        health_repository = FakeHealthRepository()
        reauthorization_calls = []

        async def handle_reauthorization(
            broadcaster_id,
            reason,
        ):
            reauthorization_calls.append(
                (broadcaster_id, reason)
            )

        await validate_enabled_broadcaster_credentials(
            runtime,
            repository,
            handle_reauthorization,
            health_repository,
        )

        self.assertEqual(
            reauthorization_calls,
            [("100", "Refresh token rejected.")],
        )
        self.assertEqual(token_manager.calls, 2)
        self.assertEqual(
            health_repository.successes[0][:2],
            ("token_validation", "200"),
        )
        self.assertEqual(
            health_repository.failures[0][2][
                "error_code"
            ],
            "reauthorization_required",
        )

    async def test_eventsub_starts_for_enabled_channels(
        self,
    ) -> None:
        repository = FakeIdentityRepository(
            ("100",)
        )
        factory = FakeEventSubFactory()
        stop_event = asyncio.Event()

        task = asyncio.create_task(
            eventsub_supervisor_loop(
                repository,
                factory,
                stop_event,
                sync_interval_seconds=0.01,
            )
        )

        first_ids = await asyncio.wait_for(
            factory.call_queue.get(),
            timeout=1,
        )

        self.assertEqual(
            first_ids,
            ("100",),
        )

        stop_event.set()

        await asyncio.wait_for(
            task,
            timeout=1,
        )

        self.assertTrue(
            factory.services[0].stopped.is_set()
        )

    async def test_eventsub_restarts_when_list_changes(
        self,
    ) -> None:
        repository = FakeIdentityRepository(
            ("100",)
        )
        factory = FakeEventSubFactory()
        stop_event = asyncio.Event()

        task = asyncio.create_task(
            eventsub_supervisor_loop(
                repository,
                factory,
                stop_event,
                sync_interval_seconds=0.01,
            )
        )

        await asyncio.wait_for(
            factory.call_queue.get(),
            timeout=1,
        )

        first_service = factory.services[0]

        repository.broadcaster_ids = (
            "100",
            "200",
        )

        second_ids = await asyncio.wait_for(
            factory.call_queue.get(),
            timeout=1,
        )

        self.assertEqual(
            second_ids,
            ("100", "200"),
        )
        self.assertTrue(
            first_service.stopped.is_set()
        )

        stop_event.set()

        await asyncio.wait_for(
            task,
            timeout=1,
        )

    async def test_eventsub_waits_without_channels(
        self,
    ) -> None:
        repository = FakeIdentityRepository()
        factory = FakeEventSubFactory()
        stop_event = asyncio.Event()

        task = asyncio.create_task(
            eventsub_supervisor_loop(
                repository,
                factory,
                stop_event,
                sync_interval_seconds=0.01,
            )
        )

        await asyncio.sleep(0.03)
        stop_event.set()

        await asyncio.wait_for(
            task,
            timeout=1,
        )

        self.assertEqual(factory.calls, [])

    async def test_rejects_invalid_sync_interval(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            await eventsub_supervisor_loop(
                FakeIdentityRepository(),
                FakeEventSubFactory(),
                asyncio.Event(),
                sync_interval_seconds=0,
            )

    async def test_removed_broadcaster_is_cleaned_up(
        self,
    ) -> None:
        repository = FakeIdentityRepository(
            ("100",)
        )
        factory = FakeEventSubFactory()
        cleanup = FakeBroadcasterCleanup()
        stop_event = asyncio.Event()

        task = asyncio.create_task(
            eventsub_supervisor_loop(
                repository,
                factory,
                stop_event,
                broadcaster_cleanup=cleanup,
                sync_interval_seconds=0.01,
            )
        )

        await asyncio.wait_for(
            factory.call_queue.get(),
            timeout=1,
        )

        first_service = factory.services[0]
        repository.broadcaster_ids = ()

        await asyncio.wait_for(
            cleanup.called.wait(),
            timeout=1,
        )

        # Cleanup is requested for exactly the removed
        # broadcaster.
        self.assertEqual(
            cleanup.calls,
            [("100",)],
        )

        # Allow the supervisor to finish reconfiguration.
        await asyncio.wait_for(
            first_service.stopped.wait(),
            timeout=1,
        )

        stop_event.set()

        await asyncio.wait_for(
            task,
            timeout=1,
        )

if __name__ == "__main__":
    unittest.main()
