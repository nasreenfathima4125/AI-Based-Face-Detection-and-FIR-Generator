"""
complaint_manager.py
--------------------
Complaint data handling and validation module for the
Integrated AI Surveillance and FIR Assistance System.

Key responsibilities:
1. Define official supported complaint categories.
2. Provide transparent, explainable validation rules for:
   - Complainant name (non-empty, trimmed, supports any Unicode script).
   - Contact number (allows '+', '-', spaces, '()', 7-15 digits, no fake verification).
   - Category (must belong to defined supported list).
   - Incident date (cannot be in future, accepts today or past).
   - Incident location (non-empty, trimmed, Unicode supported).
   - Incident description (non-empty, trimmed, preserves English, Malayalam, Hindi).
   - Optional additional info (optional, normalized whitespace).
3. Conversational step validation for rule-based chatbot complaint flow.
4. Prevent duplicate form submissions via submission fingerprinting.
5. Construct clean complaint records with accurate status:
   "Complaint Submitted — FIR Draft Not Yet Generated".
"""

from datetime import date, datetime
import hashlib
import re
from typing import Dict, Tuple, Any, List, Optional, Union

# Supported complaint categories (with Malayalam translations for accessibility)
SUPPORTED_CATEGORIES: List[str] = [
    "Theft / Burglary (മോഷണം)",
    "Missing Person (കാണാതായ വ്യക്തി)",
    "Assault / Physical Harm (ശാരീരികോപദ്രവം)",
    "Cybercrime / Online Fraud (സൈബർ കുറ്റകൃത്യം)",
    "Harassment / Threat (ഭീഷണിപ്പെടുത്തൽ)",
    "Property Damage / Mischief (സ്വത്ത് നശിപ്പിക്കൽ)",
    "Other Incident (മറ്റുള്ളവ)",
]

# UI Dropdown options starting with placeholder
CATEGORY_PLACEHOLDER: str = "Select a category..."
COMPLAINT_CATEGORIES: List[str] = [CATEGORY_PLACEHOLDER] + SUPPORTED_CATEGORIES

# Sequence of conversational collection steps
CHAT_STEPS: List[str] = [
    "description",
    "name",
    "contact",
    "category",
    "date_time",
    "location",
    "additional_info",
]


def create_empty_complaint_slots() -> Dict[str, Any]:
    """Returns an empty dictionary of slots to populate during the conversation."""
    return {
        "description": "",
        "name": "",
        "contact_number": "",
        "category": "",
        "incident_date": date.today().isoformat(),
        "incident_time": "",
        "location": "",
        "additional_info": "",
    }


def validate_contact_number(contact_number: str) -> Tuple[bool, str]:
    """
    Validates a contact phone number:
    - Allows reasonable formatting characters: digits 0-9, leading '+', spaces, '-', '()'.
    - Rejects letters, symbols (like '@', '#', '$'), and blank strings.
    - Ensures total digit count is between 7 and 15 digits (ITU-T E.164 standard allows up to 15 digits).
    - Avoids assuming an exact 10-digit number so landlines, local, and international numbers work.
    - Note: This only checks format plausibility; it does NOT claim ownership or verification.

    Returns:
        (is_valid, error_message): Tuple of boolean and descriptive error message.
    """
    cleaned = (contact_number or "").strip()
    if not cleaned:
        return False, "Contact number is required."

    # Check for disallowed characters (letters or unauthorized symbols)
    # Allowed: digits, spaces, '+', '-', '(', ')'
    if re.search(r"[^\d\s\-()+]", cleaned):
        return False, "Contact number contains invalid characters. Only digits, '+', '-', '()', and spaces are allowed."

    # Extract digits only to check length
    digits_only = re.sub(r"\D", "", cleaned)
    if len(digits_only) < 7:
        return False, "Contact number is too short. Please enter a valid number with at least 7 digits."
    if len(digits_only) > 15:
        return False, "Contact number is too long. Contact numbers cannot exceed 15 digits."

    return True, ""


def validate_incident_date(incident_date: Union[date, str, None]) -> Tuple[bool, str]:
    """
    Validates the incident date:
    - Rejects None or empty.
    - Accepts date object or ISO-format date string (YYYY-MM-DD).
    - Strictly rejects future dates (cannot report an incident that has not occurred yet).
    - Accepts today and past dates.

    Returns:
        (is_valid, error_message): Tuple of boolean and descriptive error message.
    """
    if incident_date is None:
        return False, "Incident date is required."

    parsed_date: Optional[date] = None
    if isinstance(incident_date, date):
        parsed_date = incident_date
    elif isinstance(incident_date, str):
        cleaned_str = incident_date.strip()
        if not cleaned_str:
            return False, "Incident date is required."
        try:
            parsed_date = datetime.strptime(cleaned_str, "%Y-%m-%d").date()
        except ValueError:
            return False, "Incident date format is invalid. Please use YYYY-MM-DD format."
    else:
        return False, "Invalid incident date type."

    today = date.today()
    if parsed_date > today:
        return False, "Incident date cannot be in the future. Please select today or a past date."

    return True, ""


