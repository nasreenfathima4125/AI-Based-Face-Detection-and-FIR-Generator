"""SMS provider interface and Twilio implementation."""

from __future__ import annotations

import base64
import os
import re
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class SmsProviderError(Exception):
    """Raised when an SMS provider is unavailable or rejects a message."""


class SmsProvider(Protocol):
    def send_sms(self, phone_number: str, message: str) -> None:
        """Send a message without returning or logging its contents."""


class MockSmsProvider:
    """Captures outgoing messages in memory for isolated tests."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def send_sms(self, phone_number: str, message: str) -> None:
        self.messages.append((phone_number, message))


class TwilioSmsProvider:
    """Sends SMS messages through the Twilio Messages REST API."""

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        sender_number: str | None = None,
        messaging_service_sid: str | None = None,
    ) -> None:
        if not sender_number and not messaging_service_sid:
            raise SmsProviderError(
                "Configure a Twilio sender number or messaging service."
            )
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.sender_number = sender_number
        self.messaging_service_sid = messaging_service_sid

    def send_sms(self, phone_number: str, message: str) -> None:
        normalized_number = re.sub(r"[\s().-]", "", phone_number)
        if not re.fullmatch(r"\+[1-9][0-9]{7,14}", normalized_number):
            raise SmsProviderError(
                "Use an international phone number with its + country code "
                "to receive a recovery code."
            )

        form = {
            "To": normalized_number,
            "Body": message,
        }
        if self.messaging_service_sid:
            form["MessagingServiceSid"] = self.messaging_service_sid
        else:
            form["From"] = self.sender_number or ""

        url = (
            "https://api.twilio.com/2010-04-01/Accounts/"
            f"{self.account_sid}/Messages.json"
        )
        credentials = base64.b64encode(
            f"{self.account_sid}:{self.auth_token}".encode("utf-8")
        ).decode("ascii")
        request = Request(
            url,
            data=urlencode(form).encode("ascii"),
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=10) as response:
                if response.status != 201:
                    raise SmsProviderError(
                        "The SMS provider did not accept the message."
                    )
        except HTTPError as exc:
            raise SmsProviderError(
                "The SMS provider rejected the message."
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise SmsProviderError(
                "The SMS provider is temporarily unavailable."
            ) from exc


def get_sms_provider() -> SmsProvider:
    """Builds the configured provider; never silently falls back to mock."""
    provider_name = os.environ.get("SMS_PROVIDER", "").strip().lower()
    if provider_name == "mock":
        raise SmsProviderError(
            "The mock SMS provider does not deliver messages and is available "
            "only for automated tests."
        )
    if provider_name != "twilio":
        raise SmsProviderError(
            "SMS recovery is not configured. Set SMS_PROVIDER to twilio "
            "with valid Twilio credentials."
        )

    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    sender_number = os.environ.get("TWILIO_FROM_NUMBER", "").strip() or None
    messaging_service_sid = (
        os.environ.get("TWILIO_MESSAGING_SERVICE_SID", "").strip() or None
    )
    if not account_sid or not auth_token:
        raise SmsProviderError(
            "Twilio account credentials are not configured."
        )
    return TwilioSmsProvider(
        account_sid=account_sid,
        auth_token=auth_token,
        sender_number=sender_number,
        messaging_service_sid=messaging_service_sid,
    )
