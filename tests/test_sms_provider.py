"""Provider tests that never send an actual SMS."""

import os
import unittest
from unittest.mock import patch
from urllib.error import URLError

from sms_provider import (
    MockSmsProvider,
    SmsProviderError,
    TwilioSmsProvider,
    get_sms_provider,
)


class TestSmsProviders(unittest.TestCase):
    def test_mock_provider_captures_messages_in_memory(self):
        provider = MockSmsProvider()
        provider.send_sms("+15551234567", "Test OTP message")

        self.assertEqual(
            provider.messages,
            [("+15551234567", "Test OTP message")],
        )

    def test_mock_provider_is_not_reported_as_real_delivery(self):
        with patch.dict(os.environ, {"SMS_PROVIDER": "mock"}):
            with self.assertRaisesRegex(SmsProviderError, "does not deliver"):
                get_sms_provider()

    def test_twilio_configuration_is_required(self):
        with patch.dict(os.environ, {"SMS_PROVIDER": "twilio"}, clear=True):
            with self.assertRaisesRegex(SmsProviderError, "credentials"):
                get_sms_provider()

    def test_twilio_network_failure_is_sanitized(self):
        provider = TwilioSmsProvider(
            account_sid="AC" + "1" * 32,
            auth_token="test-token",
            sender_number="+15551234567",
        )
        with patch("sms_provider.urlopen", side_effect=URLError("private detail")):
            with self.assertRaisesRegex(
                SmsProviderError,
                "temporarily unavailable",
            ) as raised:
                provider.send_sms(
                    "+91 98765 43210",
                    "The OTP is 123456.",
                )

        self.assertNotIn("private detail", str(raised.exception))

    def test_twilio_rejects_local_number_without_country_code(self):
        provider = TwilioSmsProvider(
            account_sid="AC" + "1" * 32,
            auth_token="test-token",
            sender_number="+15551234567",
        )
        with self.assertRaisesRegex(SmsProviderError, "international"):
            provider.send_sms("9876543210", "Test OTP")


if __name__ == "__main__":
    unittest.main()
