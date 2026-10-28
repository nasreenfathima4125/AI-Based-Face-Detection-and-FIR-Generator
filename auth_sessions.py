"""Server-side authentication session management."""

from datetime import datetime, timedelta, timezone
import hashlib
import os
import re
import secrets
from typing import Any, Dict, Mapping, Optional, Tuple

import database

SESSION_COOKIE_NAME = "fir_auth_session"
DEFAULT_SESSION_TTL_SECONDS = 12 * 60 * 60
MAX_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def session_ttl_seconds() -> int:
    """Returns the configured absolute session lifetime."""
    raw_value = os.environ.get(
        "FIR_AUTH_SESSION_TTL_SECONDS",
        str(DEFAULT_SESSION_TTL_SECONDS),
    )
    try:
        ttl_seconds = int(raw_value)
    except ValueError as exc:
        raise ValueError(
            "FIR_AUTH_SESSION_TTL_SECONDS must be an integer."
        ) from exc

    if not 300 <= ttl_seconds <= MAX_SESSION_TTL_SECONDS:
        raise ValueError(
            "FIR_AUTH_SESSION_TTL_SECONDS must be between 300 seconds "
            "and 30 days."
        )
    return ttl_seconds


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _token_digest(token: str) -> Optional[str]:
    if not isinstance(token, str) or not _TOKEN_PATTERN.fullmatch(token):
        return None
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create_session(
    user_id: int,
    now: Optional[datetime] = None,
) -> Tuple[str, datetime]:
    """Creates an opaque bearer token and stores only its SHA-256 digest."""
    created_at = now or _utc_now()
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    created_at = created_at.astimezone(timezone.utc)
    expires_at = created_at + timedelta(seconds=session_ttl_seconds())
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()

    database.create_auth_session(
        token_hash=token_hash,
        user_id=user_id,
        created_at=created_at.isoformat(),
        expires_at=expires_at.isoformat(),
    )
    return token, expires_at


def resolve_session(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Validates a token and loads the user's current role from the database."""
    if token is None:
        return None
    token_hash = _token_digest(token)
    if token_hash is None:
        return None
    return database.get_auth_session_user(
        token_hash=token_hash,
        now=_utc_now().isoformat(),
    )


def current_user_from_cookies(
    cookies: Mapping[str, str],
) -> Optional[Dict[str, Any]]:
    """Resolves the authenticated user from the request cookie collection."""
    return resolve_session(cookies.get(SESSION_COOKIE_NAME))


def revoke_session(token: Optional[str]) -> bool:
    """Revokes a validly formatted session token without storing it."""
    if token is None:
        return False
    token_hash = _token_digest(token)
    if token_hash is None:
        return False
    return database.revoke_auth_session(
        token_hash=token_hash,
        revoked_at=_utc_now().isoformat(),
    )


def cookie_secure_enabled() -> bool:
    """Reads the explicit HTTPS cookie setting used by the gateway."""
    value = os.environ.get("FIR_AUTH_COOKIE_SECURE", "false").strip().lower()
    if value not in {"true", "false"}:
        raise ValueError("FIR_AUTH_COOKIE_SECURE must be true or false.")
    return value == "true"
