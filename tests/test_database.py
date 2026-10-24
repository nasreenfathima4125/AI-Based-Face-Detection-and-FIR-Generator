"""
tests/test_database.py
----------------------
Unit tests for the SQLite persistent storage, authentication security,
complaint linking, audit logging, and restart resilience.
"""

from datetime import date
import os
import unittest
import database


class TestDatabaseLayer(unittest.TestCase):
    """Test suite for database persistence and authentication."""

    def setUp(self):
        """Ensure schema is initialized before each test."""
        database.init_db()

    def test_seed_users_exist(self):
        """Verify seeded demonstration users exist."""
        users = database.get_all_users()
        self.assertTrue(len(users) >= 3)
        roles = {u["role"] for u in users}
        self.assertIn("police", roles)
        self.assertIn("admin", roles)
        self.assertIn("citizen", roles)

    def test_user_authentication(self):
        """Verify secure authentication for seeded police account."""
        success, msg, user = database.authenticate_user("officer@keralapolice.demo", "Police@123")
        self.assertTrue(success)
        self.assertIsNotNone(user)
        self.assertEqual(user["role"], "police")

        # Wrong password
        success_bad, msg_bad, _ = database.authenticate_user("officer@keralapolice.demo", "WrongPassword")
        self.assertFalse(success_bad)

    def test_complaint_persistence_and_reference_generation(self):
        """Verify complaints persist and receive unique reference numbers."""
        success, msg, record = database.save_complaint(
            complainant_name="Test Complainant",
            contact_number="+91 9447111222",
            category="Theft / Burglary (മോഷണം)",
            incident_date="2026-10-24",
            incident_location="Kochi Town",
            description="Laptop bag taken from vehicle parked near market.",
            additional_info="HP laptop inside",
            incident_time="3:30 PM",
            intake_language="en",
        )
        self.assertTrue(success)
        self.assertIn("reference_no", record)
        self.assertTrue(record["reference_no"].startswith("CMP-"))

        # Fetch by reference number
        fetched = database.get_complaint_by_reference(record["reference_no"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["complainant_name"], "Test Complainant")
        self.assertEqual(fetched["status"], "Submitted")

    def test_secure_complaint_linking(self):
        """Verify complaint linking requires phone number match."""
        # Create unauthenticated complaint
        _, _, record = database.save_complaint(
            complainant_name="Anoop",
            contact_number="+91 9876543210",
            category="Cybercrime / Online Fraud (സൈബർ കുറ്റകൃത്യം)",
            incident_date="2026-10-24",
            incident_location="Ernakulam",
            description="Online banking fraud unauthorized transaction.",
        )
        ref_no = record["reference_no"]

        # Link with wrong phone number should fail
        linked_bad, msg_bad = database.link_complaint_to_citizen(
            reference_no=ref_no,
            contact_number="9999999999",
            citizen_user_id=1,
        )
        self.assertFalse(linked_bad)
        self.assertIn("Ownership verification failed", msg_bad)

        # Link with matching phone number should succeed
        linked_good, msg_good = database.link_complaint_to_citizen(
            reference_no=ref_no,
            contact_number="+91 98765-43210",
            citizen_user_id=1,
        )
        self.assertTrue(linked_good)

    def test_fir_draft_and_approval_workflow(self):
        """Verify FIR draft review, editing, return for correction, and approval."""
        _, _, record = database.save_complaint(
            complainant_name="Sangeetha",
            contact_number="+91 9447123999",
            category="Theft / Burglary (മോഷണം)",
            incident_date="2026-10-24",
            incident_location="Aluva",
            description="Gold chain snatched by two motorcycle riders.",
        )
        complaint_id = record["id"]

        # 1. Fetch initial draft
        draft = database.get_latest_fir_draft(complaint_id)
        self.assertIsNotNone(draft)
        self.assertEqual(draft["status"], "Pending Police Approval")

        # 2. Update FIR draft with Malayalam content
        ml_content = "പ്രഥമ വിവര വിവരണം: സ്വർണ്ണമാല കവർച്ച ചെയ്യപ്പെട്ടു."
        updated = database.update_fir_draft(
            complaint_id=complaint_id,
            draft_content_ml=ml_content,
            reviewer_user_id=1,
            reviewer_notes="Draft revised with witness facts.",
        )
        self.assertTrue(updated)

        # 3. Return for correction
        ret = database.return_complaint_for_correction(
            complaint_id=complaint_id,
            officer_user_id=1,
            reason="Exact motorcycle model and color required.",
        )
        self.assertTrue(ret)
        c_ret = database.get_complaint_by_id(complaint_id)
        self.assertEqual(c_ret["status"], "More Information Required")

        # 4. Approve FIR
        app = database.approve_fir_draft(
            complaint_id=complaint_id,
            officer_user_id=1,
            officer_notes="Verified by Station Officer.",
        )
        self.assertTrue(app)
        c_app = database.get_complaint_by_id(complaint_id)
        self.assertEqual(c_app["is_approved"], 1)
        self.assertEqual(c_app["fir_status"], "Approved")


if __name__ == "__main__":
    unittest.main()
