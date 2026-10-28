"""Helpers for generating and protecting complaint recovery OTPs."""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timezone

import database


OTP_LENGTH = 6
OTP_TTL_SECONDS = 5 * 60
OTP_RESEND_COOLDOWN_SECONDS = 60
OTP_SEND_WINDOW_SECONDS = 15 * 60
OTP_MAX_SENDS_PER_WINDOW = 3
OTP_MAX_ATTEMPTS = 5
OTP_LOCKOUT_SECONDS = 15 * 60
RECOVERY_HANDLE_BYTES = 32


def get_otp_secret() -> bytes:
    """Loads the server-side HMAC key; refuses weak or missing configuration."""
    secret = os.environ.get("FIR_OTP_HMAC_SECRET", "").encode("utf-8")
    if len(secret) < 32:
        raise ValueError(
            "FIR_OTP_HMAC_SECRET must contain at least 32 bytes."
        )
    return secret


def create_recovery_handle() -> tuple[str, str]:
    """Returns an unguessable URL handle and its non-reversible database hash."""
    handle = secrets.token_urlsafe(RECOVERY_HANDLE_BYTES)
    handle_hash = hashlib.sha256(handle.encode("ascii")).hexdigest()
    return handle, handle_hash


def hash_recovery_handle(handle: str) -> str:
    """Hashes a recovery handle before using it in a database lookup."""
    return hashlib.sha256(handle.encode("utf-8")).hexdigest()


def create_otp() -> str:
    """Creates a zero-padded six-digit code using the operating system RNG."""
    return f"{secrets.randbelow(10**OTP_LENGTH):0{OTP_LENGTH}d}"


def hash_otp(secret: bytes, handle_hash: str, otp: str) -> str:
    """Uses a keyed digest so a database leak cannot cheaply brute-force OTPs."""
    payload = f"{handle_hash}:{otp}".encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def hash_phone_for_rate_limit(secret: bytes, phone_number: str) -> str:
    """Creates a keyed phone identifier without persisting the raw number."""
    normalized_phone = database.re_clean_phone(phone_number)
    return hmac.new(
        secret,
        f"phone:{normalized_phone}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def hash_public_lookup_client(secret: bytes, client_address: str) -> str:
    """Creates a keyed, scope-separated client key for status lookup limits."""
    return hmac.new(
        secret,
        f"public-complaint-lookup:{client_address}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def current_utc_time() -> datetime:
    """Returns a timezone-aware UTC timestamp for persisted OTP deadlines."""
    return datetime.now(timezone.utc)


def mask_phone_number(phone_number: str) -> str:
    """Returns only the final four digits for delivery confirmation."""
    digits = database.re_clean_phone(phone_number)
    return f"••••{digits[-4:]}" if digits else "the saved phone number"
