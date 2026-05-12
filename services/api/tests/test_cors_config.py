"""Strict CORS (Task 2.5).

Two layers:

  - Unit tests on :func:`parse_allowed_origins` + :func:`cors_kwargs`
    in ``middleware/cors_config.py`` — easy to assert the rejection of
    ``*`` + credentials, fallback behaviour, and the explicit method /
    header lists.

  - HTTP-level smoke tests through the FastAPI test client confirming
    Starlette's CORSMiddleware honors the allowlist on real requests
    (preflight OPTIONS for an allowed origin, denial for a disallowed
    origin).
"""
from __future__ import annotations

import pytest

from middleware.cors_config import (
    ALLOWED_METHODS,
    ALLOWED_REQUEST_HEADERS,
    EXPOSED_RESPONSE_HEADERS,
    InsecureCORSConfig,
    cors_kwargs,
    parse_allowed_origins,
)


# ---------------------------------------------------------------------------
# parse_allowed_origins
# ---------------------------------------------------------------------------


def test_parses_comma_separated_list():
    out = parse_allowed_origins(
        "https://app.shadowpages.io,http://localhost:8080",
        allow_credentials=True,
    )
    assert out == ["https://app.shadowpages.io", "http://localhost:8080"]


def test_strips_whitespace_and_empties():
    out = parse_allowed_origins(
        "  https://a.com , , https://b.com , ", allow_credentials=True
    )
    assert out == ["https://a.com", "https://b.com"]


def test_falls_back_to_localhost_dev_defaults_when_empty():
    out = parse_allowed_origins("", allow_credentials=True)
    assert "http://localhost:3000" in out
    assert "http://localhost:8080" in out


def test_falls_back_to_localhost_dev_defaults_when_none():
    out = parse_allowed_origins(None, allow_credentials=True)
    assert "http://localhost:3000" in out


def test_wildcard_with_credentials_raises():
    """The whole point of Task 2.5 — '*' + credentials is silently
    insecure and must fail loudly at startup."""
    with pytest.raises(InsecureCORSConfig):
        parse_allowed_origins("*", allow_credentials=True)


def test_wildcard_with_credentials_in_a_list_also_raises():
    """Embedded ``*`` is just as dangerous as a sole ``*``."""
    with pytest.raises(InsecureCORSConfig):
        parse_allowed_origins(
            "https://app.shadowpages.io,*", allow_credentials=True
        )


def test_wildcard_without_credentials_is_allowed():
    """If credentials are disabled, '*' is a valid public-API config."""
    out = parse_allowed_origins("*", allow_credentials=False)
    assert out == ["*"]


# ---------------------------------------------------------------------------
# cors_kwargs — enumerated methods/headers + env routing
# ---------------------------------------------------------------------------


def test_cors_kwargs_uses_allowed_origins_env_first():
    kw = cors_kwargs(env={"ALLOWED_ORIGINS": "https://app.example.com"})
    assert kw["allow_origins"] == ["https://app.example.com"]


def test_cors_kwargs_falls_back_to_legacy_cors_origins_env():
    """In-place deploys that still use the old var name should keep
    working until the env is renamed."""
    kw = cors_kwargs(env={"CORS_ORIGINS": "https://legacy.example.com"})
    assert kw["allow_origins"] == ["https://legacy.example.com"]


def test_cors_kwargs_enumerates_methods_not_wildcard():
    kw = cors_kwargs(env={"ALLOWED_ORIGINS": "https://x.com"})
    assert kw["allow_methods"] == ALLOWED_METHODS
    assert "*" not in kw["allow_methods"]


def test_cors_kwargs_enumerates_headers_not_wildcard():
    kw = cors_kwargs(env={"ALLOWED_ORIGINS": "https://x.com"})
    assert kw["allow_headers"] == ALLOWED_REQUEST_HEADERS
    assert "X-CSRF-Token" in kw["allow_headers"]
    assert "Idempotency-Key" in kw["allow_headers"]
    assert "*" not in kw["allow_headers"]


def test_cors_kwargs_exposes_replay_and_retry_after():
    kw = cors_kwargs(env={"ALLOWED_ORIGINS": "https://x.com"})
    assert kw["expose_headers"] == EXPOSED_RESPONSE_HEADERS
    assert "Idempotent-Replay" in kw["expose_headers"]
    assert "Retry-After" in kw["expose_headers"]


# ---------------------------------------------------------------------------
# End-to-end through the FastAPI app
# ---------------------------------------------------------------------------


async def test_get_with_allowed_origin_echoes_in_response(client):
    """An allowed origin gets reflected back in
    ``Access-Control-Allow-Origin`` so the browser allows JS to read
    the response. Default test env uses the localhost defaults."""
    r = await client.get(
        "/api/health", headers={"Origin": "http://localhost:3000"}
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert r.headers.get("access-control-allow-credentials") == "true"


async def test_get_with_disallowed_origin_has_no_acao_header(client):
    """A non-allowlisted origin gets no ACAO header, so the browser
    blocks JS from reading the response."""
    r = await client.get(
        "/api/health", headers={"Origin": "https://evil.example.com"}
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") is None


async def test_preflight_allows_csrf_and_idempotency_headers(client):
    """OPTIONS preflight for a POST that uses the headers our frontend
    actually sends — both must be permitted by the allowlist."""
    r = await client.options(
        "/api/reference-pages",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-csrf-token,idempotency-key,content-type",
        },
    )
    assert r.status_code == 200
    allowed = (r.headers.get("access-control-allow-headers") or "").lower()
    assert "x-csrf-token" in allowed
    assert "idempotency-key" in allowed
