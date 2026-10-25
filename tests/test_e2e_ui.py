"""
tests/test_e2e_ui.py
--------------------
End-to-end tests for the Phase 1 public-service multi-page redesign:
1. Editorial landing page (Hero copy, single primary CTA, top navigation).
2. Language selection -> Conversational complaint assistant.
3. Conversational validation and Unicode preservation (Malayalam & Hindi).
4. AI fallback to guided form (preserving recoverable entered inputs).
5. Verification review & persistent SQLite database storage.
6. Authentication, Police Queue, and side-by-side FIR review and approval.
7. Citizen dashboard with locked FIR download policy.
"""

from datetime import date, datetime, timedelta, timezone
import unittest
import os
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

from test_database_support import isolate_database

import database
import otp_service
import sms_provider


class TestPhase1ApplicationE2E(unittest.TestCase):
    """End-to-end testing of the complete Phase 1 application flow."""

    def setUp(self):
        """Give this UI test its own database, separate from production data."""
        self.database_path = isolate_database(self, database)

    def _open_valid_complaint_review(self):
        """Navigate through the real intake UI to a valid complaint review."""
        at = AppTest.from_file("../app.py").run()
        [b for b in at.button if "Report an incident" in b.label][0].click().run()
        [b for b in at.button if b.label == "Continue"][0].click().run()
        [
            b for b in at.button if "Use guided form instead" in b.label
        ][0].click().run()

        at.text_input[0].set_value("Fictional Test Citizen")
        at.text_input[1].set_value("+91 98765 43210")
        at.selectbox[0].select("Theft / Burglary (മോഷണം)")
        at.text_input[3].set_value("Sample Road")
        at.text_area[0].set_value("A fictional bag was taken from a sample vehicle.")
        [b for b in at.button if b.label == "Review complaint"][0].click().run()
        self.assertEqual(at.session_state["current_page"], "complaint_verify")
        return at

    def test_editorial_landing_page_requirements(self):
        """Verify the current landing page and its primary navigation controls."""
        at = AppTest.from_file("../app.py").run()
        self.assertFalse(at.exception)

        self.assertEqual(at.session_state["current_page"], "landing")

        markdown_joined = " ".join([m.value for m in at.markdown])
        self.assertIn("Justice begins", markdown_joined)
        self.assertIn("Share what happened in your preferred language", markdown_joined)
        self.assertIn("You can begin without creating an account", markdown_joined)

        btn_labels = [b.label for b in at.button]
        self.assertTrue(any("Track Complaint" in lbl for lbl in btn_labels))
        self.assertTrue(any("Sign in" in lbl for lbl in btn_labels))
        self.assertTrue(any("Report an incident" in lbl for lbl in btn_labels))

    def test_complaint_intake_navigation_and_language_selection(self):
        """Verify landing navigation and multilingual chat prompts."""
        at = AppTest.from_file("../app.py").run()
        hero_btn = [b for b in at.button if "Report an incident" in b.label][0]
        hero_btn.click().run()

        self.assertEqual(at.session_state["current_page"], "language_select")

        at.radio[0].set_value("മലയാളം").run()
        [b for b in at.button if b.label == "Continue"][0].click().run()

        self.assertEqual(at.session_state["current_page"], "complaint_chat")
        self.assertEqual(at.session_state["selected_language"], "ml")
        self.assertTrue(len(at.chat_message) > 0)
        self.assertIn(
            "സംഭവം എന്താണെന്ന് വ്യക്തമായി വിവരിക്കുക",
            at.chat_message[0].markdown[0].value,
        )

    def test_ai_fallback_to_guided_form_preserves_inputs(self):
        """Verify guided-form fallback preserves the current complaint details."""
        at = AppTest.from_file("../app.py").run()
        [b for b in at.button if "Report an incident" in b.label][0].click().run()
        [b for b in at.button if b.label == "Continue"][0].click().run()

        test_desc = "My black backpack containing a laptop was stolen from my vehicle parked near Market Road."
        slots = at.session_state["complaint_slots"]
        slots["description"] = test_desc
        at.session_state["complaint_slots"] = slots
        at.run()

        fallback_btn = [
            b for b in at.button if "Use guided form instead" in b.label
        ][0]
        fallback_btn.click().run()

        self.assertEqual(at.session_state["current_page"], "complaint_guided_form")
        self.assertIn(test_desc, [field.value for field in at.text_area])

    def test_verification_and_sqlite_persistence(self):
        """Verify the guided form, citizen review, and isolated persistence."""
        at = self._open_valid_complaint_review()
        [b for b in at.button if b.label == "Submit complaint"][0].click().run()
        self.assertEqual(at.session_state["current_page"], "complaint_confirmed")
        ref_no = at.session_state["last_submitted_ref"]
        self.assertTrue(ref_no.startswith("CMP-"))
        self.assertTrue(at.success)
        self.assertTrue(at.query_params.get("recovery"))
        self.assertNotIn("reference", at.query_params)

        persisted = database.get_complaint_by_reference(ref_no)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted["complainant_name"], "Fictional Test Citizen")
        self.assertEqual(persisted["status"], "Submitted")

        draft = database.get_latest_fir_draft(persisted["id"])
        self.assertIsNotNone(draft)
        self.assertIn("പ്രഥമ വിവര വിവരണം", draft["draft_content_ml"])
        self.assertIn("Fictional Test Citizen", draft["draft_content_ml"])
        with database.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM complaints"
            ).fetchone()[0]
        self.assertEqual(count, 1)
        at.run()
        self.assertEqual(at.session_state["current_page"], "complaint_confirmed")
        with database.get_db_connection() as connection:
            count_after_rerun = connection.execute(
                "SELECT COUNT(*) FROM complaints"
            ).fetchone()[0]
        self.assertEqual(count_after_rerun, 1)

    def test_confirmation_refresh_recovers_reference_after_contact_verification(self):
        """Verify a fresh session requires SMS OTP before showing the reference."""
        at = self._open_valid_complaint_review()
        [b for b in at.button if b.label == "Submit complaint"][0].click().run()
        reference = at.session_state["last_submitted_ref"]

        at.session_state["last_submitted_ref"] = None
        at.session_state["last_submitted_id"] = None
        at.session_state["complaint_submission_completed"] = False
        at.session_state["confirmation_verified_reference"] = None
        at.run()

        self.assertEqual(at.session_state["current_page"], "complaint_confirmed")
        self.assertTrue(
            any(b.label == "Send or resend code" for b in at.button)
        )
        self.assertFalse(at.code)
        sent_messages = []

        def capture_message(phone_number, message):
            sent_messages.append((phone_number, message))

        test_sms_environment = {
            "SMS_PROVIDER": "twilio",
            "TWILIO_ACCOUNT_SID": "AC" + "1" * 32,
            "TWILIO_AUTH_TOKEN": "test-auth-token-not-a-secret",
            "TWILIO_FROM_NUMBER": "+15551234567",
            "FIR_OTP_HMAC_SECRET": "test-key-" + "x" * 32,
        }
        with patch.dict(os.environ, test_sms_environment):
            with patch.object(
                sms_provider.TwilioSmsProvider,
                "send_sms",
                side_effect=capture_message,
            ):
                [b for b in at.button if b.label == "Send or resend code"][0].click().run()

        self.assertEqual(len(sent_messages), 1)
        self.assertEqual(sent_messages[0][0], "+91 98765 43210")
        code = sent_messages[0][1].split(" is ", 1)[1].split(".", 1)[0]
        self.assertEqual(len(code), 6)

        at.text_input[0].set_value("000000")
        [b for b in at.button if b.label == "Verify code"][0].click().run()
        self.assertTrue(at.error)
        self.assertFalse(at.code)
        self.assertEqual(at.session_state["current_page"], "complaint_confirmed")

        at.text_input[0].set_value(code)
        with patch.dict(os.environ, test_sms_environment):
            [b for b in at.button if b.label == "Verify code"][0].click().run()

        self.assertEqual(at.session_state["current_page"], "complaint_confirmed")
        self.assertTrue(at.session_state["confirmation_verified_handle"])
        self.assertEqual(at.code[0].value, reference)
        with database.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM complaints"
            ).fetchone()[0]
        self.assertEqual(count, 1)

        # A separate session cannot inherit authorization from persisted verified_at.
        at.session_state["last_submitted_ref"] = None
        at.session_state["last_submitted_id"] = None
        at.session_state["last_submitted_recovery_handle"] = None
        at.session_state["complaint_submission_completed"] = False
        at.session_state["confirmation_verified_handle"] = None
        at.run()
        self.assertFalse(at.code)
        self.assertTrue(
            any(button.label == "Send or resend code" for button in at.button)
        )
        self.assertIsNone(at.session_state["confirmation_verified_handle"])

    def test_expired_recovery_handle_cannot_show_reference_or_send_code(self):
        at = self._open_valid_complaint_review()
        [b for b in at.button if b.label == "Submit complaint"][0].click().run()
        handle = at.query_params["recovery"]
        handle_hash = otp_service.hash_recovery_handle(handle)
        expired_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with database.get_db_connection() as connection:
            connection.execute(
                """
                UPDATE complaint_recovery_challenges
                SET recovery_expires_at = ?
                WHERE handle_hash = ?
                """,
                (expired_at, handle_hash),
            )
            connection.commit()

        at.session_state["last_submitted_ref"] = None
        at.session_state["last_submitted_id"] = None
        at.session_state["last_submitted_recovery_handle"] = None
        at.session_state["complaint_submission_completed"] = False
        at.session_state["confirmation_verified_handle"] = None
        at.run()

        self.assertFalse(at.code)
        self.assertFalse(
            any(button.label == "Send or resend code" for button in at.button)
        )
        self.assertTrue(
            any(
                "This confirmation cannot be verified." in warning.value
                for warning in at.warning
            )
        )
    def test_confirmation_missing_or_invalid_reference_shows_recovery_message(self):
        """Verify invalid or missing confirmation references show no other record."""
        at = self._open_valid_complaint_review()
        [b for b in at.button if b.label == "Submit complaint"][0].click().run()

        at.session_state["last_submitted_ref"] = None
        at.session_state["last_submitted_id"] = None
        at.session_state["last_submitted_recovery_handle"] = None
        at.session_state["complaint_submission_completed"] = False
        at.session_state["confirmation_verified_handle"] = None
        at.query_params["recovery"] = "not-a-valid-recovery-handle"
        at.run()

        self.assertFalse(at.code)
        self.assertTrue(
            any("This confirmation cannot be verified." in warning.value
                for warning in at.warning)
        )
        self.assertEqual(at.session_state["current_page"], "complaint_confirmed")

        del at.query_params["recovery"]
        at.run()
        self.assertFalse(at.code)
        self.assertTrue(
            any("This confirmation cannot be verified." in warning.value
                for warning in at.warning)
        )

    def test_sms_provider_failure_does_not_create_a_valid_otp(self):
        """Verify provider errors leave no active code or exposed reference."""
        at = self._open_valid_complaint_review()
        [b for b in at.button if b.label == "Submit complaint"][0].click().run()
        complaint_id = at.session_state["last_submitted_id"]
        at.session_state["last_submitted_ref"] = None
        at.session_state["last_submitted_recovery_handle"] = None
        at.session_state["last_submitted_id"] = None
        at.session_state["complaint_submission_completed"] = False
        at.run()

        test_sms_environment = {
            "SMS_PROVIDER": "twilio",
            "TWILIO_ACCOUNT_SID": "AC" + "1" * 32,
            "TWILIO_AUTH_TOKEN": "test-auth-token-not-a-secret",
            "TWILIO_FROM_NUMBER": "+15551234567",
            "FIR_OTP_HMAC_SECRET": "test-key-" + "x" * 32,
        }
        with patch.dict(os.environ, test_sms_environment):
            with patch.object(
                sms_provider.TwilioSmsProvider,
                "send_sms",
                side_effect=sms_provider.SmsProviderError(
                    "The SMS provider is temporarily unavailable."
                ),
            ):
                [
                    b for b in at.button if b.label == "Send or resend code"
                ][0].click().run()

        self.assertTrue(
            any("temporarily unavailable" in error.value for error in at.error)
        )
        self.assertFalse(at.code)
        handle_hash = at.session_state.get("confirmation_verified_handle")
        self.assertIsNone(handle_hash)
        with database.get_db_connection() as connection:
            row = connection.execute(
                """
                SELECT otp_hash FROM complaint_recovery_challenges
                WHERE complaint_id = ?
                """,
                (complaint_id,),
            ).fetchone()
        self.assertIsNone(row["otp_hash"])

    def test_new_intake_clears_previous_confirmation_state(self):
        """Verify a new intake cannot reuse the preceding complaint reference."""
        at = self._open_valid_complaint_review()
        [b for b in at.button if b.label == "Submit complaint"][0].click().run()
        handle = at.session_state["last_submitted_recovery_handle"]
        handle_hash = otp_service.hash_recovery_handle(handle)
        self.assertTrue(at.query_params.get("recovery"))

        [b for b in at.button if b.label == "Return home"][0].click().run()
        [b for b in at.button if "Report an incident" in b.label][0].click().run()

        self.assertEqual(at.session_state["current_page"], "language_select")
        self.assertNotIn("recovery", at.query_params)
        self.assertFalse(at.session_state["complaint_submission_completed"])
        self.assertIsNone(at.session_state["last_submitted_ref"])
        self.assertEqual(at.session_state["complaint_slots"]["description"], "")
        challenge = database.get_recovery_challenge(handle_hash)
        self.assertIsNotNone(challenge["revoked_at"])
        with database.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM complaints"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_failed_validation_stays_on_review_without_saving(self):
        """Verify invalid complaint data cannot reach confirmation or storage."""
        at = self._open_valid_complaint_review()
        slots = at.session_state["complaint_slots"]
        slots["description"] = ""
        at.session_state["complaint_slots"] = slots
        at.run()

        [b for b in at.button if b.label == "Submit complaint"][0].click().run()

        self.assertEqual(at.session_state["current_page"], "complaint_verify")
        self.assertTrue(at.error)
        with database.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM complaints"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_database_save_failure_stays_on_review(self):
        """Verify failed persistence displays an error and does not navigate."""
        at = self._open_valid_complaint_review()
        with patch.object(
            database,
            "save_complaint",
            return_value=(False, "Simulated database failure.", {}),
        ):
            [b for b in at.button if b.label == "Submit complaint"][0].click().run()

        self.assertEqual(at.session_state["current_page"], "complaint_verify")
        self.assertTrue(
            any("Simulated database failure." in error.value for error in at.error)
        )
        with database.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM complaints"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_police_queue_and_side_by_side_review_workflow(self):
        """Verify police queue and approval using only the test database."""
        _, _, complaint = database.save_complaint(
            complainant_name="Fictional Review Citizen",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date=date.today().isoformat(),
            incident_location="Sample Road",
            description="A fictional bag was taken from a sample vehicle.",
        )
        at = AppTest.from_file("../app.py").run()
        [b for b in at.button if b.label == "Sign in"][0].click().run()
        at.text_input[0].set_value("officer@keralapolice.demo")
        at.text_input[1].set_value("Police@123")
        [b for b in at.button if b.label == "Sign in"][-1].click().run()
        self.assertEqual(at.session_state["current_page"], "police_dashboard")

        rev_buttons = [b for b in at.button if "Inspect & Review" in b.label]
        self.assertTrue(len(rev_buttons) > 0)
        rev_buttons[0].click().run()

        case_id = at.session_state["active_police_case_id"]
        self.assertEqual(case_id, complaint["id"])

        review_checkbox = next(
            checkbox
            for checkbox in at.checkbox
            if "reviewed the draft" in checkbox.label
        )
        review_checkbox.check().run()
        approve_btn = [b for b in at.button if "Approve FIR Draft" in b.label][0]
        approve_btn.click().run()

        case_record = database.get_complaint_by_id(case_id)
        self.assertEqual(case_record["is_approved"], 1)
        self.assertEqual(case_record["fir_status"], "Approved")

    def test_citizen_can_reach_dashboard_through_sign_in(self):
        """Verify the citizen dashboard is reached through actual sign-in."""
        at = AppTest.from_file("../app.py").run()
        [b for b in at.button if b.label == "Sign in"][0].click().run()
        at.text_input[0].set_value("citizen@example.com")
        at.text_input[1].set_value("Citizen@123")
        [b for b in at.button if b.label == "Sign in"][-1].click().run()

        self.assertEqual(at.session_state["current_page"], "citizen_dashboard")
        self.assertTrue(any("My dashboard" in item.value for item in at.markdown))


if __name__ == "__main__":
    unittest.main()
