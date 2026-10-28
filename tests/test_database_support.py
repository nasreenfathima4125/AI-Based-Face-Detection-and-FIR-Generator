"""Temporary SQLite database setup shared by database and UI tests."""

import os
import tempfile
from unittest.mock import patch


_IMPORT_SAFE_DIRECTORY = tempfile.TemporaryDirectory(
    prefix="fir-assistance-test-import-"
)
os.environ["FIR_SYSTEM_DB_PATH"] = os.path.join(
    _IMPORT_SAFE_DIRECTORY.name,
    "import-safe.sqlite3",
)
os.environ["FIR_ENABLE_DEMO_ACCOUNTS"] = "true"


def isolate_database(test_case, database_module):
    """Give one test a fresh database and initialize only that database."""
    temporary_directory = tempfile.TemporaryDirectory(
        prefix="fir-assistance-test-"
    )
    test_case.addCleanup(temporary_directory.cleanup)
    database_path = os.path.join(
        temporary_directory.name,
        "fir_system_test.sqlite3",
    )

    environment_patch = patch.dict(
        os.environ,
        {"FIR_SYSTEM_DB_PATH": database_path},
    )
    environment_patch.start()
    test_case.addCleanup(environment_patch.stop)

    database_path_patch = patch.object(
        database_module,
        "DB_PATH",
        database_path,
    )
    database_path_patch.start()
    test_case.addCleanup(database_path_patch.stop)

    database_module.init_db()
    return database_path
