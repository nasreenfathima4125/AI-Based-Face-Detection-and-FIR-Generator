"""Tests for expiring, revocable server-side authentication sessions."""

from datetime import datetime, timedelta, timezone
import hashlib
import os
import secrets
import unittest
from unittest.mock import patch

from test_database_support import isolate_database

import auth_sessions
import database


class TestAuthenticationSessions(unittest.TestCase):
    def setUp(self):
        self.database_path = isolate_database(self, database)
        success, _, self.user = database.authenticate_user(
            "officer@keralapolice.demo",
            "Police@123",
        )
        self.assertTrue(success)
        self.assertIsNotNone(self.user)
        with database.get_db_connection() as connection:
            self.admin_user_id = connection.execute(
                "SELECT id FROM users WHERE role = 'admin' LIMIT 1"
            ).fetchone()[0]

    def test_created_token_is_hashed_and_resolves_current_user(self):
        token, _ = auth_sessions.create_session(self.user["id"])
        self.addCleanup(auth_sessions.revoke_session, token)

        with database.get_db_connection() as connection:
            row = connection.execute(
                "SELECT token_hash FROM auth_sessions WHERE user_id = ?",
                (self.user["id"],),
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertNotEqual(row["token_hash"], token)
        self.assertEqual(
            row["token_hash"],
            hashlib.sha256(token.encode("ascii")).hexdigest(),
        )
        self.assertEqual(
            auth_sessions.current_user_from_cookies(
                {auth_sessions.SESSION_COOKIE_NAME: token}
            )["role"],
            "police",
        )

    def test_session_can_be_resolved_from_a_new_request_cookie(self):
        token, _ = auth_sessions.create_session(self.user["id"])
        self.addCleanup(auth_sessions.revoke_session, token)

        refreshed_request_cookies = {
            auth_sessions.SESSION_COOKIE_NAME: token,
        }
        refreshed_user = auth_sessions.current_user_from_cookies(
            refreshed_request_cookies
        )
        self.assertEqual(refreshed_user["id"], self.user["id"])

    def test_repeated_reruns_do_not_create_duplicate_sessions(self):
        token, _ = auth_sessions.create_session(self.user["id"])
        self.addCleanup(auth_sessions.revoke_session, token)
        for _ in range(3):
            self.assertEqual(
                auth_sessions.resolve_session(token)["id"],
                self.user["id"],
            )
        with database.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM auth_sessions WHERE user_id = ?",
                (self.user["id"],),
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_expired_session_is_rejected_and_marked_revoked(self):
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        database.create_auth_session(
            token_hash=token_hash,
            user_id=self.user["id"],
            created_at=(expired_at - timedelta(hours=1)).isoformat(),
            expires_at=expired_at.isoformat(),
        )

        self.assertIsNone(auth_sessions.resolve_session(token))
        with database.get_db_connection() as connection:
            row = connection.execute(
                "SELECT revoked_at FROM auth_sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        self.assertIsNotNone(row["revoked_at"])

    def test_malformed_persisted_expiry_is_revoked(self):
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        database.create_auth_session(
            token_hash=token_hash,
            user_id=self.user["id"],
            created_at=now,
            expires_at="invalid-timestamp",
        )

        self.assertIsNone(auth_sessions.resolve_session(token))
        with database.get_db_connection() as connection:
            row = connection.execute(
                "SELECT revoked_at FROM auth_sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        self.assertIsNotNone(row["revoked_at"])

    def test_revoked_session_is_rejected(self):
        token, _ = auth_sessions.create_session(self.user["id"])
        self.assertTrue(auth_sessions.revoke_session(token))
        self.assertFalse(auth_sessions.revoke_session(token))
        self.assertIsNone(auth_sessions.resolve_session(token))

    def test_malformed_and_unknown_tokens_are_rejected(self):
        for token in ("", "bad-token", "A" * 42, "A" * 43 + "!"):
            with self.subTest(token_length=len(token)):
                self.assertIsNone(auth_sessions.resolve_session(token))
        self.assertIsNone(auth_sessions.resolve_session(secrets.token_urlsafe(32)))
        self.assertIsNone(auth_sessions.current_user_from_cookies({}))

    def test_database_role_change_applies_to_the_next_validation(self):
        token, _ = auth_sessions.create_session(self.user["id"])
        self.addCleanup(auth_sessions.revoke_session, token)

        _, _, complaint = database.save_complaint(
            complainant_name="Synthetic Revoked Officer Citizen",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Synthetic Test Location",
            description="Synthetic complaint for session-role revocation.",
        )

        self.assertEqual(auth_sessions.resolve_session(token)["role"], "police")
        self.assertTrue(database.update_user_role(self.user["id"], "citizen", admin_user_id=self.admin_user_id))
        refreshed_user = auth_sessions.resolve_session(token)
        self.assertEqual(refreshed_user["role"], "citizen")
        with self.assertRaises(database.AuthorizationError):
            database.approve_fir_draft(
                complaint_id=complaint["id"],
                officer_user_id=refreshed_user["id"],
            )

    def test_session_lifetime_has_a_bounded_default(self):
        with patch.dict(
            os.environ,
            {"FIR_AUTH_SESSION_TTL_SECONDS": "43200"},
        ):
            self.assertEqual(auth_sessions.session_ttl_seconds(), 12 * 60 * 60)
        for invalid_value in ("1", "2592001", "not-a-number"):
            with self.subTest(invalid_value=invalid_value):
                with patch.dict(
                    os.environ,
                    {"FIR_AUTH_SESSION_TTL_SECONDS": invalid_value},
                ):
                    with self.assertRaises(ValueError):
                        auth_sessions.session_ttl_seconds()

    def test_session_table_initialization_preserves_existing_complaints(self):
        success, _, complaint = database.save_complaint(
            complainant_name="Fictional Migration Citizen",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Sample Road",
            description="A fictional item was reported missing.",
        )
        self.assertTrue(success)
        with database.get_db_connection() as connection:
            connection.execute("DROP TABLE auth_sessions")
            connection.commit()

        database.init_db()
        saved = database.get_complaint_by_id(complaint["id"], actor_user_id=self.user["id"])
        self.assertIsNotNone(saved)
        self.assertEqual(saved["description"], "A fictional item was reported missing.")


if __name__ == "__main__":
    unittest.main()
