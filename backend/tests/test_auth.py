import base64
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError

from app.config import Settings
from app.models.user import User, UserRole


def _b64u(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.fixture
def rsa_auth_material():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_numbers = private_key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "kid": "test-key",
        "use": "sig",
        "alg": "RS256",
        "n": _b64u(public_numbers.n),
        "e": _b64u(public_numbers.e),
    }
    return private_pem, jwk


def _token(private_pem: bytes, **claims):
    now = int(time.time())
    payload = {
        "sub": "user-1",
        "email": "verified@example.gov.in",
        "email_verified": True,
        "aud": "authenticated",
        "iss": "https://project.supabase.co/auth/v1",
        "iat": now,
        "nbf": now,
        "exp": now + 300,
        **claims,
    }
    return jwt.encode(
        payload,
        private_pem,
        algorithm="RS256",
        headers={"kid": "test-key", "typ": "JWT"},
    )


@pytest.fixture(autouse=True)
def reset_auth_settings(monkeypatch):
    import app.auth as auth

    monkeypatch.setattr(auth, "JWKS_CACHE", None)
    monkeypatch.setattr(auth, "JWKS_CACHE_FETCHED_AT", 0.0)
    monkeypatch.setattr(auth.settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(auth.settings, "supabase_jwt_issuer", "")
    monkeypatch.setattr(auth.settings, "supabase_jwt_audience", "authenticated")
    monkeypatch.setattr(auth.settings, "supabase_jwt_algorithms", "RS256")
    monkeypatch.setattr(auth.settings, "jwt_clock_skew_seconds", 0)


@pytest.mark.asyncio
async def test_valid_supabase_jwt_verifies(rsa_auth_material, monkeypatch):
    import app.auth as auth

    private_pem, jwk = rsa_auth_material

    async def fetch_jwks():
        return {"keys": [jwk]}

    monkeypatch.setattr(auth, "_fetch_supabase_jwks", fetch_jwks)
    payload = await auth._validate_supabase_token(_token(private_pem))

    assert payload["sub"] == "user-1"


@pytest.mark.asyncio
async def test_expired_supabase_jwt_fails(rsa_auth_material, monkeypatch):
    import app.auth as auth

    private_pem, jwk = rsa_auth_material

    async def fetch_jwks():
        return {"keys": [jwk]}

    monkeypatch.setattr(auth, "_fetch_supabase_jwks", fetch_jwks)
    token = _token(private_pem, exp=int(time.time()) - 1)

    with pytest.raises(HTTPException) as exc:
        await auth._validate_supabase_token(token)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_wrong_issuer_supabase_jwt_fails(rsa_auth_material, monkeypatch):
    import app.auth as auth

    private_pem, jwk = rsa_auth_material

    async def fetch_jwks():
        return {"keys": [jwk]}

    monkeypatch.setattr(auth, "_fetch_supabase_jwks", fetch_jwks)
    token = _token(private_pem, iss="https://wrong.example/auth/v1")

    with pytest.raises(HTTPException) as exc:
        await auth._validate_supabase_token(token)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_unknown_kid_refreshes_jwks(rsa_auth_material, monkeypatch):
    import app.auth as auth

    private_pem, jwk = rsa_auth_material
    calls = 0

    async def fetch_jwks():
        nonlocal calls
        calls += 1
        return {"keys": [jwk]}

    monkeypatch.setattr(auth, "JWKS_CACHE", {"keys": []})
    monkeypatch.setattr(auth, "JWKS_CACHE_FETCHED_AT", time.monotonic())
    monkeypatch.setattr(auth, "_fetch_supabase_jwks", fetch_jwks)

    payload = await auth._validate_supabase_token(_token(private_pem))

    assert payload["sub"] == "user-1"
    assert calls == 1


@pytest.mark.asyncio
async def test_unverified_email_claim_fails(rsa_auth_material, monkeypatch):
    import app.auth as auth

    private_pem, jwk = rsa_auth_material

    async def fetch_jwks():
        return {"keys": [jwk]}

    monkeypatch.setattr(auth, "_fetch_supabase_jwks", fetch_jwks)
    token = _token(private_pem, email_verified=False, email_confirmed_at="")

    with pytest.raises(HTTPException) as exc:
        await auth._validate_supabase_token(token)

    assert exc.value.status_code == 403


def test_local_jwt_cannot_be_enabled_in_production():
    with pytest.raises(ValidationError):
        Settings(environment="production", auth_allow_local_jwt=True)


@pytest.mark.asyncio
async def test_inactive_user_is_rejected(monkeypatch):
    import app.auth as auth

    user = User(
        id="user-1",
        email="verified@example.gov.in",
        role=UserRole.APPLICANT,
        is_active=False,
        is_verified=True,
    )

    async def validate_token(_token_value: str):
        return {
            "sub": "user-1",
            "email": "verified@example.gov.in",
            "email_verified": True,
        }

    class Result:
        def scalar_one_or_none(self):
            return user

    class FakeDb:
        async def execute(self, _statement):
            return Result()

    monkeypatch.setattr(auth, "_validate_token", validate_token)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")

    with pytest.raises(HTTPException) as exc:
        await auth.get_current_user(credentials=credentials, db=FakeDb())

    assert exc.value.status_code == 403
