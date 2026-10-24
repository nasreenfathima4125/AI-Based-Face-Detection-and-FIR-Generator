"""
tests/test_complaint_manager.py
-------------------------------
Comprehensive unit tests for complaint validation and data structures (Stage 2).

Test coverage includes:
1. Valid complaints in English, Malayalam (മലയാളം), and Hindi (हिन्दी).
2. Empty and whitespace-only required fields (name, contact, location, description).
3. Contact number validation:
   - Accept reasonable formats (+, -, (), spaces, 7 to 15 digits).
   - Reject letters, special symbols (@, #), and invalid lengths (< 7 or > 15 digits).
4. Category validation:
   - Accept supported categories.
   - Reject placeholder, empty, or unsupported category names.
5. Incident date validation:
   - Accept today's date and past dates (date object or ISO string).
   - Reject future dates, invalid date strings, and missing dates.
6. Optional additional information:
   - Valid when empty, None, or whitespace-only without failing submission.
   - Whitespace trimmed during record creation.
7. Whitespace trimming:
   - Proper trimming of leading/trailing whitespace across all fields.
8. Non-saving of invalid complaints:
   - Invalid complaints are flagged with is_valid=False and not stored.
9. Record structure preservation:
   - Verify all dictionary keys and accurate status string:
     'Complaint Submitted — FIR Draft Not Yet Generated'.
10. Deterministic duplicate submission prevention:
   - Verify deterministic submission fingerprinting.
"""

from datetime import date, timedelta
import unittest

from complaint_manager import (
    SUPPORTED_CATEGORIES,
    CATEGORY_PLACEHOLDER,
    validate_complaint_input,
    validate_contact_number,
    validate_incident_date,
    compute_submission_fingerprint,
    create_complaint_record,
)


