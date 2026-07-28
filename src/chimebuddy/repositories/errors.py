class RepositoryError(RuntimeError):
    """Base error for repository operations."""


class AccountLinkNotVerifiedError(RepositoryError):
    """Raised when broadcaster ownership is not verified."""