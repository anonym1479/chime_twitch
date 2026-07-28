import asyncio
import time

import aiohttp

from chimebuddy.config import (
    ConfigurationError,
    Settings,
    load_settings,
)
from chimebuddy.database import Database
from chimebuddy.models import (
    OAuthCredential,
    OAuthCredentialKind,
    TwitchAccount,
)
from chimebuddy.repositories import (
    IdentityRepository,
    OAuthCredentialRepository,
)
from chimebuddy.twitch.device_authorization import (
    DeviceAuthorizationError,
    TwitchDeviceAuthorizationClient,
)
from chimebuddy.twitch.oauth_client import (
    OAuthResponseError,
    TwitchOAuthClient,
)
from chimebuddy.twitch.scopes import BOT_CHAT_SCOPES


async def authorize_bot(settings: Settings) -> None:
    if not settings.twitch_client_id:
        raise ConfigurationError(
            "TWITCH_CLIENT_ID is missing."
        )

    if not settings.twitch_client_secret:
        raise ConfigurationError(
            "TWITCH_CLIENT_SECRET is missing."
        )

    database = Database(settings.database_path)
    await database.initialize()

    repository = OAuthCredentialRepository(database)
    identity_repository = IdentityRepository(database)

    existing_credentials = (
        await repository.list_by_kind(
            OAuthCredentialKind.BOT
        )
    )

    async with aiohttp.ClientSession() as session:
        device_client = (
            TwitchDeviceAuthorizationClient(
                session=session,
                client_id=settings.twitch_client_id,
            )
        )

        authorization = await device_client.start(
            BOT_CHAT_SCOPES
        )

        print()
        print("=" * 60)
        print("CHIMEBUDDY V2 - TWITCH BOT AUTHORIZATION")
        print("=" * 60)
        print()
        print("1. Open this address:")
        print()
        print(f"   {authorization.verification_uri}")
        print()
        print("2. If Twitch asks for a code, enter:")
        print()
        print(f"   {authorization.user_code}")
        print()
        print(
            "3. Sign in using the Twitch BOT account."
        )
        print()
        print("Requested permissions:")

        for scope in BOT_CHAT_SCOPES:
            print(f"   - {scope}")

        print()
        print("Waiting for Twitch authorization...")
        print(
            "Press Ctrl+C if you want to cancel."
        )
        print("=" * 60)

        tokens = await wait_for_authorization(
            device_client,
            authorization,
        )

        oauth_client = TwitchOAuthClient(
            session=session,
            client_id=settings.twitch_client_id,
            client_secret=settings.twitch_client_secret,
        )

        validation = await oauth_client.validate(
            tokens.access_token
        )

    if validation.client_id != settings.twitch_client_id:
        raise RuntimeError(
            "The authorized token belongs to a "
            "different Twitch application."
        )

    if not validation.user_id:
        raise RuntimeError(
            "Twitch did not return a user ID. "
            "A user access token is required."
        )

    if not validation.login:
        raise RuntimeError(
            "Twitch did not return an account login."
        )

    missing_scopes = (
        set(BOT_CHAT_SCOPES)
        - set(validation.scopes)
    )

    if missing_scopes:
        scopes_text = ", ".join(
            sorted(missing_scopes)
        )

        raise RuntimeError(
            "The authorized token is missing scopes: "
            f"{scopes_text}"
        )

    conflicting_credentials = [
        credential
        for credential in existing_credentials
        if (
            credential.twitch_user_id
            != validation.user_id
        )
    ]

    if conflicting_credentials:
        existing_ids = ", ".join(
            credential.twitch_user_id
            for credential in conflicting_credentials
        )

        raise RuntimeError(
            "The database already contains another "
            "bot identity: "
            f"{existing_ids}. It was not overwritten."
        )

    print()
    print(
        "Twitch account authorized successfully:"
    )
    print(f"  Login: {validation.login}")
    print(f"  User ID: {validation.user_id}")
    print()
    print(
        "No access token or refresh token will "
        "be printed."
    )

    answer = await asyncio.to_thread(
        input,
        "Save this account as ChimeBuddy's bot? "
        "[y/N]: ",
    )

    if answer.strip().casefold() not in {
        "y",
        "yes",
    }:
        print(
            "Authorization was not saved."
        )
        return

    credential = OAuthCredential(
        twitch_user_id=validation.user_id,
        credential_kind=OAuthCredentialKind.BOT,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        scopes=validation.scopes,
        expires_at=(
            int(time.time())
            + validation.expires_in
        ),
    )

    await identity_repository.save_twitch_account(
    TwitchAccount(
        twitch_user_id=validation.user_id,
        login=validation.login,
        display_name=validation.login,
        )
    )
    await repository.save(credential)

    print()
    print(
        "Bot credential saved securely in SQLite."
    )
    print(
        f"Database: {settings.database_path}"
    )


async def wait_for_authorization(
    device_client: TwitchDeviceAuthorizationClient,
    authorization,
):
    event_loop = asyncio.get_running_loop()

    deadline = (
        event_loop.time()
        + authorization.expires_in
    )

    while event_loop.time() < deadline:
        await asyncio.sleep(
            authorization.interval
        )

        tokens = await device_client.poll(
            authorization,
            BOT_CHAT_SCOPES,
        )

        if tokens is not None:
            return tokens

        print(".", end="", flush=True)

    raise DeviceAuthorizationError(
        "The Twitch device authorization expired."
    )


def main() -> None:
    try:
        settings = load_settings()
        settings.validate_for_twitch()

        asyncio.run(authorize_bot(settings))

    except KeyboardInterrupt:
        raise SystemExit(
            "\nAuthorization cancelled."
        ) from None

    except (
        ConfigurationError,
        DeviceAuthorizationError,
        OAuthResponseError,
        RuntimeError,
    ) as exc:
        raise SystemExit(
            f"Authorization error: {exc}"
        ) from exc


if __name__ == "__main__":
    main()