"""
complaint_manager.py
--------------------
Complaint data handling, multilingual conversational intake,
and Malayalam FIR draft generation for the Integrated AI Surveillance
and FIR Assistance System.

Key responsibilities:
1. Define official supported complaint categories.
2. Multilingual conversation prompts (English, Malayalam, Hindi).
3. Field validation rules (name, contact, date, category, location, description).
4. Deterministic, fact-faithful Malayalam FIR draft generation.
5. Conversational slot-filling state machine with AI fallback support.
"""

from datetime import date, datetime
import hashlib
import re
from typing import Dict, Tuple, Any, List, Optional, Union

from citizen_i18n import CHAT_PROMPTS, conversation_prompt

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


def create_empty_complaint_slots(lang: str = "en") -> Dict[str, Any]:
    """Returns an empty dictionary of slots to populate during the intake conversation."""
    return {
        "description": "",
        "name": "",
        "contact_number": "",
        "category": "",
        "incident_date": "",
        "incident_time": "",
        "location": "",
        "additional_info": "",
        "language": lang,
    }


def validate_contact_number(contact_number: str) -> Tuple[bool, str]:
    """
    Validates a contact phone number:
    - Allows digits 0-9, leading '+', spaces, '-', '()'.
    - Rejects letters, symbols (like '@', '#', '$'), and blank strings.
    - Ensures total digit count is between 7 and 15 digits (ITU-T E.164 standard).
    - Note: Only checks format plausibility; does NOT claim ownership or verification.
    """
    cleaned = (contact_number or "").strip()
    if not cleaned:
        return False, "Contact number is required."

    if re.search(r"[^\d\s\-()+]", cleaned):
        return False, "Contact number contains invalid characters. Only digits, '+', '-', '()', and spaces are allowed."

    digits_only = re.sub(r"\D", "", cleaned)
    if len(digits_only) < 7:
        return False, "Contact number is too short. Please enter a valid number with at least 7 digits."
    if len(digits_only) > 15:
        return False, "Contact number is too long. Contact numbers cannot exceed 15 digits."

    return True, ""


def validate_incident_date(incident_date: Union[date, str, None]) -> Tuple[bool, str]:
    """
    Validates the incident date:
    - Accepts an explicit unknown value without substituting today's date.
    - Rejects None or empty.
    - Accepts date object, ISO-format date string (YYYY-MM-DD), or "Unknown".
    - Strictly rejects future dates.
    - Accepts today and past dates.
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
        if cleaned_str.casefold() in {
            "unknown",
            "not known",
            "i don't know",
            "ഇല്ല",
            "അറിയില്ല",
            "पता नहीं",
            "मालूम नहीं",
        }:
            return True, ""
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
    Returns (is_valid, errors_dict).
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

    is_valid = len(errors) == 0
    return is_valid, errors


# ==============================================================================
# MULTILINGUAL PROMPTS
# Kept as a compatibility alias; citizen-facing strings live in citizen_i18n.
MULTILINGUAL_PROMPTS = CHAT_PROMPTS


def get_step_prompt(step_name: str, lang: str = "en") -> str:
    """Returns a centrally translated question for the selected intake language."""
    return conversation_prompt(step_name, lang)


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
        matched_cat = None
        lower_input = cleaned.lower()
        for cat in SUPPORTED_CATEGORIES:
            if lower_input in cat.lower() or cat.lower() in lower_input:
                matched_cat = cat
                break
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

        if lower_input in {
            "unknown",
            "not known",
            "i don't know",
            "അറിയില്ല",
            "पता नहीं",
            "मालूम नहीं",
        }:
            return True, "", {"incident_date": "Unknown", "incident_time": ""}

        if any(w in lower_input for w in ["today", "ഇന്ന്", "आज"]):
            chosen_date = today
            remainder = re.sub(r"(today|ഇന്ന്|आज|at|,)", "", lower_input).strip()
            if remainder:
                time_part = remainder
        elif any(w in lower_input for w in ["yesterday", "ഇന്നലെ", "कल"]):
            from datetime import timedelta
            chosen_date = today - timedelta(days=1)
            remainder = re.sub(r"(yesterday|ഇന്നലെ|कल|at|,)", "", lower_input).strip()
            if remainder:
                time_part = remainder
        else:
            date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", cleaned)
            if date_match:
                try:
                    parsed = datetime.strptime(date_match.group(1), "%Y-%m-%d").date()
                    if parsed > today:
                        return False, "Incident date cannot be in the future. Please select today or a past date.", {}
                    chosen_date = parsed
                    time_part = cleaned.replace(date_match.group(1), "").strip(" ,at")
                except ValueError:
                    return False, "Invalid date format. Please use YYYY-MM-DD or 'Today'.", {}
            else:
                return False, (
                    "Please use a calendar date, 'Today', 'Yesterday', or "
                    "'Unknown' if the date is not known."
                ), {}

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


# ==============================================================================
# MALAYALAM FIR DRAFT GENERATOR
# ==============================================================================
def generate_malayalam_fir_draft(
    complainant_name: str,
    contact_number: str,
    category: str,
    incident_date: str,
    incident_location: str,
    description: str,
    incident_time: str = "",
    additional_info: str = "",
    reference_no: str = "CMP-DRAFT",
) -> str:
    """
    Generates a structured, formal Malayalam First Information Report draft
    strictly from confirmed complainant facts without hallucination or invented sections.
    """
    time_str = f"സമയം: {incident_time}" if incident_time else "സമയം: പരാതിയിൽ വ്യക്തമല്ല"
    extra_str = additional_info if additional_info else "പ്രത്യേക വിവരങ്ങൾ പരാതിയിൽ ഉൾപ്പെടുത്തിയിട്ടില്ല."

    draft_template = f"""പ്രഥമ വിവര വിവരണം (കരട് — ഉദ്യോഗസ്ഥ പരിശോധനയ്ക്ക് വിധേയം)
