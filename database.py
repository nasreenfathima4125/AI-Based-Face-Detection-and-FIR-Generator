"""
database.py
-----------
SQLite persistent storage layer for Integrated AI Surveillance and FIR Assistance System.

Manages relational persistence across application restarts:
1. Users & Credentials (secure salted PBKDF2 hashing).
2. Complaints (persisted with unique reference numbers, multilingual support).
3. FIR Drafts (Malayalam drafts, revisions, review statuses).
4. Audit Logs (immutable action history with timestamps and actor tracking).
"""

from datetime import datetime, timedelta, timezone
import hashlib
from contextlib import contextmanager
import os
import secrets
import sqlite3
from typing import Dict, Any, List, Optional, Tuple, Generator

DB_PATH = os.environ.get("FIR_SYSTEM_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fir_system.db",
)
RECOVERY_HANDLE_TTL_SECONDS = 24 * 60 * 60


@contextmanager
def get_db_connection() -> Generator[sqlite3.Connection, None, None]:
    """Creates a database connection with row factory enabled and automatically closes it."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """Hashes a password securely using PBKDF2-HMAC-SHA256 with a unique random salt."""
    if not salt:
        salt = secrets.token_hex(16)
    pwd_bytes = password.encode("utf-8")
    salt_bytes = salt.encode("utf-8")
    key = hashlib.pbkdf2_hmac("sha256", pwd_bytes, salt_bytes, 100_000)
    return key.hex(), salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verifies a plain password against the stored hash and salt."""
    computed_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(computed_hash, stored_hash)


def init_db() -> None:
    """Initializes the database schema and seeds default demonstration accounts."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 1. Users table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                contact_number TEXT,
                role TEXT NOT NULL CHECK(role IN ('citizen', 'police', 'admin')),
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # 2. Complaints table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS complaints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference_no TEXT UNIQUE NOT NULL,
                citizen_user_id INTEGER,
                complainant_name TEXT NOT NULL,
                contact_number TEXT NOT NULL,
                category TEXT NOT NULL,
                incident_date TEXT NOT NULL,
                incident_time TEXT,
                incident_location TEXT NOT NULL,
                description TEXT NOT NULL,
                additional_info TEXT,
                intake_language TEXT DEFAULT 'en',
                status TEXT NOT NULL DEFAULT 'Submitted',
                fir_status TEXT NOT NULL DEFAULT 'Draft Generated',
                verification_token TEXT,
                is_approved INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (citizen_user_id) REFERENCES users (id) ON DELETE SET NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS complaint_recovery_challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                complaint_id INTEGER NOT NULL UNIQUE,
                handle_hash TEXT NOT NULL UNIQUE,
                recovery_expires_at TEXT,
                revoked_at TEXT,
                otp_hash TEXT,
                expires_at TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                send_count INTEGER NOT NULL DEFAULT 0,
                send_window_started_at TEXT,
                last_sent_at TEXT,
                locked_until TEXT,
                verified_at TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (complaint_id) REFERENCES complaints (id) ON DELETE CASCADE
            )
            """
        )

        recovery_columns = {
            row["name"]
            for row in cursor.execute(
                "PRAGMA table_info(complaint_recovery_challenges)"
            ).fetchall()
        }
        if "recovery_expires_at" not in recovery_columns:
            cursor.execute(
                "ALTER TABLE complaint_recovery_challenges "
                "ADD COLUMN recovery_expires_at TEXT"
            )
        if "revoked_at" not in recovery_columns:
            cursor.execute(
                "ALTER TABLE complaint_recovery_challenges ADD COLUMN revoked_at TEXT"
            )

        # Existing handles get a bounded lifetime based on their original creation.
        for challenge in cursor.execute(
            """
            SELECT id, created_at
            FROM complaint_recovery_challenges
            WHERE recovery_expires_at IS NULL
            """
        ).fetchall():
            created_at = datetime.fromisoformat(str(challenge["created_at"]))
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            recovery_expires_at = (
                created_at.astimezone(timezone.utc)
                + timedelta(seconds=RECOVERY_HANDLE_TTL_SECONDS)
            ).isoformat()
            cursor.execute(
                """
                UPDATE complaint_recovery_challenges
                SET recovery_expires_at = ?
                WHERE id = ?
                """,
                (recovery_expires_at, challenge["id"]),
            )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sms_otp_rate_limits (
                phone_hash TEXT PRIMARY KEY,
                window_started_at TEXT NOT NULL,
                send_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        # 3. FIR Drafts table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS fir_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                complaint_id INTEGER NOT NULL,
                draft_content_ml TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'Pending Police Approval',
                reviewed_by_user_id INTEGER,
                reviewer_notes TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (complaint_id) REFERENCES complaints (id) ON DELETE CASCADE,
                FOREIGN KEY (reviewed_by_user_id) REFERENCES users (id) ON DELETE SET NULL
            )
            """
        )

        # 4. Audit Logs table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                complaint_id INTEGER,
                actor_user_id INTEGER,
                action TEXT NOT NULL,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (complaint_id) REFERENCES complaints (id) ON DELETE CASCADE,
                FOREIGN KEY (actor_user_id) REFERENCES users (id) ON DELETE SET NULL
            )
            """
        )

        conn.commit()

        # Seed initial accounts if not present
        _seed_users(cursor, conn)


