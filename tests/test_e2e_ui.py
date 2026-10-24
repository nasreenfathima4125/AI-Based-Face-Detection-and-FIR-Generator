"""
tests/test_e2e_ui.py
--------------------
End-to-end simulated user journey tests for the multi-page application:
1. Verifies app opens on Landing Page as default screen.
2. Tests 'Start a Complaint' navigation (no login required).
3. Tests conversational complaint chat (validation of invalid inputs, Unicode handling).
4. Tests Incident Verification screen (editing, cancelling without saving, confirming).
5. Tests single-save confirmation and locked FIR download notice.
6. Tests Portal Login and Role-Specific Dashboards (Citizen, Police, Admin).
"""

from datetime import date
import unittest
from streamlit.testing.v1 import AppTest


class TestStreamlitAppMultiPageE2E(unittest.TestCase):
    """End-to-end testing of the complete multi-page flow using Streamlit AppTest."""

    def test_app_opens_on_landing_page(self):
        """Verify the app launches on the landing page with proper actions and disclaimer."""
        at = AppTest.from_file("../app.py").run()
        self.assertFalse(at.exception)

        # Default page must be landing
        self.assertEqual(at.session_state["current_page"], "landing")

        # Verify buttons present on landing page
        button_labels = [b.label for b in at.button]
        self.assertTrue(any("Start a Complaint" in lbl for lbl in button_labels))
        self.assertTrue(any("Portal Login" in lbl or "Login" in lbl for lbl in button_labels))
        self.assertTrue(any("Create Account" in lbl for lbl in button_labels))

        # Check disclaimer exists and does NOT contain student/college wording
        disclaimer_texts = [m.value for m in at.markdown if "Not an Official Police Portal" in m.value]
        self.assertTrue(len(disclaimer_texts) > 0)
        for dt in disclaimer_texts:
            self.assertNotIn("student", dt.lower())
            self.assertNotIn("college", dt.lower())

    def test_start_complaint_opens_chat(self):
        """Verify clicking Start a Complaint opens the conversational chat."""
        at = AppTest.from_file("../app.py").run()
        start_btn = [b for b in at.button if "Start a Complaint" in b.label][0]
        start_btn.click().run()

        self.assertEqual(at.session_state["current_page"], "chat")
        self.assertTrue(len(at.chat_input) > 0)
        self.assertTrue(len(at.chat_message) > 0)
        self.assertIn("Welcome", at.chat_message[0].markdown[0].value)

    def test_chat_conversational_validation_and_unicode(self):
        """
        Verify conversational intake:
        - Rejects invalid/short input with helpful guidance.
        - Preserves Malayalam Unicode text.
        """
        at = AppTest.from_file("../app.py").run()
        at.session_state["current_page"] = "chat"
        at.run()

        # 1. Invalid short description
        at.chat_input[0].set_value("Short").run()
        self.assertIn("Please clarify", at.chat_message[-1].markdown[0].value)
        self.assertEqual(at.session_state["chat_step_index"], 0)

        # 2. Valid Malayalam description
        malayalam_desc = "ഇന്നലെ വൈകുന്നേരം 5 മണിക്ക് ആലുവ റെയിൽവേ സ്റ്റേഷനിൽ വെച്ച് എന്റെ ബാഗ് നഷ്ടപ്പെട്ടു."
        at.chat_input[0].set_value(malayalam_desc).run()
        self.assertEqual(at.session_state["chat_step_index"], 1)
        self.assertEqual(at.session_state["complaint_slots"]["description"], malayalam_desc)

        # 3. Invalid short name
        at.chat_input[0].set_value("A").run()
        self.assertIn("at least 2 characters", at.chat_message[-1].markdown[0].value)
        self.assertEqual(at.session_state["chat_step_index"], 1)

        # 4. Valid Malayalam name
        malayalam_name = "രാജേഷ് കുമാർ"
        at.chat_input[0].set_value(malayalam_name).run()
        self.assertEqual(at.session_state["chat_step_index"], 2)
        self.assertEqual(at.session_state["complaint_slots"]["name"], malayalam_name)

    def test_verification_cancellation_does_not_save(self):
        """Verify cancelling from the verification screen does not save any complaint."""
        at = AppTest.from_file("../app.py").run()
        at.session_state["current_page"] = "verify"
        at.session_state["complaint_slots"] = {
            "name": "Rajesh Kumar",
            "contact_number": "+91 9447123456",
            "category": "Theft / Burglary (മോഷണം)",
            "incident_date": date.today().isoformat(),
            "incident_time": "3:00 PM",
            "location": "Aluva Station",
            "description": "My bag was stolen near the platform at around 3 PM.",
            "additional_info": "Black leather",
        }
        at.run()

        # Initial complaints count is 0
        self.assertEqual(len(at.session_state["complaints"]), 0)

        # Click Cancel
        cancel_btn = [b for b in at.button if "Cancel Complaint" in b.label][0]
        cancel_btn.click().run()

        # Returns to landing and no complaint was saved
        self.assertEqual(at.session_state["current_page"], "landing")
        self.assertEqual(len(at.session_state["complaints"]), 0)

    def test_verification_confirmation_saves_once_and_shows_policy(self):
        """
        Verify that confirming on the verification screen:
        1. Saves the complaint record exactly once.
        2. Assigns a unique reference ID.
        3. Moves to the confirmation screen.
        4. Informs citizen that FIR download is locked until police approval.
        """
        at = AppTest.from_file("../app.py").run()
        at.session_state["current_page"] = "verify"
        at.session_state["complaint_slots"] = {
            "name": "Rajesh Kumar",
            "contact_number": "+91 9447123456",
            "category": "Theft / Burglary (മോഷണം)",
            "incident_date": date.today().isoformat(),
            "incident_time": "3:00 PM",
            "location": "Aluva Station",
            "description": "My bag was stolen near the platform at around 3 PM.",
            "additional_info": "Black leather",
        }
        at.run()

        confirm_btn = [b for b in at.button if "Confirm Details" in b.label][0]
        confirm_btn.click().run()

        self.assertEqual(at.session_state["current_page"], "confirmation")
        self.assertEqual(len(at.session_state["complaints"]), 1)

        saved = at.session_state["complaints"][0]
        self.assertTrue(saved["complaint_id"].startswith("CMP-"))
        self.assertEqual(saved["complainant_name"], "Rajesh Kumar")
        self.assertEqual(saved["status"], "Complaint Submitted — FIR Draft Not Yet Generated")

        # Verify confirmation screen explains locked FIR download
        info_texts = [inf.value for inf in at.info]
        self.assertTrue(any("unlocked only after police personnel" in t for t in info_texts))

    def test_login_and_role_dashboards(self):
        """Verify role selection and role dashboards for Citizen, Police, and Admin."""
        at = AppTest.from_file("../app.py").run()
        at.session_state["current_page"] = "login"
        at.run()

        # 1. Citizen Dashboard
        cit_btn = [b for b in at.button if "Citizen" in b.label][0]
        cit_btn.click().run()
        self.assertEqual(at.session_state["current_page"], "citizen_dashboard")
        self.assertEqual(at.session_state["user_role"], "citizen")

        # 2. Police Dashboard
        at.session_state["current_page"] = "login"
        at.run()
        pol_btn = [b for b in at.button if "Police Officer" in b.label][0]
        pol_btn.click().run()
        self.assertEqual(at.session_state["current_page"], "police_dashboard")
        self.assertEqual(at.session_state["user_role"], "police")

        # 3. Admin Dashboard
        at.session_state["current_page"] = "login"
        at.run()
        adm_btn = [b for b in at.button if "Administrator" in b.label][0]
        adm_btn.click().run()
        self.assertEqual(at.session_state["current_page"], "admin_dashboard")
        self.assertEqual(at.session_state["user_role"], "admin")


if __name__ == "__main__":
    unittest.main()
