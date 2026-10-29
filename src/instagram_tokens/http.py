"""Bounded, per-thread HTTP without redirects or ambient proxies."""

import threading
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

MAX_RESPONSE_BYTES = 1024 * 1024
DEFAULT_MAX_PARALLEL_REQUESTS = 10

CONTRACTS = (
    (
        "instagram.identity",
        "GET",
        "https://graph.instagram.com/{version}/me",
        "id,user_id,username,name,account_type",
        "read",
    ),
    (
        "meta.identity",
        "GET",
        "https://graph.facebook.com/{version}/{ig_user_id}",
        "id,username",
        "read",
    ),
    (
        "publishing.capability",
        "GET",
        "{graph_origin}/{version}/{ig_user_id}/content_publishing_limit",
        "config,quota_usage",
        "read",
    ),
    (
        "meta.introspection",
        "GET",
        "https://graph.facebook.com/{version}/debug_token",
        "input_token",
        "read",
    ),
    (
        "instagram.code.exchange",
        "POST",
        "https://api.instagram.com/oauth/access_token",
        "client_id,client_secret,grant_type,redirect_uri,code",
        "grant",
    ),
    (
        "instagram.long_lived.exchange",
        "GET",
        "https://graph.instagram.com/access_token",
        "grant_type,client_secret,access_token",
        "grant",
    ),
    (
        "instagram.long_lived.refresh",
        "GET",
        "https://graph.instagram.com/refresh_access_token",
        "grant_type,access_token",
        "grant",
    ),
    (
        "instagram.authorize",
        "BROWSER",
        "https://www.instagram.com/oauth/authorize",
        "client_id,redirect_uri,response_type,scope,state",
        "consent",
    ),
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_local = threading.local()


def urlopen(request, *, timeout):
    if not hasattr(_local, "opener"):
        _local.opener = build_opener(ProxyHandler({}), NoRedirect())
    return _local.opener.open(request, timeout=timeout)


def read_bounded(response):
    body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("Instagram API response exceeded its byte budget")
    return body