class TestComplaintValidationStage2(unittest.TestCase):
    """Test suite covering Stage 2 validation rules and record management."""

    def test_valid_english_complaint(self):
        """Test submission of a completely valid complaint in English."""
        is_valid, errors = validate_complaint_input(
            name="John Doe",
            contact_number="+91 98765 43210",
            category="Theft / Burglary (മോഷണം)",
            incident_date=date.today(),
            location="Market Road, Ernakulam",
            description="My black backpack containing a laptop was stolen near Market Road at around 3 PM.",
            additional_info="The laptop is a silver Dell Inspiron.",
        )
        self.assertTrue(is_valid, f"Expected valid submission, got errors: {errors}")
        self.assertEqual(len(errors), 0)

    def test_valid_malayalam_complaint(self):
        """Test submission with Malayalam Unicode characters across name, location, and description."""
        is_valid, errors = validate_complaint_input(
            name="രാജേഷ് കുമാർ",
            contact_number="9447123456",
            category="Theft / Burglary (മോഷണം)",
            incident_date=date.today() - timedelta(days=2),
            location="ആലുവ റെയിൽവേ സ്റ്റേഷൻ",
            description="ഇന്നലെ വൈകുന്നേരം 5 മണിക്ക് ആലുവ റെയിൽവേ സ്റ്റേഷനിൽ വെച്ച് എന്റെ ബാഗ് നഷ്ടപ്പെട്ടു. അതിൽ പ്രധാന രേഖകളും പണവും ഉണ്ടായിരുന്നു.",
            additional_info="കറുത്ത ലെതർ ബാഗ് ആയിരുന്നു.",
        )
        self.assertTrue(is_valid, f"Expected valid Malayalam submission, got errors: {errors}")
        self.assertEqual(len(errors), 0)

    def test_valid_hindi_complaint(self):
        """Test submission with Hindi Unicode characters across name, location, and description."""
        is_valid, errors = validate_complaint_input(
            name="अमित शर्मा",
            contact_number="+91-9876543210",
            category="Property Damage / Mischief (സ്വത്ത് നശിപ്പിക്കൽ)",
            incident_date=date.today() - timedelta(days=1),
            location="एमजी रोड, कोच्चि",
            description="कल दोपहर में मेरी दुकान के बाहर अज्ञात व्यक्तियों द्वारा खिड़की का शीशा तोड़कर संपत्ति को नुकसान पहुंचाया गया।",
            additional_info="",
        )
        self.assertTrue(is_valid, f"Expected valid Hindi submission, got errors: {errors}")
        self.assertEqual(len(errors), 0)

    def test_name_empty_and_whitespace_only(self):
        """Test rejection of empty and whitespace-only complainant names."""
        for invalid_name in ["", "   ", "\t\n", None]:
            is_valid, errors = validate_complaint_input(
                name=invalid_name,  # type: ignore
                contact_number="9876543210",
                category=SUPPORTED_CATEGORIES[0],
                incident_date=date.today(),
                location="Kochi City",
                description="Valid incident description explaining what happened.",
            )
            self.assertFalse(is_valid)
            self.assertIn("name", errors)

    def test_name_too_short(self):
        """Test that single-character names are rejected."""
        is_valid, errors = validate_complaint_input(
            name="A",
            contact_number="9876543210",
            category=SUPPORTED_CATEGORIES[0],
            incident_date=date.today(),
            location="Kochi City",
            description="Valid incident description explaining what happened.",
        )
        self.assertFalse(is_valid)
        self.assertIn("name", errors)

    def test_contact_number_valid_formats(self):
        """Test various reasonable phone number formats (spaces, +, -, (), 7-15 digits)."""
        valid_formats = [
            "9876543210",              # 10 digits
            "+91 98765 43210",         # International with country code and spaces
            "+91-98765-43210",         # Hyphens
            "(0484) 2345678",          # Landline with area code
            "044 1234 5678",           # Standard space-separated
            "1234567",                 # Minimum 7 digits
            "+1 234 567 890 1234",     # Up to 15 digits
        ]
        for num in valid_formats:
            is_valid, err_msg = validate_contact_number(num)
            self.assertTrue(is_valid, f"Expected '{num}' to be valid, but got error: '{err_msg}'")

    def test_contact_number_invalid_formats(self):
        """Test rejection of clearly malformed contact numbers."""
        invalid_numbers = [
            ("", "empty"),
            ("   ", "whitespace"),
            ("12345", "too few digits (5)"),
            ("1234567890123456", "too many digits (16)"),
            ("not-a-number", "alphabetic letters"),
            ("+91-98765@3210", "unauthorized symbol @"),
            ("phone#9876543210", "unauthorized symbol #"),
        ]
        for num, reason in invalid_numbers:
            is_valid, err_msg = validate_contact_number(num)
            self.assertFalse(is_valid, f"Expected '{num}' ({reason}) to be invalid, but passed.")
            self.assertTrue(len(err_msg) > 0)

    def test_category_validation(self):
        """Test category validation: must belong to SUPPORTED_CATEGORIES."""
        # Supported categories should all pass
        for cat in SUPPORTED_CATEGORIES:
            is_valid, errors = validate_complaint_input(
                name="Ramesh",
                contact_number="9876543210",
                category=cat,
                incident_date=date.today(),
                location="Kottayam",
                description="Valid incident description explaining what happened.",
            )
            self.assertTrue(is_valid, f"Expected category '{cat}' to be valid.")

        # Placeholder, empty, or unsupported should fail
        invalid_categories = [CATEGORY_PLACEHOLDER, "", "   ", "Random Unsupported Category"]
        for bad_cat in invalid_categories:
            is_valid, errors = validate_complaint_input(
                name="Ramesh",
                contact_number="9876543210",
                category=bad_cat,
                incident_date=date.today(),
                location="Kottayam",
                description="Valid incident description explaining what happened.",
            )
            self.assertFalse(is_valid, f"Expected bad category '{bad_cat}' to fail.")
            self.assertIn("category", errors)

    def test_incident_date_validation(self):
        """Test date validation: today and past are accepted, future is rejected."""
        today = date.today()
        yesterday = today - timedelta(days=1)
        past_date = date(2025, 1, 15)
        future_date = today + timedelta(days=1)

        # Today is valid
        is_valid, _ = validate_incident_date(today)
        self.assertTrue(is_valid)

        # Yesterday and past date are valid
        is_valid, _ = validate_incident_date(yesterday)
        self.assertTrue(is_valid)
        is_valid, _ = validate_incident_date(past_date)
        self.assertTrue(is_valid)

        # ISO string format is valid
        is_valid, _ = validate_incident_date("2025-06-20")
        self.assertTrue(is_valid)

        # Future date is rejected
        is_valid, err = validate_incident_date(future_date)
        self.assertFalse(is_valid)
        self.assertIn("future", err.lower())

        # None or empty string is rejected
        is_valid, _ = validate_incident_date(None)
        self.assertFalse(is_valid)
        is_valid, _ = validate_incident_date("   ")
        self.assertFalse(is_valid)

        # Invalid string format is rejected
        is_valid, err = validate_incident_date("invalid-date-format")
        self.assertFalse(is_valid)

    def test_incident_location_empty_and_whitespace(self):
        """Test rejection of empty, whitespace-only, or overly short locations."""
        for invalid_loc in ["", "   ", "A", "AB"]:
            is_valid, errors = validate_complaint_input(
                name="Ramesh",
                contact_number="9876543210",
                category=SUPPORTED_CATEGORIES[0],
                incident_date=date.today(),
                location=invalid_loc,
                description="Valid incident description explaining what happened.",
            )
            self.assertFalse(is_valid)
            self.assertIn("location", errors)

    def test_incident_description_empty_and_short(self):
        """Test rejection of empty, whitespace-only, or overly short descriptions."""
        for invalid_desc in ["", "   ", "Short"]:
            is_valid, errors = validate_complaint_input(
                name="Ramesh",
                contact_number="9876543210",
                category=SUPPORTED_CATEGORIES[0],
                incident_date=date.today(),
                location="Kottayam Railway Station",
                description=invalid_desc,
            )
            self.assertFalse(is_valid)
            self.assertIn("description", errors)

    def test_optional_additional_info(self):
        """Test that additional information is truly optional and handles whitespace gracefully."""
        # None, empty, and whitespace should all pass without error
        for opt_val in ["", "   ", None, "Vehicle registration: KL-07-AB-1234"]:
            is_valid, errors = validate_complaint_input(
                name="Ramesh",
                contact_number="9876543210",
                category=SUPPORTED_CATEGORIES[0],
                incident_date=date.today(),
                location="Kottayam Railway Station",
                description="Valid incident description with sufficient detail.",
                additional_info=opt_val or "",  # type: ignore
            )
            self.assertTrue(is_valid, f"Expected additional_info='{opt_val}' to be valid.")
            self.assertEqual(len(errors), 0)

    def test_whitespace_trimming_in_records(self):
        """Test that leading and trailing whitespace is trimmed when creating records."""
        record = create_complaint_record(
            name="   Suresh G   ",
            contact_number="   +91 9447111222   ",
            category=SUPPORTED_CATEGORIES[0],
            incident_date=date(2026, 1, 10),
            location="   Aluva Town   ",
            description="   Detailed description of theft with spaces.   ",
            additional_info="   Extra note.   ",
        )
        self.assertEqual(record["complainant_name"], "Suresh G")
        self.assertEqual(record["contact_number"], "+91 9447111222")
        self.assertEqual(record["incident_location"], "Aluva Town")
        self.assertEqual(record["description"], "Detailed description of theft with spaces.")
        self.assertEqual(record["additional_info"], "Extra note.")

    def test_invalid_complaint_not_saved_workflow(self):
        """Test that a complaint failing validation is rejected and not added to complaints list."""
        complaints_list = []
        is_valid, errors = validate_complaint_input(
            name="",  # Invalid: empty name
            contact_number="123",  # Invalid: short contact
            category="Select a category...",  # Invalid: placeholder
            incident_date=date.today() + timedelta(days=5),  # Invalid: future
            location="",
            description="",
        )
        self.assertFalse(is_valid)
        self.assertTrue(len(errors) > 0)

        # Logic in application: only save when is_valid is True
        if is_valid:
            complaints_list.append(create_complaint_record(
                name="",
                contact_number="123",
                category="Select a category...",
                incident_date=date.today(),
                location="",
                description="",
            ))

        self.assertEqual(len(complaints_list), 0, "Invalid complaint must not be saved.")

    def test_complaint_record_structure_and_stage2_status(self):
        """Test that complaint records have the exact required keys and accurate Stage 2 status."""
        fixed_date = date(2026, 3, 15)
        record = create_complaint_record(
            name="Anjali Nair",
            contact_number="+91 9447000000",
            category="Missing Person (കാണാതായ വ്യക്തി)",
            incident_date=fixed_date,
            location="Thiruvananthapuram",
            description="Missing person incident report description.",
            additional_info="Last seen wearing blue jeans.",
            custom_id="CMP-TEST-001",
        )

        expected_keys = {
            "complaint_id",
            "complainant_name",
            "contact_number",
            "category",
            "incident_date",
            "incident_time",
            "incident_location",
            "description",
            "additional_info",
            "submission_timestamp",
            "status",
            "has_draft",
            "fir_draft",
            "is_approved",
        }
        self.assertEqual(set(record.keys()), expected_keys)
        self.assertEqual(record["complaint_id"], "CMP-TEST-001")
        self.assertEqual(record["incident_date"], "2026-03-15")
        # Accurate status: does NOT claim an AI draft exists
        self.assertEqual(record["status"], "Complaint Submitted — FIR Draft Not Yet Generated")
        self.assertFalse(record["has_draft"])
        self.assertIsNone(record["fir_draft"])

    def test_duplicate_submission_fingerprinting(self):
        """Test that compute_submission_fingerprint generates consistent deterministic hashes."""
        fp1 = compute_submission_fingerprint(
            name="Rajesh Kumar",
            contact_number="+91 98765 43210",
            category=SUPPORTED_CATEGORIES[0],
            incident_date=date(2026, 5, 1),
            location="Ernakulam",
            description="Laptop bag stolen from car.",
            additional_info="Dell Inspiron",
        )
        # Even with slight surrounding whitespace differences, fingerprint must match
        fp2 = compute_submission_fingerprint(
            name="  Rajesh Kumar  ",
            contact_number="+91-98765-43210",  # Same digits
            category=SUPPORTED_CATEGORIES[0],
            incident_date=date(2026, 5, 1),
            location="  ernakulam  ",  # Lowercase / stripped match
            description="Laptop bag stolen from car.",
            additional_info="Dell Inspiron",
        )
        self.assertEqual(fp1, fp2, "Expected identical fingerprint to detect duplicate submissions.")

        # Different description should yield different fingerprint
        fp3 = compute_submission_fingerprint(
            name="Rajesh Kumar",
            contact_number="+91 98765 43210",
            category=SUPPORTED_CATEGORIES[0],
            incident_date=date(2026, 5, 1),
            location="Ernakulam",
            description="Different incident description.",
            additional_info="Dell Inspiron",
        )
        self.assertNotEqual(fp1, fp3)

    def test_conversational_step_validation(self):
        """Test validation for conversational chatbot steps."""
        from complaint_manager import validate_chat_step_input, get_step_prompt, CHAT_STEPS

        # 1. Step prompts exist for all chat steps
        for step in CHAT_STEPS:
            prompt = get_step_prompt(step)
            self.assertTrue(len(prompt) > 10, f"Prompt for step '{step}' was too short.")

        # 2. Description step: min 10 chars, accepts Unicode
        is_valid, err, slots = validate_chat_step_input("description", "Too short")
        self.assertFalse(is_valid)
        is_valid, err, slots = validate_chat_step_input("description", "മോഷണം നടന്നു ആലുവയിൽ വെച്ച്.")
        self.assertTrue(is_valid)
        self.assertEqual(slots["description"], "മോഷണം നടന്നു ആലുവയിൽ വെച്ച്.")

        # 3. Name step: min 2 chars
        is_valid, err, slots = validate_chat_step_input("name", "A")
        self.assertFalse(is_valid)
        is_valid, err, slots = validate_chat_step_input("name", "Rajesh Kumar")
        self.assertTrue(is_valid)
        self.assertEqual(slots["name"], "Rajesh Kumar")

        # 4. Contact step
        is_valid, err, slots = validate_chat_step_input("contact", "invalid-phone")
        self.assertFalse(is_valid)
        is_valid, err, slots = validate_chat_step_input("contact", "+91 9447123456")
        self.assertTrue(is_valid)
        self.assertEqual(slots["contact_number"], "+91 9447123456")

        # 5. Category step: accepts name or index
        is_valid, err, slots = validate_chat_step_input("category", "Theft")
        self.assertTrue(is_valid)
        self.assertIn("Theft", slots["category"])

        # 6. Date & Time step
        is_valid, err, slots = validate_chat_step_input("date_time", "Today at 3:30 PM")
        self.assertTrue(is_valid)
        self.assertEqual(slots["incident_date"], date.today().isoformat())

        # 7. Additional info step: handles skip/none
        is_valid, err, slots = validate_chat_step_input("additional_info", "None")
        self.assertTrue(is_valid)
        self.assertEqual(slots["additional_info"], "")


if __name__ == "__main__":
    unittest.main()
