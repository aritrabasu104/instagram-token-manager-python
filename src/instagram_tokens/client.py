"""Explicit Instagram/Meta OAuth and Graph calls; no automatic grant retries."""

import json
import re
from datetime import timedelta
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request

from .errors import ConfigurationError, GrantRejected, GraphError, TransientError, ValidationError
from .http import read_bounded, urlopen
from .models import TokenGrant, plausible_token

MAX_TOKEN_LIFETIME = timedelta(days=366)
ORIGINS = frozenset({"https://graph.instagram.com", "https://graph.facebook.com"})


def _numeric_error(payload, status):
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    if not isinstance(error, dict):
        error = {}
    return GraphError(
        http_status=status, code=error.get("code"), subcode=error.get("error_subcode")
    )


class TokenClient:
    """Stateless API client. Every grant requires a pre-dispatch callback."""

    def __init__(
        self, *, origin="https://graph.instagram.com", version=None, timeout=30, opener=None
    ):
        if origin not in ORIGINS or (
            version is not None and not re.fullmatch(r"v[1-9][0-9]*\.0", version)
        ):
            raise ConfigurationError("Invalid Graph origin or version")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < timeout <= 120
        ):
            raise ConfigurationError("Invalid API timeout")
        self.origin, self.version, self.timeout = origin, version, timeout
        self._open = opener or urlopen

    def _json(self, request, *, grant=False):
        try:
            with self._open(request, timeout=self.timeout) as response:
                status = int(getattr(response, "status", 200))
                raw = read_bounded(response)
        except HTTPError as error:
            try:
                status = int(error.code)
                if grant:
                    if 400 <= status < 500:
                        raise GrantRejected(retryable=status == 429) from None
                    raise TransientError("Instagram token exchange outcome is unknown") from None
                try:
                    payload = json.loads(read_bounded(error))
                except Exception:
                    payload = {}
                raise _numeric_error(payload, status) from None
            finally:
                try:
                    error.close()
                except Exception:
                    pass
        except Exception:
            raise TransientError("Instagram API transport is unavailable") from None
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise TransientError("Instagram API returned invalid JSON") from None
        if not isinstance(payload, dict):
            raise TransientError("Instagram API returned an invalid response")
        if status >= 400 or "error" in payload:
            if grant:
                if 400 <= status < 500:
                    raise GrantRejected(retryable=status == 429)
                raise TransientError("Instagram token exchange outcome is unknown")
            raise _numeric_error(payload, status)
        return payload

    def graph_get(self, token, path, params=None):
        if not self.version or not plausible_token(token):
            raise ConfigurationError("Graph reads require a version and credential")
        if (
            not isinstance(path, str)
            or not re.fullmatch(r"[A-Za-z0-9_/-]+", path)
            or path.startswith("/")
            or "//" in path
        ):
            raise ConfigurationError("Graph path must be relative to the configured origin")
        query = urlencode({key: str(value) for key, value in (params or {}).items()})
        request = Request(
            f"{self.origin}/{self.version}/{path}" + ("?" + query if query else ""), method="GET"
        )
        request.add_header("Authorization", f"Bearer {token}")
        return self._json(request)

    def _grant(self, url, *, before_dispatch, form=None, require_lifetime=True):
        if not callable(before_dispatch):
            raise ConfigurationError("A durable pre-dispatch callback is required")
        data = urlencode(form).encode() if form is not None else None
        request = Request(url, data=data, method="POST" if data is not None else "GET")
        request.add_header("Accept", "application/json")
        request.add_header("Cache-Control", "no-store")
        if data is not None:
            request.add_header("Content-Type", "application/x-www-form-urlencoded")
        before_dispatch()
        payload = self._json(request, grant=True)
        try:
            expires_in = int(payload.get("expires_in", 0))
            lifetime = timedelta(seconds=expires_in)
        except (ValueError, TypeError, OverflowError):
            lifetime = timedelta(0)
        token = payload.get("access_token")
        if (
            not plausible_token(token)
            or not (
                timedelta(0) < lifetime <= MAX_TOKEN_LIFETIME
                or (not require_lifetime and "expires_in" not in payload)
            )
            or str(payload.get("token_type") or "bearer").casefold() != "bearer"
        ):
            raise ValidationError("Instagram returned an invalid credential")
        return TokenGrant(token, expires_in)

    def refresh_token(self, token, *, before_dispatch):
        if self.origin != "https://graph.instagram.com" or not plausible_token(token):
            raise ValidationError("Instagram refresh requires an Instagram-login credential")
        query = urlencode({"grant_type": "ig_refresh_token", "access_token": token})
        return self._grant(
            f"{self.origin}/refresh_access_token?{query}", before_dispatch=before_dispatch
        )

    def exchange_code(self, *, client_id, client_secret, code, redirect_uri, before_dispatch):
        if not all(
            isinstance(value, str) and value
            for value in (client_id, client_secret, code, redirect_uri)
        ):
            raise ConfigurationError("The original authorized code and app binding are required")
        return self._grant(
            "https://api.instagram.com/oauth/access_token",
            before_dispatch=before_dispatch,
            require_lifetime=False,
            form={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )

    def exchange_long_lived(self, token, *, client_secret, before_dispatch):
        if not plausible_token(token) or not isinstance(client_secret, str) or not client_secret:
            raise ConfigurationError("A short-lived credential and app secret are required")
        query = urlencode(
            {
                "grant_type": "ig_exchange_token",
                "client_secret": client_secret,
                "access_token": token,
            }
        )
        return self._grant(
            f"https://graph.instagram.com/access_token?{query}", before_dispatch=before_dispatch
        )
