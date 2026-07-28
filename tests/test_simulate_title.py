import unittest

from chimebuddy.models import Trigger
from chimebuddy.tools.simulate_title import (
    simulate_title,
)


class FakeTriggerRepository:
    def __init__(self, triggers):
        self.triggers = triggers
        self.calls = []

    async def list_triggers(
        self,
        broadcaster_twitch_user_id,
    ):
        self.calls.append(
            broadcaster_twitch_user_id
        )
        return self.triggers


class SimulateTitleTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_selects_matching_trigger(self):
        repository = FakeTriggerRepository(
            [
                Trigger(
                    broadcaster_twitch_user_id="100",
                    name="V2 Test",
                    expression="chimev2test",
                    response_message="It works.",
                    priority=10,
                    trigger_id=1,
                )
            ]
        )

        simulation = await simulate_title(
            repository,
            "100",
            "Playing solo - chimev2test",
        )

        self.assertEqual(
            simulation.loaded_trigger_count,
            1,
        )
        self.assertEqual(
            simulation.selected_trigger.trigger_id,
            1,
        )
        self.assertEqual(
            repository.calls,
            ["100"],
        )

    async def test_reports_no_match(self):
        repository = FakeTriggerRepository(
            [
                Trigger(
                    broadcaster_twitch_user_id="100",
                    name="V2 Test",
                    expression="chimev2test",
                    response_message="It works.",
                    trigger_id=1,
                )
            ]
        )

        simulation = await simulate_title(
            repository,
            "100",
            "Playing with viewers",
        )

        self.assertEqual(
            simulation.matched_triggers,
            (),
        )
        self.assertIsNone(
            simulation.selected_trigger
        )


if __name__ == "__main__":
    unittest.main()