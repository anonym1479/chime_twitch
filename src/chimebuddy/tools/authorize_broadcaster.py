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
    wait_for_device_authorization,
)
from chimebuddy.twitch.oauth_client import (
    OAuthResponseError,
    RefreshedTokens,
    TokenValidation,
    TwitchOAuthClient,
)
from chimebuddy.twitch.scopes import (
    BROADCASTER_CHAT_SCOPES,
)


async def save_broadcaster_authorization(
    identity_repository: IdentityRepository,
    credential_repository: OAuthCredentialRepository,
    validation: TokenValidation,
    tokens: RefreshedTokens,
) -> None:
    """
    Save identity before credential to satisfy the
    database foreign-key relationship.
    """

    if not validation.user_id:
        raise RuntimeError(
            "Twitch did not return a broadcaster user ID."
        )

    if not validation.login:
        raise RuntimeError(
            "Twitch did not return a broadcaster login."
        )

    await identity_repository.save_twitch_account(
        TwitchAccount(
            twitch_user_id=validation.user_id,
            login=validation.login,
            display_name=validation.login,
        )
    )

    await credential_repository.save(
        OAuthCredential(
            twitch_user_id=validation.user_id,
            credential_kind=(
                OAuthCredentialKind.BROADCASTER
            ),
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            scopes=validation.scopes,
            expires_at=(
                int(time.time())
                + validation.expires_in
            ),
        )
    )


async def authorize_broadcaster(
    settings: Settings,
) -> None:
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

    identity_repository = IdentityRepository(
        database
    )
    credential_repository = (
        OAuthCredentialRepository(database)
    )

    async with aiohttp.ClientSession() as session:
        device_client = (
            TwitchDeviceAuthorizationClient(
                session=session,
                client_id=settings.twitch_client_id,
            )
        )

        authorization = await device_client.start(
            BROADCASTER_CHAT_SCOPES
        )

        print()
        print("=" * 60)
        print(
            "CHIMEBUDDY V2 - BROADCASTER AUTHORIZATION"
        )
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
            "3. Sign in using the BROADCASTER "
            "account, not the bot account."
        )
        print()
        print("Requested permissions:")

        for scope in BROADCASTER_CHAT_SCOPES:
            print(f"   - {scope}")

        print()
        print("Waiting for Twitch authorization...")
        print(
            "Press Ctrl+C if you want to cancel."
        )
        print("=" * 60)

        tokens = await wait_for_device_authorization(
            device_client,
            authorization,
            BROADCASTER_CHAT_SCOPES,
        )

        oauth_client = TwitchOAuthClient(
            session=session,
            client_id=settings.twitch_client_id,
            client_secret=(
                settings.twitch_client_secret
            ),
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
            "Twitch did not return a user ID."
        )

    if not validation.login:
        raise RuntimeError(
            "Twitch did not return an account login."
        )

    missing_scopes = (
        set(BROADCASTER_CHAT_SCOPES)
        - set(validation.scopes)
    )

    if missing_scopes:
        scopes_text = ", ".join(
            sorted(missing_scopes)
        )

        raise RuntimeError(
            "The broadcaster token is missing scopes: "
            f"{scopes_text}"
        )

    print()
    print(
        "Broadcaster authorized successfully:"
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
        "Save this broadcaster authorization? "
        "[y/N]: ",
    )

    if answer.strip().casefold() not in {
        "y",
        "yes",
    }:
        print(
            "Broadcaster authorization was not saved."
        )
        return

    await save_broadcaster_authorization(
        identity_repository,
        credential_repository,
        validation,
        tokens,
    )

    print()
    print(
        "Broadcaster credential saved in SQLite."
    )
    print(
        "The channel is not enabled yet."
    )


def main() -> None:
    try:
        settings = load_settings()
        settings.validate_for_twitch()

        asyncio.run(
            authorize_broadcaster(settings)
        )

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