def validate_complaint_input(
    name: str,
    contact_number: str,
    category: str,
    incident_date: Any,
    location: str,
    description: str,
    additional_info: str = "",
) -> Tuple[bool, Dict[str, str]]:
    """
    Validates all inputs for a citizen complaint submission.

    Rules:
    1. Complainant Name: Required, non-empty, trimmed, min 2 characters.
       Supports English, Malayalam, Hindi, and any Unicode characters.
    2. Contact Number: Required, 7-15 digits, formatting allowed (+, -, (), spaces).
    3. Category: Must belong to SUPPORTED_CATEGORIES (placeholder/empty rejected).
    4. Incident Date: Required, today or past date (future dates rejected).
    5. Incident Location: Required, non-empty, trimmed, min 3 characters.
    6. Incident Description: Required, non-empty, trimmed, min 10 characters.
       Exact Unicode text preserved without translation, rewriting, or hallucination.
    7. Additional Info: Optional. Surrounding whitespace trimmed without penalty.

    Returns:
        (is_valid, errors): Boolean flag and a dict mapping field name -> error message.
    """
    errors: Dict[str, str] = {}

    # 1. Complainant Name validation
    cleaned_name = (name or "").strip()
    if not cleaned_name:
        errors["name"] = "Complainant name is required and cannot be empty or whitespace only."
    elif len(cleaned_name) < 2:
        errors["name"] = "Complainant name must be at least 2 characters long."

    # 2. Contact Number validation
    is_contact_valid, contact_err = validate_contact_number(contact_number)
    if not is_contact_valid:
        errors["contact_number"] = contact_err

    # 3. Complaint Category validation
    if not category or category == CATEGORY_PLACEHOLDER or category not in SUPPORTED_CATEGORIES:
        errors["category"] = "Please select a supported complaint category from the provided list."

    # 4. Incident Date validation
    is_date_valid, date_err = validate_incident_date(incident_date)
    if not is_date_valid:
        errors["incident_date"] = date_err

    # 5. Incident Location validation
    cleaned_location = (location or "").strip()
    if not cleaned_location:
        errors["location"] = "Incident location is required and cannot be empty or whitespace only."
    elif len(cleaned_location) < 3:
        errors["location"] = "Please provide a more descriptive incident location (at least 3 characters)."

    # 6. Incident Description validation (accepts and preserves Unicode: English, Malayalam, Hindi)
    cleaned_description = (description or "").strip()
    if not cleaned_description:
        errors["description"] = (
            "Incident description is required. You may enter details in English, Malayalam, or Hindi."
        )
    elif len(cleaned_description) < 10:
        errors["description"] = (
            "Please provide a more detailed incident description (at least 10 characters)."
        )

    # 7. Additional Info is optional - no validation failure if empty
    is_valid = len(errors) == 0
    return is_valid, errors


def get_step_prompt(step_name: str) -> str:
    """Returns the conversational prompt for a given complaint chat step."""
    prompts = {
        "description": (
            "Welcome to the Incident Reporting Assistant. Please describe what happened in your own words.\n\n"
            "🌐 *You can type in English, Malayalam (മലയാളം), or Hindi (हिन्दी).*"
        ),
        "name": (
            "Thank you for describing the incident. To prepare the complaint record, "
            "what is your **Full Name**?"
        ),
        "contact": (
            "Please provide a working **Contact Phone Number** where station personnel "
            "can reach you for verification and case updates (e.g., `+91 98765 43210` or `(0484) 2345678`)."
        ),
        "category": (
            "Please select or specify the **Complaint Category** that best describes this incident.\n\n"
            "Choose from:\n"
            + "\n".join([f"- **{cat}**" for cat in SUPPORTED_CATEGORIES])
        ),
        "date_time": (
            "When did this incident take place? Please provide the **Incident Date** (YYYY-MM-DD or 'Today' / 'Yesterday') "
            "and approximate time if known (e.g., `2026-10-24 around 3:30 PM` or `Today, 5:00 PM`)."
        ),
        "location": (
            "Where did the incident occur? Please specify the **Incident Location** "
            "(e.g., landmark, street, junction, town or railway station)."
        ),
        "additional_info": (
            "Do you have any **Additional Information** to add (e.g., suspect physical descriptions, "
            "vehicle registration numbers, stolen item serial numbers, or witness details)?\n\n"
            "Type your details, or reply **'None'** / **'Skip'** if not applicable."
        ),
    }
    return prompts.get(step_name, "Please provide the required details.")