def _seed_users(cursor: sqlite3.Cursor, conn: sqlite3.Connection) -> None:
    """Seeds default demonstration roles for police, admin, and citizen."""
    seeds = [
        ("officer@keralapolice.demo", "Inspector V. Suresh", "+91 9447100001", "police", "Police@123"),
        ("admin@firsystem.demo", "System Administrator", "+91 9447100002", "admin", "Admin@123"),
        ("citizen@example.com", "Rajesh Kumar", "+91 9447123456", "citizen", "Citizen@123"),
    ]

    for email, name, phone, role, pwd in seeds:
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        if not cursor.fetchone():
            pwd_hash, salt = hash_password(pwd)
            cursor.execute(
                """
                INSERT INTO users (email, full_name, contact_number, role, password_hash, salt)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (email, name, phone, role, pwd_hash, salt),
            )
    conn.commit()


# ==============================================================================
# USER & AUTH OPERATIONS
# ==============================================================================
def create_user(
    email: str,
    full_name: str,
    password: str,
    contact_number: str = "",
    role: str = "citizen",
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Registers a new user account with validated credentials and hashed password."""
    cleaned_email = (email or "").strip().lower()
    cleaned_name = (full_name or "").strip()
    cleaned_phone = (contact_number or "").strip()

    if not cleaned_email or "@" not in cleaned_email:
        return False, "Please enter a valid email address.", None
    if len(cleaned_name) < 2:
        return False, "Full name must be at least 2 characters long.", None
    if len(password) < 6:
        return False, "Password must be at least 6 characters long.", None
    if role not in ["citizen", "police", "admin"]:
        role = "citizen"

    pwd_hash, salt = hash_password(password)

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO users (email, full_name, contact_number, role, password_hash, salt)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (cleaned_email, cleaned_name, cleaned_phone, role, pwd_hash, salt),
            )
            user_id = cursor.lastrowid
            conn.commit()

            # Record audit event
            log_audit(
                complaint_id=None,
                actor_user_id=user_id,
                action="USER_REGISTRATION",
                details=f"User {cleaned_email} registered with role {role}.",
            )

            return True, "User registered successfully.", {
                "id": user_id,
                "email": cleaned_email,
                "full_name": cleaned_name,
                "contact_number": cleaned_phone,
                "role": role,
            }
    except sqlite3.IntegrityError:
        return False, "An account with this email already exists.", None
    except Exception as e:
        return False, f"Failed to register account: {str(e)}", None


