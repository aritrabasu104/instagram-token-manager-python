"""Instagram token APIs and durable renewal with application-owned credentials."""

from .client import TokenClient
from .errors import (
    ConfigurationError,
    GrantRejected,
    GraphError,
    RefreshRequired,
    TokenError,
    TransientError,
    ValidationError,
)
from .locks import DEFAULT_MAX_PARALLEL_REQUESTS, FileLock, map_accounts
from .manager import TokenManager
from .models import Health, Identity, SecretRef, TokenGrant, TokenResult
from .state import RenewalState
from .storage import SQLiteStore

__version__ = "0.1.1"
__all__ = [
    "TokenClient",
    "TokenManager",
    "Health",
    "Identity",
    "SecretRef",
    "TokenGrant",
    "TokenResult",
    "RenewalState",
    "SQLiteStore",
    "FileLock",
    "map_accounts",
    "DEFAULT_MAX_PARALLEL_REQUESTS",
    "TokenError",
    "ConfigurationError",
    "ValidationError",
    "TransientError",
    "RefreshRequired",
    "GrantRejected",
    "GraphError",
]
