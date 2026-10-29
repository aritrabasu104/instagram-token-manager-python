from datetime import UTC, datetime, timedelta
from pathlib import Path

from instagram_tokens import FileLock, Health, Identity, SecretRef, SQLiteStore, TokenManager
from instagram_tokens.state import digest

OLD = "synthetic-existing-credential-value"
NEW = "synthetic-renewed-credential-value"
NOW = datetime(2025, 1, 1, tzinfo=UTC)
LIFETIME = 60 * 86400


class Vault:
    def __init__(self):
        self.items = {}

    def read_secret(self, *, service, account):
        return self.items.get((service, account))

    def store_secret(self, *, service, account, label, secret):
        self.items[(service, account)] = secret

    def copy_item(
        self, *, source_service, source_account, destination_service, destination_account, label
    ):
        value = self.items.get((source_service, source_account))
        if value is None:
            return False
        self.items[(destination_service, destination_account)] = value
        return True

    def delete_item(self, *, service, account):
        self.items.pop((service, account), None)


class Fixture:
    def __init__(self, directory, name="example"):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.identity = Identity(
            name,
            "example_user",
            "https://graph.instagram.com",
            SecretRef("example-credential-store", name),
            digest(["example", name]),
        )
        self.vault = Vault()
        self.vault.items[(self.identity.target.service, self.identity.target.account)] = OLD
        self.store = SQLiteStore(self.root / "state.sqlite3")
        self.metadata = {"expires_at": (NOW + timedelta(days=3)).isoformat()}
        self.calls = 0
        self.fail_validation = False
        self.fail_write = False
        self.manager = TokenManager(
            identity=self.identity,
            store=self.store,
            vault=self.vault,
            metadata_health=self.metadata_health,
            validator=self.validate,
            metadata_writer=self.write,
            refresher=self.refresh,
            lock=FileLock(self.root / "account.lock"),
        )

    def metadata_health(self, now):
        if self.metadata is None:
            return None, self.health("regeneration_required", "metadata_missing")
        return self.metadata, None

    def health(self, state="valid", reason="checked", expiry=""):
        return Health(
            self.identity.profile_id,
            state,
            reason,
            NOW.isoformat(),
            self.identity.username,
            "example-account",
            "BUSINESS",
            expiry,
        )

    def validate(self, token, *, use_metadata):
        from instagram_tokens import TransientError

        if self.fail_validation and token == NEW:
            raise TransientError("temporary validation failure")
        return self.health(
            expiry=self.metadata.get("expires_at", "") if self.metadata and use_metadata else ""
        )

    def refresh(self, token):
        assert token == OLD
        self.calls += 1
        return NEW, LIFETIME

    def write(self, *, account_type, now, expires_at, expires_in, auth_source):
        if self.fail_write:
            raise OSError("synthetic metadata write failure")
        self.metadata = {
            "expires_at": expires_at.isoformat(),
            "expires_in": expires_in,
            "captured_at": now.isoformat(),
            "auth_source": auth_source,
        }
        return expires_at.isoformat()
