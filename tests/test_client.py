import io
import json
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

from helpers import LIFETIME, NEW, OLD

from instagram_tokens import (
    ConfigurationError,
    GrantRejected,
    GraphError,
    TokenClient,
    TokenGrant,
    TransientError,
    ValidationError,
)
from instagram_tokens.http import MAX_RESPONSE_BYTES, NoRedirect


class Response(io.BytesIO):
    status = 200


class ClientTests(unittest.TestCase):
    def client(self, payload=None):
        self.requests = []

        def open(request, **kwargs):
            self.requests.append((request, kwargs))
            return Response(
                json.dumps(payload or {"access_token": NEW, "expires_in": LIFETIME}).encode()
            )

        return TokenClient(version="v25.0", opener=open)

    def test_refresh_has_original_intent_before_http(self):
        client = self.client()
        events = []
        original = client._open

        def open(*args, **kwargs):
            self.assertEqual(events, ["intent"])
            return original(*args, **kwargs)

        client._open = open
        grant = client.refresh_token(OLD, before_dispatch=lambda: events.append("intent"))
        self.assertEqual(grant.access_token, NEW)
        request, options = self.requests[0]
        self.assertEqual(urlparse(request.full_url).path, "/refresh_access_token")
        self.assertEqual(
            parse_qs(urlparse(request.full_url).query)["grant_type"], ["ig_refresh_token"]
        )
        self.assertEqual(options["timeout"], 30)
        self.assertNotIn(NEW, repr(grant) + json.dumps(grant.safe_dict()))

    def test_missing_intent_never_dispatches(self):
        with self.assertRaises(ConfigurationError):
            self.client().refresh_token(OLD, before_dispatch=None)
        self.assertFalse(self.requests)

    def test_meta_system_user_never_uses_instagram_refresh(self):
        client = TokenClient(
            origin="https://graph.facebook.com", opener=lambda *a, **k: self.fail("HTTP")
        )
        with self.assertRaises(ValidationError):
            client.refresh_token(OLD, before_dispatch=lambda: None)

    def test_transport_error_does_not_echo_credential_url(self):
        def failed(*a, **k):
            raise URLError("https://example.invalid/?access_token=" + OLD)

        client = TokenClient(opener=failed)
        with self.assertRaises(TransientError) as caught:
            client.refresh_token(OLD, before_dispatch=lambda: None)
        self.assertNotIn(OLD, str(caught.exception))

    def test_only_actual_4xx_response_proves_rejection(self):
        for status, error_type in (
            (400, GrantRejected),
            (429, GrantRejected),
            (500, TransientError),
            (302, TransientError),
        ):

            def failed(*a, status=status, **k):
                raise HTTPError("https://example.invalid/" + OLD, status, "", {}, io.BytesIO(b"{}"))

            with self.subTest(status=status), self.assertRaises(error_type) as caught:
                TokenClient(opener=failed).refresh_token(OLD, before_dispatch=lambda: None)
            self.assertNotIn(OLD, str(caught.exception))
            if status == 429:
                self.assertTrue(caught.exception.retryable)

    def test_invalid_or_oversize_response_is_sanitized(self):
        for body in (b"not JSON", b"x" * (MAX_RESPONSE_BYTES + 1), b"[]"):
            with self.subTest(size=len(body)), self.assertRaises(TransientError):
                TokenClient(opener=lambda *a, body=body, **k: Response(body)).refresh_token(
                    OLD, before_dispatch=lambda: None
                )

    def test_graph_read_uses_bearer_without_changing_origin(self):
        client = self.client({"id": "example-account"})
        self.assertEqual(client.graph_get(OLD, "me", {"fields": "id"})["id"], "example-account")
        self.assertEqual(self.requests[0][0].get_header("Authorization"), "Bearer " + OLD)
        for path in ("../other", "//other", "https://other.invalid/a", "me?access_token=x"):
            with self.assertRaises(ConfigurationError):
                client.graph_get(OLD, path)

    def test_graph_errors_keep_only_numeric_fields(self):
        client = self.client({"error": {"code": 190, "error_subcode": 7, "message": OLD}})
        with self.assertRaises(GraphError) as caught:
            client.graph_get(OLD, "me")
        self.assertEqual(caught.exception.code, 190)
        self.assertNotIn(OLD, str(caught.exception))

    def test_code_exchange_accepts_omitted_short_token_expiry(self):
        client = self.client({"access_token": NEW, "user_id": "example-account"})
        grant = client.exchange_code(
            client_id="example-app",
            client_secret="synthetic-secret",
            code="authorized-example-code",
            redirect_uri="https://example.invalid/callback",
            before_dispatch=lambda: None,
        )
        self.assertEqual(grant.expires_in, 0)
        self.assertEqual(self.requests[0][0].method, "POST")

    def test_long_lived_exchange_requires_actual_lifetime(self):
        grant = self.client().exchange_long_lived(
            OLD, client_secret="synthetic-secret", before_dispatch=lambda: None
        )
        self.assertIsInstance(grant, TokenGrant)
        with self.assertRaises(ValidationError):
            self.client({"access_token": NEW}).exchange_long_lived(
                OLD, client_secret="synthetic-secret", before_dispatch=lambda: None
            )

    def test_untrusted_origin_and_invalid_timeout_fail_before_http(self):
        for kwargs in (
            {"origin": "https://example.invalid"},
            {"timeout": 0},
            {"timeout": True},
            {"timeout": float("nan")},
        ):
            with self.assertRaises(ConfigurationError):
                TokenClient(**kwargs)

    def test_redirect_handler_never_forwards_credentials(self):
        self.assertIsNone(
            NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.invalid")
        )
