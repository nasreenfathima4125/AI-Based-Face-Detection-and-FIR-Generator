"""Regression tests for citizen-facing language selection and Unicode handling."""

import unittest
from unittest.mock import patch

from citizen_i18n import (
    TRANSLATIONS,
    category_value_from_label,
    conversation_prompt,
    translate,
    translate_category,
)
from complaint_manager import generate_malayalam_fir_draft


class TestCitizenTranslations(unittest.TestCase):
    def test_supported_languages_have_the_same_interface_keys(self):
        english_keys = set(TRANSLATIONS["en"])
        self.assertEqual(set(TRANSLATIONS["ml"]), english_keys)
        self.assertEqual(set(TRANSLATIONS["hi"]), english_keys)

    def test_missing_key_and_unknown_language_fall_back_safely(self):
        self.assertEqual(translate("chat.title", "unsupported"), "Tell us what happened")
        with patch.dict(TRANSLATIONS["ml"]):
            del TRANSLATIONS["ml"]["chat.title"]
            self.assertEqual(translate("chat.title", "ml"), "Tell us what happened")
        self.assertEqual(translate("missing.example", "ml"), "missing.example")

    def test_chat_prompts_and_categories_are_localized_but_values_stay_stable(self):
        category = "Theft / Burglary (മോഷണം)"
        for language in ("en", "ml", "hi"):
            with self.subTest(language=language):
                self.assertTrue(conversation_prompt("description", language))
                shown_label = translate_category(category, language)
                self.assertEqual(category_value_from_label(shown_label, language), category)

    def test_template_draft_preserves_malayalam_and_hindi_facts_exactly(self):
        name = "കൽപ്പിത പൗരൻ"
        location = "नमूना मार्ग"
        description = "ഒരു സാങ്കൽപ്പിക സംഭവം — एक काल्पनिक घटना।"
        draft = generate_malayalam_fir_draft(
            complainant_name=name,
            contact_number="+91 98765 43210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location=location,
            description=description,
            additional_info="ഇത് ഒരു പരിശോധനാ രേഖയാണ്।",
        )
        for fact in (name, location, description, "ഇത് ഒരു പരിശോധനാ രേഖയാണ്।"):
            self.assertIn(fact, draft)


if __name__ == "__main__":
    unittest.main()
