"""Pure-function tests for auth helpers — no DB required.

Acts as a smoke check that the test framework is configured correctly and
that the password / token primitives behave as advertised.
"""
from middleware.auth import (
    create_access_token,
    hash_password,
    verify_access_token,
    verify_password,
)


def test_password_hash_roundtrip():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong password", h) is False


def test_password_hash_is_salted():
    """Same password hashed twice must produce different stored values."""
    a = hash_password("samepw")
    b = hash_password("samepw")
    assert a != b
    assert verify_password("samepw", a) is True
    assert verify_password("samepw", b) is True


def test_access_token_roundtrip():
    from uuid import uuid4

    uid = uuid4()
    token = create_access_token(uid, role="user")
    payload = verify_access_token(token)
    assert payload["sub"] == str(uid)
    assert payload["role"] == "user"
    assert payload["type"] == "access"


def test_access_token_rejects_garbage():
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        verify_access_token("not.a.real.token")
    assert exc.value.status_code == 401
