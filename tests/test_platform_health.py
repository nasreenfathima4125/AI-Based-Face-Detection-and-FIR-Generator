"""Tests for isolated platform health checks and their side effects."""

import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_database_support import isolate_database

import database
import platform_health


class TestPlatformHealth(unittest.TestCase):
    def setUp(self):
        self.database_path = isolate_database(self, database)

    def test_database_check_validates_sqlite_and_essential_schema(self):
        result = platform_health.check_database()
        self.assertEqual(result["status"], "Available")
        self.assertIn("essential application tables", result["detail"])
        self.assertIn("checked_at", result)

    def test_database_check_reports_missing_schema_without_exposing_path(self):
        with tempfile.TemporaryDirectory(prefix="fir-health-invalid-") as root:
            invalid_path = os.path.join(root, "invalid.sqlite3")
            connection = sqlite3.connect(invalid_path)
            try:
                connection.execute("CREATE TABLE unrelated (id INTEGER)")
            finally:
                connection.close()
            with patch.object(database, "DB_PATH", invalid_path):
                result = platform_health.check_database()
        self.assertEqual(result["status"], "Unavailable")
        self.assertNotIn(invalid_path, result["detail"])

    def test_database_check_reports_missing_file_without_creating_it(self):
        with tempfile.TemporaryDirectory(prefix="fir-health-missing-") as root:
            missing_path = os.path.join(root, "not-created.sqlite3")
            with patch.object(database, "DB_PATH", missing_path):
                result = platform_health.check_database()
            self.assertFalse(os.path.exists(missing_path))
        self.assertEqual(result["status"], "Unavailable")
        self.assertIn("does not exist", result["detail"])

    def test_complaint_intake_check_runs_the_real_validator(self):
        result = platform_health.check_complaint_intake()
        self.assertEqual(result["status"], "Available")
        self.assertIn("synthetic smoke test", result["detail"])

    def test_complaint_intake_check_reports_missing_validator(self):
        with patch.object(
            platform_health.importlib,
            "import_module",
            return_value=SimpleNamespace(SUPPORTED_CATEGORIES=[]),
        ):
            result = platform_health.check_complaint_intake()
        self.assertEqual(result["status"], "Unavailable")

    def test_template_draft_check_is_labelled_as_non_llm(self):
        result = platform_health.check_template_draft_generator()
        self.assertEqual(result["status"], "Available")
        self.assertIn("template-based", result["detail"])
        self.assertIn("no LLM is integrated", result["detail"])

    def test_authentication_check_uses_configured_endpoint_and_timeout(self):
        response = Mock(status=200)
        response.read.return_value = b"ok"
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.dict(
            os.environ,
            {
                "FIR_AUTH_GATEWAY_HOST": "127.0.0.1",
                "FIR_AUTH_GATEWAY_PORT": "8765",
                "FIR_AUTH_GATEWAY_HEALTH_TIMEOUT_SECONDS": "0.7",
            },
        ), patch.object(
            platform_health.http.client,
            "HTTPConnection",
            return_value=connection,
        ) as connection_factory:
            result = platform_health.check_authentication_gateway()
        connection_factory.assert_called_once_with(
            "127.0.0.1",
            8765,
            timeout=0.7,
        )
        connection.request.assert_called_once_with("GET", "/auth/health")
        self.assertEqual(result["status"], "Available")

    def test_authentication_check_reports_unavailable_service(self):
        with patch.object(
            platform_health.http.client,
            "HTTPConnection",
            side_effect=OSError("synthetic unavailable service"),
        ), patch.dict(
            os.environ,
            {"FIR_AUTH_GATEWAY_HOST": "127.0.0.1", "FIR_AUTH_GATEWAY_PORT": "0"},
        ):
            result = platform_health.check_authentication_gateway()
        self.assertEqual(result["status"], "Unavailable")

    def test_authentication_check_reports_gateway_timeout(self):
        connection = Mock()
        connection.getresponse.side_effect = TimeoutError("synthetic timeout")
        with patch.object(
            platform_health.http.client,
            "HTTPConnection",
            return_value=connection,
        ), patch.dict(
            os.environ,
            {"FIR_AUTH_GATEWAY_HOST": "127.0.0.1", "FIR_AUTH_GATEWAY_PORT": "8765"},
        ):
            result = platform_health.check_authentication_gateway()
        self.assertEqual(result["status"], "Unavailable")
        connection.close.assert_called_once()

    def test_audit_writer_health_check_rolls_back_its_transient_record(self):
        self.assertTrue(
            database.log_audit(
                complaint_id=None,
                actor_user_id=None,
                action="SYNTHETIC_TEST_BASELINE",
                details="Baseline row for health-check preservation test.",
            )
        )
        with database.get_db_connection() as connection:
            before = [
                tuple(row)
                for row in connection.execute(
                    "SELECT id, action, details, timestamp FROM audit_logs ORDER BY id"
                ).fetchall()
            ]
            table_counts_before = {
                table: connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                for table in ("users", "complaints", "fir_drafts")
            }
        result = platform_health.check_audit_writer()
        with database.get_db_connection() as connection:
            after = [
                tuple(row)
                for row in connection.execute(
                    "SELECT id, action, details, timestamp FROM audit_logs ORDER BY id"
                ).fetchall()
            ]
            table_counts_after = {
                table: connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                for table in ("users", "complaints", "fir_drafts")
            }
        self.assertEqual(result["status"], "Available")
        self.assertEqual(after, before)
        self.assertEqual(table_counts_after, table_counts_before)

    def test_all_check_results_have_supported_status_and_explanation(self):
        with patch.dict(os.environ, {"FIR_AUTH_GATEWAY_PORT": "0"}):
            results = platform_health.run_platform_health_checks()
        allowed_statuses = {"Available", "Degraded", "Unavailable", "Unknown"}
        self.assertEqual(len(results), 5)
        for result in results:
            self.assertIn(result["status"], allowed_statuses)
            self.assertTrue(result["component"])
            self.assertTrue(result["detail"])
            self.assertTrue(result["checked_at"])

    def test_one_unexpected_health_failure_does_not_stop_other_checks(self):
        with patch.object(
            platform_health,
            "check_database",
            side_effect=RuntimeError("synthetic check failure"),
        ), patch.dict(
            os.environ,
            {"FIR_AUTH_GATEWAY_PORT": "0"},
        ):
            results = platform_health.run_platform_health_checks()
        self.assertEqual(len(results), 5)
        self.assertEqual(results[0]["status"], "Unknown")
        self.assertTrue(all("checked_at" in result for result in results))


if __name__ == "__main__":
    unittest.main()
