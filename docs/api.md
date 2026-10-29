# API inventory

Set the Graph version explicitly when making versioned reads. The origin must be
`https://graph.instagram.com` or `https://graph.facebook.com`; redirects and
ambient proxies are disabled. Request/response bodies are bounded to 1 MiB,
requests have a finite timeout and grant calls have no automatic HTTP retries.

| Purpose | Method | Endpoint |
|---|---|---|
| Instagram account identity | GET | `https://graph.instagram.com/{version}/me` |
| Meta Instagram asset identity | GET | `https://graph.facebook.com/{version}/{ig_user_id}` |
| Publishing capability | GET | `{graph_origin}/{version}/{ig_user_id}/content_publishing_limit` |
| Meta credential introspection | GET | `https://graph.facebook.com/{version}/debug_token` |
| Instagram authorization and consent | Interactive | `https://www.instagram.com/oauth/authorize` |
| Authorized-code exchange | POST | `https://api.instagram.com/oauth/access_token` |
| Long-lived exchange | GET | `https://graph.instagram.com/access_token` |
| Long-lived renewal | GET | `https://graph.instagram.com/refresh_access_token` |

`TokenClient.graph_get` covers versioned reads. `exchange_code`,
`exchange_long_lived` and `refresh_token` make one exchange after the caller’s
required pre-dispatch callback. The OAuth code and redirect must belong to the
original approved authorization; retain CSRF state and never replay unknown
code exchanges. A short-token response may omit its lifetime; the package
reports `expires_in=0` as unknown rather than inventing an expiry. Long-lived
exchanges require a real positive lifetime.

Instagram-login refresh requires a still-valid, eligible long-lived credential.
It cannot regenerate a missing/revoked credential, extend arbitrary system-user
credentials, grant new permissions or replace genuine login/consent. App secrets
and ordinary publishing tokens do not establish business administrator authority
to mint replacement system-user credentials.

For the platform’s current requirements, consult
[Meta’s Instagram platform documentation](https://developers.facebook.com/docs/instagram-platform/)
and your app’s approved configuration. Availability and granted permissions
remain provider-controlled. This independent client makes no claim that static
SDK inspection establishes authorization or a password-login API.
