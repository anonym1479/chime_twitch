import asyncio
import unittest
from types import SimpleNamespace

from chimebuddy.twitch.worker import (
    eventsub_supervisor_loop,
    token_validation_loop,
)


class FakeTokenManager:
    def __init__(self):
        self.calls = 0
        self.called_event = asyncio.Event()

    async def validate_registered(self):
        self.calls += 1
        self.called_event.set()
        return {}


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


class TwitchWorkerTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_periodic_token_validation(self):
        token_manager = FakeTokenManager()

        runtime = SimpleNamespace(
            token_manager=token_manager
        )

        stop_event = asyncio.Event()

        task = asyncio.create_task(
            token_validation_loop(
                runtime,
                stop_event,
                validation_interval_seconds=0.01,
            )
        )

        await asyncio.wait_for(
            token_manager.called_event.wait(),
            timeout=1,
        )

        stop_event.set()

        await asyncio.wait_for(
            task,
            timeout=1,
        )

        self.assertGreaterEqual(
            token_manager.calls,
            1,
        )

    async def test_rejects_invalid_token_interval(self):
        runtime = SimpleNamespace(
            token_manager=FakeTokenManager()
        )

        with self.assertRaises(ValueError):
            await token_validation_loop(
                runtime,
                asyncio.Event(),
                validation_interval_seconds=0,
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