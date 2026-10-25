"""
tests/test_database.py
----------------------
Unit tests for the SQLite persistent storage, authentication security,
complaint linking, audit logging, and restart resilience.
"""

from datetime import date
import sqlite3
import unittest
from unittest.mock import patch

from test_database_support import isolate_database

import database
from complaint_manager import generate_malayalam_fir_draft


class TestDatabaseLayer(unittest.TestCase):
    """Test suite for database persistence and authentication."""

    def setUp(self):
        """Initialize a fresh, isolated database before each test."""
        self.database_path = isolate_database(self, database)

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

    def test_complaint_persistence_survives_reopening_database(self):
        """Verify a saved complaint is available after opening a new connection."""
        success, _, record = database.save_complaint(
            complainant_name="Fictional Citizen",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Sample Road",
            description="A fictional item was taken from a sample location.",
        )
        self.assertTrue(success)

        with database.get_db_connection() as connection:
            row = connection.execute(
                "SELECT reference_no FROM complaints WHERE id = ?",
                (record["id"],),
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["reference_no"], record["reference_no"])

    def test_each_complaint_receives_a_unique_reference(self):
        """Verify separate complaint submissions receive distinct references."""
        references = set()
        for name in ("Fictional Citizen One", "Fictional Citizen Two"):
            success, _, record = database.save_complaint(
                complainant_name=name,
                contact_number="9876543210",
                category="Theft / Burglary (മോഷണം)",
                incident_date="Unknown",
                incident_location="Sample Road",
                description="A fictional item was taken from a sample location.",
            )
            self.assertTrue(success)
            references.add(record["reference_no"])

        self.assertEqual(len(references), 2)

    def test_duplicate_reference_fails_without_saving_second_complaint(self):
        """Verify the unique database constraint rejects a repeated reference."""
        with patch.object(
            database,
            "generate_reference_number",
            return_value="CMP-TEST-DUPLICATE",
        ):
            database.save_complaint(
                complainant_name="Fictional Citizen One",
                contact_number="9876543210",
                category="Theft / Burglary (മോഷണം)",
                incident_date="Unknown",
                incident_location="Sample Road",
                description="A fictional item was taken from a sample location.",
            )
            with self.assertRaises(sqlite3.IntegrityError):
                database.save_complaint(
                    complainant_name="Fictional Citizen Two",
                    contact_number="9876543211",
                    category="Theft / Burglary (മോഷണം)",
                    incident_date="Unknown",
                    incident_location="Sample Road",
                    description="A second fictional item was taken from a sample location.",
                )

        with database.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM complaints"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_saved_generated_draft_uses_persisted_reference(self):
        """Ensure the generator's placeholder is replaced with the saved reference."""
        draft_content = generate_malayalam_fir_draft(
            complainant_name="Fictional Complainant",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Fictional Market Road",
            description="A fictional item was reported missing.",
        )
        success, _, record = database.save_complaint(
            complainant_name="Fictional Complainant",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Fictional Market Road",
            description="A fictional item was reported missing.",
            draft_content_ml=draft_content,
        )

        self.assertTrue(success)
        saved_draft = database.get_latest_fir_draft(record["id"])
        self.assertIsNotNone(saved_draft)
        self.assertIn(record["reference_no"], saved_draft["draft_content_ml"])
        self.assertNotIn("CMP-DRAFT", saved_draft["draft_content_ml"])

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
