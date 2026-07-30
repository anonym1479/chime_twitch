from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable

from chimebuddy.models import (
    OAuthCredential,
    OAuthCredentialKind,
)
from chimebuddy.repositories import (
    OAuthCredentialRepository,
)
from chimebuddy.twitch.oauth_client import (
    InvalidAccessTokenError,
    InvalidRefreshTokenError,
    TokenValidation,
    TwitchOAuthClient,
)

logger = logging.getLogger(
    "chimebuddy.twitch.token_manager"
)

REFRESH_SAFETY_MARGIN_SECONDS = 300


CredentialKey = tuple[str, OAuthCredentialKind]


class TokenManagerError(RuntimeError):
    """Base error for token-management failures."""


class CredentialNotFoundError(TokenManagerError):
    """Raised when no stored OAuth credential exists."""


class TokenClientMismatchError(TokenManagerError):
    """Raised when a token belongs to another Twitch app."""


class TokenIdentityMismatchError(TokenManagerError):
    """Raised when a token belongs to another Twitch user."""


class MissingScopesError(TokenManagerError):
    """Raised when a token lacks required Twitch scopes."""

    def __init__(
        self,
        missing_scopes: Iterable[str],
    ) -> None:
        self.missing_scopes = tuple(
            sorted(set(missing_scopes))
        )

        scopes_text = ", ".join(self.missing_scopes)

        super().__init__(
            f"OAuth token is missing scopes: {scopes_text}"
        )


class ReauthorizationRequiredError(TokenManagerError):
    """Raised when Twitch rejects the refresh token."""


