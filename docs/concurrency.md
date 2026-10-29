# Concurrency and recovery

One account’s original lock owns validation, grant admission, candidate custody,
promotion and rollback. Every refresh reloads current state after locking. Ten
simultaneous callers share one completed renewal, including providers returning
the same token bytes. Different accounts can proceed together through
`map_accounts`, whose default and maximum concurrency are 10.

The manager records intent before dispatch. It stages a returned candidate in
the supplied vault before a later account-validation call can fail. Validation
outages and interrupted promotion retain that same candidate and original
expiry. Metadata failure restores the prior credential and preserves the
candidate for reconciliation.

A transport timeout, invalid response or server failure leaves the original
grant unknown. Subsequent calls do not submit another grant. An actual HTTP 429
rejection shares a 60-second cooldown and at most two retries on that operation.
Restarts do not reset its counter. Other definite rejections remain rejected.

An unknown grant also blocks a new authorization request through `ensure()`,
including when local metadata later expires or disappears. A successful
completed receipt may repair a stale expiry only for its exact current
credential, with fresh validation and its original lifetime preserved.

After validation succeeds, the current credential is backed up, the candidate
is promoted, exact lifetime metadata is committed and temporary vault references
are deleted. The application remains responsible for its vault’s durability,
cleanup failures and any external consent recovery. There is no watcher,
background refresher, scheduler or automatic browser fallback.