def authenticate_user(email: str, password: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Authenticates a user by email and password, returning user dictionary on success."""
    cleaned_email = (email or "").strip().lower()
    if not cleaned_email or not password:
        return False, "Email and password are required.", None

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (cleaned_email,))
        row = cursor.fetchone()
        if not row:
            return False, "Invalid email or password.", None

        if verify_password(password, row["password_hash"], row["salt"]):
            user_dict = {
                "id": row["id"],
                "email": row["email"],
                "full_name": row["full_name"],
                "contact_number": row["contact_number"],
                "role": row["role"],
            }
            log_audit(
                complaint_id=None,
                actor_user_id=row["id"],
                action="USER_LOGIN",
                details=f"User {cleaned_email} successfully authenticated as {row['role']}.",
            )
            return True, "Authentication successful.", user_dict
        else:
            return False, "Invalid email or password.", None


def get_all_users() -> List[Dict[str, Any]]:
    """Retrieves all registered users for administrative management."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, email, full_name, contact_number, role, created_at FROM users ORDER BY id ASC")
        return [dict(row) for row in cursor.fetchall()]


def update_user_role(user_id: int, new_role: str, admin_user_id: Optional[int] = None) -> bool:
    """Updates user role (administrator authorization required)."""
    if new_role not in ["citizen", "police", "admin"]:
        return False
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
        conn.commit()
        log_audit(
            complaint_id=None,
            actor_user_id=admin_user_id,
            action="ROLE_CHANGE",
            details=f"User ID {user_id} role updated to {new_role}.",
        )
        return cursor.rowcount > 0


# ==============================================================================
# COMPLAINT & FIR OPERATIONS
# ==============================================================================
def generate_reference_number() -> str:
    """Generates an official, unique complaint reference identifier."""
    today_str = datetime.now().strftime("%Y%m%d")
    random_suffix = secrets.token_hex(3).upper()
    return f"CMP-{today_str}-{random_suffix}"


def save_complaint(
    complainant_name: str,
    contact_number: str,
    category: str,
    incident_date: str,
    incident_location: str,
    description: str,
    additional_info: str = "",
    incident_time: str = "",
    intake_language: str = "en",
    citizen_user_id: Optional[int] = None,
    draft_content_ml: Optional[str] = None,
    recovery_handle_hash: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Persists a verified complaint into the SQLite database.
    Generates reference number, creates initial FIR draft, and records audit trail.
    """
    ref_no = generate_reference_number()
    # 4-digit verification token for subsequent complaint linking
    verification_token = secrets.token_hex(2).upper()

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO complaints (
                reference_no, citizen_user_id, complainant_name, contact_number,
                category, incident_date, incident_time, incident_location,
                description, additional_info, intake_language, status, fir_status,
                verification_token
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Submitted', 'Pending Police Approval', ?)
            """,
            (
                ref_no,
                citizen_user_id,
                complainant_name.strip(),
                contact_number.strip(),
                category.strip(),
                str(incident_date).strip(),
                incident_time.strip(),
                incident_location.strip(),
                description.strip(),
                (additional_info or "").strip(),
                intake_language,
                verification_token,
            ),
        )
        complaint_id = cursor.lastrowid

        # Insert initial FIR draft
        if draft_content_ml:
            initial_draft = draft_content_ml.replace(
                "Reference ID): CMP-DRAFT",
                f"Reference ID): {ref_no}",
                1,
            )
        else:
            initial_draft = "കരട് എഫ്.ഐ.ആർ തയ്യാറാക്കുന്നു..."
        cursor.execute(
            """
            INSERT INTO fir_drafts (complaint_id, draft_content_ml, status)
            VALUES (?, ?, 'Pending Police Approval')
            """,
            (complaint_id, initial_draft),
        )

        if recovery_handle_hash:
            recovery_expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=RECOVERY_HANDLE_TTL_SECONDS)
            ).isoformat()
            cursor.execute(
                """
                INSERT INTO complaint_recovery_challenges (
                    complaint_id, handle_hash, recovery_expires_at
                )
                VALUES (?, ?, ?)
                """,
                (complaint_id, recovery_handle_hash, recovery_expires_at),
            )

        conn.commit()

        # Audit log
        log_audit(
            complaint_id=complaint_id,
            actor_user_id=citizen_user_id,
            action="COMPLAINT_SUBMITTED",
            details=f"Complaint {ref_no} submitted in {intake_language}. Category: {category}.",
        )

        record = get_complaint_by_id(complaint_id)
        return True, "Complaint persisted successfully.", record or {}


