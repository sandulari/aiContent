"""Backend XSS sanitization (Task 2.3).

Covers ``services.sanitizer`` directly + the Pydantic validator on
``UserCreate.display_name`` + the email-template escape pass.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.user import UserCreate
from services.email_templates import password_reset_email, welcome_email
from services.sanitizer import clean_text, escape_for_html


# ---------------------------------------------------------------------------
# clean_text — strips HTML, preserves text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("<script>alert(1)</script>", "alert(1)"),  # tag stripped, text kept
        ("<b>Bold</b>", "Bold"),
        ('<img src=x onerror="alert(1)">', ""),  # void tag with no text
        ("Hello <a href='evil'>world</a>", "Hello world"),
        ("  Whitespace  ", "Whitespace"),  # trims edges
        ("plain text", "plain text"),
    ],
)
def test_clean_text_strips_html(raw, expected):
    assert clean_text(raw) == expected


def test_clean_text_passes_none_through():
    assert clean_text(None) is None


# ---------------------------------------------------------------------------
# escape_for_html — defense-in-depth for email templates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("<script>", "&lt;script&gt;"),
        ('"quoted"', "&quot;quoted&quot;"),
        ("plain", "plain"),
        (None, ""),
    ],
)
def test_escape_for_html(raw, expected):
    assert escape_for_html(raw) == expected


# ---------------------------------------------------------------------------
# Pydantic integration — UserCreate.display_name
# ---------------------------------------------------------------------------


def test_user_create_strips_script_from_display_name():
    """The classic XSS attempt: user signs up with <script>... as their
    display name. We strip the tag at the Pydantic layer so the stored
    row contains plain text."""
    u = UserCreate(
        email="x@example.com",
        password="testpass123",
        display_name="Eve<script>alert(1)</script>",
    )
    # Tag stripped, text content kept.
    assert "<" not in u.display_name
    assert "script" in u.display_name  # body text survives
    assert "alert(1)" in u.display_name


def test_user_create_rejects_display_name_that_becomes_empty_after_strip():
    """A user-supplied display_name made entirely of HTML tags is
    effectively empty after sanitization — refuse the registration
    rather than store an empty string."""
    with pytest.raises(ValidationError):
        UserCreate(
            email="x@example.com",
            password="testpass123",
            display_name="<img><br><hr>",
        )


# ---------------------------------------------------------------------------
# Email templates — escaped at the interpolation point
# ---------------------------------------------------------------------------


def test_welcome_email_escapes_display_name():
    """Even with a legacy / admin-set display_name containing HTML, the
    email template's escape pass renders it as visible text."""
    _, html = welcome_email("<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_password_reset_email_escapes_display_name_and_url():
    _, html = password_reset_email(
        "<b>Mallory</b>",
        "https://app.shadowpages.io/reset?token=abc&user=1",
    )
    assert "<b>Mallory</b>" not in html
    assert "&lt;b&gt;Mallory&lt;/b&gt;" in html
    # & in the URL must be escaped too so the href attribute parses
    # correctly across mail clients.
    assert "token=abc&amp;user=1" in html
