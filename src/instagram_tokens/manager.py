"""Application-owned session orchestration; interactive consent stays external."""

from datetime import UTC, datetime, timedelta

from .errors import ConfigurationError, RefreshRequired, TokenError, TransientError
from .models import Health, parse_time
from .renewal import _ensured, completed_lifetime, renew
from .state import RenewalState, cached_health, invalidate_health, retain_health

DEFAULT_RENEWAL_MARGIN = timedelta(days=7)


class TokenManager:
    """Renew under one account lock using injected vault and metadata adapters.

    All callbacks run inside that lock. They must not begin interactive login;
    handle RefreshRequired after the call releases its lock.
    """

    def __init__(
        self,
        *,
        identity,
        store,
        vault,
        metadata_health,
        validator,
        metadata_writer,
        lock,
        refresher=None,
        client=None,
        state_factory=None,
        renewal_margin=DEFAULT_RENEWAL_MARGIN,
    ):
        self.identity, self.store, self.vault = identity, store, vault
        self.metadata_health, self.validator, self.writer = (
            metadata_health,
            validator,
            metadata_writer,
        )
        if (refresher is None) == (client is None):
            raise ConfigurationError("Provide exactly one token client or refresh callback")
        self.refresher = refresher or (
            lambda token: client.refresh_token(token, before_dispatch=lambda: None)
        )
        self.lock, self.renewal_margin = lock, renewal_margin
        self.state_factory = state_factory or (lambda: RenewalState(identity, store))

    def _refresh_locked(
        self, now, *, repair_metadata=False, auth_source="instagram_long_lived_token_refresh"
    ):
        return renew(
            self.identity,
            state_factory=self.state_factory,
            bridge=self.vault,
            read_current=lambda: self.vault.read_secret(
                service=self.identity.target.service, account=self.identity.target.account
            ),
            metadata_health=self.metadata_health,
            validator=self.validator,
            metadata_writer=self.writer,
            token_refresher=self.refresher,
            now=now,
            skip_metadata_gate=repair_metadata,
            metadata_auth_source=auth_source,
        )

    def refresh(
        self, *, now=None, repair_metadata=False, auth_source="instagram_long_lived_token_refresh"
    ):
        with self.lock():
            try:
                return self._refresh_locked(
                    now or datetime.now(UTC),
                    repair_metadata=repair_metadata,
                    auth_source=auth_source,
                )
            except TokenError:
                raise
            except Exception:
                raise TransientError("Instagram renewal needs credential reconciliation") from None

    def invalidate(self, token):
        """Discard cached validation for the exact credential a provider rejected."""
        with self.lock():
            try:
                invalidate_health(self.store, self.identity, token)
            except Exception:
                raise TransientError("Instagram validation cache is unavailable") from None

    def ensure(self, *, now=None):
        with self.lock():
            try:
                moment = now or datetime.now(UTC)
                metadata, local_health = self.metadata_health(moment)
                pending = self.state_factory().value
                if pending and pending.get("status") not in {
                    "complete", "rejected", "candidate_rejected",
                }:
                    return self._refresh_locked(moment, repair_metadata=True)
                if local_health is not None:
                    if local_health.may_regenerate and local_health.reason == "metadata_expired":
                        token = self.vault.read_secret(
                            service=self.identity.target.service, account=self.identity.target.account
                        )
                        if completed_lifetime(self.identity, pending, token, now=moment) is not None:
                            return self._refresh_locked(moment, repair_metadata=True)
                    if local_health.reason in {
                        "metadata_missing",
                        "metadata_expiry_invalid",
                        "metadata_near_expiry",
                    }:
                        return self._refresh_locked(moment, repair_metadata=True)
                    if local_health.may_regenerate:
                        raise RefreshRequired(local_health)
                    raise ConfigurationError("Token metadata failed its binding contract")
                if (
                    self.identity.origin == "https://graph.instagram.com"
                    and metadata
                    and metadata.get("expires_at")
                    and parse_time(metadata["expires_at"]) <= moment + self.renewal_margin
                ):
                    return self._refresh_locked(moment)
                token = self.vault.read_secret(
                    service=self.identity.target.service, account=self.identity.target.account
                )
                saved = (
                    cached_health(
                        self.store, self.identity, token, now=moment.timestamp(), metadata=metadata
                    )
                    if token
                    else None
                )
                health = Health(**saved) if saved else self.validator(token, use_metadata=True)
                result = _ensured(self.identity, health, token)
                if not saved:
                    retain_health(
                        self.store,
                        self.identity,
                        token,
                        health.__dict__,
                        now=moment.timestamp(),
                        metadata=metadata,
                    )
                return result
            except TokenError:
                raise
            except Exception:
                raise TransientError("Instagram session validation is unavailable") from None