def get_complaint_by_id(complaint_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves full complaint record by primary key."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM complaints WHERE id = ?", (complaint_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_complaint_by_reference(reference_no: str) -> Optional[Dict[str, Any]]:
    """Retrieves complaint record by public reference number."""
    cleaned = (reference_no or "").strip().upper()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM complaints WHERE reference_no = ?", (cleaned,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_recovery_challenge(handle_hash: str) -> Optional[Dict[str, Any]]:
    """Returns a recovery challenge and its complaint contact/reference data."""
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT r.*, c.reference_no, c.contact_number
            FROM complaint_recovery_challenges r
            JOIN complaints c ON c.id = r.complaint_id
            WHERE r.handle_hash = ?
            """,
            (handle_hash,),
        ).fetchone()
        return dict(row) if row else None


def reserve_recovery_otp(
    handle_hash: str,
    phone_hash: str,
    otp_hash: str,
    now: datetime,
    otp_ttl_seconds: int = 300,
    resend_cooldown_seconds: int = 60,
    send_window_seconds: int = 900,
    max_sends_per_window: int = 3,
) -> Tuple[bool, str]:
    """Atomically reserves an OTP send and enforces persisted phone limits."""
    now = now.astimezone(timezone.utc)
    now_text = now.isoformat()
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        challenge = conn.execute(
            """
            SELECT id, recovery_expires_at, revoked_at, last_sent_at, locked_until,
                   send_count, send_window_started_at
            FROM complaint_recovery_challenges
            WHERE handle_hash = ?
            """,
            (handle_hash,),
        ).fetchone()
        if challenge is None:
            return False, "not_found"
        if challenge["revoked_at"]:
            return False, "revoked"
        recovery_expires_at = challenge["recovery_expires_at"]
        if (
            not recovery_expires_at
            or now >= datetime.fromisoformat(recovery_expires_at)
        ):
            return False, "handle_expired"

        locked_until = challenge["locked_until"]
        if locked_until and now < datetime.fromisoformat(locked_until):
            return False, "locked"

        last_sent_at = challenge["last_sent_at"]
        if last_sent_at:
            elapsed = (now - datetime.fromisoformat(last_sent_at)).total_seconds()
            if elapsed < resend_cooldown_seconds:
                return False, "cooldown"

        window_started_at = challenge["send_window_started_at"]
        challenge_send_count = challenge["send_count"]
        if (
            not window_started_at
            or (now - datetime.fromisoformat(window_started_at)).total_seconds()
            >= send_window_seconds
        ):
            window_started_at = now_text
            challenge_send_count = 0

        rate_limit = conn.execute(
            """
            SELECT window_started_at, send_count
            FROM sms_otp_rate_limits
            WHERE phone_hash = ?
            """,
            (phone_hash,),
        ).fetchone()
        if rate_limit:
            rate_window = datetime.fromisoformat(rate_limit["window_started_at"])
            if (now - rate_window).total_seconds() < send_window_seconds:
                if rate_limit["send_count"] >= max_sends_per_window:
                    return False, "rate_limited"
                conn.execute(
                    """
                    UPDATE sms_otp_rate_limits
                    SET send_count = send_count + 1
                    WHERE phone_hash = ?
                    """,
                    (phone_hash,),
                )
            else:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO sms_otp_rate_limits (
                        phone_hash, window_started_at, send_count
                    )
                    VALUES (?, ?, 1)
                    """,
                    (phone_hash, now_text),
                )
        else:
            conn.execute(
                """
                INSERT OR REPLACE INTO sms_otp_rate_limits (
                    phone_hash, window_started_at, send_count
                )
                VALUES (?, ?, 1)
                """,
                (phone_hash, now_text),
            )

        if challenge_send_count >= max_sends_per_window:
            return False, "rate_limited"

        conn.execute(
            """
            UPDATE complaint_recovery_challenges
            SET otp_hash = ?, expires_at = ?, attempt_count = 0,
                send_count = ?, send_window_started_at = ?,
                last_sent_at = ?, locked_until = NULL, verified_at = NULL
            WHERE handle_hash = ?
            """,
            (
                otp_hash,
                (now + timedelta(seconds=otp_ttl_seconds)).isoformat(),
                challenge_send_count + 1,
                window_started_at,
                now_text,
                handle_hash,
            ),
        )
        conn.commit()
        return True, "sent"


def cancel_recovery_otp(handle_hash: str, otp_hash: str) -> None:
    """Invalidates an OTP when the SMS provider fails to deliver it."""
    with get_db_connection() as conn:
        conn.execute(
            """
            UPDATE complaint_recovery_challenges
            SET otp_hash = NULL, expires_at = NULL
            WHERE handle_hash = ? AND otp_hash = ? AND verified_at IS NULL
            """,
            (handle_hash, otp_hash),
        )
        conn.commit()


def revoke_recovery_challenge(
    handle_hash: str,
    now: Optional[datetime] = None,
) -> bool:
    """Revokes a recovery handle and invalidates any pending OTP."""
    revoked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE complaint_recovery_challenges
            SET revoked_at = ?, otp_hash = NULL, expires_at = NULL,
                verified_at = NULL
            WHERE handle_hash = ? AND revoked_at IS NULL
            """,
            (revoked_at.isoformat(), handle_hash),
        )
        conn.commit()
        return cursor.rowcount > 0


def verify_recovery_otp(
    handle_hash: str,
    candidate_hash: str,
    now: datetime,
    max_attempts: int = 5,
    lockout_seconds: int = 900,
) -> str:
    """Checks and consumes an OTP, recording failures under a write lock."""
    now = now.astimezone(timezone.utc)
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        challenge = conn.execute(
            """
            SELECT otp_hash, expires_at, recovery_expires_at, revoked_at,
                   attempt_count, locked_until, verified_at
            FROM complaint_recovery_challenges
            WHERE handle_hash = ?
            """,
            (handle_hash,),
        ).fetchone()
        if challenge is None:
            return "not_found"
        if challenge["revoked_at"]:
            return "revoked"
        recovery_expires_at = challenge["recovery_expires_at"]
        if (
            not recovery_expires_at
            or now >= datetime.fromisoformat(recovery_expires_at)
        ):
            return "handle_expired"
        if challenge["verified_at"]:
            return "already_verified"
        if challenge["locked_until"]:
            if now < datetime.fromisoformat(challenge["locked_until"]):
                return "locked"
            conn.execute(
                """
                UPDATE complaint_recovery_challenges
                SET locked_until = NULL, attempt_count = 0
                WHERE handle_hash = ?
                """,
                (handle_hash,),
            )
            attempt_count = 0
        else:
            attempt_count = challenge["attempt_count"]
        if not challenge["otp_hash"] or not challenge["expires_at"]:
            return "not_sent"
        if now >= datetime.fromisoformat(challenge["expires_at"]):
            conn.execute(
                """
                UPDATE complaint_recovery_challenges
                SET otp_hash = NULL, expires_at = NULL
                WHERE handle_hash = ?
                """,
                (handle_hash,),
            )
            conn.commit()
            return "expired"
        if secrets.compare_digest(challenge["otp_hash"], candidate_hash):
            conn.execute(
                """
                UPDATE complaint_recovery_challenges
                SET otp_hash = NULL, expires_at = NULL, verified_at = ?,
                    locked_until = NULL
                WHERE handle_hash = ?
                """,
                (now.isoformat(), handle_hash),
            )
            conn.commit()
            return "verified"

        attempts = attempt_count + 1
        locked_until = (
            (now + timedelta(seconds=lockout_seconds)).isoformat()
            if attempts >= max_attempts
            else None
        )
        conn.execute(
            """
            UPDATE complaint_recovery_challenges
            SET attempt_count = ?, otp_hash = ?, expires_at = ?,
                locked_until = ?
            WHERE handle_hash = ?
            """,
            (
                attempts,
                None if locked_until else challenge["otp_hash"],
                None if locked_until else challenge["expires_at"],
                locked_until,
                handle_hash,
            ),
        )
        conn.commit()
        return "locked" if locked_until else "invalid"


def get_complaints_for_citizen(citizen_user_id: int) -> List[Dict[str, Any]]:
    """Retrieves all complaints owned by or linked to a specific citizen account."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM complaints 
            WHERE citizen_user_id = ? 
            ORDER BY id DESC
            """,
            (citizen_user_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_all_complaints_for_police(
    status_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
    search_query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieves complaints queue for police officers with flexible filtering and search."""
    query = "SELECT * FROM complaints WHERE 1=1"
    params: List[Any] = []

    if status_filter and status_filter != "All Statuses":
        query += " AND status = ?"
        params.append(status_filter)

    if category_filter and category_filter != "All Categories":
        query += " AND category = ?"
        params.append(category_filter)

    if search_query:
        cleaned_search = f"%{search_query.strip()}%"
        query += " AND (reference_no LIKE ? OR complainant_name LIKE ? OR incident_location LIKE ?)"
        params.extend([cleaned_search, cleaned_search, cleaned_search])

    query += " ORDER BY id DESC"

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def get_latest_fir_draft(complaint_id: int) -> Optional[Dict[str, Any]]:
    """Fetches the latest FIR draft for a given complaint."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM fir_drafts 
            WHERE complaint_id = ? 
            ORDER BY version DESC, id DESC 
            LIMIT 1
            """,
            (complaint_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def update_fir_draft(
    complaint_id: int,
    draft_content_ml: str,
    reviewer_user_id: int,
    reviewer_notes: str = "",
    status: str = "Pending Police Approval",
) -> bool:
    """Updates the Malayalam FIR draft content and saves revision."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE fir_drafts 
            SET draft_content_ml = ?, status = ?, reviewed_by_user_id = ?, reviewer_notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE complaint_id = ?
            """,
            (draft_content_ml, status, reviewer_user_id, reviewer_notes, complaint_id),
        )
        cursor.execute(
            """
            UPDATE complaints 
            SET fir_status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, complaint_id),
        )
        conn.commit()

        log_audit(
            complaint_id=complaint_id,
            actor_user_id=reviewer_user_id,
            action="FIR_DRAFT_UPDATED",
            details=f"FIR draft updated. Status: {status}. Notes: {reviewer_notes}",
        )
        return True


def update_complaint_status(
    complaint_id: int,
    new_status: str,
    officer_user_id: int,
    notes: str = "",
) -> bool:
    """Updates case review status (e.g., Pending Review, Under Review, More Information Required, Closed)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE complaints 
            SET status = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE id = ?
            """,
            (new_status, complaint_id),
        )
        conn.commit()

        log_audit(
            complaint_id=complaint_id,
            actor_user_id=officer_user_id,
            action="STATUS_CHANGE",
            details=f"Complaint status updated to '{new_status}'. Officer notes: {notes}",
        )
        return True


def approve_fir_draft(
    complaint_id: int,
    officer_user_id: int,
    officer_notes: str = "Approved by Station Reviewer",
) -> bool:
    """Marks FIR draft as approved by authorized police personnel and unlocks download."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE complaints 
            SET is_approved = 1, status = 'Accepted for Further Processing', fir_status = 'Approved', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (complaint_id,),
        )
        cursor.execute(
            """
            UPDATE fir_drafts 
            SET status = 'Approved', reviewed_by_user_id = ?, reviewer_notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE complaint_id = ?
            """,
            (officer_user_id, officer_notes, complaint_id),
        )
        conn.commit()

        log_audit(
            complaint_id=complaint_id,
            actor_user_id=officer_user_id,
            action="FIR_APPROVED",
            details=f"FIR draft approved for case ID {complaint_id}. Citizen download unlocked.",
        )
        return True


def return_complaint_for_correction(
    complaint_id: int,
    officer_user_id: int,
    reason: str,
) -> bool:
    """Returns complaint to citizen for correction with mandatory recorded reason."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE complaints 
            SET status = 'More Information Required', fir_status = 'Returned for Correction', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (complaint_id,),
        )
        cursor.execute(
            """
            UPDATE fir_drafts 
            SET status = 'Returned for Correction', reviewed_by_user_id = ?, reviewer_notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE complaint_id = ?
            """,
            (officer_user_id, reason, complaint_id),
        )
        conn.commit()

        log_audit(
            complaint_id=complaint_id,
            actor_user_id=officer_user_id,
            action="RETURNED_FOR_CORRECTION",
            details=f"Complaint returned for correction. Reason: {reason}",
        )
        return True


def link_complaint_to_citizen(
    reference_no: str,
    contact_number: str,
    citizen_user_id: int,
) -> Tuple[bool, str]:
    """
    Securely links an unauthenticated complaint to a citizen account.
    Requires ownership verification matching phone number or verification token.
    Prevents unauthorized access through guessing reference numbers.
    """
    cleaned_ref = (reference_no or "").strip().upper()
    cleaned_phone = re_clean_phone(contact_number)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM complaints WHERE reference_no = ?", (cleaned_ref,))
        row = cursor.fetchone()
        if not row:
            return False, "Complaint reference number not found."

        stored_phone = re_clean_phone(row["contact_number"])

        # Ownership verification
        if cleaned_phone != stored_phone:
            return False, "Ownership verification failed: Contact number does not match the complaint record."

        # Link complaint
        cursor.execute(
            """
            UPDATE complaints 
            SET citizen_user_id = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE id = ?
            """,
            (citizen_user_id, row["id"]),
        )
        conn.commit()

        log_audit(
            complaint_id=row["id"],
            actor_user_id=citizen_user_id,
            action="COMPLAINT_LINKED",
            details=f"Complaint {cleaned_ref} verified and linked to Citizen User ID {citizen_user_id}.",
        )
        return True, "Complaint successfully verified and linked to your citizen dashboard."


def re_clean_phone(phone: str) -> str:
    """Helper to extract pure digits from phone strings for reliable comparison."""
    import re
    return re.sub(r"\D", "", phone or "")


# ==============================================================================
# AUDIT LOGGING
# ==============================================================================
def log_audit(
    complaint_id: Optional[int],
    actor_user_id: Optional[int],
    action: str,
    details: str,
) -> None:
    """Appends an immutable audit log entry."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO audit_logs (complaint_id, actor_user_id, action, details)
                VALUES (?, ?, ?, ?)
                """,
                (complaint_id, actor_user_id, action, details),
            )
            conn.commit()
    except Exception as e:
        print(f"Audit log failure: {e}")


def get_audit_logs(complaint_id: Optional[int] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieves recent audit logs, optionally filtered by complaint."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if complaint_id:
            cursor.execute(
                """
                SELECT a.*, u.email as actor_email, u.role as actor_role 
                FROM audit_logs a 
                LEFT JOIN users u ON a.actor_user_id = u.id 
                WHERE a.complaint_id = ? 
                ORDER BY a.id DESC 
                LIMIT ?
                """,
                (complaint_id, limit),
            )
        else:
            cursor.execute(
                """
                SELECT a.*, u.email as actor_email, u.role as actor_role, c.reference_no 
                FROM audit_logs a 
                LEFT JOIN users u ON a.actor_user_id = u.id 
                LEFT JOIN complaints c ON a.complaint_id = c.id 
                ORDER BY a.id DESC 
                LIMIT ?
                """,
                (limit,),
            )
        return [dict(row) for row in cursor.fetchall()]


# Auto-initialize database on import
init_db()
