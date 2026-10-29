"""Credential-free renewal checkpoints with an injected compare-and-swap store."""

import hashlib
import json


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def token_binding(token):
    return hashlib.sha256(token.encode()).hexdigest()


def credential_epoch(binding, token, metadata):
    return digest(
        {
            "profile": binding,
            "credential": token_binding(token),
            "lifetime": {
                key: (metadata or {}).get(key)
                for key in (
                    "captured_at",
                    "expires_at",
                    "expires_in",
                    "auth_source",
                    "browser_request_id",
                )
            },
        }
    )


class RenewalState:
    """The caller holds its account lock across each CAS and provider dispatch."""

    def __init__(self, identity, store, *, namespace="instagram-token-api"):
        self.identity = identity
        self.namespace = namespace
        self.store = store
        self.key = "refresh/" + identity.profile_id
        self.record = self.store.get(self.namespace, self.key)
        self.value = dict(self.record.payload) if self.record else {}
        if self.value and self.value.get("profile_binding") != identity.binding:
            if self.value.get("status") not in {"complete", "rejected", "candidate_rejected"}:
                raise ValueError(
                    "An original Instagram API renewal belongs to another profile binding"
                )
            self.value = {}

    def save(self, **changes):
        self.value.update(changes)
        self.record = self.store.put(
            self.namespace,
            self.key,
            self.value,
            expected_revision=self.record.revision if self.record else 0,
        )

    def reserve(self, token, metadata, *, at):
        epoch = credential_epoch(self.identity.binding, token, metadata)
        identifier = digest([self.identity.profile_id, epoch])[:24]
        predecessor = self.value.get("operation_id")
        if self.value.get("epoch") == epoch and self.value.get("status") == "rejected":
            self.save(status="reserved")
            return
        self.value = {
            "schema": "instagram.api-refresh.v1",
            "profile_binding": self.identity.binding,
            "operation_id": identifier,
            "epoch": epoch,
            "prior_token_binding": token_binding(token),
            "status": "reserved",
            "started_at": at,
            "candidate": {
                "service": (
                    self.identity.candidate_prefix + f"{self.identity.profile_id}.{identifier}"
                ),
                "account": self.identity.username,
            },
            "backup": {
                "service": (
                    self.identity.backup_prefix + f"{self.identity.profile_id}.{identifier}"
                ),
                "account": self.identity.username,
            },
        }
        if predecessor:
            self.value["predecessor_operation_id"] = predecessor
        self.save()

    def coordinates(self):
        return tuple(
            (self.value[name]["service"], self.value[name]["account"])
            for name in ("candidate", "backup")
        ) + ((self.identity.target.service, self.identity.target.account),)

    def candidate(self, bridge):
        item = self.value.get("candidate")
        return (
            bridge.read_secret(service=item["service"], account=item["account"]) if item else None
        )


def cached_health(
    store, identity, token, *, now, metadata=None, max_age=60, namespace="instagram-token-api"
):
    saved = store.get(namespace, "validation/" + identity.profile_id)
    value = saved.payload if saved else {}
    if (
        value.get("profile_binding") == identity.binding
        and value.get("token_binding") == token_binding(token)
        and value.get("metadata_binding") == digest(metadata)
        and 0 <= now - value.get("checked_at", 0) < max_age
    ):
        return value.get("health")
    return None


def retain_health(
    store, identity, token, health, *, now, metadata=None, namespace="instagram-token-api"
):
    key = "validation/" + identity.profile_id
    saved = store.get(namespace, key)
    store.put(
        namespace,
        key,
        {
            "schema": "instagram.api-validation.v1",
            "profile_binding": identity.binding,
            "token_binding": token_binding(token),
            "checked_at": now,
            "metadata_binding": digest(metadata),
            "health": health,
        },
        expected_revision=saved.revision if saved else 0,
    )


def invalidate_health(store, identity, token, *, namespace="instagram-token-api"):
    """A fresh refusal cannot be hidden by an older successful health snapshot."""
    key = "validation/" + identity.profile_id
    saved = store.get(namespace, key)
    if (
        saved
        and saved.payload.get("profile_binding") == identity.binding
        and saved.payload.get("token_binding") == token_binding(token)
    ):
        value = dict(saved.payload)
        value["health"] = None
        try:
            store.put(namespace, key, value, expected_revision=saved.revision)
        except Exception:
            # A newer result/credential retains its own CAS. If storage itself
            # is unavailable, fail closed instead of returning a cached token.
            latest = store.get(namespace, key)
            if latest and latest.revision == saved.revision:
                raise
