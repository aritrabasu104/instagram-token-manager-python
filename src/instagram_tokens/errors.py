"""Sanitized errors: provider messages and credentials never enter exception text."""


class TokenError(RuntimeError):
    """Base authentication error."""


class ConfigurationError(TokenError):
    """The supplied configuration or state binding is inconsistent."""


class ValidationError(TokenError):
    """A credential did not meet the account or permission contract."""


class TransientError(TokenError):
    """A temporary failure or unresolved operation needs reconciliation."""


class RefreshRequired(ValidationError):
    """The application must recover authorization through its consent owner."""

    def __init__(self, health):
        self.health = health
        super().__init__("Instagram authorization recovery is required")


class GrantRejected(ValidationError):
    """An actual provider response proves a rejected grant."""

    def __init__(self, *, retryable=False):
        self.retryable = retryable
        super().__init__("Instagram token exchange was rejected")


class GraphError(TokenError):
    """Only numeric provider diagnostics are retained."""

    def __init__(self, *, http_status, code=None, subcode=None):
        self.http_status = int(http_status)
        self.code = code if type(code) is int else None
        self.subcode = subcode if type(subcode) is int else None
        super().__init__("Instagram Graph request was rejected")