def validate_chat_step_input(
    step_name: str,
    user_text: str,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Validates a single user response within the conversational chatbot flow.
    Returns (is_valid, error_message, extracted_slot_updates).
    """
    cleaned = (user_text or "").strip()
    if not cleaned and step_name != "additional_info":
        return False, "This field cannot be empty. Please provide the requested information.", {}

    if step_name == "description":
        if len(cleaned) < 10:
            return False, "Please provide a more detailed incident description (at least 10 characters).", {}
        return True, "", {"description": cleaned}

    elif step_name == "name":
        if len(cleaned) < 2:
            return False, "Complainant name must be at least 2 characters long.", {}
        return True, "", {"name": cleaned}

    elif step_name == "contact":
        is_valid, err = validate_contact_number(cleaned)
        if not is_valid:
            return False, err, {}
        return True, "", {"contact_number": cleaned}

    elif step_name == "category":
        # Check direct match or case-insensitive match
        matched_cat = None
        lower_input = cleaned.lower()
        for cat in SUPPORTED_CATEGORIES:
            if lower_input in cat.lower() or cat.lower() in lower_input:
                matched_cat = cat
                break
        # Also check numeric index 1-7
        if not matched_cat and cleaned.isdigit():
            idx = int(cleaned) - 1
            if 0 <= idx < len(SUPPORTED_CATEGORIES):
                matched_cat = SUPPORTED_CATEGORIES[idx]

        if not matched_cat:
            return False, (
                "Please choose one of the supported categories (e.g., Theft, Missing Person, Cybercrime, Harassment, etc.)."
            ), {}
        return True, "", {"category": matched_cat}

    elif step_name == "date_time":
        lower_input = cleaned.lower()
        today = date.today()
        chosen_date = today
        time_part = ""

        if "today" in lower_input or "ഇന്ന്" in lower_input or "आज" in lower_input:
            chosen_date = today
            # extract remainder as time
            remainder = re.sub(r"(today|ഇന്ന്|आज|at|,)", "", lower_input).strip()
            if remainder:
                time_part = remainder
        elif "yesterday" in lower_input or "ഇന്നലെ" in lower_input or "कल" in lower_input:
            from datetime import timedelta
            chosen_date = today - timedelta(days=1)
            remainder = re.sub(r"(yesterday|ഇന്നലെ|कल|at|,)", "", lower_input).strip()
            if remainder:
                time_part = remainder
        else:
            # Check for standard YYYY-MM-DD pattern
            date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", cleaned)
            if date_match:
                try:
                    parsed = datetime.strptime(date_match.group(1), "%Y-%m-%d").date()
                    if parsed > today:
                        return False, "Incident date cannot be in the future. Please select today or a past date.", {}
                    chosen_date = parsed
                    # remainder after date
                    time_part = cleaned.replace(date_match.group(1), "").strip(" ,at")
                except ValueError:
                    return False, "Invalid date format. Please use YYYY-MM-DD or 'Today'.", {}
            else:
                # If cannot parse exact date, accept today with user text as time
                time_part = cleaned

        return True, "", {
            "incident_date": chosen_date.isoformat(),
            "incident_time": time_part,
        }

    elif step_name == "location":
        if len(cleaned) < 3:
            return False, "Please provide a more descriptive incident location (at least 3 characters).", {}
        return True, "", {"location": cleaned}

    elif step_name == "additional_info":
        lower_input = cleaned.lower()
        if lower_input in ["none", "skip", "no", "n/a", "nil", "ഇല്ല", "नहीं", ""]:
            return True, "", {"additional_info": ""}
        return True, "", {"additional_info": cleaned}

    return True, "", {}


def compute_submission_fingerprint(
    name: str,
    contact_number: str,
    category: str,
    incident_date: Any,
    location: str,
    description: str,
    additional_info: str = "",
) -> str:
    """
    Generates a deterministic hash fingerprint from cleaned complaint fields.
    Used to detect and prevent accidental duplicate submissions from duplicate form events.
    """
    date_str = (
        incident_date.isoformat()
        if isinstance(incident_date, date)
        else str(incident_date or "").strip()
    )
    payload = "|".join([
        (name or "").strip().lower(),
        re.sub(r"\D", "", (contact_number or "").strip()),
        (category or "").strip(),
        date_str,
        (location or "").strip().lower(),
        (description or "").strip(),
        (additional_info or "").strip(),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_complaint_record(
    name: str,
    contact_number: str,
    category: str,
    incident_date: Any,
    location: str,
    description: str,
    additional_info: str = "",
    incident_time: str = "",
    custom_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Creates a structured complaint dictionary from validated inputs.
    - Trims unnecessary leading/trailing whitespace.
    - Preserves exact Unicode characters for Malayalam, Hindi, and English.
    - Sets accurate stage status: 'Complaint Submitted — FIR Draft Not Yet Generated'.
    - Does NOT claim the complaint is an officially registered FIR or that an AI draft exists.
    """
    date_val = (
        incident_date.isoformat()
        if isinstance(incident_date, date)
        else str(incident_date).strip()
    )
    cid = custom_id if custom_id else f"CMP-{int(datetime.now().timestamp())}"

    return {
        "complaint_id": cid,
        "complainant_name": (name or "").strip(),
        "contact_number": (contact_number or "").strip(),
        "category": (category or "").strip(),
        "incident_date": date_val,
        "incident_time": (incident_time or "").strip(),
        "incident_location": (location or "").strip(),
        "description": (description or "").strip(),
        "additional_info": (additional_info or "").strip(),
        "submission_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "Complaint Submitted — FIR Draft Not Yet Generated",
        "has_draft": False,
        "fir_draft": None,
        "is_approved": False,
    }
