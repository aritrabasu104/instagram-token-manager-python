# Integrating the manager

An unresolved renewal always resumes or waits on its original receipt before
metadata repair or interactive recovery. In particular, `dispatching` and
`unknown` do not become `RefreshRequired` when local metadata expires. Returned
candidates retain their original validation and promotion path.

For a stale expiry file, `completed_lifetime(identity, record, token, now=...)`
identifies an unexpired completed receipt bound to the exact credential and
profile. `ensure()` uses this proof to restore the original issuance/expiry
after fresh remote validation, without another grant. The helper is read-only
and supplies no provider clearance. A changed credential, expired receipt,
binding error or current provider refusal retains its normal recovery gate.

`TokenClient` is a stateless HTTP API. `TokenManager` adds durable renewal and
session reuse using explicit application adapters. Importing either performs no
network or credential access.

## Identity and ownership

Create an `Identity` with your account key, expected username, Graph origin,
`SecretRef(service, account)` and an opaque binding fingerprint. The fingerprint
must cover the complete expected account/app/permission/credential-location
contract. Change it when that contract changes. Never use a raw credential as a
binding or account key.

Pass a callable `lock` returning a context manager. `FileLock(path)` supplies a
blocking POSIX cross-process lock; applications with an existing account owner
should pass that owner’s lock. Other operating systems require an equivalent
application-provided cross-process lock. All processes for one account must use
the same lock and store. Independent accounts use different locks.

## Credential vault

Pass an adapter implementing:

```python
read_secret(*, service, account) -> str | None
store_secret(*, service, account, label, secret) -> None
copy_item(*, source_service, source_account,
          destination_service, destination_account, label) -> bool
delete_item(*, service, account) -> None
```

Use an existing OS credential store or managed secret service. `copy_item` must
support replacing the destination safely. Candidates and rollback copies use
separate references in this same vault. No credential is written to a checkpoint.

## Checkpoints

The store implements `get(namespace, key)` and
`put(namespace, key, payload, expected_revision=revision)`. Reads return `None`
or an object with `payload` and `revision`; writes atomically compare the old
revision and return the new snapshot. Production stores must durably commit
before returning. `SQLiteStore(explicit_path)` is available for applications
without an existing store. No database or background process starts implicitly.

`RenewalState(identity, store)` stores only the current operation, credential
fingerprints, vault references, provider outcome, timestamps and cumulative
rejection counters. Do not edit unresolved records or reset them to obtain
another grant. Preserve the same state across restarts.

## Validation and metadata callbacks

`metadata_health(now)` returns `(metadata, health_or_none)`. It must authenticate
metadata’s binding and report expired/invalid credentials without inventing an
issuance time. Return `None` as health only when metadata is usable. Missing
metadata may report `Health(state="regeneration_required",
reason="metadata_missing", ...)`. Near-expiry renewal defaults to seven days.

`validator(token, *, use_metadata)` returns `Health`. It must verify the exact
account ID, username, professional-account type and required permission/capability
readback. `use_metadata=False` skips only local lifetime metadata, and never skips
remote account or permission validation. Wrong accounts or permissions must fail.

`metadata_writer(*, account_type, now, expires_at, expires_in, auth_source)`
atomically records the exact verified receipt and returns the canonical expiry
string. It receives no credential value. Never estimate a new lifetime for a lost
response. For Meta system-user credentials, retain actual introspection proof
rather than treating zero or missing expiry as a renewable Instagram token.

Pass either `client=TokenClient()` or `refresher=callable`, not both. A custom
refresher returns `TokenGrant` or `(token, expires_in)` and performs exactly one
grant call with no hidden retries. The manager commits intent before invoking it.

## Results and consent

`ensure()` reuses a valid session, with a successful validation snapshot reusable
for up to 60 seconds and bound to credential bytes, identity and exact metadata.
After a fresh provider refusal, call `manager.invalidate(the_rejected_token)` so
an older successful readback cannot hide that outcome. Direct Graph checks
are always fresh. `refresh()` performs an eligible refresh or coalesces an
already completed operation. A known token younger than 24 hours is reused.

Only explicit `.access_token` access reveals a credential. Use `.safe_dict()` for
logs; representations are redacted. Do not use unrestricted dataclass
serialization on credential objects.

Handle `RefreshRequired` after the manager releases the account lock. Your
existing consent/login owner must serialize interactive recovery globally and
preserve any in-flight or unknown authorization attempt. The library does not
open browsers or manufacture consent. Recheck the exact account before adopting
an externally recovered credential. Security/permission failures do not authorize
another grant or a new login attempt.

A provider-rejected current credential also raises `RefreshRequired`, even when
its saved expiry is in the future. The saved date cannot override a fresh
rejection. Its `health.recovery_action` is `reauthorize`; this is different from
`api_maintenance` for repairable lifetime metadata. Transient validation uses
`retry_validation` and account/permission mismatches use `repair_configuration`.
These labels are diagnostic only and never issue a grant or open a browser.

An application can remain entirely API based while a reusable authorization
exists. Initial authorization or revocation recovery remains an explicit
external dependency. A verified system-user credential with no scheduled expiry
avoids routine expiry renewal, but it can still be revoked. Do not treat a
publishing credential or an app secret as authority to issue replacement tokens.
