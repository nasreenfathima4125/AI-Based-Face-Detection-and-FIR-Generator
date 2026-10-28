"""
tests/test_e2e_ui.py
--------------------
End-to-end tests for the Phase 1 public-service multi-page redesign:
1. Editorial landing page (Hero copy, single primary CTA, top navigation).
2. Language selection -> Conversational complaint assistant.
3. Conversational validation and Unicode preservation (Malayalam & Hindi).
4. AI fallback to guided form (preserving recoverable entered inputs).
5. Verification review & persistent SQLite database storage.
6. Authentication, Police Queue, and side-by-side FIR review and approval.
7. Citizen dashboard with locked FIR download policy.
"""

from datetime import date, datetime, timedelta, timezone
import sqlite3
import unittest
import os
from types import SimpleNamespace
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
import streamlit as st

from test_database_support import isolate_database

import app as application
import auth_sessions
import database
import otp_service
import sms_provider
from citizen_i18n import (
    conversation_prompt,
    translate,
    translate_category,
    translate_validation_message,
)


class TestPhase1ApplicationE2E(unittest.TestCase):
    """End-to-end testing of the complete Phase 1 application flow."""

    def setUp(self):
        """Give this UI test its own database, separate from production data."""
        self.database_path = isolate_database(self, database)
        with database.get_db_connection() as connection:
            self.role_ids = {
                row["role"]: row["id"]
                for row in connection.execute(
                    "SELECT id, role FROM users"
                ).fetchall()
            }
        self.health_environment = patch.dict(
            os.environ,
            {
                "FIR_AUTH_GATEWAY_HOST": "127.0.0.1",
                "FIR_AUTH_GATEWAY_PORT": "0",
                "FIR_AUTH_GATEWAY_HEALTH_TIMEOUT_SECONDS": "0.1",
            },
        )
        self.health_environment.start()
        self.addCleanup(self.health_environment.stop)

    def _open_valid_complaint_review(self):
        """Navigate through the real intake UI to a valid complaint review."""
        at = AppTest.from_file("../app.py").run()
        [b for b in at.button if "Report an incident" in b.label][0].click().run()
        [b for b in at.button if b.label == "Continue"][0].click().run()
        [
            b for b in at.button if "Use guided form instead" in b.label
        ][0].click().run()

        at.text_input[0].set_value("Fictional Test Citizen")
        at.text_input[1].set_value("+91 98765 43210")
        at.selectbox[0].select("Theft / Burglary (മോഷണം)")
        at.text_input[3].set_value("Sample Road")
        at.text_area[0].set_value("A fictional bag was taken from a sample vehicle.")
        [b for b in at.button if b.label == "Review complaint"][0].click().run()
        self.assertEqual(at.session_state["current_page"], "complaint_verify")
        return at

    def _sign_in_as(self, at, email, password):
        """Create a real test session and expose it as a simulated request cookie."""
        success, _, user = database.authenticate_user(email, password)
        self.assertTrue(success)
        self.assertIsNotNone(user)
        token, _ = auth_sessions.create_session(user["id"])
        self.addCleanup(auth_sessions.revoke_session, token)

        context_patch = patch.object(
            st,
            "context",
            SimpleNamespace(
                cookies={auth_sessions.SESSION_COOKIE_NAME: token}
            ),
        )
        context_patch.start()
        self.addCleanup(context_patch.stop)

        at.run()
        self.assertNotIn("auth_user", at.session_state)
        self.assertNotIn("password", at.session_state)
        dashboard_by_role = {
            "citizen": "citizen_dashboard",
            "police": "police_dashboard",
            "admin": "admin_dashboard",
        }
        self.assertEqual(
            at.session_state["current_page"],
            dashboard_by_role[user["role"]],
        )
        logout_link = next(
            item.value
            for item in at.markdown
            if "/auth/logout" in item.value
        )
        self.assertNotIn('target="_blank"', logout_link)
        return user

    def test_editorial_landing_page_requirements(self):
        """Verify the current landing page and its primary navigation controls."""
        at = AppTest.from_file("../app.py").run()
        self.assertFalse(at.exception)

        self.assertEqual(at.session_state["current_page"], "landing")

        markdown_joined = " ".join([m.value for m in at.markdown])
        self.assertIn("Justice begins", markdown_joined)
        self.assertIn("Share what happened in your preferred language", markdown_joined)
        self.assertIn("You can begin without creating an account", markdown_joined)
        self.assertIn("Research and evaluation", markdown_joined)
        self.assertIn(
            "not transmitted to external police systems",
            markdown_joined,
        )

        btn_labels = [b.label for b in at.button]
        self.assertTrue(any("Track Complaint" in lbl for lbl in btn_labels))
        self.assertTrue(any("Report an incident" in lbl for lbl in btn_labels))
        landing_auth_links = "\n".join(
            item.value
            for item in at.markdown
            if "/auth/login" in item.value or "/auth/signup" in item.value
        )
        self.assertIn('href="/auth/login"', landing_auth_links)
        self.assertIn('href="/auth/signup"', landing_auth_links)
        self.assertIn('href="/auth/login" target="_self"', landing_auth_links)
        self.assertIn('href="/auth/signup" target="_self"', landing_auth_links)
        self.assertIn("Create Account", landing_auth_links)
        self.assertEqual(len(at.get("text_input")), 0)

    def test_auth_pages_delegate_credentials_to_gateway(self):
        """Streamlit auth routes redirect to gateway forms without widgets."""
        at = AppTest.from_file("../app.py").run()
        self.assertEqual(len(at.get("text_input")), 0)
        landing_links = "\n".join(
            item.value
            for item in at.markdown
            if "/auth/login" in item.value or "/auth/signup" in item.value
        )
        self.assertIn('href="/auth/login"', landing_links)
        self.assertIn('href="/auth/signup"', landing_links)
        self.assertIn('target="_self"', landing_links)

        for route_renderer, gateway_path in (
            (application.render_auth_login, "/auth/login"),
            (application.render_auth_signup, "/auth/signup"),
        ):
            with self.subTest(gateway_path=gateway_path):
                rendered_markup = []
                with patch.object(
                    application,
                    "_render_html",
                    side_effect=rendered_markup.append,
                ):
                    route_renderer()

                self.assertEqual(len(rendered_markup), 1)
                self.assertIn(
                    f'<meta http-equiv="refresh" content="0;url={gateway_path}">',
                    rendered_markup[0],
                )
                self.assertIn(f'href="{gateway_path}"', rendered_markup[0])

    def test_complaint_intake_navigation_and_language_selection(self):
        """Verify landing navigation and multilingual chat prompts."""
        at = AppTest.from_file("../app.py").run()
        hero_btn = [b for b in at.button if "Report an incident" in b.label][0]
        hero_btn.click().run()

        self.assertEqual(at.session_state["current_page"], "language_select")

        at.radio[0].set_value("മലയാളം").run()
        [b for b in at.button if b.label == translate("continue", "ml")][0].click().run()

        self.assertEqual(at.session_state["current_page"], "complaint_chat")
        self.assertEqual(at.session_state["selected_language"], "ml")
        self.assertTrue(len(at.chat_message) > 0)
        self.assertTrue(len(at.chat_input) > 0)
        self.assertIn(
            "സംഭവം എന്താണെന്ന് വ്യക്തമായി വിവരിക്കുക",
            at.chat_message[0].markdown[0].value,
        )

    def test_citizen_complaint_labels_and_required_errors_are_localized(self):
        language_labels = {"English": "en", "മലയാളം": "ml", "हिन्दी": "hi"}
        for label, language in language_labels.items():
            with self.subTest(language=language):
                at = AppTest.from_file("../app.py").run()
                next(button for button in at.button if "Report an incident" in button.label).click().run()
                at.radio[0].set_value(label).run()
                next(
                    button for button in at.button
                    if button.label == translate("continue", language)
                ).click().run()
                self.assertIn(
                    conversation_prompt("description", language),
                    at.chat_message[0].markdown[0].value,
                )
                next(
                    button for button in at.button
                    if button.label == translate("chat.use_form", language)
                ).click().run()

                self.assertEqual(at.session_state["selected_language"], language)
                self.assertIn(translate("form.title", language), " ".join(m.value for m in at.markdown))
                visible_labels = [item.label for item in at.text_input] + [item.label for item in at.text_area]
                self.assertIn(translate("field.name", language), visible_labels)
                self.assertIn(translate("field.date_unknown", language), [item.label for item in at.checkbox])
                next(
                    button for button in at.button
                    if button.label == translate("form.review", language)
                ).click().run()

                rendered_errors = " ".join(item.value for item in at.error)
                self.assertIn(
                    translate_validation_message(
                        "Complainant name is required and cannot be empty or whitespace only.",
                        language,
                    ),
                    rendered_errors,
                )
                self.assertEqual(
                    translate_category("Theft / Burglary (മോഷണം)", language),
                    translate("category.theft", language),
                )

    def test_verification_screen_localizes_labels_and_preserves_facts(self):
        language_labels = {"en": "English", "ml": "മലയാളം", "hi": "हिन्दी"}
        original_fact = "एक काल्पनिक विवरण — ഒരു സാങ്കൽപ്പിക സംഭവം"
        for language, label in language_labels.items():
            with self.subTest(language=language):
                at = self._open_valid_complaint_review()
                at.session_state["selected_language"] = language
                at.session_state["complaint_slots"]["description"] = original_fact
                at.run()
                rendered = " ".join(item.value for item in at.markdown)
                self.assertIn(translate("review.title", language), rendered)
                self.assertIn(translate("review.description", language), rendered)
                self.assertIn(original_fact, rendered)
                self.assertIn(translate("review.submit", language), [b.label for b in at.button])

    def test_public_tracking_form_uses_the_selected_language(self):
        at = AppTest.from_file("../app.py").run()
        next(
            button for button in at.button
            if "Track an existing complaint" in button.label
        ).click().run()
        at.session_state["selected_language"] = "ml"
        at.run()
        self.assertIn(translate("track.title", "ml"), " ".join(item.value for item in at.markdown))
        self.assertIn(translate("track.reference", "ml"), [item.label for item in at.text_input])
        next(
            button for button in at.button
            if button.label == translate("track.check", "ml")
        ).click().run()
        self.assertTrue(
            any(translate("track.required", "ml") in item.value for item in at.error)
        )

    def test_submission_confirmation_and_account_invites_are_localized(self):
        for language in ("en", "ml", "hi"):
            with self.subTest(language=language):
                at = self._open_valid_complaint_review()
                at.session_state["selected_language"] = language
                at.run()
                next(
                    button for button in at.button
                    if button.label == translate("review.submit", language)
                ).click().run()

                self.assertEqual(at.session_state["current_page"], "complaint_confirmed")
                visible = " ".join(
                    [item.value for item in at.markdown]
                    + [item.value for item in at.caption]
                )
                self.assertIn(translate("confirm.title", language), visible)
                self.assertIn(translate("confirm.account_help", language), visible)
                self.assertTrue(
                    any(translate("confirm.success", language) in item.value for item in at.success)
                )
                auth_links = " ".join(
                    item.value for item in at.markdown
                    if "/auth/login" in item.value or "/auth/signup" in item.value
                )
                self.assertIn(translate("confirm.sign_in", language), auth_links)
                self.assertIn(translate("confirm.create_account", language), auth_links)

    def test_switching_language_keeps_entered_complaint_data(self):
        at = AppTest.from_file("../app.py").run()
        next(button for button in at.button if "Report an incident" in button.label).click().run()
        at.radio[0].set_value("മലയാളം").run()
        next(button for button in at.button if button.label == translate("continue", "ml")).click().run()

        original_fact = "ഒരു സാങ്കൽപ്പിക പരാതി — विवरण सुरक्षित"
        slots = dict(at.session_state["complaint_slots"])
        slots["description"] = original_fact
        at.session_state["complaint_slots"] = slots
        at.session_state["chat_step_index"] = 1
        at.session_state["chat_messages"] = [
            {"role": "assistant", "content": "old prompt"},
            {"role": "user", "content": original_fact},
        ]
        at.run()
        next(button for button in at.button if button.label == translate("chat.change_language", "ml")).click().run()
        at.radio[0].set_value("हिन्दी").run()
        next(button for button in at.button if button.label == translate("continue", "hi")).click().run()

        self.assertEqual(at.session_state["selected_language"], "hi")
        self.assertEqual(at.session_state["complaint_slots"]["description"], original_fact)
        self.assertIn(
            original_fact,
            [message["content"] for message in at.session_state["chat_messages"]],
        )
        self.assertIn(
            translate("chat.title", "hi"),
            " ".join(item.value for item in at.markdown),
        )

    def test_guided_form_language_switch_saves_current_values(self):
        at = AppTest.from_file("../app.py").run()
        next(button for button in at.button if "Report an incident" in button.label).click().run()
        at.radio[0].set_value("English").run()
        next(button for button in at.button if button.label == "Continue").click().run()
        next(
            button for button in at.button
            if button.label == translate("chat.use_form", "en")
        ).click().run()

        at.text_input[0].set_value("Fictional Citizen")
        at.text_input[1].set_value("+91 98765 43210")
        at.text_input[2].set_value("Sample Road")
        at.text_area[0].set_value("ഒരു സാങ്കൽപ്പിക സംഭവം — एक काल्पनिक घटना")
        next(
            button for button in at.button
            if button.label == translate("form.change_language", "en")
        ).click().run()

        self.assertEqual(at.session_state["current_page"], "language_select")
        self.assertEqual(at.session_state["complaint_slots"]["name"], "Fictional Citizen")
        self.assertEqual(
            at.session_state["complaint_slots"]["description"],
            "ഒരു സാങ്കൽപ്പിക സംഭവം — एक काल्पनिक घटना",
        )
        at.radio[0].set_value("हिन्दी").run()
        next(button for button in at.button if button.label == translate("continue", "hi")).click().run()
        self.assertEqual(at.session_state["current_page"], "complaint_guided_form")
        self.assertEqual(at.text_input[0].value, "Fictional Citizen")
        self.assertEqual(at.text_area[0].value, "ഒരു സാങ്കൽപ്പിക സംഭവം — एक काल्पनिक घटना")
        self.assertIn(translate("field.name", "hi"), [item.label for item in at.text_input])

    def test_ai_fallback_to_guided_form_preserves_inputs(self):
        """Verify guided-form fallback preserves the current complaint details."""
        at = AppTest.from_file("../app.py").run()
        [b for b in at.button if "Report an incident" in b.label][0].click().run()
        [b for b in at.button if b.label == "Continue"][0].click().run()

        test_desc = "My black backpack containing a laptop was stolen from my vehicle parked near Market Road."
        slots = at.session_state["complaint_slots"]
        slots["description"] = test_desc
        at.session_state["complaint_slots"] = slots
        at.run()

        fallback_btn = [
            b for b in at.button if "Use guided form instead" in b.label
        ][0]
        fallback_btn.click().run()

        self.assertEqual(at.session_state["current_page"], "complaint_guided_form")
        self.assertIn(test_desc, [field.value for field in at.text_area])
        form_headings = " ".join(item.value for item in at.markdown)
        self.assertIn("Complainant information", form_headings)
        self.assertIn("Incident details", form_headings)
        self.assertIn("Description and additional information", form_headings)

    def test_guided_form_back_to_chat_preserves_entered_values(self):
        """Verify Back submits form values without saving or validating them."""
        at = AppTest.from_file("../app.py").run()
        [b for b in at.button if "Report an incident" in b.label][0].click().run()
        [b for b in at.button if b.label == "Continue"][0].click().run()
        [
            b for b in at.button if "Use guided form instead" in b.label
        ][0].click().run()

        at.text_input[0].set_value("Fictional Citizen")
        at.text_input[1].set_value("+91 98765 43210")
        at.text_input[2].set_value("Around noon")
        at.text_input[3].set_value("Sample Road")
        at.selectbox[0].select("Theft / Burglary (മോഷണം)")
        at.text_area[0].set_value(
            "A fictional bag was taken from a sample vehicle."
        )
        at.text_area[1].set_value("Fictional witness details.")

        [
            b for b in at.button if b.label == "← Back to conversation"
        ][0].click().run()

        self.assertEqual(at.session_state["current_page"], "complaint_chat")
        slots = at.session_state["complaint_slots"]
        self.assertEqual(slots["name"], "Fictional Citizen")
        self.assertEqual(slots["contact_number"], "+91 98765 43210")
        self.assertEqual(slots["category"], "Theft / Burglary (മോഷണം)")
        self.assertEqual(slots["incident_date"], "Unknown")
        self.assertEqual(slots["incident_time"], "Around noon")
        self.assertEqual(slots["location"], "Sample Road")
        self.assertEqual(
            slots["description"],
            "A fictional bag was taken from a sample vehicle.",
        )
        self.assertEqual(slots["additional_info"], "Fictional witness details.")
        with database.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM complaints"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_review_screen_displays_sections_and_cancel_leaves_no_record(self):
        """Verify the review screen is organized and cancel does not save."""
        at = self._open_valid_complaint_review()
        markdown_joined = " ".join(item.value for item in at.markdown)
        self.assertIn("Review your complaint", markdown_joined)
        self.assertIn("Complainant details", markdown_joined)
        self.assertIn("Incident details", markdown_joined)
        self.assertIn("Description and additional information", markdown_joined)

        [b for b in at.button if b.label == "Cancel complaint"][0].click().run()
        self.assertEqual(at.session_state["current_page"], "landing")
        with database.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM complaints"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_editing_reviewed_details_saves_the_corrected_values(self):
        at = self._open_valid_complaint_review()
        next(button for button in at.button if button.label == "Edit details").click().run()
        self.assertEqual(at.session_state["current_page"], "complaint_guided_form")
        at.text_input[0].set_value("Corrected Fictional Citizen")
        at.text_area[0].set_value("Corrected fictional complaint details.")
        next(
            button
            for button in at.button
            if button.label == "Review complaint"
        ).click().run()
        self.assertTrue(
            any(
                "Corrected Fictional Citizen" in item.value
                for item in at.markdown
            )
        )

        next(
            button
            for button in at.button
            if button.label == "Submit complaint"
        ).click().run()
        reference = at.session_state["last_submitted_ref"]
        tracking = database.get_complaint_by_reference(
            reference,
            "+91 98765 43210",
        )
        saved = database.get_complaint_by_id(
            tracking["id"],
            actor_user_id=self.role_ids["police"],
        )
        self.assertEqual(saved["complainant_name"], "Corrected Fictional Citizen")
        self.assertEqual(saved["description"], "Corrected fictional complaint details.")

    def test_submitted_complaint_preserves_english_malayalam_and_hindi(self):
        descriptions = (
            ("English", "A fictional bag was reported missing."),
            ("മലയാളം", "ഒരു സാങ്കൽപ്പിക ബാഗ് കാണാതായി."),
            ("हिन्दी", "एक काल्पनिक बैग गुम होने की सूचना दी गई।"),
        )
        saved_descriptions = []
        for language, description in descriptions:
            with self.subTest(language=language):
                at = self._open_valid_complaint_review()
                slots = dict(at.session_state["complaint_slots"])
                slots["description"] = description
                at.session_state["complaint_slots"] = slots
                at.run()
                next(
                    button
                    for button in at.button
                    if button.label == "Submit complaint"
                ).click().run()
                complaint = database.get_complaint_by_id(
                    at.session_state["last_submitted_id"],
                    actor_user_id=self.role_ids["police"],
                )
                self.assertEqual(complaint["description"], description)
                saved_descriptions.append(complaint["description"])
        self.assertEqual(saved_descriptions, [text for _, text in descriptions])

    def test_confirmation_screen_explains_submission_status_and_tracking(self):
        """Verify submission confirmation is accurate and supports tracking."""
        at = self._open_valid_complaint_review()
        [b for b in at.button if b.label == "Submit complaint"][0].click().run()

        self.assertEqual(at.session_state["current_page"], "complaint_confirmed")
        self.assertTrue(
            any(
                "saved in this application" in info.value.lower()
                and "official fir" in info.value.lower()
                and "police have been notified" in info.value.lower()
                for info in at.info
            )
        )
        self.assertTrue(
            any("Complaint submitted successfully." in item.value for item in at.success)
        )
        self.assertTrue(
            any(
                'href="/auth/login"' in item.value
                for item in at.markdown
            )
        )
        visible_copy = " ".join(
            str(item.value)
            for collection in (
                at.markdown,
                at.info,
                at.success,
                at.caption,
                at.warning,
                at.error,
            )
            for item in collection
        ).lower()
        self.assertNotIn("prototype", visible_copy)
        self.assertNotIn("demonstration", visible_copy)

    def test_public_tracking_rate_limit_is_shared_across_streamlit_sessions(self):
        """A failed lookup in one session blocks a new session before DB lookup."""
        _, _, complaint = database.save_complaint(
            complainant_name="Synthetic Rate Limit Citizen",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Synthetic Rate Limit Location",
            description="Synthetic complaint for the tracking UI limit test.",
        )
        environment = {
            "FIR_PUBLIC_LOOKUP_RATE_LIMIT": "1",
            "FIR_PUBLIC_LOOKUP_RATE_WINDOW_SECONDS": "900",
            "FIR_OTP_HMAC_SECRET": "synthetic-test-hmac-key-" + "x" * 32,
        }
        shared_client_key = "a" * 64

        first_session = AppTest.from_file("../app.py").run()
        first_session.button(key="landing_track_complaint").click().run()
        with patch.dict(os.environ, environment), patch.object(
            application,
            "_public_lookup_client_key",
            return_value=shared_client_key,
        ), patch.object(
            database,
            "get_complaint_by_reference",
            wraps=database.get_complaint_by_reference,
        ) as first_lookup:
            first_session.text_input[0].set_value("CMP-NOT-A-REAL-REFERENCE")
            first_session.text_input[1].set_value("1111111111")
            next(
                button
                for button in first_session.button
                if button.label == "Check status"
            ).click().run()
            self.assertTrue(
                any("No complaint matched" in error.value for error in first_session.error)
            )
            self.assertEqual(first_lookup.call_count, 1)

            # A distinct AppTest instance has a new Streamlit session, but the
            # database-backed key is still the same trusted client identity.
            second_session = AppTest.from_file("../app.py").run()
            second_session.button(key="landing_track_complaint").click().run()
            second_session.text_input[0].set_value(complaint["reference_no"])
            second_session.text_input[1].set_value(complaint["contact_number"])
            with patch.object(
                database,
                "get_complaint_by_reference",
                side_effect=AssertionError("Rate-limited lookup reached complaint storage."),
            ) as blocked_lookup:
                next(
                    button
                    for button in second_session.button
                    if button.label == "Check status"
                ).click().run()

            self.assertEqual(blocked_lookup.call_count, 0)
            self.assertTrue(
                any("Too many status checks" in error.value for error in second_session.error)
            )
            visible_errors = " ".join(error.value for error in second_session.error)
            self.assertNotIn(complaint["reference_no"], visible_errors)
            self.assertNotIn(complaint["contact_number"], visible_errors)
            self.assertNotIn("matched", visible_errors.lower())

    def test_public_lookup_client_address_requires_trusted_proxy_header(self):
        self.assertEqual(
            application._trusted_public_lookup_client_address(
                "198.51.100.99, 203.0.113.7",
                trust_proxy=True,
            ),
            "203.0.113.7",
        )
        self.assertEqual(
            application._trusted_public_lookup_client_address(
                "198.51.100.99",
                trust_proxy=False,
            ),
            "unattributed-client",
        )
        self.assertEqual(
            application._trusted_public_lookup_client_address(
                "not-an-ip",
                trust_proxy=True,
            ),
            "unattributed-client",
        )

    def test_verification_and_sqlite_persistence(self):
        """Verify the guided form, citizen review, and isolated persistence."""
        at = self._open_valid_complaint_review()
        [b for b in at.button if b.label == "Submit complaint"][0].click().run()
        self.assertEqual(at.session_state["current_page"], "complaint_confirmed")
        ref_no = at.session_state["last_submitted_ref"]
        self.assertTrue(ref_no.startswith("CMP-"))
        self.assertTrue(at.success)
        self.assertTrue(at.query_params.get("recovery"))
        self.assertNotIn("reference", at.query_params)

        tracking = database.get_complaint_by_reference(
            ref_no,
            at.session_state["complaint_slots"]["contact_number"],
        )
        persisted = database.get_complaint_by_id(
            tracking["id"], actor_user_id=self.role_ids["police"]
        )
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted["complainant_name"], "Fictional Test Citizen")
        self.assertEqual(persisted["status"], "Submitted")

        draft = database.get_latest_fir_draft(persisted["id"], actor_user_id=self.role_ids["police"])
        self.assertIsNotNone(draft)
        self.assertIn("പ്രഥമ വിവര വിവരണം", draft["draft_content_ml"])
        self.assertIn("Fictional Test Citizen", draft["draft_content_ml"])
        with database.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM complaints"
            ).fetchone()[0]
        self.assertEqual(count, 1)
        at.run()
        self.assertEqual(at.session_state["current_page"], "complaint_confirmed")
        with database.get_db_connection() as connection:
            count_after_rerun = connection.execute(
                "SELECT COUNT(*) FROM complaints"
            ).fetchone()[0]
        self.assertEqual(count_after_rerun, 1)

    def test_confirmation_refresh_recovers_reference_after_contact_verification(self):
        """Verify a fresh session requires SMS OTP before showing the reference."""
        at = self._open_valid_complaint_review()
        [b for b in at.button if b.label == "Submit complaint"][0].click().run()
        reference = at.session_state["last_submitted_ref"]

        at.session_state["last_submitted_ref"] = None
        at.session_state["last_submitted_id"] = None
        at.session_state["complaint_submission_completed"] = False
        at.session_state["confirmation_verified_reference"] = None
        at.run()

        self.assertEqual(at.session_state["current_page"], "complaint_confirmed")
        self.assertTrue(
            any(b.label == "Send or resend code" for b in at.button)
        )
        self.assertFalse(at.code)
        sent_messages = []

        def capture_message(phone_number, message):
            sent_messages.append((phone_number, message))

        test_sms_environment = {
            "SMS_PROVIDER": "twilio",
            "TWILIO_ACCOUNT_SID": "AC" + "1" * 32,
            "TWILIO_AUTH_TOKEN": "test-auth-token-not-a-secret",
            "TWILIO_FROM_NUMBER": "+15551234567",
            "FIR_OTP_HMAC_SECRET": "test-key-" + "x" * 32,
        }
        with patch.dict(os.environ, test_sms_environment):
            with patch.object(
                sms_provider.TwilioSmsProvider,
                "send_sms",
                side_effect=capture_message,
            ):
                [b for b in at.button if b.label == "Send or resend code"][0].click().run()

        self.assertEqual(len(sent_messages), 1)
        self.assertEqual(sent_messages[0][0], "+91 98765 43210")
        code = sent_messages[0][1].split(" is ", 1)[1].split(".", 1)[0]
        self.assertEqual(len(code), 6)

        at.text_input[0].set_value("000000")
        [b for b in at.button if b.label == "Verify code"][0].click().run()
        self.assertTrue(at.error)
        self.assertFalse(at.code)
        self.assertEqual(at.session_state["current_page"], "complaint_confirmed")

        at.text_input[0].set_value(code)
        with patch.dict(os.environ, test_sms_environment):
            [b for b in at.button if b.label == "Verify code"][0].click().run()

        self.assertEqual(at.session_state["current_page"], "complaint_confirmed")
        self.assertTrue(at.session_state["confirmation_verified_handle"])
        self.assertEqual(at.code[0].value, reference)
        with database.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM complaints"
            ).fetchone()[0]
        self.assertEqual(count, 1)

        # A separate session cannot inherit authorization from persisted verified_at.
        at.session_state["last_submitted_ref"] = None
        at.session_state["last_submitted_id"] = None
        at.session_state["last_submitted_recovery_handle"] = None
        at.session_state["complaint_submission_completed"] = False
        at.session_state["confirmation_verified_handle"] = None
        at.run()
        self.assertFalse(at.code)
        self.assertTrue(
            any(button.label == "Send or resend code" for button in at.button)
        )
        self.assertIsNone(at.session_state["confirmation_verified_handle"])

    def test_expired_recovery_handle_cannot_show_reference_or_send_code(self):
        at = self._open_valid_complaint_review()
        [b for b in at.button if b.label == "Submit complaint"][0].click().run()
        handle = at.query_params["recovery"]
        handle_hash = otp_service.hash_recovery_handle(handle)
        expired_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with database.get_db_connection() as connection:
            connection.execute(
                """
                UPDATE complaint_recovery_challenges
                SET recovery_expires_at = ?
                WHERE handle_hash = ?
                """,
                (expired_at, handle_hash),
            )
            connection.commit()

        at.session_state["last_submitted_ref"] = None
        at.session_state["last_submitted_id"] = None
        at.session_state["last_submitted_recovery_handle"] = None
        at.session_state["complaint_submission_completed"] = False
        at.session_state["confirmation_verified_handle"] = None
        at.run()

        self.assertFalse(at.code)
        self.assertFalse(
            any(button.label == "Send or resend code" for button in at.button)
        )
        self.assertTrue(
            any(
                "This confirmation cannot be verified." in warning.value
                for warning in at.warning
            )
        )
    def test_confirmation_missing_or_invalid_reference_shows_recovery_message(self):
        """Verify invalid or missing confirmation references show no other record."""
        at = self._open_valid_complaint_review()
        [b for b in at.button if b.label == "Submit complaint"][0].click().run()

        at.session_state["last_submitted_ref"] = None
        at.session_state["last_submitted_id"] = None
        at.session_state["last_submitted_recovery_handle"] = None
        at.session_state["complaint_submission_completed"] = False
        at.session_state["confirmation_verified_handle"] = None
        at.query_params["recovery"] = "not-a-valid-recovery-handle"
        at.run()

        self.assertFalse(at.code)
        self.assertTrue(
            any("This confirmation cannot be verified." in warning.value
                for warning in at.warning)
        )
        self.assertEqual(at.session_state["current_page"], "complaint_confirmed")

        del at.query_params["recovery"]
        at.run()
        self.assertFalse(at.code)
        self.assertTrue(
            any("This confirmation cannot be verified." in warning.value
                for warning in at.warning)
        )

    def test_sms_provider_failure_does_not_create_a_valid_otp(self):
        """Verify provider errors leave no active code or exposed reference."""
        at = self._open_valid_complaint_review()
        [b for b in at.button if b.label == "Submit complaint"][0].click().run()
        complaint_id = at.session_state["last_submitted_id"]
        at.session_state["last_submitted_ref"] = None
        at.session_state["last_submitted_recovery_handle"] = None
        at.session_state["last_submitted_id"] = None
        at.session_state["complaint_submission_completed"] = False
        at.run()

        test_sms_environment = {
            "SMS_PROVIDER": "twilio",
            "TWILIO_ACCOUNT_SID": "AC" + "1" * 32,
            "TWILIO_AUTH_TOKEN": "test-auth-token-not-a-secret",
            "TWILIO_FROM_NUMBER": "+15551234567",
            "FIR_OTP_HMAC_SECRET": "test-key-" + "x" * 32,
        }
        with patch.dict(os.environ, test_sms_environment):
            with patch.object(
                sms_provider.TwilioSmsProvider,
                "send_sms",
                side_effect=sms_provider.SmsProviderError(
                    "The SMS provider is temporarily unavailable."
                ),
            ):
                [
                    b for b in at.button if b.label == "Send or resend code"
                ][0].click().run()

        self.assertTrue(
            any(
                translate("confirm.sms_unavailable", "en") in error.value
                for error in at.error
            )
        )
        self.assertFalse(at.code)
        handle_hash = at.session_state.get("confirmation_verified_handle")
        self.assertIsNone(handle_hash)
        with database.get_db_connection() as connection:
            row = connection.execute(
                """
                SELECT otp_hash FROM complaint_recovery_challenges
                WHERE complaint_id = ?
                """,
                (complaint_id,),
            ).fetchone()
        self.assertIsNone(row["otp_hash"])

    def test_new_intake_clears_previous_confirmation_state(self):
        """Verify a new intake cannot reuse the preceding complaint reference."""
        at = self._open_valid_complaint_review()
        [b for b in at.button if b.label == "Submit complaint"][0].click().run()
        handle = at.session_state["last_submitted_recovery_handle"]
        handle_hash = otp_service.hash_recovery_handle(handle)
        self.assertTrue(at.query_params.get("recovery"))

        [b for b in at.button if b.label == "Return home"][0].click().run()
        [b for b in at.button if "Report an incident" in b.label][0].click().run()

        self.assertEqual(at.session_state["current_page"], "language_select")
        self.assertNotIn("recovery", at.query_params)
        self.assertFalse(at.session_state["complaint_submission_completed"])
        self.assertIsNone(at.session_state["last_submitted_ref"])
        self.assertEqual(at.session_state["complaint_slots"]["description"], "")
        challenge = database.get_recovery_challenge(handle_hash)
        self.assertIsNotNone(challenge["revoked_at"])
        with database.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM complaints"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_failed_validation_stays_on_review_without_saving(self):
        """Verify invalid complaint data cannot reach confirmation or storage."""
        at = self._open_valid_complaint_review()
        slots = at.session_state["complaint_slots"]
        slots["description"] = ""
        at.session_state["complaint_slots"] = slots
        at.run()

        [b for b in at.button if b.label == "Submit complaint"][0].click().run()

        self.assertEqual(at.session_state["current_page"], "complaint_verify")
        self.assertTrue(at.error)
        with database.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM complaints"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_database_save_failure_stays_on_review(self):
        """Verify failed persistence displays an error and does not navigate."""
        at = self._open_valid_complaint_review()
        with patch.object(
            database,
            "save_complaint",
            return_value=(False, "Simulated database failure.", {}),
        ):
            [b for b in at.button if b.label == "Submit complaint"][0].click().run()

        self.assertEqual(at.session_state["current_page"], "complaint_verify")
        self.assertTrue(
            any(translate("submit.failed", "en") in error.value for error in at.error)
        )
        with database.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM complaints"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_police_queue_and_side_by_side_review_workflow(self):
        """Verify police queue and approval using only the test database."""
        _, _, complaint = database.save_complaint(
            complainant_name="Fictional Review Citizen",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date=date.today().isoformat(),
            incident_location="Sample Road",
            description="A fictional bag was taken from a sample vehicle.",
        )
        at = AppTest.from_file("../app.py").run()
        self._sign_in_as(
            at,
            "officer@keralapolice.demo",
            "Police@123",
        )
        self.assertEqual(at.session_state["current_page"], "police_dashboard")

        at.session_state["active_police_case_id"] = 999999
        at.run()
        self.assertTrue(
            any(
                "selected complaint could not be found" in error.value.lower()
                for error in at.error
            )
        )

        [b for b in at.button if b.label == "Inspect & Review"][0].click().run()
        self.assertTrue(
            any(
                "select a submitted complaint" in error.value.lower()
                for error in at.error
            )
        )
        self.assertIsNone(at.session_state["active_police_case_id"])

        selected_label = next(
            label
            for label in at.selectbox[0].options
            if complaint["reference_no"] in label
        )
        at.selectbox[0].select(selected_label).run()
        rev_buttons = [b for b in at.button if "Inspect & Review" in b.label]
        self.assertTrue(len(rev_buttons) > 0)
        rev_buttons[0].click().run()

        case_id = at.session_state["active_police_case_id"]
        self.assertEqual(case_id, complaint["id"])
        self.assertEqual(at.session_state["police_dashboard_tabs"], "Case details")

        at.session_state["police_dashboard_tabs"] = "FIR drafting"
        at.run()
        self.assertEqual(at.session_state["active_police_case_id"], complaint["id"])
        draft = database.get_latest_fir_draft(complaint["id"], actor_user_id=self.role_ids["police"])
        self.assertIn(
            f"police_draft_{complaint['id']}_{draft['id']}",
            [area.key for area in at.text_area],
        )

        edited_draft_text = "Updated fictional Malayalam draft: തിരുത്തിയ കരട്."
        draft_widget = next(
            area
            for area in at.text_area
            if area.key == f"police_draft_{complaint['id']}_{draft['id']}"
        )
        draft_widget.set_value(edited_draft_text)
        at.button(key=f"save_draft_{complaint['id']}").click().run()
        saved_draft = database.get_latest_fir_draft(
            complaint["id"],
            actor_user_id=self.role_ids["police"],
        )
        self.assertEqual(saved_draft["draft_content_ml"], edited_draft_text)

        review_checkbox = next(
            checkbox
            for checkbox in at.checkbox
            if "reviewed the draft" in checkbox.label
        )
        approve_btn = [b for b in at.button if "Approve FIR Draft" in b.label][0]
        self.assertTrue(approve_btn.disabled)
        case_before_approval = database.get_complaint_by_id(complaint["id"], actor_user_id=self.role_ids["police"])
        self.assertEqual(case_before_approval["is_approved"], 0)

        review_checkbox.check().run()
        approve_btn = [b for b in at.button if "Approve FIR Draft" in b.label][0]
        approve_btn.click().run()

        case_record = database.get_complaint_by_id(case_id, actor_user_id=self.role_ids["police"])
        self.assertEqual(case_record["is_approved"], 1)
        self.assertEqual(case_record["fir_status"], "Approved")
        self.assertEqual(
            at.session_state["active_police_case_id"],
            complaint["id"],
        )
        self.assertEqual(
            at.session_state["police_dashboard_tabs"],
            "FIR drafting",
        )
        self.assertTrue(
            any(
                "Draft approved in this application's review process" in item.value
                for item in at.success
            )
        )

        at.run()
        self.assertEqual(
            at.session_state["active_police_case_id"],
            complaint["id"],
        )
        self.assertEqual(
            at.session_state["police_dashboard_tabs"],
            "FIR drafting",
        )
        self.assertTrue(
            any(
                "Draft approved in this application's review process" in item.value
                for item in at.success
            )
        )
        self.assertEqual(
            database.get_latest_fir_draft(complaint["id"], actor_user_id=self.role_ids["police"])["status"],
            "Approved",
        )

    def test_police_approval_failure_remains_visible_after_rerun(self):
        """Report a failed approval without implying it was successful."""
        _, _, complaint = database.save_complaint(
            complainant_name="Fictional Approval Failure Citizen",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Sample Road",
            description="A fictional item was reported missing.",
            draft_content_ml="Fictional demonstration draft.",
        )
        at = AppTest.from_file("../app.py").run()
        self._sign_in_as(
            at,
            "officer@keralapolice.demo",
            "Police@123",
        )

        at.selectbox[0].select(at.selectbox[0].options[0]).run()
        [b for b in at.button if b.label == "Inspect & Review"][0].click().run()
        at.session_state["police_dashboard_tabs"] = "FIR drafting"
        at.run()
        review_checkbox = next(
            checkbox
            for checkbox in at.checkbox
            if "reviewed the draft" in checkbox.label
        )
        review_checkbox.check().run()

        with patch.object(
            database,
            "review_fir_draft",
            side_effect=sqlite3.OperationalError("database is locked"),
        ):
            [b for b in at.button if b.label == "Approve FIR Draft"][0].click().run()

        error_messages = [item.value for item in at.error]
        self.assertTrue(
            any(
                "Approval could not be confirmed" in message
                and "Unable to complete the request" in message
                for message in error_messages
            )
        )
        self.assertFalse(
            any(
                "Draft approved in this application's review process" in item.value
                for item in at.success
            )
        )
        self.assertEqual(
            at.session_state["active_police_case_id"],
            complaint["id"],
        )
        self.assertEqual(
            at.session_state["police_dashboard_tabs"],
            "FIR drafting",
        )
        at.run()
        self.assertTrue(
            any(
                "Approval could not be confirmed" in item.value
                and "Unable to complete the request" in item.value
                for item in at.error
            )
        )
        stored_case = database.get_complaint_by_id(complaint["id"], actor_user_id=self.role_ids["police"])
        stored_draft = database.get_latest_fir_draft(complaint["id"], actor_user_id=self.role_ids["police"])
        self.assertEqual(stored_case["is_approved"], 0)
        self.assertEqual(stored_case["fir_status"], "Pending Police Approval")
        self.assertEqual(stored_draft["status"], "Pending Police Approval")

    def test_citizen_download_requires_approved_current_draft(self):
        """A stale complaint approval flag cannot unlock a pending draft."""
        _, _, citizen = database.authenticate_user(
            "citizen@example.com",
            "Citizen@123",
        )
        self.assertIsNotNone(citizen)
        _, _, complaint = database.save_complaint(
            complainant_name="Fictional Dashboard Citizen",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Sample Road",
            description="A fictional bag was reported missing.",
            citizen_user_id=citizen["id"],
            draft_content_ml="Fictional approved demonstration draft.",
        )

        at = AppTest.from_file("../app.py").run()
        self._sign_in_as(
            at,
            "citizen@example.com",
            "Citizen@123",
        )
        self.assertEqual(at.session_state["current_page"], "citizen_dashboard")
        self.assertEqual(len(at.get("download_button")), 0)

        database.approve_fir_draft(
            complaint["id"],
            officer_user_id=self.role_ids["police"],
            officer_notes="Approved for prototype test.",
        )
        with database.get_db_connection() as connection:
            connection.execute(
                """
                UPDATE fir_drafts
                SET status = 'Pending Police Approval'
                WHERE complaint_id = ?
                """,
                (complaint["id"],),
            )
            connection.commit()

        at.run()
        self.assertEqual(len(at.get("download_button")), 0)

        approved_text = "Reviewed Malayalam version: മലയാളം परीक्षण"
        self.assertTrue(
            database.review_fir_draft(
                complaint_id=complaint["id"],
                reviewer_user_id=self.role_ids["police"],
                decision="approve",
                draft_content_ml=approved_text,
                reviewer_notes="Fictional approval for download test.",
            )
        )
        with patch.object(
            application.st,
            "download_button",
            wraps=application.st.download_button,
        ) as download_call:
            at.run()
        self.assertEqual(len(at.get("download_button")), 1)
        download_call.assert_called_once()
        download_arguments = download_call.call_args.kwargs
        self.assertEqual(download_arguments["data"], approved_text)
        self.assertEqual(download_arguments["mime"], "text/plain; charset=utf-8")

    def test_returned_or_incomplete_approval_never_shows_citizen_download(self):
        _, _, citizen = database.authenticate_user(
            "citizen@example.com",
            "Citizen@123",
        )
        _, _, complaint = database.save_complaint(
            complainant_name="Fictional Download Gate Citizen",
            contact_number="9876543210",
            category="Theft / Burglary (മോഷണം)",
            incident_date="Unknown",
            incident_location="Sample Road",
            description="A fictional item was reported missing.",
            citizen_user_id=citizen["id"],
            draft_content_ml="Fictional pending draft.",
        )
        at = AppTest.from_file("../app.py").run()
        self._sign_in_as(at, "citizen@example.com", "Citizen@123")

        self.assertTrue(
            database.return_complaint_for_correction(
                complaint["id"],
                officer_user_id=self.role_ids["police"],
                reason="A fictional detail needs clarification.",
            )
        )
        at.run()
        self.assertEqual(len(at.get("download_button")), 0)

        self.assertTrue(
            database.approve_fir_draft(
                complaint["id"],
                officer_user_id=self.role_ids["police"],
                officer_notes="Fictional test approval.",
            )
        )
        with database.get_db_connection() as connection:
            connection.execute(
                "UPDATE complaints SET fir_status = 'Pending Police Approval' WHERE id = ?",
                (complaint["id"],),
            )
            connection.commit()
        at.run()
        self.assertEqual(len(at.get("download_button")), 0)

    def test_citizen_can_reach_dashboard_through_sign_in(self):
        """Verify the validated citizen role reaches its own dashboard."""
        at = AppTest.from_file("../app.py").run()
        self._sign_in_as(
            at,
            "citizen@example.com",
            "Citizen@123",
        )

        self.assertEqual(at.session_state["current_page"], "citizen_dashboard")
        self.assertTrue(any("My dashboard" in item.value for item in at.markdown))

    def test_request_cookie_survives_a_new_streamlit_session(self):
        """A new app session resolves the same cookie through the database."""
        success, _, user = database.authenticate_user(
            "officer@keralapolice.demo",
            "Police@123",
        )
        self.assertTrue(success)
        token, _ = auth_sessions.create_session(user["id"])
        self.addCleanup(auth_sessions.revoke_session, token)
        context_patch = patch.object(
            st,
            "context",
            SimpleNamespace(
                cookies={auth_sessions.SESSION_COOKIE_NAME: token}
            ),
        )
        context_patch.start()
        self.addCleanup(context_patch.stop)

        for _ in range(2):
            at = AppTest.from_file("../app.py").run()
            self.assertEqual(at.session_state["current_page"], "police_dashboard")
            self.assertNotIn("auth_user", at.session_state)

    def test_authenticated_root_routes_each_database_role_to_its_dashboard(self):
        for role, expected_page in (
            ("citizen", "citizen_dashboard"),
            ("police", "police_dashboard"),
            ("admin", "admin_dashboard"),
        ):
            with self.subTest(role=role):
                token, _ = auth_sessions.create_session(self.role_ids[role])
                self.addCleanup(auth_sessions.revoke_session, token)
                with patch.object(
                    st,
                    "context",
                    SimpleNamespace(
                        cookies={auth_sessions.SESSION_COOKIE_NAME: token}
                    ),
                ):
                    at = AppTest.from_file("../app.py").run()
                self.assertFalse(at.exception)
                self.assertEqual(at.session_state["current_page"], expected_page)

    def test_root_uses_refreshed_role_after_database_role_change(self):
        officer_id = self.role_ids["police"]
        admin_id = self.role_ids["admin"]
        token, _ = auth_sessions.create_session(officer_id)
        self.addCleanup(auth_sessions.revoke_session, token)
        cookie_context = SimpleNamespace(
            cookies={auth_sessions.SESSION_COOKIE_NAME: token}
        )

        with patch.object(st, "context", cookie_context):
            officer_app = AppTest.from_file("../app.py").run()
        self.assertEqual(
            officer_app.session_state["current_page"],
            "police_dashboard",
        )
        self.assertTrue(
            database.update_user_role(
                officer_id,
                "citizen",
                admin_user_id=admin_id,
            )
        )

        with patch.object(st, "context", cookie_context):
            refreshed_app = AppTest.from_file("../app.py").run()
        self.assertEqual(
            refreshed_app.session_state["current_page"],
            "citizen_dashboard",
        )

    def test_invalid_or_revoked_session_keeps_root_on_public_landing(self):
        revoked_token, _ = auth_sessions.create_session(self.role_ids["citizen"])
        self.assertTrue(auth_sessions.revoke_session(revoked_token))
        expired_token, _ = auth_sessions.create_session(
            self.role_ids["citizen"],
            now=datetime.now(timezone.utc) - timedelta(days=1),
        )
        self.addCleanup(auth_sessions.revoke_session, expired_token)

        for token in ("malformed", revoked_token, expired_token):
            with self.subTest(session="invalid" if token == "malformed" else "unusable"):
                with patch.object(
                    st,
                    "context",
                    SimpleNamespace(
                        cookies={auth_sessions.SESSION_COOKIE_NAME: token}
                    ),
                ):
                    at = AppTest.from_file("../app.py").run()
                self.assertFalse(at.exception)
                self.assertEqual(at.session_state["current_page"], "landing")
                self.assertTrue(
                    any("Report an incident" in button.label for button in at.button)
                )

    def test_administrator_can_reach_administration_dashboard(self):
        at = AppTest.from_file("../app.py").run()
        self._sign_in_as(
            at,
            "admin@firsystem.demo",
            "Admin@123",
        )
        self.assertEqual(at.session_state["current_page"], "admin_dashboard")
        self.assertTrue(any("Administration" in item.value for item in at.markdown))
        self.assertTrue(
            any("Platform Health & Subsystems" in item.value for item in at.markdown)
        )

        def database_snapshot():
            with database.get_db_connection() as connection:
                return {
                    table: [tuple(row) for row in connection.execute(
                        f"SELECT * FROM {table} ORDER BY 1"
                    ).fetchall()]
                    for table in ("users", "complaints", "fir_drafts", "audit_logs")
                }

        before = database_snapshot()
        at.button(key="admin_health_recheck").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(database_snapshot(), before)

    def test_admin_health_check_failure_is_visible_without_crashing_dashboard(self):
        at = self._open_admin_dashboard()
        with patch.object(
            application.platform_health,
            "run_platform_health_checks",
            side_effect=RuntimeError("synthetic health failure"),
        ):
            at.button(key="admin_health_recheck").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(
            any(
                "Health checks could not be completed." in item.value
                for item in at.markdown
            )
        )

    def _open_admin_dashboard(self):
        at = AppTest.from_file("../app.py").run()
        self._sign_in_as(
            at,
            "admin@firsystem.demo",
            "Admin@123",
        )
        self.assertEqual(at.session_state["current_page"], "admin_dashboard")
        return at

    def _select_admin_role(self, at, email, role):
        account_label = next(
            option for option in at.selectbox[0].options if email in option
        )
        at.selectbox[0].select(account_label).run()
        at.selectbox[1].select(role).run()

    def test_admin_role_update_shows_confirmed_success_after_rerun(self):
        at = self._open_admin_dashboard()
        self._select_admin_role(at, "citizen@example.com", "police")

        at.button(key="admin_update_role").click().run()

        feedback = at.session_state["admin_role_update_feedback"]
        self.assertEqual(feedback["level"], "success")
        self.assertEqual(
            feedback["message"],
            "Role updated successfully. The account now has the role: police.",
        )
        self.assertTrue(any(feedback["message"] in item.value for item in at.success))
        with database.get_db_connection() as connection:
            saved_role = connection.execute(
                "SELECT role FROM users WHERE id = ?",
                (self.role_ids["citizen"],),
            ).fetchone()[0]
        self.assertEqual(saved_role, "police")

        at.run()
        self.assertTrue(
            any(feedback["message"] in item.value for item in at.success)
        )

        at.button(key="admin_update_role").click().run()
        replacement_feedback = at.session_state["admin_role_update_feedback"]
        self.assertEqual(replacement_feedback["level"], "info")
        self.assertIn("already has the role: police", replacement_feedback["message"])
        self.assertFalse(
            any(
                "Role updated successfully" in item.value
                for item in at.success
            )
        )

    def test_admin_role_update_rejection_shows_error_without_success(self):
        at = self._open_admin_dashboard()
        self._select_admin_role(at, "citizen@example.com", "police")

        with patch.object(
            database,
            "update_user_role",
            side_effect=database.AuthorizationError("synthetic authorization rejection"),
        ):
            at.button(key="admin_update_role").click().run()

        feedback = at.session_state["admin_role_update_feedback"]
        self.assertEqual(feedback["level"], "error")
        self.assertIn("Unable to complete the request", feedback["message"])
        self.assertTrue(any(feedback["message"] in item.value for item in at.error))
        self.assertFalse(at.success)

    def test_admin_role_update_unchanged_role_shows_information(self):
        at = self._open_admin_dashboard()
        self._select_admin_role(at, "citizen@example.com", "citizen")

        with patch.object(database, "update_user_role") as update_role:
            at.button(key="admin_update_role").click().run()

        update_role.assert_not_called()
        feedback = at.session_state["admin_role_update_feedback"]
        self.assertEqual(feedback["level"], "info")
        self.assertIn("already has the role: citizen", feedback["message"])
        self.assertTrue(any(feedback["message"] in item.value for item in at.info))

    def test_protected_police_dashboard_rejects_anonymous_and_citizen_sessions(self):
        anonymous = AppTest.from_string(
            "import app\napp.render_police_dashboard()"
        ).run()
        self.assertTrue(
            any("Please sign in" in item.value for item in anonymous.warning)
        )
        self.assertFalse(
            any("Police review workspace" in item.value for item in anonymous.markdown)
        )

        token, _ = auth_sessions.create_session(self.role_ids["citizen"])
        self.addCleanup(auth_sessions.revoke_session, token)
        with patch.object(
            st,
            "context",
            SimpleNamespace(cookies={auth_sessions.SESSION_COOKIE_NAME: token}),
        ):
            citizen_page = AppTest.from_string(
                "import app\napp.render_police_dashboard()"
            ).run()
        self.assertTrue(
            any("permission to access" in item.value.lower() for item in citizen_page.error)
        )
        self.assertFalse(
            any("Police review workspace" in item.value for item in citizen_page.markdown)
        )

    def test_citizen_and_police_sessions_cannot_open_admin_dashboard(self):
        for role in ("citizen", "police"):
            with self.subTest(role=role):
                token, _ = auth_sessions.create_session(self.role_ids[role])
                self.addCleanup(auth_sessions.revoke_session, token)
                with patch.object(
                    st,
                    "context",
                    SimpleNamespace(
                        cookies={auth_sessions.SESSION_COOKIE_NAME: token}
                    ),
                ):
                    at = AppTest.from_string(
                        "import app\napp.render_admin_dashboard()"
                    ).run()
                self.assertTrue(
                    any(
                        "permission to access" in item.value.lower()
                        for item in at.error
                    )
                )
                self.assertFalse(
                    any("Administration" in item.value for item in at.markdown)
                )


if __name__ == "__main__":
    unittest.main()
