import argparse
import asyncio

from chimebuddy.config import (
    ConfigurationError,
    Settings,
    load_settings,
)
from chimebuddy.database import Database
from chimebuddy.models import (
    AccountLink,
    AccountLinkStatus,
    Broadcaster,
    DiscordAccount,
    OAuthCredentialKind,
    Trigger,
)
from chimebuddy.repositories import (
    DuplicateTriggerNameError,
    IdentityRepository,
    OAuthCredentialRepository,
    TriggerRepository,
)
from chimebuddy.twitch.scopes import (
    BROADCASTER_CHAT_SCOPES,
)


DEFAULT_TRIGGER_NAME = "V2 Title Test"
DEFAULT_EXPRESSION = "chimev2test"
DEFAULT_MESSAGE = (
    "ChimeBuddy V2 title trigger is working."
)


async def bootstrap_test_channel(
    settings: Settings,
    twitch_user_id: str,
    *,
    expression: str = DEFAULT_EXPRESSION,
    response_message: str = DEFAULT_MESSAGE,
) -> None:
    user_id = str(twitch_user_id).strip()

    if not user_id:
        raise ValueError(
            "twitch_user_id cannot be empty."
        )

    if settings.developer_discord_user_id is None:
        raise ConfigurationError(
            "DEVELOPER_DISCORD_USER_ID is missing. "
            "Add your Discord user ID to V2's .env."
        )

    database = Database(settings.database_path)
    await database.initialize()

    identity_repository = IdentityRepository(database)
    credential_repository = (
        OAuthCredentialRepository(database)
    )
    trigger_repository = TriggerRepository(database)

    broadcaster_credential = (
        await credential_repository.get(
            user_id,
            OAuthCredentialKind.BROADCASTER,
        )
    )

    if broadcaster_credential is None:
        raise RuntimeError(
            "No broadcaster OAuth credential exists "
            f"for Twitch user {user_id}. Run "
            "chimebuddy-authorize-broadcaster first."
        )

    missing_scopes = (
        set(BROADCASTER_CHAT_SCOPES)
        - set(broadcaster_credential.scopes)
    )

    if missing_scopes:
        scopes_text = ", ".join(
            sorted(missing_scopes)
        )

        raise RuntimeError(
            "The broadcaster credential is missing "
            f"scopes: {scopes_text}"
        )

    discord_user_id = str(
        settings.developer_discord_user_id
    )

    await identity_repository.save_discord_account(
        DiscordAccount(
            discord_user_id=discord_user_id,
            username=(
                f"developer_{discord_user_id}"
            ),
            display_name="ChimeBuddy Developer",
        )
    )

    await identity_repository.save_account_link(
        AccountLink(
            twitch_user_id=user_id,
            discord_user_id=discord_user_id,
            status=AccountLinkStatus.VERIFIED,
            verification_method=(
                "developer_bootstrap"
            ),
        )
    )

    await identity_repository.save_broadcaster(
        Broadcaster(
            twitch_user_id=user_id,
            owner_discord_user_id=(
                discord_user_id
            ),
            enabled=True,
        )
    )

    try:
        trigger = (
            await trigger_repository.create_trigger(
                Trigger(
                    broadcaster_twitch_user_id=(
                        user_id
                    ),
                    name=DEFAULT_TRIGGER_NAME,
                    expression=expression,
                    response_message=(
                        response_message
                    ),
                    pin_message=True,
                    priority=10,
                )
            )
        )

        trigger_message = (
            "Created test trigger with ID "
            f"{trigger.trigger_id}."
        )

    except DuplicateTriggerNameError:
        trigger_message = (
            "The V2 test trigger already exists; "
            "it was not duplicated."
        )

    print()
    print("=" * 60)
    print("CHIMEBUDDY V2 TEST CHANNEL READY")
    print("=" * 60)
    print(f"Twitch user ID: {user_id}")
    print(
        f"Discord owner ID: {discord_user_id}"
    )
    print("Broadcaster enabled: yes")
    print(f"Trigger expression: {expression}")
    print(
        f"Trigger response: {response_message}"
    )
    print("Pin message: yes")
    print(trigger_message)
    print("=" * 60)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description=(
            "Enable a development broadcaster and "
            "create one safe title trigger."
        )
    )

    parser.add_argument(
        "twitch_user_id",
        help="Your broadcaster Twitch user ID.",
    )

    parser.add_argument(
        "--expression",
        default=DEFAULT_EXPRESSION,
        help=(
            "Text that must appear in the live title."
        ),
    )

    parser.add_argument(
        "--message",
        default=DEFAULT_MESSAGE,
        help="Chat message sent by the test trigger.",
    )

    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()

    try:
        settings = load_settings()
        settings.validate_for_twitch()

        asyncio.run(
            bootstrap_test_channel(
                settings,
                arguments.twitch_user_id,
                expression=arguments.expression,
                response_message=arguments.message,
            )
        )

    except (
        ConfigurationError,
        RuntimeError,
        ValueError,
    ) as exc:
        raise SystemExit(
            f"Bootstrap error: {exc}"
        ) from exc


if __name__ == "__main__":
    main()