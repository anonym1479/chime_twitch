import secrets
import time
from collections.abc import (
    Awaitable,
    Callable,
)
from dataclasses import dataclass, field

from dotenv.main import logger

from chimebuddy.models import (
    AccountLinkSession,
    BroadcasterRequest,
    BroadcasterRequestStatus,
    DiscordAccount,
    OAuthCredential,
    OAuthCredentialKind,
    TwitchAccount,
)
from chimebuddy.repositories import (
    AccountLinkCompletionRepository,
    AccountLinkSessionRepository,
    BroadcasterBlacklistRepository,
    IdentityRepository,
)
from chimebuddy.services.onboarding_service import (
    BlacklistedIdentityError,
    OnboardingService,
)
from chimebuddy.twitch.device_authorization import (
    DeviceAuthorization,
    DeviceAuthorizationDeniedError,
    DeviceAuthorizationExpiredError,
    TwitchDeviceAuthorizationClient,
    wait_for_device_authorization,
)
from chimebuddy.twitch.oauth_client import (
    RefreshedTokens,
    TokenValidation,
    TwitchOAuthClient,
)
from chimebuddy.twitch.scopes import (
    BROADCASTER_CHAT_SCOPES,
)


CONFIRMATION_WINDOW_SECONDS = 600

AuthorizationWaiter = Callable[
    [
        TwitchDeviceAuthorizationClient,
        DeviceAuthorization,
        tuple[str, ...],
    ],
    Awaitable[RefreshedTokens],
]


class AccountLinkingError(RuntimeError):
    """Base error for combined account linking."""


class ExistingBroadcasterRequestError(
    AccountLinkingError
):
    """Raised when Discord already owns an open request."""

    def __init__(
        self,
        request: BroadcasterRequest,
    ) -> None:
        self.request = request

        super().__init__(
            "This Discord account already has "
            f"request {request.request_id} with status "
            f"{request.status.value}."
        )


class LinkAuthorizationValidationError(
    AccountLinkingError
):
    """Raised when Twitch authorization cannot be trusted."""


class LinkSessionCompletionError(
    AccountLinkingError
):
    """Raised when a pending link session cannot be completed."""


