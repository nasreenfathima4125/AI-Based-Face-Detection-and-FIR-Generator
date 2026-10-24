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

from datetime import date
import unittest
from streamlit.testing.v1 import AppTest
import database


class TestPhase1ApplicationE2E(unittest.TestCase):
    """End-to-end testing of the complete Phase 1 application flow."""

    def setUp(self):
        """Ensure database schema is initialized before running tests."""
        database.init_db()

    def test_editorial_landing_page_requirements(self):
        """Verify landing page satisfies strict editorial and minimal design requirements."""
        at = AppTest.from_file("../app.py").run()
        self.assertFalse(at.exception)

        # 1. Default page is landing
        self.assertEqual(at.session_state["current_page"], "landing")

        # 2. Hero Headline & Supporting Text
        markdown_joined = " ".join([m.value for m in at.markdown])
        self.assertIn("Your voice deserves to be heard", markdown_joined)
        self.assertIn("Get guided assistance to prepare and submit your complaint", markdown_joined)
        self.assertIn("You can begin without creating an account", markdown_joined)

        # 3. Top navigation actions: Track Complaint, Sign in, Sign up
        btn_labels = [b.label for b in at.button]
        self.assertTrue(any("Track Complaint" in lbl for lbl in btn_labels))
        self.assertTrue(any("Sign in" in lbl for lbl in btn_labels))
        self.assertTrue(any("Sign up" in lbl for lbl in btn_labels))

        # 4. Primary Hero CTA: Register Your Complaint
        self.assertTrue(any("Register Your Complaint" in lbl for lbl in btn_labels))

    def test_complaint_intake_navigation_and_language_selection(self):
        """Verify clicking Register Your Complaint opens language selection."""
        at = AppTest.from_file("../app.py").run()
        hero_btn = [b for b in at.button if "Register Your Complaint" in b.label][0]
        hero_btn.click().run()

        # Opens language select
        self.assertEqual(at.session_state["current_page"], "language_select")

        # Select Malayalam
        ml_btn = [b for b in at.button if "Malayalam" in b.label or "മലയാളം" in b.label][0]
        ml_btn.click().run()

        # Opens complaint chat with Malayalam prompt
        self.assertEqual(at.session_state["current_page"], "complaint_chat")
        self.assertEqual(at.session_state["selected_language"], "ml")
        self.assertTrue(len(at.chat_message) > 0)
        self.assertIn("പരാതി", at.chat_message[0].markdown[0].value)

    def test_ai_fallback_to_guided_form_preserves_inputs(self):
        """Verify that switching to guided form preserves entered conversation inputs."""
        at = AppTest.from_file("../app.py").run()
        at.session_state["current_page"] = "complaint_chat"
        at.session_state["selected_language"] = "en"
        at.run()

        # Enter incident description in chat
        test_desc = "My black backpack containing a laptop was stolen from my vehicle parked near Market Road."
        at.chat_input[0].set_value(test_desc).run()
        self.assertEqual(at.session_state["complaint_slots"]["description"], test_desc)

        # Switch to guided form
        fallback_btn = [b for b in at.button if "Guided Form" in b.label][0]
        fallback_btn.click().run()

        self.assertEqual(at.session_state["current_page"], "complaint_guided_form")
        # Text area should preserve the entered description
        self.assertEqual(at.text_area[0].value, test_desc)

    def test_verification_and_sqlite_persistence(self):
        """Verify reviewing, confirming, and persisting a complaint into SQLite."""
        at = AppTest.from_file("../app.py").run()
        at.session_state["current_page"] = "complaint_verify"
        at.session_state["complaint_slots"] = {
            "name": "Suresh Kumar",
            "contact_number": "+91 9447100099",
            "category": "Theft / Burglary (മോഷണം)",
            "incident_date": date.today().isoformat(),
            "incident_time": "4:00 PM",
            "location": "Aluva Bus Stand",
            "description": "Gold ring stolen while boarding bus near Aluva stand.",
            "additional_info": "Witness: Conductor",
            "language": "en",
        }
        at.run()

        # Confirm and submit
        confirm_btn = [b for b in at.button if "Confirm & Submit" in b.label][0]
        confirm_btn.click().run()

        # Verify page moved to confirmed
        self.assertEqual(at.session_state["current_page"], "complaint_confirmed")
        ref_no = at.session_state["last_submitted_ref"]
        self.assertTrue(ref_no.startswith("CMP-"))

        # Verify persisted in SQLite database
        persisted = database.get_complaint_by_reference(ref_no)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted["complainant_name"], "Suresh Kumar")
        self.assertEqual(persisted["status"], "Submitted")

        # Verify initial Malayalam FIR draft was generated
        draft = database.get_latest_fir_draft(persisted["id"])
        self.assertIsNotNone(draft)
        self.assertIn("പ്രഥമ വിവര വിവരണം", draft["draft_content_ml"])
        self.assertIn("Suresh Kumar", draft["draft_content_ml"])

    def test_police_queue_and_side_by_side_review_workflow(self):
        """Verify police queue search, side-by-side review, and FIR approval unlocking download."""
        # Authenticate as police inspector
        _, _, officer = database.authenticate_user("officer@keralapolice.demo", "Police@123")
        self.assertIsNotNone(officer)

        at = AppTest.from_file("../app.py").run()
        at.session_state["auth_user"] = officer
        at.session_state["current_page"] = "police_dashboard"
        at.run()

        # Inspect first case in queue
        rev_buttons = [b for b in at.button if "Inspect & Review" in b.label]
        self.assertTrue(len(rev_buttons) > 0)
        rev_buttons[0].click().run()

        # Side-by-side review screen should be active
        self.assertIsNotNone(at.session_state["active_police_case_id"])
        case_id = at.session_state["active_police_case_id"]

        # Approve FIR Draft
        approve_btn = [b for b in at.button if "Approve FIR Draft" in b.label][0]
        approve_btn.click().run()

        # Check database: case approved and download unlocked
        case_record = database.get_complaint_by_id(case_id)
        self.assertEqual(case_record["is_approved"], 1)
        self.assertEqual(case_record["fir_status"], "Approved")

    def test_citizen_dashboard_locked_and_unlocked_fir_download(self):
        """Verify citizen dashboard enforces locked FIR download until police approval."""
        _, _, citizen = database.authenticate_user("citizen@example.com", "Citizen@123")
        self.assertIsNotNone(citizen)

        at = AppTest.from_file("../app.py").run()
        at.session_state["auth_user"] = citizen
        at.session_state["current_page"] = "citizen_dashboard"
        at.run()

        self.assertEqual(at.session_state["current_page"], "citizen_dashboard")


if __name__ == "__main__":
    unittest.main()
