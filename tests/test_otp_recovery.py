"""Isolated tests for OTP storage, expiry, and rate-limiting behavior."""

import unittest
from datetime import datetime, timedelta, timezone

from test_database_support import isolate_database

import database


class TestOtpRecoveryStorage(unittest.TestCase):
    """Exercise persisted challenge lifecycle with a temporary SQLite file."""

    def setUp(self):
        self.database_path = isolate_database(self, database)
        self.now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
        self.phone_hash = "phone-hash-for-test"
        self.handle_hash = "handle-hash-one"
        _, _, self.complaint = database.save_complaint(
            complainant_name="Fictional OTP Citizen",
            contact_number="+91 98765 43210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Sample Road",
            description="A fictional item was reported missing.",
            recovery_handle_hash=self.handle_hash,
        )

    def _reserve(self, handle_hash=None, now=None, otp_hash="otp-hash-valid"):
        return database.reserve_recovery_otp(
            handle_hash=handle_hash or self.handle_hash,
            phone_hash=self.phone_hash,
            otp_hash=otp_hash,
            now=now or self.now,
        )

    def test_valid_otp_is_single_use(self):
        reserved, status = self._reserve()
        self.assertTrue(reserved)
        self.assertEqual(status, "sent")

        verified = database.verify_recovery_otp(
            self.handle_hash,
            "otp-hash-valid",
            self.now + timedelta(seconds=1),
        )
        self.assertEqual(verified, "verified")
        replayed = database.verify_recovery_otp(
            self.handle_hash,
            "otp-hash-valid",
            self.now + timedelta(seconds=2),
        )
        self.assertEqual(replayed, "already_verified")

        reserved_again = self._reserve(
            now=self.now + timedelta(seconds=61),
            otp_hash="otp-hash-second",
        )
        self.assertEqual(reserved_again, (True, "sent"))
        reverified = database.verify_recovery_otp(
            self.handle_hash,
            "otp-hash-second",
            self.now + timedelta(seconds=62),
        )
        self.assertEqual(reverified, "verified")

    def test_expired_otp_is_rejected_and_invalidated(self):
        self._reserve()
        result = database.verify_recovery_otp(
            self.handle_hash,
            "otp-hash-valid",
            self.now + timedelta(seconds=301),
        )
        self.assertEqual(result, "expired")
        challenge = database.get_recovery_challenge(self.handle_hash)
        self.assertIsNone(challenge["otp_hash"])

    def test_expired_recovery_handle_rejects_send_and_verification(self):
        with database.get_db_connection() as connection:
            connection.execute(
                """
                UPDATE complaint_recovery_challenges
                SET recovery_expires_at = ?
                WHERE handle_hash = ?
                """,
                (
                    (self.now - timedelta(seconds=1)).isoformat(),
                    self.handle_hash,
                ),
            )
            connection.commit()

        self.assertEqual(
            self._reserve(),
            (False, "handle_expired"),
        )
        self.assertEqual(
            database.verify_recovery_otp(
                self.handle_hash,
                "otp-hash-valid",
                self.now,
            ),
            "handle_expired",
        )

    def test_revoked_recovery_handle_invalidates_pending_otp(self):
        self.assertEqual(self._reserve(), (True, "sent"))
        self.assertTrue(
            database.revoke_recovery_challenge(self.handle_hash, self.now)
        )

        challenge = database.get_recovery_challenge(self.handle_hash)
        self.assertIsNotNone(challenge["revoked_at"])
        self.assertIsNone(challenge["otp_hash"])
        self.assertEqual(
            self._reserve(now=self.now + timedelta(seconds=61)),
            (False, "revoked"),
        )
        self.assertEqual(
            database.verify_recovery_otp(
                self.handle_hash,
                "otp-hash-valid",
                self.now + timedelta(seconds=1),
            ),
            "revoked",
        )

    def test_failed_attempts_lock_challenge(self):
        self._reserve()
        for _ in range(4):
            result = database.verify_recovery_otp(
                self.handle_hash,
                "wrong-hash",
                self.now + timedelta(seconds=1),
            )
            self.assertEqual(result, "invalid")

        locked = database.verify_recovery_otp(
            self.handle_hash,
            "wrong-hash",
            self.now + timedelta(seconds=2),
        )
        self.assertEqual(locked, "locked")
        challenge = database.get_recovery_challenge(self.handle_hash)
        self.assertIsNone(challenge["otp_hash"])

    def test_resend_cooldown_and_phone_window_limit_are_persisted(self):
        self.assertEqual(self._reserve(), (True, "sent"))
        self.assertEqual(
            self._reserve(now=self.now + timedelta(seconds=30)),
            (False, "cooldown"),
        )
        self.assertEqual(
            self._reserve(now=self.now + timedelta(seconds=61)),
            (True, "sent"),
        )
        self.assertEqual(
            self._reserve(now=self.now + timedelta(seconds=122)),
            (True, "sent"),
        )

        second_handle = "handle-hash-two"
        database.save_complaint(
            complainant_name="Another Fictional Citizen",
            contact_number="+91 98765 43210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Sample Road",
            description="Another fictional item was reported missing.",
            recovery_handle_hash=second_handle,
        )
        self.assertEqual(
            self._reserve(
                handle_hash=second_handle,
                now=self.now + timedelta(seconds=183),
            ),
            (False, "rate_limited"),
        )

    def test_failed_sms_send_can_invalidate_reserved_code(self):
        self._reserve()
        database.cancel_recovery_otp(self.handle_hash, "otp-hash-valid")

        challenge = database.get_recovery_challenge(self.handle_hash)
        self.assertIsNone(challenge["otp_hash"])
        self.assertEqual(
            database.verify_recovery_otp(
                self.handle_hash,
                "otp-hash-valid",
                self.now + timedelta(seconds=1),
            ),
            "not_sent",
        )


if __name__ == "__main__":
    unittest.main()