@dataclass(frozen=True, slots=True)
class AccountLinkChallenge:
    session_id: str
    discord_user_id: str
    user_code: str
    verification_uri: str
    expires_at: int
    requested_scopes: tuple[str, ...]
    authorization: DeviceAuthorization = field(
        repr=False
    )
    existing_request: BroadcasterRequest | None = field(
        default=None,
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class AccountLinkAuthorization:
    """Validated authorization waiting for user confirmation."""

    session_id: str
    discord_user_id: str
    twitch_user_id: str
    twitch_login: str
    confirmation_expires_at: int
    twitch_account: TwitchAccount = field(
        repr=False
    )
    credential: OAuthCredential = field(
        repr=False
    )
    existing_request: BroadcasterRequest | None = field(
        default=None,
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class AccountLinkResult:
    session_id: str
    discord_user_id: str
    twitch_user_id: str
    twitch_login: str
    request: BroadcasterRequest
    was_reauthorization: bool = False


class AccountLinkingService:
    """Authenticates, confirms and links Twitch accounts."""

    def __init__(
        self,
        *,
        device_client: TwitchDeviceAuthorizationClient,
        oauth_client: TwitchOAuthClient,
        identity_repository: IdentityRepository,
        session_repository: AccountLinkSessionRepository,
        completion_repository: (
            AccountLinkCompletionRepository
        ),
        blacklist_repository: (
            BroadcasterBlacklistRepository
        ),
        onboarding_service: OnboardingService,
        authorization_waiter: AuthorizationWaiter = (
            wait_for_device_authorization
        ),
        scopes: tuple[str, ...] = (
            BROADCASTER_CHAT_SCOPES
        ),
    ) -> None:
        normalized_scopes = tuple(
            sorted(
                {
                    str(scope).strip()
                    for scope in scopes
                    if str(scope).strip()
                }
            )
        )

        if not normalized_scopes:
            raise ValueError(
                "At least one broadcaster scope "
                "is required."
            )

        self.device_client = device_client
        self.oauth_client = oauth_client
        self.identity_repository = (
            identity_repository
        )
        self.session_repository = (
            session_repository
        )
        self.completion_repository = (
            completion_repository
        )
        self.blacklist_repository = (
            blacklist_repository
        )
        self.onboarding_service = (
            onboarding_service
        )
        self.authorization_waiter = (
            authorization_waiter
        )
        self.scopes = normalized_scopes

    async def start(
        self,
        discord_account: DiscordAccount,
    ) -> AccountLinkChallenge:
        blacklist_entry = (
            await self.blacklist_repository.find_active(
                discord_user_id=(
                    discord_account.discord_user_id
                )
            )
        )

        if blacklist_entry is not None:
            raise BlacklistedIdentityError(
                "This Discord account cannot request "
                "ChimeBuddy access."
            )

        existing_request = (
            await self.onboarding_service
            .get_open_request_for_discord(
                discord_account.discord_user_id
            )
        )

        if (
            existing_request is not None
            and existing_request.status
            is not BroadcasterRequestStatus
            .REAUTHORIZATION_REQUIRED
        ):
            raise ExistingBroadcasterRequestError(
                existing_request
            )

        await self.identity_repository.save_discord_account(
            discord_account
        )

        authorization = await self.device_client.start(
            self.scopes
        )

        session_id = secrets.token_urlsafe(24)
        expires_at = (
            int(time.time())
            + authorization.expires_in
        )

        await self.session_repository.create(
            AccountLinkSession(
                session_id=session_id,
                discord_user_id=(
                    discord_account.discord_user_id
                ),
                requested_scopes=self.scopes,
                expires_at=expires_at,
            )
        )

        return AccountLinkChallenge(
            session_id=session_id,
            discord_user_id=(
                discord_account.discord_user_id
            ),
            user_code=authorization.user_code,
            verification_uri=(
                authorization.verification_uri
            ),
            expires_at=expires_at,
            requested_scopes=self.scopes,
            authorization=authorization,
            existing_request=existing_request,
        )

    async def authenticate(
        self,
        challenge: AccountLinkChallenge,
    ) -> AccountLinkAuthorization:
        try:
            tokens = await self.authorization_waiter(
                self.device_client,
                challenge.authorization,
                challenge.requested_scopes,
            )

            validation = await self.oauth_client.validate(
                tokens.access_token
            )

            logger.info(
                "Twitch broadcaster authorization received: "
                "user_id=%s, login=%s, requested_scopes=%s, "
                "granted_scopes=%s, missing_scopes=%s",
                validation.user_id,
                validation.login,
                sorted(challenge.requested_scopes),
                sorted(validation.scopes),
                sorted(
                    set(challenge.requested_scopes)
                    - set(validation.scopes)
                ),
            )

            self._validate_authorization(
                validation,
                challenge.requested_scopes,
            )

            twitch_user_id = validation.user_id
            twitch_login = validation.login

            if (
                twitch_user_id is None
                or twitch_login is None
            ):
                raise LinkAuthorizationValidationError(
                    "Twitch did not return a valid "
                    "user identity."
                )

            if (
                challenge.existing_request is not None
                and (
                    challenge.existing_request
                    .twitch_user_id
                    != twitch_user_id
                )
            ):
                raise LinkAuthorizationValidationError(
                    "Sign in with the Twitch account "
                    "already connected to this ChimeBuddy "
                    "request."
                )

            blacklist_entry = (
                await self.blacklist_repository.find_active(
                    discord_user_id=(
                        challenge.discord_user_id
                    ),
                    twitch_user_id=twitch_user_id,
                )
            )

            if blacklist_entry is not None:
                raise BlacklistedIdentityError(
                    "This Discord or Twitch account cannot "
                    "request ChimeBuddy access."
                )

            confirmation_expires_at = (
                int(time.time())
                + CONFIRMATION_WINDOW_SECONDS
            )

            extended = (
                await self.session_repository
                .extend_expiry(
                    challenge.session_id,
                    confirmation_expires_at,
                )
            )

            if not extended:
                raise LinkSessionCompletionError(
                    "The account-link session is no "
                    "longer pending."
                )

            twitch_account = TwitchAccount(
                twitch_user_id=twitch_user_id,
                login=twitch_login,
                display_name=twitch_login,
            )

            credential = OAuthCredential(
                twitch_user_id=twitch_user_id,
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

            return AccountLinkAuthorization(
                session_id=challenge.session_id,
                discord_user_id=(
                    challenge.discord_user_id
                ),
                twitch_user_id=twitch_user_id,
                twitch_login=twitch_login,
                confirmation_expires_at=(
                    confirmation_expires_at
                ),
                twitch_account=twitch_account,
                credential=credential,
                existing_request=(
                    challenge.existing_request
                ),
            )

        except DeviceAuthorizationExpiredError:
            await self.session_repository.expire(
                challenge.session_id
            )
            raise

        except DeviceAuthorizationDeniedError:
            await self.session_repository.fail(
                challenge.session_id,
                "Twitch authorization was denied.",
            )
            raise

        except Exception:
            await self.session_repository.fail(
                challenge.session_id,
                "Account linking failed.",
            )
            raise

    async def confirm_and_create_request(
        self,
        authorization: AccountLinkAuthorization,
        *,
        requester_message: str | None = None,
    ) -> AccountLinkResult:
        try:
            completed = (
                await self.completion_repository.complete(
                    authorization.session_id,
                    twitch_account=(
                        authorization.twitch_account
                    ),
                    credential=(
                        authorization.credential
                    ),
                )
            )

            if not completed:
                raise LinkSessionCompletionError(
                    "The account-link confirmation "
                    "expired or was already completed."
                )

        except Exception:
            await self.session_repository.fail(
                authorization.session_id,
                "Account-link confirmation failed.",
            )
            raise

        existing_request = authorization.existing_request

        if existing_request is None:
            request = (
                await self.onboarding_service.create_request(
                    twitch_user_id=(
                        authorization.twitch_user_id
                    ),
                    discord_user_id=(
                        authorization.discord_user_id
                    ),
                    requester_message=requester_message,
                )
            )
        else:
            request = (
                await self.onboarding_service
                .complete_reauthorization(
                    existing_request.request_id,
                    twitch_user_id=(
                        authorization.twitch_user_id
                    ),
                    discord_user_id=(
                        authorization.discord_user_id
                    ),
                )
            )

        return AccountLinkResult(
            session_id=authorization.session_id,
            discord_user_id=(
                authorization.discord_user_id
            ),
            twitch_user_id=(
                authorization.twitch_user_id
            ),
            twitch_login=authorization.twitch_login,
            request=request,
            was_reauthorization=(
                existing_request is not None
            ),
        )

    async def cancel_authorization(
        self,
        authorization: AccountLinkAuthorization,
    ) -> bool:
        return await self.session_repository.cancel(
            authorization.session_id
        )

    async def complete(
        self,
        challenge: AccountLinkChallenge,
        *,
        requester_message: str | None = None,
    ) -> AccountLinkResult:
        """
        Compatibility wrapper used by the current Discord UI.

        This will be removed after the confirmation panel
        is connected.
        """

        authorization = await self.authenticate(
            challenge
        )

        return await self.confirm_and_create_request(
            authorization,
            requester_message=requester_message,
        )

    def _validate_authorization(
        self,
        validation: TokenValidation,
        required_scopes: tuple[str, ...],
    ) -> None:
        if (
            validation.client_id
            != self.oauth_client.client_id
        ):
            raise LinkAuthorizationValidationError(
                "The Twitch token belongs to a "
                "different application."
            )

        if not validation.user_id:
            raise LinkAuthorizationValidationError(
                "Twitch did not return a user ID."
            )

        if not validation.login:
            raise LinkAuthorizationValidationError(
                "Twitch did not return a login."
            )

        missing_scopes = (
            set(required_scopes)
            - set(validation.scopes)
        )

        if missing_scopes:
            scopes_text = ", ".join(
                sorted(missing_scopes)
            )

            raise LinkAuthorizationValidationError(
                "The Twitch token is missing scopes: "
                f"{scopes_text}"
            )
