"""Low-level usage. Supply an application-owned durable reservation callback."""

from instagram_tokens import TokenClient


def refresh_existing_token(token: str, reserve_original_intent):
    client = TokenClient()
    grant = client.refresh_token(token, before_dispatch=reserve_original_intent)
    # Persist through your existing credential vault before another network call.
    # Return the private value only to authorized application code.
    return grant