FIRST INFORMATION REPORT DRAFT (PENDING POLICE REVIEW)
റഫറൻസ് നമ്പർ (Reference ID): {reference_no}

1. പരാതിക്കാരൻ്റെ വിവരങ്ങൾ (Complainant Particulars):
   - പൂർണ്ണ നാമം (Full Name): {complainant_name}
   - ഫോൺ നമ്പർ (Contact Number): {contact_number}

2. പരാതിയുടെ വിഭാഗം (Incident Category):
   - വിഭാഗം: {category}

3. സംഭവ സ്ഥലം, തീയതി, സമയം (Occurrence of Offence):
   - തീയതി (Date of Incident): {incident_date}
   - {time_str}
   - സംഭവ സ്ഥലം (Place of Occurrence): {incident_location}

4. കുറ്റകൃത്യ വിവരണം (Detailed Statement of Incident):
   {description}

5. അധിക വിവരങ്ങൾ / തെളിവുകൾ (Supplementary Facts / Witnesses):
   {extra_str}

--------------------------------------------------------------------------------
നിയമപരമായ നിരാകരണം (Operational Notice):
ഈ രേഖ പരാതിക്കാരൻ നൽകിയ വിവരങ്ങളെ അടിസ്ഥാനമാക്കി തയ്യാറാക്കിയ മാതൃകാ കരട് മാത്രമാണ്.
ഈ ആപ്ലിക്കേഷനിലെ പരിശോധനയോ അംഗീകാരമോ ഇതിനെ ഔദ്യോഗികമായി രജിസ്റ്റർ ചെയ്ത എഫ്.ഐ.ആർ ആക്കുന്നില്ല.
ഔദ്യോഗിക രജിസ്ട്രേഷൻ നിലവിലുള്ള പോലീസ് നടപടിക്രമങ്ങൾ പ്രകാരം മാത്രമാണ് നടക്കുക.
"""
    return draft_template.strip()


def compute_submission_fingerprint(
    name: str,
    contact_number: str,
    category: str,
    incident_date: Any,
    location: str,
    description: str,
    additional_info: str = "",
) -> str:
    """Generates a deterministic hash fingerprint from cleaned complaint fields."""
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
    """Creates a structured complaint dictionary for backwards-compatibility."""
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
