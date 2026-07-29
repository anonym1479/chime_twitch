class RepositoryError(RuntimeError):
    """Base error for repository operations."""


class AccountLinkNotVerifiedError(RepositoryError):
    """Raised when broadcaster ownership is not verified."""

class DuplicateTriggerNameError(RepositoryError):
    """Raised when a broadcaster already has this trigger name."""

class RepositoryError(RuntimeError):
    """Base error for repository operations."""


class AccountLinkNotVerifiedError(RepositoryError):
    """Raised when broadcaster ownership is not verified."""


class DuplicateTriggerNameError(RepositoryError):
    """Raised when a broadcaster already has this trigger name."""


class PendingAccountLinkSessionError(RepositoryError):
    """Raised when a Discord user already has a pending link session."""

class OpenBroadcasterRequestError(RepositoryError):
    """Raised when an account already has an open broadcaster request."""

class ActiveBlacklistEntryError(RepositoryError):
    """Raised when an identity is already actively blacklisted."""

class BroadcasterPanelExistsError(RepositoryError):
    """Raised when a broadcaster request already has a private panel."""