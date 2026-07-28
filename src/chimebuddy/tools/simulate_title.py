import argparse
import asyncio
from dataclasses import dataclass

from chimebuddy.config import (
    ConfigurationError,
    load_settings,
)
from chimebuddy.database import Database
from chimebuddy.models import Trigger
from chimebuddy.repositories import (
    TriggerRepository,
)
from chimebuddy.services import (
    TitleTriggerMatcher,
)


@dataclass(frozen=True, slots=True)
class TitleSimulation:
    broadcaster_twitch_user_id: str
    title: str
    loaded_trigger_count: int
    matched_triggers: tuple[Trigger, ...]
    selected_trigger: Trigger | None


async def simulate_title(
    trigger_repository: TriggerRepository,
    broadcaster_twitch_user_id: str,
    title: str,
) -> TitleSimulation:
    """
    Evaluate a title without changing runtime state
    or contacting Twitch.
    """

    broadcaster_id = str(
        broadcaster_twitch_user_id
    ).strip()

    if not broadcaster_id:
        raise ValueError(
            "broadcaster_twitch_user_id "
            "cannot be empty."
        )

    triggers = await trigger_repository.list_triggers(
        broadcaster_id
    )

    evaluation = TitleTriggerMatcher().evaluate(
        title,
        triggers,
    )

    return TitleSimulation(
        broadcaster_twitch_user_id=broadcaster_id,
        title=str(title),
        loaded_trigger_count=len(triggers),
        matched_triggers=(
            evaluation.matched_triggers
        ),
        selected_trigger=(
            evaluation.selected_trigger
        ),
    )


def print_simulation(
    simulation: TitleSimulation,
) -> None:
    print()
    print("=" * 60)
    print("CHIMEBUDDY V2 TITLE SIMULATION")
    print("=" * 60)
    print(
        "Broadcaster Twitch ID: "
        f"{simulation.broadcaster_twitch_user_id}"
    )
    print(f"Simulated title: {simulation.title}")
    print(
        "Loaded triggers: "
        f"{simulation.loaded_trigger_count}"
    )
    print(
        "Matching triggers: "
        f"{len(simulation.matched_triggers)}"
    )
    print()

    if not simulation.matched_triggers:
        print("Result: no trigger matched.")
        print("Chat message: none")
        print("Pin action: none")
    else:
        print("Matches in priority order:")

        for trigger in simulation.matched_triggers:
            print(
                f"  - {trigger.name} "
                f"(ID {trigger.trigger_id}, "
                f"priority {trigger.priority})"
            )

        selected = simulation.selected_trigger

        if selected is None:
            raise RuntimeError(
                "Simulation has matches but no "
                "selected trigger."
            )

        print()
        print(
            f"Selected trigger: {selected.name}"
        )
        print(
            f"Expression: {selected.expression}"
        )
        print(
            "Match type: "
            f"{selected.match_type.value}"
        )
        print(
            "Would send: "
            f"{selected.response_message}"
        )
        print(
            "Would pin: "
            f"{'yes' if selected.pin_message else 'no'}"
        )

    print()
    print("Twitch API calls: none")
    print("Database state changes: none")
    print("=" * 60)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description=(
            "Safely evaluate a fake stream title "
            "using the triggers stored in SQLite."
        )
    )

    parser.add_argument(
        "twitch_user_id",
        help="Broadcaster Twitch user ID.",
    )

    parser.add_argument(
        "title",
        help=(
            "Simulated title. Wrap it in quotes "
            "if it contains spaces."
        ),
    )

    return parser.parse_args()


async def run() -> None:
    arguments = parse_arguments()
    settings = load_settings()
    settings.validate_common()

    database = Database(settings.database_path)
    await database.initialize()

    repository = TriggerRepository(database)

    simulation = await simulate_title(
        repository,
        arguments.twitch_user_id,
        arguments.title,
    )

    print_simulation(simulation)


def main() -> None:
    try:
        asyncio.run(run())
    except (
        ConfigurationError,
        RuntimeError,
        ValueError,
    ) as exc:
        raise SystemExit(
            f"Simulation error: {exc}"
        ) from exc


if __name__ == "__main__":
    main()