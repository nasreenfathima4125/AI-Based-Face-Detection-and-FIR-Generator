"""Lightweight, side-effect-conscious checks for the admin health panel."""

from datetime import datetime
import http.client
import importlib
import logging
import os
import sqlite3
from typing import Callable, Dict

import database


_LOGGER = logging.getLogger(__name__)
_ESSENTIAL_TABLES = {
    "users",
    "complaints",
    "fir_drafts",
    "auth_sessions",
    "audit_logs",
}


def _result(component: str, status: str, detail: str) -> Dict[str, str]:
    return {
        "component": component,
        "status": status,
        "detail": detail,
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def check_database() -> Dict[str, str]:
    """Checks SQLite reachability and essential schema without changing data."""
    try:
        if not os.path.isfile(database.DB_PATH):
            return _result(
                "Database",
                "Unavailable",
                "The configured database file does not exist.",
            )
        with database.get_db_connection() as connection:
            connection.execute("SELECT 1").fetchone()
            objects = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        missing = sorted(_ESSENTIAL_TABLES - objects)
        if missing:
            _LOGGER.warning("Database health check found missing schema objects.")
            return _result(
                "Database",
                "Unavailable",
                "The database is reachable, but required application tables are missing.",
            )
        return _result(
            "Database",
            "Available",
            "SQLite is reachable and the essential application tables are present.",
        )
    except (OSError, sqlite3.Error):
        _LOGGER.exception("Database health check failed.")
        return _result(
            "Database",
            "Unavailable",
            "The configured database could not be checked.",
        )


def check_complaint_intake() -> Dict[str, str]:
    """Checks the live complaint validator and runs a synthetic smoke test."""
    try:
        manager = importlib.import_module("complaint_manager")
        validator = getattr(manager, "validate_complaint_input", None)
        categories = getattr(manager, "SUPPORTED_CATEGORIES", ())
        if not callable(validator) or not categories:
            return _result(
                "Complaint intake",
                "Unavailable",
                "Required complaint validation functions are not available.",
            )
        valid, errors = validator(
            name="Synthetic Health Check Citizen",
            contact_number="9876543210",
            category=categories[0],
            incident_date="Unknown",
            location="Synthetic Test Location",
            description="Synthetic complaint validation smoke test.",
            additional_info="",
        )
        if not valid or errors:
            return _result(
                "Complaint intake",
                "Degraded",
                "The validator loaded, but its synthetic smoke test did not pass.",
            )
        return _result(
            "Complaint intake",
            "Available",
            "Complaint validation is available and passed a synthetic smoke test.",
        )
    except Exception:
        _LOGGER.exception("Complaint intake health check failed.")
        return _result(
            "Complaint intake",
            "Unavailable",
            "Complaint validation could not be checked.",
        )


def check_template_draft_generator() -> Dict[str, str]:
    """Checks the template-based FIR generator using synthetic input only."""
    try:
        manager = importlib.import_module("complaint_manager")
        generator = getattr(manager, "generate_malayalam_fir_draft", None)
        if not callable(generator):
            return _result(
                "Template FIR draft generator",
                "Unavailable",
                "The template-based draft generator is not available.",
            )
        generated = generator(
            complainant_name="Synthetic Health Check Citizen",
            contact_number="0000000000",
            category="Synthetic category",
            incident_date="Unknown",
            incident_location="Synthetic Test Location",
            description="Synthetic draft-generation smoke test.",
            reference_no="HEALTH-CHECK-ONLY",
        )
        if not isinstance(generated, str) or not generated.strip():
            return _result(
                "Template FIR draft generator",
                "Degraded",
                "The generator is callable, but returned no draft text.",
            )
        return _result(
            "Template FIR draft generator",
            "Available",
            "The template-based generator passed a synthetic in-memory smoke test; no LLM is integrated.",
        )
    except Exception:
        _LOGGER.exception("Template draft generator health check failed.")
        return _result(
            "Template FIR draft generator",
            "Unavailable",
            "The template-based draft generator could not be checked.",
        )


def _configured_timeout() -> float:
    raw_timeout = os.environ.get("FIR_AUTH_GATEWAY_HEALTH_TIMEOUT_SECONDS", "2")
    timeout = float(raw_timeout)
    if not 0.1 <= timeout <= 10:
        raise ValueError("Health timeout must be between 0.1 and 10 seconds.")
    return timeout


def check_authentication_gateway() -> Dict[str, str]:
    """Checks the configured gateway's non-sensitive availability endpoint."""
    connection: http.client.HTTPConnection | None = None
    try:
        host = os.environ.get("FIR_AUTH_GATEWAY_HOST", "127.0.0.1")
        port = int(os.environ.get("FIR_AUTH_GATEWAY_PORT", "8502"))
        timeout = _configured_timeout()
        connection = http.client.HTTPConnection(host, port, timeout=timeout)
        connection.request("GET", "/auth/health")
        response = connection.getresponse()
        body = response.read(128)
        if response.status == 200 and body == b"ok":
            return _result(
                "Authentication gateway",
                "Available",
                "The configured authentication gateway health endpoint responded.",
            )
        return _result(
            "Authentication gateway",
            "Degraded",
            "The configured gateway responded, but its health endpoint returned an unexpected response.",
        )
    except (OSError, ValueError, http.client.HTTPException):
        _LOGGER.exception("Authentication gateway health check failed.")
        return _result(
            "Authentication gateway",
            "Unavailable",
            "The configured authentication gateway did not pass its availability check.",
        )
    finally:
        if connection is not None:
            connection.close()


def check_audit_writer() -> Dict[str, str]:
    """Tests the audit writer in a savepoint that is always rolled back."""
    try:
        if not database.check_audit_logging():
            return _result(
                "Audit logging",
                "Unavailable",
                "The transactional audit-writer check did not pass.",
            )
        return _result(
            "Audit logging",
            "Available",
            "The audit writer accepted a transient check that was rolled back.",
        )
    except (OSError, sqlite3.Error):
        _LOGGER.exception("Audit logging health check failed.")
        return _result(
            "Audit logging",
            "Unavailable",
            "The audit-writer capability could not be checked.",
        )


def run_platform_health_checks() -> list[Dict[str, str]]:
    """Runs each check independently so one failure cannot stop the panel."""
    checks: tuple[Callable[[], Dict[str, str]], ...] = (
        check_database,
        check_complaint_intake,
        check_template_draft_generator,
        check_authentication_gateway,
        check_audit_writer,
    )
    results = []
    for check in checks:
        try:
            results.append(check())
        except Exception:
            _LOGGER.exception("Unexpected platform health check failure.")
            results.append(
                _result(
                    "Platform subsystem",
                    "Unknown",
                    "This check could not be completed.",
                )
            )
    return results
