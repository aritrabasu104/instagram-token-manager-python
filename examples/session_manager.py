"""Connect existing credential, validation and metadata adapters to the manager."""

from instagram_tokens import FileLock, Identity, SecretRef, TokenClient, TokenManager


def create_manager(
    *,
    account_key,
    username,
    binding_fingerprint,
    credential_service,
    credential_account,
    checkpoint_store,
    credential_vault,
    inspect_metadata,
    validate_credential,
    write_metadata,
    account_lock_path,
):
    identity = Identity(
        profile_id=account_key,
        username=username,
        origin="https://graph.instagram.com",
        target=SecretRef(credential_service, credential_account),
        binding=binding_fingerprint,
    )
    return TokenManager(
        identity=identity,
        store=checkpoint_store,
        vault=credential_vault,
        metadata_health=inspect_metadata,
        validator=validate_credential,
        metadata_writer=write_metadata,
        client=TokenClient(),
        lock=FileLock(account_lock_path),
    )
