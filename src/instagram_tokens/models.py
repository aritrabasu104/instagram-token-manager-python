"""Application-supplied account bindings and redacted credential results."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class SecretRef:
    service: str
    account: str


@dataclass(frozen=True)
class Identity:
    profile_id: str
    username: str
    origin: str
    target: SecretRef
    binding: str
    candidate_prefix: str = "instagram-token-manager.candidate."
    backup_prefix: str = "instagram-token-manager.backup."


@dataclass(frozen=True)
class Health:
    profile_id: str
    state: str
    reason: str
    checked_at: str
    username: str
    ig_user_id: str
    account_type: str = ""
    expires_at: str = ""

    @property
    def valid(self):
        return self.state == "valid"

    @property
    def may_regenerate(self):
        return self.state == "regeneration_required"

    @property
    def recovery_action(self):
        """Describe the next safe operation without starting authorization."""
        if self.valid:
            return "reuse"
        if self.state == "transient_failure":
            return "retry_validation"
        if self.may_regenerate:
            if self.reason in {"metadata_missing", "metadata_expiry_invalid", "metadata_near_expiry"}:
                return "api_maintenance"
            return "reauthorize"
        return "repair_configuration"

    def safe_dict(self):
        return {**self.__dict__, "recovery_action": self.recovery_action, "secret_exposed": False}


@dataclass(repr=False)
class TokenGrant:
    access_token: str = field(repr=False)
    expires_in: int

    def __repr__(self):
        return f"TokenGrant(access_token=<redacted>, expires_in={self.expires_in!r})"

    def safe_dict(self):
        return {"expires_in": self.expires_in, "secret_exposed": False}


@dataclass(repr=False)
class TokenResult:
    profile_id: str
    username: str
    ig_user_id: str
    account_type: str
    expires_at: str
    regenerated: bool
    _access_token: str = field(repr=False)
    refreshed: bool = False

    @property
    def access_token(self):
        return self._access_token

    def __repr__(self):
        return f"TokenResult(profile_id={self.profile_id!r}, access_token=<redacted>)"

    def safe_dict(self):
        return {key: value for key, value in self.__dict__.items() if key != "_access_token"} | {
            "secret_exposed": False
        }


def iso(value):
    return value.astimezone(UTC).isoformat()


def parse_time(value, *, label="timestamp"):
    from .errors import ConfigurationError

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone missing")
        return parsed.astimezone(UTC)
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise ConfigurationError(f"Invalid {label}") from None


def plausible_token(value):
    return bool(
        isinstance(value, str)
        and 20 <= len(value) <= 16384
        and value.isascii()
        and all(0x21 <= ord(character) <= 0x7E for character in value)
    )
