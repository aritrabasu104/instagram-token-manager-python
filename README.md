# Instagram Token Manager for Python

An independent Python package for Instagram token APIs, session reuse and durable
renewal across concurrent callers. Python 3.11–3.14; no runtime dependencies.

- Instagram-login long-lived token refresh and OAuth code/token exchange.
- Versioned Instagram/Meta Graph reads with bounded, credential-safe HTTP.
- One renewal per account, with shared state and application-owned credentials.
- Returned-candidate recovery, rollback and protection against replaying a grant
  after its response is lost.
- Independent-account concurrency, defaulting to 10 callers.

Missing, expired or revoked authorization may require genuine Meta login and
consent. The package reports that requirement; it does not automate passwords,
extract cookies or bypass account/security requirements. Meta system-user tokens
must use their actual account, permissions and introspection results rather than
Instagram-login refresh.

## Install

```sh
python -m pip install "git+https://github.com/aritrabasu104/instagram-token-manager-python.git@v0.1.1"
```

For reproducible deployments, replace the tag with a reviewed full commit SHA.
A PyPI release is not required to install this repository as a package.

## Import and use

```python
from instagram_tokens import TokenClient

client = TokenClient(version="v25.0")  # Choose a supported version for your app.
account = client.graph_get(existing_token, "me", {"fields": "id,username"})
```

Supply `existing_token` from your application’s credential store. No token,
password, cookie, app secret or account configuration is included in this repo.
The CLI exposes only package information and the API inventory:

```sh
instagram-tokens version
instagram-tokens list-apis
```

A low-level refresh requires a callback that durably reserves the original
operation before HTTP:

```python
from instagram_tokens import TokenClient

grant = TokenClient().refresh_token(
    existing_token,
    before_dispatch=reserve_original_refresh_intent,
)
persist_in_existing_credential_vault(grant.access_token)
print(grant.safe_dict())  # Lifetime only; credential value is excluded.
```

For concurrent or restartable applications, use `TokenManager` rather than
implementing grant recovery yourself. It accepts your existing vault, metadata
validator/writer, durable checkpoint store and account lock. See the runnable
adapter factory in [examples/session_manager.py](examples/session_manager.py)
and the [integration guide](docs/integration.md).

```python
from instagram_tokens import map_accounts

sessions = map_accounts(lambda manager: manager.ensure(), managers)
# Up to 10 independent accounts; one account keeps its own renewal lock.
```

`TokenManager.ensure()` never opens a browser. Catch `RefreshRequired` when a
current credential is missing, expired or provider rejected; the existing login
owner must restore that authorization. `error.health.safe_dict()` includes a
credential-free `recovery_action` so callers can distinguish reauthorization,
API metadata maintenance, temporary validation failures and configuration fixes.

## Documentation

- [Integration, adapter contracts and session lifecycle](docs/integration.md)
- [API inventory and consent boundaries](docs/api.md)
- [Concurrency and failure recovery](docs/concurrency.md)
- [Security and sensitive-data handling](SECURITY.md)

## Development

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
python -m instagram_tokens list-apis
```

Tests use synthetic credentials and temporary local state. No live account is
required. This project is independent of Meta and is not an official Meta SDK.
