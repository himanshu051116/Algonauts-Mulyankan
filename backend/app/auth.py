"""Authentication: validates Supabase JWTs and enforces role-based access.

New users are auto-created in the local database on first login with
role=APPLICANT and is_active=False. An administrator must approve them
before they can access the system.

Supabase JWTs are verified through JWKS key selection by kid. Local JWTs
are permitted only when explicitly enabled for development.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, TypeAlias

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from jwt import PyJWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User, UserRole
from app.services.audit import create_audit_event

logger = logging.getLogger("mulyankan.auth")


JsonObject: TypeAlias = dict[str, Any]
RoleDependency: TypeAlias = Callable[..., Awaitable[User]]

security = HTTPBearer()

JWKS_CACHE: JsonObject | None = None
JWKS_CACHE_FETCHED_AT: float = 0.0


def _auth_error() -> HTTPException:
    """Return the standard authentication failure response."""

    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"X-Auth-Error": "invalid_credentials"},
    )


def _normalise_mapping(
    value: object,
    *,
    context: str,
) -> JsonObject:
    """Validate and normalise an external dictionary."""

    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")

    return {
        str(key): item
        for key, item in value.items()
    }


def _normalise_jwks(value: object) -> JsonObject:
    """Validate a JWKS document and its key collection."""

    jwks = _normalise_mapping(
        value,
        context="JWKS response",
    )

    raw_keys: object = jwks.get("keys")

    if not isinstance(raw_keys, list):
        raise ValueError(
            "JWKS response must contain a 'keys' list"
        )

    keys: list[JsonObject] = []

    for index, raw_key in enumerate(raw_keys):
        keys.append(
            _normalise_mapping(
                raw_key,
                context=f"JWKS key at index {index}",
            )
        )

    jwks["keys"] = keys

    return jwks


def _email_verified(payload: JsonObject) -> bool:
    """Determine whether the token confirms the email address."""

    user_metadata = payload.get("user_metadata")
    app_metadata = payload.get("app_metadata")

    user_metadata_verified = (
        isinstance(user_metadata, dict)
        and user_metadata.get("email_verified") is True
    )

    app_metadata_verified = (
        isinstance(app_metadata, dict)
        and app_metadata.get("email_verified") is True
    )

    return any(
        (
            payload.get("email_verified") is True,
            bool(payload.get("email_confirmed_at")),
            user_metadata_verified,
            app_metadata_verified,
        )
    )


def _validate_common_claims(payload: JsonObject) -> None:
    """Validate claims shared by Supabase and local JWTs."""

    subject = payload.get("sub")

    if not isinstance(subject, str) or not subject.strip():
        raise _auth_error()

    token_type = payload.get("token_type")

    if token_type is not None:
        if not isinstance(token_type, str):
            raise _auth_error()

        if token_type not in {
            "access_token",
            "bearer",
        }:
            raise _auth_error()

    if not _email_verified(payload):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email address is not verified.",
        )


async def _fetch_supabase_jwks() -> JsonObject:
    """Fetch and validate the Supabase JWKS document."""

    if not settings.supabase_url:
        raise _auth_error()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            settings.resolved_supabase_jwks_url,
            timeout=10,
        )

    response.raise_for_status()

    raw_payload: object = response.json()

    try:
        return _normalise_jwks(raw_payload)
    except ValueError as exc:
        raise _auth_error() from exc


async def _get_supabase_jwks(
    force_refresh: bool = False,
) -> JsonObject:
    """Return cached JWKS data or refresh it when necessary."""

    global JWKS_CACHE
    global JWKS_CACHE_FETCHED_AT

    cache_age = (
        time.monotonic()
        - JWKS_CACHE_FETCHED_AT
    )

    if (
        not force_refresh
        and JWKS_CACHE is not None
        and cache_age
        < settings.supabase_jwks_cache_seconds
    ):
        return JWKS_CACHE

    fetched_jwks = await _fetch_supabase_jwks()

    JWKS_CACHE = fetched_jwks
    JWKS_CACHE_FETCHED_AT = time.monotonic()

    return fetched_jwks


def _find_jwk(
    jwks: JsonObject,
    kid: str,
) -> JsonObject | None:
    """Find the signing key matching the JWT key identifier."""

    raw_keys: object = jwks.get("keys")

    if not isinstance(raw_keys, list):
        return None

    for raw_key in raw_keys:
        if not isinstance(raw_key, dict):
            continue

        key = {
            str(name): value
            for name, value in raw_key.items()
        }

        key_id = key.get("kid")

        if (
            isinstance(key_id, str)
            and key_id == kid
        ):
            return key

    return None


async def _select_supabase_jwk(
    kid: str,
) -> JsonObject:
    """Select a key, refreshing JWKS once for an unknown kid."""

    jwks = await _get_supabase_jwks()
    key = _find_jwk(jwks, kid)

    if key is not None:
        return key

    refreshed_jwks = await _get_supabase_jwks(
        force_refresh=True,
    )
    key = _find_jwk(refreshed_jwks, kid)

    if key is None:
        raise _auth_error()

    return key


async def _validate_supabase_token(
    token: str,
) -> JsonObject:
    """Validate a Supabase JWT and return its payload."""

    try:
        raw_header: object = jwt.get_unverified_header(
            token
        )
        header = _normalise_mapping(
            raw_header,
            context="JWT header",
        )
    except (PyJWTError, ValueError, TypeError) as exc:
        logger.warning("auth_failure: malformed_jwt_header")
        raise _auth_error() from exc

    kid_value = header.get("kid")
    algorithm_value = header.get("alg")
    token_header_type = header.get("typ")

    if (
        not isinstance(kid_value, str)
        or not kid_value
    ):
        logger.warning("auth_failure: missing_kid")
        raise _auth_error()

    if (
        not isinstance(algorithm_value, str)
        or algorithm_value
        not in settings.supabase_jwt_algorithm_list
    ):
        logger.warning(
            "auth_failure: unsupported_algorithm alg=%s allowed=%s",
            algorithm_value,
            settings.supabase_jwt_algorithms,
        )
        raise _auth_error()

    if token_header_type is not None:
        if (
            not isinstance(token_header_type, str)
            or token_header_type.upper() != "JWT"
        ):
            logger.warning("auth_failure: invalid_token_type")
            raise _auth_error()

    try:
        key = await _select_supabase_jwk(
            kid_value
        )

        signing_key = jwt.PyJWK.from_dict(key)
        raw_payload: object = jwt.decode(
            token,
            signing_key,
            algorithms=[algorithm_value],
            audience=(
                settings.supabase_jwt_audience
                or None
            ),
            issuer=(
                settings.resolved_supabase_jwt_issuer
            ),
            leeway=settings.jwt_clock_skew_seconds,
            options={
                "verify_aud": bool(
                    settings.supabase_jwt_audience
                ),
                "verify_exp": True,
                "verify_iat": True,
                "verify_nbf": True,
            },
        )

        payload = _normalise_mapping(
            raw_payload,
            context="Supabase JWT payload",
        )
    except HTTPException:
        raise
    except (
        PyJWTError,
        ValueError,
        TypeError,
    ) as exc:
        error_msg = str(exc)
        if "signature" in error_msg.lower():
            logger.warning("auth_failure: invalid_signature kid=%s", kid_value)
        elif "expired" in error_msg.lower():
            logger.warning("auth_failure: expired_token")
        elif "issuer" in error_msg.lower():
            logger.warning("auth_failure: invalid_issuer")
        elif "audience" in error_msg.lower() or "aud" in error_msg.lower():
            logger.warning("auth_failure: invalid_audience")
        elif "not yet" in error_msg.lower() or "nbf" in error_msg.lower():
            logger.warning("auth_failure: not_yet_valid")
        else:
            logger.warning("auth_failure: jwt_decode_error")
        raise _auth_error() from exc

    _validate_common_claims(payload)

    return payload


async def _validate_local_token(
    token: str,
) -> JsonObject:
    """Validate a development-only local JWT."""

    if (
        not settings.auth_allow_local_jwt
        or settings.is_production
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Local JWT authentication is disabled.",
        )

    try:
        raw_payload: object = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=(
                settings.local_jwt_audience
                or None
            ),
            issuer=(
                settings.local_jwt_issuer
                or None
            ),
            leeway=settings.jwt_clock_skew_seconds,
            options={
                "verify_aud": bool(
                    settings.local_jwt_audience
                ),
                "verify_iss": bool(
                    settings.local_jwt_issuer
                ),
                "verify_exp": True,
                "verify_iat": True,
                "verify_nbf": True,
            },
        )

        payload = _normalise_mapping(
            raw_payload,
            context="Local JWT payload",
        )
    except (
        PyJWTError,
        ValueError,
        TypeError,
    ) as exc:
        raise _auth_error() from exc

    _validate_common_claims(payload)

    return payload


async def _validate_token(
    token: str,
) -> JsonObject:
    """Validate through the configured authentication provider."""

    if settings.supabase_url:
        return await _validate_supabase_token(token)

    return await _validate_local_token(token)


async def _get_or_create_user(
    db: AsyncSession,
    user_id: str,
    user_email: str | None,
    email_verified: bool,
) -> User:
    """Resolve or provision the local user record."""

    result = await db.execute(
        select(User).where(
            User.id == user_id
        )
    )
    user = result.scalar_one_or_none()

    if user is None and user_email:
        email_result = await db.execute(
            select(User).where(
                User.email == user_email
            )
        )
        user = email_result.scalar_one_or_none()

    if user is None:
        user = User(
            id=user_id,
            email=(
                user_email
                or f"{user_id}@supabase.auth"
            ),
            role=UserRole.APPLICANT,
            is_active=False,
            is_verified=email_verified,
        )

        db.add(user)
        await db.flush()

        await create_audit_event(
            db,
            event_type="user.registered",
            user=user,
            resource_type="user",
            resource_id=user.id,
            details={
                "email": user.email,
                "auth_provider": (
                    "supabase"
                    if settings.supabase_url
                    else "local"
                ),
            },
        )

        logger.info(
            "user_created uid=%s email=%s role=%s",
            user.id,
            user.email,
            user.role.value if hasattr(user.role, "value") else str(user.role),
        )

        await db.commit()
        await db.refresh(user)

    elif email_verified and not user.is_verified:
        user.is_verified = True

        logger.info("user_verified uid=%s", user.id)

        await db.commit()
        await db.refresh(user)

    return user


async def get_authenticated_user(
    credentials: HTTPAuthorizationCredentials = Depends(
        security
    ),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Return a verified authenticated user, even when approval is pending.

    This dependency is intentionally limited to account-status and onboarding
    endpoints. Business routes must continue to depend on ``get_current_user``.
    """

    payload = await _validate_token(credentials.credentials)
    raw_user_id = payload.get("sub")
    raw_user_email = payload.get("email")

    if not isinstance(raw_user_id, str) or not raw_user_id.strip():
        logger.warning("auth_failure: missing_subject")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject.",
        )

    user_email = (
        raw_user_email
        if isinstance(raw_user_email, str) and raw_user_email.strip()
        else None
    )
    email_verified = _email_verified(payload)
    user = await _get_or_create_user(
        db,
        raw_user_id,
        user_email,
        email_verified,
    )

    if not user.is_verified:
        logger.info("auth_failure: unverified_email uid=%s", raw_user_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email address is not verified.",
        )
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Return the verified and administratively active user.

    Keeping the credential/database signature also preserves compatibility with
    direct service tests and non-FastAPI callers.
    """

    user = await get_authenticated_user(credentials=credentials, db=db)
    if not user.is_active:
        logger.info(
            "auth_failure: inactive_user uid=%s role=%s approval=%s",
            user.id,
            user.role.value if hasattr(user.role, "value") else str(user.role),
            user.approval_status,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active. Contact an administrator.",
            headers={"X-Auth-Error": "account_inactive"},
        )
    return user


def require_role(
    *roles: UserRole,
) -> RoleDependency:
    """Create a FastAPI dependency requiring one of the roles."""

    if not roles:
        raise ValueError(
            "At least one required role must be provided"
        )

    async def role_checker(
        current_user: User = Depends(
            get_current_user
        ),
    ) -> User:
        if current_user.role not in roles:
            allowed_roles = ", ".join(
                role.value
                for role in roles
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Requires one of these roles: "
                    f"{allowed_roles}"
                ),
            )

        return current_user

    return role_checker