class TwitchTokenManager:
    """
    Supplies current Twitch user access tokens.

    It validates stored tokens, refreshes expired tokens,
    saves rotated credentials, and prevents concurrent
    refresh attempts for the same Twitch account.
    """

    def __init__(
        self,
        oauth_client: TwitchOAuthClient,
        credential_repository: OAuthCredentialRepository,
        *,
        validation_interval: int = 3600,
        refresh_window: int | None = None,
    ) -> None:
        if validation_interval <= 0:
            raise ValueError(
                "validation_interval must be positive."
            )

        if refresh_window is None:
            refresh_window = (
                validation_interval
                + REFRESH_SAFETY_MARGIN_SECONDS
            )

        if refresh_window < 0:
            raise ValueError(
                "refresh_window cannot be negative."
            )

        self.oauth_client = oauth_client
        self.credential_repository = (
            credential_repository
        )
        self.validation_interval = validation_interval
        self.refresh_window = refresh_window

        self._locks: dict[
            CredentialKey,
            asyncio.Lock,
        ] = {}

        self._validated_until: dict[
            CredentialKey,
            int,
        ] = {}

        self._requirements: dict[
            CredentialKey,
            tuple[str, ...],
        ] = {}

    def register(
        self,
        twitch_user_id: str,
        credential_kind: OAuthCredentialKind,
        required_scopes: Iterable[str] = (),
    ) -> None:
        """
        Register a credential for periodic validation.

        Registering it does not make a Twitch request.
        """

        key = self._make_key(
            twitch_user_id,
            credential_kind,
        )

        scopes = self._normalize_scopes(
            required_scopes
        )

        existing = self._requirements.get(key, ())

        self._requirements[key] = tuple(
            sorted(set(existing) | set(scopes))
        )

    async def get_access_token(
        self,
        twitch_user_id: str,
        credential_kind: OAuthCredentialKind,
        required_scopes: Iterable[str] = (),
    ) -> str:
        """
        Return a valid access token for a Twitch account.

        The first request validates it with Twitch. Later
        requests reuse it until validation is due.
        """

        key = self._make_key(
            twitch_user_id,
            credential_kind,
        )

        self.register(
            twitch_user_id,
            credential_kind,
            required_scopes,
        )

        scopes = self._requirements[key]
        now = int(time.time())

        credential = await self._get_credential(key)

        if self._can_use_cached(
            key,
            credential,
            scopes,
            now,
        ):
            return credential.access_token

        async with self._lock_for(key):
            credential = await self._get_credential(key)
            now = int(time.time())

            if self._can_use_cached(
                key,
                credential,
                scopes,
                now,
            ):
                return credential.access_token

            return await self._validate_or_refresh(
                key,
                credential,
                scopes,
                now,
            )

    async def validate_now(
        self,
        twitch_user_id: str,
        credential_kind: OAuthCredentialKind,
        required_scopes: Iterable[str] = (),
    ) -> str:
        """Force immediate validation with Twitch."""

        key = self._make_key(
            twitch_user_id,
            credential_kind,
        )

        self.register(
            twitch_user_id,
            credential_kind,
            required_scopes,
        )

        async with self._lock_for(key):
            credential = await self._get_credential(key)

            return await self._validate_or_refresh(
                key,
                credential,
                self._requirements[key],
                int(time.time()),
            )

    async def validate_registered(
        self,
    ) -> dict[CredentialKey, str]:
        """
        Validate every registered credential immediately.

        The Twitch worker will later call this hourly.
        """

        results: dict[CredentialKey, str] = {}

        for key, scopes in tuple(
            self._requirements.items()
        ):
            user_id, credential_kind = key

            results[key] = await self.validate_now(
                user_id,
                credential_kind,
                scopes,
            )

        return results

    async def recover_after_unauthorized(
        self,
        twitch_user_id: str,
        credential_kind: OAuthCredentialKind,
        rejected_access_token: str,
        required_scopes: Iterable[str] = (),
    ) -> str:
        """
        Recover after a Twitch API request returns 401.

        If another task already refreshed the token, its
        newer token is reused. Otherwise, refresh once.
        """

        key = self._make_key(
            twitch_user_id,
            credential_kind,
        )

        self.register(
            twitch_user_id,
            credential_kind,
            required_scopes,
        )

        rejected = str(
            rejected_access_token
        ).strip()

        if not rejected:
            raise ValueError(
                "rejected_access_token cannot be empty."
            )

        async with self._lock_for(key):
            credential = await self._get_credential(key)
            scopes = self._requirements[key]

            if credential.access_token != rejected:
                self._require_scopes(
                    credential.scopes,
                    scopes,
                )
                return credential.access_token

            return await self._refresh(
                key,
                credential,
                scopes,
                int(time.time()),
            )

    def invalidate(
        self,
        twitch_user_id: str,
        credential_kind: OAuthCredentialKind,
    ) -> None:
        """Force validation on the next token request."""

        key = self._make_key(
            twitch_user_id,
            credential_kind,
        )

        self._validated_until.pop(key, None)

    async def _validate_or_refresh(
        self,
        key: CredentialKey,
        credential: OAuthCredential,
        required_scopes: tuple[str, ...],
        now: int,
    ) -> str:
        if credential.expires_within(
            self.refresh_window,
            now=now,
        ):
            return await self._refresh(
                key,
                credential,
                required_scopes,
                now,
            )

        try:
            validation = await self.oauth_client.validate(
                credential.access_token
            )
        except InvalidAccessTokenError:
            return await self._refresh(
                key,
                credential,
                required_scopes,
                now,
            )

        await self._accept_validation(
            key,
            credential,
            validation,
            required_scopes,
            now,
        )

        return credential.access_token

    async def _refresh(
        self,
        key: CredentialKey,
        credential: OAuthCredential,
        required_scopes: tuple[str, ...],
        now: int,
    ) -> str:
        logger.info(
            "Refreshing Twitch OAuth credential: "
            "kind=%s, user_id=%s.",
            credential.credential_kind.value,
            credential.twitch_user_id,
        )
        try:
            refreshed = await self.oauth_client.refresh(
                credential.refresh_token
            )
        except InvalidRefreshTokenError as exc:
            logger.error(
                "Twitch rejected the refresh token: "
                "kind=%s, user_id=%s. "
                "Reauthorization is required.",
                credential.credential_kind.value,
                credential.twitch_user_id,
            )
            raise ReauthorizationRequiredError(
                "Twitch rejected the refresh token. "
                "This account must authorize the bot again."
            ) from exc

        try:
            validation = await self.oauth_client.validate(
                refreshed.access_token
            )
        except InvalidAccessTokenError as exc:
            raise TokenManagerError(
                "Twitch returned a refreshed access token "
                "that failed validation."
            ) from exc

        refreshed_credential = OAuthCredential(
            twitch_user_id=credential.twitch_user_id,
            credential_kind=credential.credential_kind,
            access_token=refreshed.access_token,
            refresh_token=refreshed.refresh_token,
            scopes=validation.scopes,
            expires_at=now + validation.expires_in,
        )

        await self._accept_validation(
            key,
            refreshed_credential,
            validation,
            required_scopes,
            now,
        )
        logger.info(
            "Twitch OAuth credential refreshed "
            "successfully: kind=%s, user_id=%s, "
            "valid_for_seconds=%s.",
            credential.credential_kind.value,
            credential.twitch_user_id,
            validation.expires_in,
        )

        return refreshed_credential.access_token

    async def _accept_validation(
        self,
        key: CredentialKey,
        credential: OAuthCredential,
        validation: TokenValidation,
        required_scopes: tuple[str, ...],
        now: int,
    ) -> None:
        if validation.client_id != self.oauth_client.client_id:
            raise TokenClientMismatchError(
                "OAuth token belongs to a different "
                "Twitch application."
            )

        expected_user_id = credential.twitch_user_id

        if validation.user_id != expected_user_id:
            raise TokenIdentityMismatchError(
                "OAuth token belongs to a different "
                "Twitch account."
            )

        self._require_scopes(
            validation.scopes,
            required_scopes,
        )

        updated_credential = OAuthCredential(
            twitch_user_id=credential.twitch_user_id,
            credential_kind=credential.credential_kind,
            access_token=credential.access_token,
            refresh_token=credential.refresh_token,
            scopes=validation.scopes,
            expires_at=now + validation.expires_in,
        )

        await self.credential_repository.save(
            updated_credential
        )

        next_validation = min(
            now + self.validation_interval,
            updated_credential.expires_at
            - self.refresh_window,
        )

        self._validated_until[key] = max(
            now,
            next_validation,
        )

    async def _get_credential(
        self,
        key: CredentialKey,
    ) -> OAuthCredential:
        user_id, credential_kind = key

        credential = (
            await self.credential_repository.get(
                user_id,
                credential_kind,
            )
        )

        if credential is None:
            raise CredentialNotFoundError(
                "No OAuth credential is stored for "
                f"Twitch user {user_id!r} "
                f"({credential_kind.value})."
            )

        return credential

    def _can_use_cached(
        self,
        key: CredentialKey,
        credential: OAuthCredential,
        required_scopes: tuple[str, ...],
        now: int,
    ) -> bool:
        validated_until = self._validated_until.get(
            key,
            0,
        )

        if now >= validated_until:
            return False

        if credential.expires_within(
            self.refresh_window,
            now=now,
        ):
            return False

        self._require_scopes(
            credential.scopes,
            required_scopes,
        )

        return True

    def _lock_for(
        self,
        key: CredentialKey,
    ) -> asyncio.Lock:
        lock = self._locks.get(key)

        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock

        return lock

    @staticmethod
    def _make_key(
        twitch_user_id: str,
        credential_kind: OAuthCredentialKind,
    ) -> CredentialKey:
        user_id = str(twitch_user_id).strip()

        if not user_id:
            raise ValueError(
                "twitch_user_id cannot be empty."
            )

        return (
            user_id,
            OAuthCredentialKind(credential_kind),
        )

    @staticmethod
    def _normalize_scopes(
        scopes: Iterable[str],
    ) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    str(scope).strip()
                    for scope in scopes
                    if str(scope).strip()
                }
            )
        )

    @staticmethod
    def _require_scopes(
        actual_scopes: Iterable[str],
        required_scopes: Iterable[str],
    ) -> None:
        missing = (
            set(required_scopes)
            - set(actual_scopes)
        )

        if missing:
            raise MissingScopesError(missing)