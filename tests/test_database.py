"""
tests/test_database.py
----------------------
Unit tests for the SQLite persistent storage, authentication security,
complaint linking, audit logging, and restart resilience.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import hashlib
import sqlite3
import secrets
import os
import tempfile
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
        with database.get_db_connection() as connection:
            self.role_ids = {
                row["role"]: row["id"]
                for row in connection.execute(
                    "SELECT id, role FROM users"
                ).fetchall()
            }

    def test_seed_users_exist(self):
        """Verify seeded demonstration users exist."""
        users = database.get_all_users(admin_user_id=self.role_ids["admin"])
        self.assertTrue(len(users) >= 3)
        roles = {u["role"] for u in users}
        self.assertIn("police", roles)
        self.assertIn("admin", roles)
        self.assertIn("citizen", roles)

    def test_demo_accounts_require_explicit_opt_in(self):
        with tempfile.TemporaryDirectory(prefix="fir-no-demo-seed-") as root:
            isolated_path = os.path.join(root, "no-demo-users.sqlite3")
            with patch.object(database, "DB_PATH", isolated_path), patch.dict(
                os.environ,
                {"FIR_ENABLE_DEMO_ACCOUNTS": "false"},
            ):
                database.init_db()
                with database.get_db_connection() as connection:
                    user_count = connection.execute(
                        "SELECT COUNT(*) FROM users"
                    ).fetchone()[0]
        self.assertEqual(user_count, 0)

    def test_user_authentication(self):
        """Verify secure authentication for seeded police account."""
        success, msg, user = database.authenticate_user("officer@keralapolice.demo", "Police@123")
        self.assertTrue(success)
        self.assertIsNotNone(user)
        self.assertEqual(user["role"], "police")

        # Wrong password
        success_bad, msg_bad, _ = database.authenticate_user("officer@keralapolice.demo", "WrongPassword")
        self.assertFalse(success_bad)

    def test_privileged_roles_require_an_admin_provisioner(self):
        password = secrets.token_urlsafe(18)
        for requested_role in ("police", "admin"):
            with self.subTest(role=requested_role):
                success, _, user = database.create_user(
                    email=f"untrusted-{requested_role}@example.test",
                    full_name="Synthetic Role Test",
                    password=password,
                    role=requested_role,
                )
                self.assertFalse(success)
                self.assertIsNone(user)

        success, _, provisioned = database.create_user(
            email="admin-provisioned-police@example.test",
            full_name="Synthetic Provisioned Officer",
            password=password,
            role="police",
            created_by_user_id=self.role_ids["admin"],
        )
        self.assertTrue(success)
        self.assertEqual(provisioned["role"], "police")

    def test_role_changes_require_admin_and_preserve_the_last_admin(self):
        admin_id = self.role_ids["admin"]
        police_id = self.role_ids["police"]
        with self.assertRaises(database.AuthorizationError):
            database.update_user_role(
                police_id,
                "admin",
                admin_user_id=police_id,
            )
        self.assertFalse(
            database.update_user_role(
                admin_id,
                "citizen",
                admin_user_id=admin_id,
            )
        )
        self.assertTrue(
            database.update_user_role(
                police_id,
                "citizen",
                admin_user_id=admin_id,
            )
        )

    def test_admin_can_assign_roles_and_unchanged_role_is_not_a_change(self):
        admin_id = self.role_ids["admin"]
        citizen_id = self.role_ids["citizen"]
        self.assertTrue(
            database.update_user_role(
                citizen_id,
                "police",
                admin_user_id=admin_id,
            )
        )
        self.assertFalse(
            database.update_user_role(
                citizen_id,
                "police",
                admin_user_id=admin_id,
            )
        )
        self.assertTrue(
            database.update_user_role(
                citizen_id,
                "admin",
                admin_user_id=admin_id,
            )
        )

    def test_police_review_writes_and_admin_reads_reject_other_roles(self):
        _, _, complaint = database.save_complaint(
            complainant_name="Synthetic Access Test Citizen",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Synthetic Test Location",
            description="A synthetic complaint for authorization testing.",
        )
        citizen_id = self.role_ids["citizen"]
        with self.assertRaises(database.AuthorizationError):
            database.approve_fir_draft(
                complaint["id"],
                officer_user_id=citizen_id,
            )
        with self.assertRaises(database.AuthorizationError):
            database.update_fir_draft(
                complaint_id=complaint["id"],
                draft_content_ml="Synthetic unauthorized edit.",
                reviewer_user_id=citizen_id,
            )
        with self.assertRaises(database.AuthorizationError):
            database.return_complaint_for_correction(
                complaint_id=complaint["id"],
                officer_user_id=citizen_id,
                reason="Synthetic unauthorized return attempt.",
            )
        with self.assertRaises(database.AuthorizationError):
            database.update_complaint_status(
                complaint_id=complaint["id"],
                new_status="Closed",
                officer_user_id=citizen_id,
            )
        with self.assertRaises(database.AuthorizationError):
            database.get_all_users(admin_user_id=self.role_ids["police"])
        with self.assertRaises(database.AuthorizationError):
            database.get_audit_logs(admin_user_id=self.role_ids["police"])
        with self.assertRaises(database.AuthorizationError):
            database.get_all_complaints_for_police(
                police_user_id=self.role_ids["admin"]
            )
        with self.assertRaises(database.AuthorizationError):
            database.approve_fir_draft(
                complaint["id"],
                officer_user_id=self.role_ids["admin"],
            )
        stored = database.get_complaint_by_id(
            complaint["id"],
            actor_user_id=self.role_ids["police"],
        )
        self.assertFalse(stored["is_approved"])

    def test_admin_and_citizen_cannot_invoke_police_writes(self):
        _, _, complaint = database.save_complaint(
            complainant_name="Synthetic Role Boundary Citizen",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Synthetic Test Location",
            description="Synthetic facts for access-control testing.",
        )
        for role in ("citizen", "admin"):
            actor_id = self.role_ids[role]
            with self.subTest(role=role):
                with self.assertRaises(database.AuthorizationError):
                    database.update_fir_draft(
                        complaint_id=complaint["id"],
                        draft_content_ml="Synthetic unauthorized edit.",
                        reviewer_user_id=actor_id,
                    )
                with self.assertRaises(database.AuthorizationError):
                    database.return_complaint_for_correction(
                        complaint_id=complaint["id"],
                        officer_user_id=actor_id,
                        reason="Synthetic unauthorized return.",
                    )
                with self.assertRaises(database.AuthorizationError):
                    database.approve_fir_draft(
                        complaint_id=complaint["id"],
                        officer_user_id=actor_id,
                    )
                with self.assertRaises(database.AuthorizationError):
                    database.update_complaint_status(
                        complaint_id=complaint["id"],
                        new_status="Closed",
                        officer_user_id=actor_id,
                    )

    def test_reference_tracking_requires_contact_and_returns_only_status_fields(self):
        _, _, complaint = database.save_complaint(
            complainant_name="Synthetic Tracking Citizen",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Synthetic Test Location",
            description="Synthetic complaint for limited tracking output.",
        )
        self.assertIsNone(
            database.get_complaint_by_reference(
                complaint["reference_no"],
                "1111111111",
            )
        )
        tracking = database.get_complaint_by_reference(
            complaint["reference_no"],
            complaint["contact_number"],
        )
        self.assertEqual(
            set(tracking),
            {"id", "reference_no", "status", "fir_status"},
        )
        self.assertEqual(tracking["status"], "Submitted")

    def test_public_lookup_attempts_allow_valid_lookup_and_throttle_failures(self):
        _, _, complaint = database.save_complaint(
            complainant_name="Synthetic Lookup Rate Citizen",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Synthetic Rate Limit Location",
            description="Synthetic complaint used to test public lookup throttling.",
        )
        key = hashlib.sha256(b"synthetic-client-ip").hexdigest()
        now = datetime(2026, 10, 1, tzinfo=timezone.utc)

        with patch.dict(
            os.environ,
            {
                "FIR_PUBLIC_LOOKUP_RATE_LIMIT": "3",
                "FIR_PUBLIC_LOOKUP_RATE_WINDOW_SECONDS": "900",
            },
        ):
            for _ in range(2):
                self.assertIsNone(
                    database.reserve_public_complaint_lookup(key, now=now)
                )
                self.assertIsNone(
                    database.get_complaint_by_reference(
                        complaint["reference_no"],
                        "1111111111",
                    )
                )

            self.assertIsNone(
                database.reserve_public_complaint_lookup(key, now=now)
            )
            result = database.get_complaint_by_reference(
                complaint["reference_no"],
                complaint["contact_number"],
            )
            self.assertEqual(result["reference_no"], complaint["reference_no"])
            self.assertIsNotNone(
                database.reserve_public_complaint_lookup(key, now=now)
            )

    def test_public_lookup_limit_is_shared_across_sessions_and_expires(self):
        key = hashlib.sha256(b"same-client-across-browser-sessions").hexdigest()
        first_request = datetime(2026, 10, 1, tzinfo=timezone.utc)
        with patch.dict(
            os.environ,
            {
                "FIR_PUBLIC_LOOKUP_RATE_LIMIT": "1",
                "FIR_PUBLIC_LOOKUP_RATE_WINDOW_SECONDS": "60",
            },
        ):
            # The rate-limit service accepts only the client digest, not a
            # Streamlit session id, so another session uses the same bucket.
            self.assertIsNone(
                database.reserve_public_complaint_lookup(
                    key,
                    now=first_request,
                )
            )
            retry_after = database.reserve_public_complaint_lookup(
                key,
                now=first_request + timedelta(seconds=10),
            )
            self.assertEqual(retry_after, 50)
            self.assertIsNone(
                database.reserve_public_complaint_lookup(
                    key,
                    now=first_request + timedelta(seconds=60),
                )
            )

        with database.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM public_complaint_lookup_limits"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_concurrent_public_lookup_reservations_do_not_exceed_limit(self):
        key = hashlib.sha256(b"concurrent-synthetic-client").hexdigest()
        now = datetime(2026, 10, 1, tzinfo=timezone.utc)
        with patch.dict(
            os.environ,
            {
                "FIR_PUBLIC_LOOKUP_RATE_LIMIT": "4",
                "FIR_PUBLIC_LOOKUP_RATE_WINDOW_SECONDS": "900",
            },
        ):
            with ThreadPoolExecutor(max_workers=12) as executor:
                results = list(
                    executor.map(
                        lambda _index: database.reserve_public_complaint_lookup(
                            key,
                            now=now,
                        ),
                        range(20),
                    )
                )

        self.assertEqual(sum(result is None for result in results), 4)
        self.assertEqual(sum(result is not None for result in results), 16)

    def test_citizen_reads_are_limited_to_their_own_complaints(self):
        _, _, complaint = database.save_complaint(
            complainant_name="Synthetic Owner Test Citizen",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Synthetic Test Location",
            description="A synthetic complaint with an assigned owner.",
            citizen_user_id=self.role_ids["citizen"],
        )
        with self.assertRaises(database.AuthorizationError):
            database.get_complaint_by_id(
                complaint["id"],
                actor_user_id=self.role_ids["admin"],
            )
        with self.assertRaises(database.AuthorizationError):
            database.get_complaints_for_citizen(
                self.role_ids["citizen"],
                requesting_user_id=self.role_ids["admin"],
            )
        second_success, _, second_citizen = database.create_user(
            email="synthetic-second-citizen@example.test",
            full_name="Synthetic Second Citizen",
            password=secrets.token_urlsafe(18),
        )
        self.assertTrue(second_success)
        with self.assertRaises(database.AuthorizationError):
            database.get_complaints_for_citizen(
                self.role_ids["citizen"],
                requesting_user_id=second_citizen["id"],
            )
        with self.assertRaises(database.AuthorizationError):
            database.get_latest_fir_draft(
                complaint["id"],
                actor_user_id=second_citizen["id"],
            )

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
        tracking = database.get_complaint_by_reference(
            record["reference_no"], record["contact_number"]
        )
        fetched = database.get_complaint_by_id(
            tracking["id"], actor_user_id=self.role_ids["police"]
        )
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

    def test_complaint_draft_and_audit_roll_back_together_on_audit_failure(self):
        with database.get_db_connection() as connection:
            before = {
                table: connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                for table in ("complaints", "fir_drafts", "audit_logs")
            }

        with patch.object(
            database,
            "_insert_audit_log",
            side_effect=sqlite3.IntegrityError("synthetic audit failure"),
        ), self.assertRaises(sqlite3.DatabaseError):
            database.save_complaint(
                complainant_name="Fictional Atomic Citizen",
                contact_number="9876543210",
                category="Theft / Burglary (മോഷണം)",
                incident_date="Unknown",
                incident_location="Sample Road",
                description="A fictional item was reported missing.",
                draft_content_ml="Fictional template draft.",
            )

        with database.get_db_connection() as connection:
            after = {
                table: connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                for table in ("complaints", "fir_drafts", "audit_logs")
            }
        self.assertEqual(after, before)

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
        saved_draft = database.get_latest_fir_draft(record["id"], actor_user_id=self.role_ids["police"])
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
            citizen_user_id=self.role_ids["citizen"],
        )
        self.assertFalse(linked_bad)
        self.assertIn("Ownership verification failed", msg_bad)

        # Link with matching phone number should succeed
        linked_good, msg_good = database.link_complaint_to_citizen(
            reference_no=ref_no,
            contact_number="+91 98765-43210",
            citizen_user_id=self.role_ids["citizen"],
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
        draft = database.get_latest_fir_draft(complaint_id, actor_user_id=self.role_ids["police"])
        self.assertIsNotNone(draft)
        self.assertEqual(draft["status"], "Pending Police Approval")

        # 2. Update FIR draft with Malayalam content
        ml_content = "പ്രഥമ വിവര വിവരണം: സ്വർണ്ണമാല കവർച്ച ചെയ്യപ്പെട്ടു."
        updated = database.update_fir_draft(
            complaint_id=complaint_id,
            draft_content_ml=ml_content,
            reviewer_user_id=self.role_ids["police"],
            reviewer_notes="Draft revised with witness facts.",
        )
        self.assertTrue(updated)

        # 3. Return for correction
        ret = database.return_complaint_for_correction(
            complaint_id=complaint_id,
            officer_user_id=self.role_ids["police"],
            reason="Exact motorcycle model and color required.",
        )
        self.assertTrue(ret)
        c_ret = database.get_complaint_by_id(complaint_id, actor_user_id=self.role_ids["police"])
        self.assertEqual(c_ret["status"], "More Information Required")

        # 4. Approve FIR
        app = database.approve_fir_draft(
            complaint_id=complaint_id,
            officer_user_id=self.role_ids["police"],
            officer_notes="Verified by Station Officer.",
        )
        self.assertTrue(app)
        c_app = database.get_complaint_by_id(complaint_id, actor_user_id=self.role_ids["police"])
        self.assertEqual(c_app["is_approved"], 1)
        self.assertEqual(c_app["fir_status"], "Approved")

    def test_approved_download_is_owner_only_and_requires_complete_approval(self):
        created, _, other_citizen = database.create_user(
            email="other-fir-citizen@example.test",
            full_name="Other Fictional Citizen",
            password="SyntheticTestPassword!",
        )
        self.assertTrue(created)
        _, _, complaint = database.save_complaint(
            complainant_name="Fictional Download Citizen",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Sample Road",
            description="A fictional item was reported missing.",
            citizen_user_id=self.role_ids["citizen"],
            draft_content_ml="പഴയ മാതൃകാ കരട്",
        )
        complaint_id = complaint["id"]

        self.assertIsNone(
            database.get_approved_fir_draft_for_citizen(
                complaint_id,
                citizen_user_id=self.role_ids["citizen"],
            )
        )
        for user_id in (other_citizen["id"], self.role_ids["police"], self.role_ids["admin"]):
            with self.subTest(actor=user_id), self.assertRaises(database.AuthorizationError):
                database.get_approved_fir_draft_for_citizen(
                    complaint_id,
                    citizen_user_id=user_id,
                )

        self.assertTrue(
            database.return_complaint_for_correction(
                complaint_id,
                officer_user_id=self.role_ids["police"],
                reason="Request a fictional missing detail.",
            )
        )
        self.assertIsNone(
            database.get_approved_fir_draft_for_citizen(
                complaint_id,
                citizen_user_id=self.role_ids["citizen"],
            )
        )

        approved_text = "മലയാളം അംഗീകരിച്ച പതിപ്പ് — हिन्दी विवरण"
        self.assertTrue(
            database.review_fir_draft(
                complaint_id=complaint_id,
                reviewer_user_id=self.role_ids["police"],
                decision="approve",
                draft_content_ml=approved_text,
                reviewer_notes="Fictional test approval.",
            )
        )
        approved = database.get_approved_fir_draft_for_citizen(
            complaint_id,
            citizen_user_id=self.role_ids["citizen"],
        )
        self.assertEqual(approved["draft_content_ml"], approved_text)
        self.assertEqual(approved["status"], "Approved")
        self.assertEqual(approved["reviewed_by_user_id"], self.role_ids["police"])

    def test_incomplete_approval_states_do_not_unlock_download(self):
        for inconsistent_field in (
            "draft_status",
            "complaint_status",
            "reviewer",
            "audit",
        ):
            with self.subTest(field=inconsistent_field):
                _, _, complaint = database.save_complaint(
                    complainant_name="Fictional Approval State Citizen",
                    contact_number="9876543210",
                    category="Theft / Burglary (മോഷണം)",
                    incident_date="Unknown",
                    incident_location="Sample Road",
                    description="A fictional item was reported missing.",
                    citizen_user_id=self.role_ids["citizen"],
                    draft_content_ml="Fictional review draft.",
                )
                complaint_id = complaint["id"]
                self.assertTrue(
                    database.approve_fir_draft(
                        complaint_id,
                        officer_user_id=self.role_ids["police"],
                        officer_notes="Fictional state test approval.",
                    )
                )
                with database.get_db_connection() as connection:
                    if inconsistent_field == "draft_status":
                        connection.execute(
                            "UPDATE fir_drafts SET status = 'Pending Police Approval' WHERE complaint_id = ?",
                            (complaint_id,),
                        )
                    elif inconsistent_field == "complaint_status":
                        connection.execute(
                            "UPDATE complaints SET fir_status = 'Pending Police Approval' WHERE id = ?",
                            (complaint_id,),
                        )
                    elif inconsistent_field == "reviewer":
                        connection.execute(
                            "UPDATE fir_drafts SET reviewed_by_user_id = NULL WHERE complaint_id = ?",
                            (complaint_id,),
                        )
                    else:
                        connection.execute(
                            "DELETE FROM audit_logs WHERE complaint_id = ? AND action = 'FIR_APPROVED'",
                            (complaint_id,),
                        )
                    connection.commit()
                self.assertIsNone(
                    database.get_approved_fir_draft_for_citizen(
                        complaint_id,
                        citizen_user_id=self.role_ids["citizen"],
                    )
                )

    def test_police_review_decision_and_audit_roll_back_together(self):
        _, _, complaint = database.save_complaint(
            complainant_name="Fictional Atomic Review Citizen",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Sample Road",
            description="A fictional item was reported missing.",
            draft_content_ml="Original fictional draft.",
        )
        complaint_id = complaint["id"]
        with database.get_db_connection() as connection:
            before_audits = connection.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE complaint_id = ?",
                (complaint_id,),
            ).fetchone()[0]

        with patch.object(
            database,
            "_insert_audit_log",
            side_effect=sqlite3.IntegrityError("synthetic audit failure"),
        ), self.assertRaises(sqlite3.DatabaseError):
            database.review_fir_draft(
                complaint_id=complaint_id,
                reviewer_user_id=self.role_ids["police"],
                decision="approve",
                draft_content_ml="New fictional edited version.",
                reviewer_notes="Fictional approval attempt.",
            )

        case = database.get_complaint_by_id(
            complaint_id,
            actor_user_id=self.role_ids["police"],
        )
        draft = database.get_latest_fir_draft(
            complaint_id,
            actor_user_id=self.role_ids["police"],
        )
        with database.get_db_connection() as connection:
            after_audits = connection.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE complaint_id = ?",
                (complaint_id,),
            ).fetchone()[0]
        self.assertEqual(case["is_approved"], 0)
        self.assertEqual(case["fir_status"], "Pending Police Approval")
        self.assertEqual(draft["status"], "Pending Police Approval")
        self.assertEqual(draft["draft_content_ml"], "Original fictional draft.")
        self.assertEqual(after_audits, before_audits)

    def test_editing_or_returning_approved_draft_revokes_approval(self):
        """An approval applies only to the exact draft the reviewer approved."""
        _, _, record = database.save_complaint(
            complainant_name="Fictional Review Citizen",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Sample Road",
            description="A fictional bag was reported missing.",
            draft_content_ml="Fictional demonstration draft.",
        )
        complaint_id = record["id"]

        self.assertTrue(
            database.approve_fir_draft(
                complaint_id,
                officer_user_id=self.role_ids["police"],
                officer_notes="Approved for the prototype workflow.",
            )
        )
        self.assertEqual(
            database.get_complaint_by_id(complaint_id, actor_user_id=self.role_ids["police"])["is_approved"],
            1,
        )

        self.assertTrue(
            database.update_fir_draft(
                complaint_id=complaint_id,
                draft_content_ml="Revised fictional pending draft.",
                reviewer_user_id=self.role_ids["police"],
                status="Pending Police Approval",
            )
        )
        edited_complaint = database.get_complaint_by_id(complaint_id, actor_user_id=self.role_ids["police"])
        edited_draft = database.get_latest_fir_draft(complaint_id, actor_user_id=self.role_ids["police"])
        self.assertEqual(edited_complaint["is_approved"], 0)
        self.assertEqual(edited_complaint["status"], "Submitted")
        self.assertEqual(
            edited_complaint["fir_status"],
            "Pending Police Approval",
        )
        self.assertEqual(edited_draft["status"], "Pending Police Approval")

        self.assertTrue(
            database.approve_fir_draft(
                complaint_id,
                officer_user_id=self.role_ids["police"],
                officer_notes="Re-approved for the prototype workflow.",
            )
        )
        self.assertTrue(
            database.return_complaint_for_correction(
                complaint_id,
                officer_user_id=self.role_ids["police"],
                reason="Please review the fictional details.",
            )
        )
        returned_complaint = database.get_complaint_by_id(complaint_id, actor_user_id=self.role_ids["police"])
        returned_draft = database.get_latest_fir_draft(complaint_id, actor_user_id=self.role_ids["police"])
        self.assertEqual(returned_complaint["is_approved"], 0)
        self.assertEqual(
            returned_complaint["fir_status"],
            "Returned for Correction",
        )
        self.assertEqual(
            returned_draft["status"],
            "Returned for Correction",
        )


if __name__ == "__main__":
    unittest.main()
