import asyncio
import unittest
from types import SimpleNamespace

from chimebuddy.twitch.worker import (
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

    async def test_rejects_invalid_interval(self):
        runtime = SimpleNamespace(
            token_manager=FakeTokenManager()
        )

        with self.assertRaises(ValueError):
            await token_validation_loop(
                runtime,
                asyncio.Event(),
                validation_interval_seconds=0,
            )


if __name__ == "__main__":
    unittest.main()