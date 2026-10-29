"""Durable refresh and rollback using application-owned validation and storage."""

from datetime import timedelta

from .client import MAX_TOKEN_LIFETIME
from .errors import (
    ConfigurationError,
    GrantRejected,
    RefreshRequired,
    TransientError,
    ValidationError,
)
from .models import TokenGrant, TokenResult, iso, parse_time, plausible_token
from .state import credential_epoch, token_binding


def renew(
    identity,
    *,
    state_factory,
    bridge,
    read_current,
    metadata_health,
    validator,
    metadata_writer,
    token_refresher,
    now,
    skip_metadata_gate=False,
    metadata_auth_source="instagram_long_lived_token_refresh",
):
    """Resume one refresh under the application's existing account lock."""

    def inspect_token(token, *, use_metadata):
        health = validator(token, use_metadata=use_metadata)
        return (health, token if health.valid else None)

    try:
        state = state_factory()
    except Exception:
        raise ConfigurationError("Instagram API renewal state is unavailable") from None
    metadata, local_health = metadata_health(now)
    target_token = read_current()
    value = state.value
    pending = bool(
        value and value.get("status") not in {"complete", "rejected", "candidate_rejected"}
    )
    candidate = state.candidate(bridge) if pending else None
    if pending:
        current_binding = token_binding(target_token) if target_token else ""
        expected = {value["prior_token_binding"], value.get("candidate_token_binding")}
        if current_binding not in expected:
            raise ValidationError(
                "An original Instagram API renewal requires credential reconciliation"
            )
        if value.get("status") != "reserved" and (not candidate):
            raise TransientError(
                "Instagram API refresh outcome is unknown; another grant was not dispatched"
            )
    else:
        if (
            value.get("status") == "complete"
            and target_token
            and (value.get("candidate_token_binding") == token_binding(target_token))
            and (local_health is not None)
            and skip_metadata_gate
        ):
            receipt_time = parse_time(value["received_at"], label="API received_at")
            receipt_expiry = receipt_time + timedelta(seconds=value["expires_in"])
            if receipt_expiry > now:
                health, token = inspect_token(target_token, use_metadata=False)
                result = _ensured(identity, health, token)
                result.expires_at = metadata_writer(
                    account_type=health.account_type,
                    now=receipt_time,
                    expires_at=receipt_expiry,
                    expires_in=value["expires_in"],
                    auth_source=value["auth_source"],
                )
                _delete_staging(state, bridge)
                return result
        if (
            value.get("status") == "complete"
            and target_token
            and (value.get("candidate_token_binding") == token_binding(target_token))
            and (
                0
                <= (now - parse_time(value["received_at"], label="API received_at")).total_seconds()
                < 86400
            )
            and (local_health is None)
        ):
            _delete_staging(state, bridge)
            health, token = inspect_token(target_token, use_metadata=True)
            return _ensured(identity, health, token)
        if (
            value.get("status") in {"rejected", "candidate_rejected"}
            and target_token
            and (value.get("epoch") == credential_epoch(identity.binding, target_token, metadata))
        ):
            if not value.get("retry_after") or now.timestamp() < value["retry_after"]:
                error = TransientError if value.get("retryable") else ValidationError
                raise error(
                    "The original Instagram API renewal remains rejected; "
                    "no new grant was dispatched"
                )
        if not skip_metadata_gate and local_health is not None:
            if local_health.may_regenerate:
                raise RefreshRequired(local_health)
            raise ValidationError("Instagram metadata blocks API refresh")
        if identity.origin != "https://graph.instagram.com":
            raise ValidationError(
                "Instagram refresh is inapplicable to Meta system-user credentials"
            )
        health, existing_token = inspect_token(target_token, use_metadata=False)
        if not health.valid or not existing_token:
            if health.may_regenerate:
                raise RefreshRequired(health)
            error = TransientError if health.state == "transient_failure" else ValidationError
            raise error(
                "Instagram token could not be live-validated; API refresh was not attempted"
            )
        if metadata and metadata.get("captured_at") and (local_health is None):
            captured = parse_time(metadata["captured_at"], label="captured_at")
            if 0 <= (now - captured).total_seconds() < 86400:
                health, token = inspect_token(target_token, use_metadata=True)
                return _ensured(identity, health, token)
        state.reserve(existing_token, metadata, at=iso(now))
        target_token = existing_token
    if not candidate:
        state.save(
            status="dispatching",
            dispatched_at=iso(now),
            dispatch_count=state.value.get("dispatch_count", 0) + 1,
        )
        try:
            refreshed = token_refresher(target_token)
        except GrantRejected as exc:
            rejections = state.value.get("rejection_count", 0) + 1
            state.save(
                status="rejected",
                rejection_count=rejections,
                retryable=exc.retryable,
                retry_after=now.timestamp() + 60 if exc.retryable and rejections < 3 else None,
            )
            error = TransientError if exc.retryable else ValidationError
            raise error(
                "Instagram API refresh was rejected; browser regeneration was not attempted"
            ) from None
        except Exception:
            state.save(status="unknown")
            raise TransientError(
                "Instagram API refresh outcome is unknown; another grant was not dispatched"
            ) from None
        if isinstance(refreshed, TokenGrant):
            refreshed = (refreshed.access_token, refreshed.expires_in)
        if not isinstance(refreshed, tuple) or len(refreshed) != 2:
            state.save(status="unknown")
            raise ValidationError("Instagram API refresh returned an invalid credential")
        candidate, raw_lifetime = refreshed
        try:
            expires_in = int(raw_lifetime)
            lifetime = timedelta(seconds=expires_in)
        except (ValueError, TypeError, OverflowError):
            lifetime = timedelta(0)
        if not plausible_token(candidate) or not timedelta(0) < lifetime <= MAX_TOKEN_LIFETIME:
            state.save(status="unknown")
            raise ValidationError("Instagram API refresh returned an invalid credential")
        state.save(
            status="response_received",
            received_at=iso(now),
            expires_in=expires_in,
            candidate_token_binding=token_binding(candidate),
            auth_source=metadata_auth_source,
        )
        coordinates, _, _ = state.coordinates()
        try:
            bridge.store_secret(
                service=coordinates[0],
                account=coordinates[1],
                label=f"Instagram refresh candidate @{identity.username}",
                secret=candidate,
            )
        except Exception:
            raise TransientError("Instagram API candidate staging needs reconciliation") from None
    if token_binding(candidate) != state.value.get("candidate_token_binding"):
        raise ValidationError("The retained Instagram API candidate binding changed")
    received_at = parse_time(state.value["received_at"], label="API received_at")
    expires_at = received_at + timedelta(seconds=state.value["expires_in"])
    if expires_at <= now:
        raise ValidationError("The retained Instagram API candidate expired before promotion")
    try:
        health, verified = inspect_token(candidate, use_metadata=False)
    except Exception:
        raise TransientError(
            "The retained Instagram API candidate awaits live validation; "
            "no new grant was dispatched"
        ) from None
    if not health.valid or not verified:
        if health.state == "transient_failure":
            raise TransientError("The retained Instagram API candidate awaits live validation")
        state.save(status="candidate_rejected", reason=health.reason)
        _delete_staging(state, bridge)
        raise ValidationError(
            "Instagram API candidate failed account or publishing-permission "
            f"validation ({health.reason})"
        )
    candidate_coordinates, backup_coordinates, target_coordinates = state.coordinates()
    current = bridge.read_secret(service=target_coordinates[0], account=target_coordinates[1])
    if token_binding(current or "") == state.value["prior_token_binding"]:
        try:
            backed_up = bridge.copy_item(
                source_service=target_coordinates[0],
                source_account=target_coordinates[1],
                destination_service=backup_coordinates[0],
                destination_account=backup_coordinates[1],
                label=f"Instagram refresh rollback @{identity.username}",
            )
        except Exception:
            backed_up = False
        if not backed_up:
            raise TransientError("The existing Instagram credential awaits a secure rollback copy")
    elif token_binding(current or "") != state.value["candidate_token_binding"]:
        raise ValidationError("Instagram credential changed before API promotion")
    state.save(status="promoting")
    try:
        copied = bridge.copy_item(
            source_service=candidate_coordinates[0],
            source_account=candidate_coordinates[1],
            destination_service=target_coordinates[0],
            destination_account=target_coordinates[1],
            label=f"Instagram access token @{identity.username}",
        )
        if not copied:
            raise ValueError("Candidate unavailable")
        expiry = metadata_writer(
            account_type=health.account_type,
            now=received_at,
            expires_at=expires_at,
            expires_in=state.value["expires_in"],
            auth_source=state.value["auth_source"],
        )
    except Exception:
        if not _restore(bridge, backup_coordinates, target_coordinates):
            state.save(status="rollback_required")
            raise ValidationError(
                "Instagram API refresh requires credential vault recovery"
            ) from None
        state.save(status="response_received")
        raise ValidationError(
            "Instagram API promotion failed; the previous credential was restored "
            "and its candidate retained"
        ) from None
    state.save(status="complete", completed_at=iso(now))
    _delete_staging(state, bridge)
    return TokenResult(
        profile_id=identity.profile_id,
        username=health.username,
        ig_user_id=health.ig_user_id,
        account_type=health.account_type,
        expires_at=expiry,
        regenerated=True,
        _access_token=candidate,
        refreshed=True,
    )


def _ensured(identity, health, token):
    if not health.valid or not token:
        if health.may_regenerate:
            raise RefreshRequired(health)
        error = TransientError if health.state == "transient_failure" else ValidationError
        raise error("Instagram credential failed live validation; another grant was not dispatched")
    return TokenResult(
        profile_id=identity.profile_id,
        username=health.username,
        ig_user_id=health.ig_user_id,
        account_type=health.account_type,
        expires_at=health.expires_at,
        regenerated=False,
        _access_token=token,
    )


def _delete_staging(state, bridge):
    for service, account in state.coordinates()[:2]:
        try:
            bridge.delete_item(service=service, account=account)
        except Exception:
            pass


def _restore(bridge, backup, target):
    try:
        return bridge.copy_item(
            source_service=backup[0],
            source_account=backup[1],
            destination_service=target[0],
            destination_account=target[1],
            label="Instagram credential",
        )
    except Exception:
        return False
