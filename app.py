
"""
app.py

Integrated AI Surveillance and FIR Assistance System

A professional public-service platform for multilingual citizen complaint intake
and assisted First Information Report (FIR) drafting.

Architecture & Design System:
- Strict Palette: Warm Beige (#F3EBDD), Ivory (#FFFCF6), Dark Espresso (#493A2D),
  Deep Teal (#356B68), Muted Olive (#68745B), Muted Red (#A64B43), Readable Brown (#6B5B4D).
- Typography: Inter with Unicode fallbacks for Malayalam and Hindi.
- Storage: Relational SQLite database (database.py) with full restart persistence.
- Security: Salted PBKDF2 hashing, phone-matched complaint ownership verification, immutable audit logging.
- Workflows:
  1. Minimal, editorial Landing Page.
  2. Language selection -> conversational intake assistant -> guided form fallback.
  3. Structured fact verification -> persistent save & reference number -> account linking.
  4. Police Review Workspace: Complaint Queue and Malayalam FIR draft review.
  5. Citizen Dashboard: Linked complaints with FIR download policy until police approval.
  6. Administrator Portal: Role assignment, audit logs, and module telemetry.
"""

from datetime import date, datetime
from html import escape
import ipaddress
import logging
import os
import sqlite3
from textwrap import dedent
from typing import List, Dict, Any, Optional, Tuple

import streamlit as st
import auth_sessions
import database
import platform_health
import otp_service
from citizen_i18n import (
    category_value_from_label,
    conversation_prompt,
    translate,
    translate_category,
    translate_feedback,
    translate_status,
    translate_validation_message,
)
from sms_provider import SmsProviderError, get_sms_provider

from complaint_manager import (
    COMPLAINT_CATEGORIES,
    CHAT_STEPS,
    create_empty_complaint_slots,
    get_step_prompt,
    validate_chat_step_input,
    validate_complaint_input,
    generate_malayalam_fir_draft,
)

_APP_PAGE_OBJECTS: Dict[str, Any] = {}
_LOGGER = logging.getLogger(__name__)


# ==============================================================================
# SESSION STATE INITIALIZATION
# ==============================================================================

def init_session_state() -> None:
    """Initializes session state for persistent routing and user sessions."""
    if "current_page" not in st.session_state:
        st.session_state["current_page"] = "landing"

    if "selected_language" not in st.session_state:
        st.session_state["selected_language"] = "en"

    if "complaint_slots" not in st.session_state:
        st.session_state["complaint_slots"] = create_empty_complaint_slots("en")

    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = []

    if "chat_step_index" not in st.session_state:
        st.session_state["chat_step_index"] = 0

    if "last_submitted_ref" not in st.session_state:
        st.session_state["last_submitted_ref"] = None

    if "last_submitted_id" not in st.session_state:
        st.session_state["last_submitted_id"] = None

    if "last_submitted_recovery_handle" not in st.session_state:
        st.session_state["last_submitted_recovery_handle"] = None

    if "complaint_submission_completed" not in st.session_state:
        st.session_state["complaint_submission_completed"] = False

    if "confirmation_verified_handle" not in st.session_state:
        st.session_state["confirmation_verified_handle"] = None

    if "active_police_case_id" not in st.session_state:
        st.session_state["active_police_case_id"] = None


def navigate_to(page: str) -> None:
    """Switches to a registered Streamlit page without clearing app session state."""
    st.session_state["current_page"] = page
    st.switch_page(_APP_PAGE_OBJECTS[page])


def reset_intake() -> None:
    """Resets conversational slots and chat messages."""
    previous_handle = st.session_state.get("last_submitted_recovery_handle")
    if previous_handle:
        database.revoke_recovery_challenge(
            otp_service.hash_recovery_handle(previous_handle)
        )

    lang = st.session_state.get("selected_language", "en")
    st.session_state["complaint_slots"] = create_empty_complaint_slots(lang)
    st.session_state["chat_messages"] = []
    st.session_state["chat_step_index"] = 0
    st.session_state["complaint_submission_completed"] = False
    st.session_state["last_submitted_ref"] = None
    st.session_state["last_submitted_id"] = None
    st.session_state["last_submitted_recovery_handle"] = None
    st.session_state["confirmation_verified_handle"] = None
    st.session_state.pop("confirmation_otp", None)
    st.session_state.pop("confirmation_otp_clear_pending", None)
    st.session_state.pop("confirmation_otp_feedback", None)
    for key in ("reference", "recovery"):
        if key in st.query_params:
            del st.query_params[key]


# ==============================================================================
# DESIGN SYSTEM & GLOBAL CSS
# ==============================================================================

def _render_html(markup: str) -> None:
    """Render embedded HTML after removing indentation that Markdown treats as code."""
    st.markdown(dedent(markup).strip(), unsafe_allow_html=True)


def apply_custom_styles() -> None:
    """Apply the warm beige and ivory design system with accessible contrast."""
    _render_html(
        """
        <style>
        :root {
            --beige: #F3EBDD;
            --ivory: #FFFCF6;
            --espresso: #493A2D;
            --teal: #356B68;
            --teal-hover: #275250;
            --olive: #68745B;
            --muted: #6B5B4D;
            --border: #DED3C1;
            --red: #A64B43;
        }
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
            background: var(--beige) !important;
            color: var(--espresso) !important;
            font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                "Noto Sans Malayalam", "Noto Sans Devanagari", sans-serif !important;
        }
        [data-testid="stHeader"] { background: transparent !important; }
        [data-testid="stAppDeployButton"] { display: none !important; }
        [data-testid="stMainBlockContainer"] {
            max-width: 1440px;
            padding-top: 1.5rem;
            padding-bottom: 3rem;
        }
        h1, h2, h3, h4, h5, h6, p, li, label,
        [data-testid="stMarkdownContainer"] { color: var(--espresso); }
        h1, h2, h3, h4 { letter-spacing: -0.025em; line-height: 1.25; }
        h1 { font-size: clamp(2rem, 4vw, 3.25rem); }
        h2 { font-size: clamp(1.5rem, 3vw, 2.1rem); }
        [data-testid="stCaptionContainer"], .stCaption { color: var(--muted) !important; }
        .top-navbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            background: var(--ivory);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 14px 20px;
            margin-bottom: 28px;
        }
        .st-key-top-navbar {
            background: var(--ivory);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 8px 16px;
            margin-bottom: 24px;
        }
        .st-key-top-navbar [data-testid="stHorizontalBlock"] {
            align-items: center;
        }
        .brand-copy strong {
            display: block;
            color: var(--espresso);
            font-size: 1.08rem;
            font-weight: 750;
            letter-spacing: -.025em;
        }
        .brand-copy span {
            display: block;
            color: var(--muted);
            font-size: .78rem;
            margin-top: 3px;
        }
        .editorial-card, .auth-container {
            background: var(--ivory) !important;
            color: var(--espresso) !important;
            border: 1px solid var(--border) !important;
            border-radius: 10px !important;
            padding: clamp(18px, 3vw, 30px) !important;
            margin-bottom: 20px !important;
            box-shadow: 0 2px 8px rgba(73, 58, 45, 0.035);
        }
        .auth-container { max-width: 560px; margin: 24px auto; }
        [data-testid="stWidgetLabel"] p,
        [data-testid="stWidgetLabel"] span,
        [data-testid="stWidgetLabel"] label {
            color: var(--espresso) !important;
            font-weight: 600 !important;
            font-size: .93rem !important;
        }
        .stTextInput input, .stTextArea textarea, .stNumberInput input,
        [data-testid="stChatInput"] textarea {
            background: var(--ivory) !important;
            color: var(--espresso) !important;
            border: 1px solid #BFB3A2 !important;
            border-radius: 7px !important;
            font-size: .96rem !important;
            caret-color: var(--teal) !important;
        }
        .stSelectbox [data-baseweb="select"] > div,
        .stDateInput input, .stTimeInput input {
            background: var(--ivory) !important;
            color: var(--espresso) !important;
            border-color: #BFB3A2 !important;
            border-radius: 7px !important;
        }
        input::placeholder, textarea::placeholder {
            color: #756658 !important;
            opacity: 1 !important;
        }
        .stTextInput input:focus, .stTextArea textarea:focus,
        .stNumberInput input:focus, .stDateInput input:focus,
        [data-testid="stChatInput"] textarea:focus {
            border-color: var(--teal) !important;
            box-shadow: 0 0 0 2px rgba(53, 107, 104, .16) !important;
            outline: none !important;
        }
        .stButton > button, .stFormSubmitButton > button,
        [data-testid="stDownloadButton"] > button {
            min-height: 42px;
            border-radius: 7px !important;
            font-weight: 600 !important;
        }
        .stButton > button:not([kind="primary"]),
        .stFormSubmitButton > button:not([kind="primary"]),
        [data-testid="stDownloadButton"] > button {
            background: var(--ivory) !important;
            color: var(--espresso) !important;
            border: 1px solid #CFC3B2 !important;
        }
        .stButton > button:not([kind="primary"]):hover,
        .stFormSubmitButton > button:not([kind="primary"]):hover,
        [data-testid="stDownloadButton"] > button:hover {
            background: #F0E8DA !important;
            border-color: var(--teal) !important;
        }
        .stButton > button[kind="primary"],
        .stFormSubmitButton > button[kind="primary"] {
            background: var(--teal) !important;
            color: var(--ivory) !important;
            border: 1px solid var(--teal) !important;
        }
        .stButton > button[kind="primary"]:hover,
        .stFormSubmitButton > button[kind="primary"]:hover {
            background: var(--teal-hover) !important;
            border-color: var(--teal-hover) !important;
        }
        .stButton > button[kind="primary"] [data-testid="stMarkdownContainer"] p,
        .stFormSubmitButton > button[kind="primary"] [data-testid="stMarkdownContainer"] p {
            color: var(--ivory) !important;
        }
        .stButton > button:focus-visible,
        .stFormSubmitButton > button:focus-visible {
            outline: 3px solid rgba(53, 107, 104, .45) !important;
            outline-offset: 2px !important;
        }
        .auth-sign-out-link {
            box-sizing: border-box;
            display: flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            min-height: 42px;
            padding: 0 12px;
            border: 1px solid #CFC3B2;
            border-radius: 7px;
            background: var(--ivory);
            color: var(--espresso) !important;
            font-weight: 600;
            text-decoration: none !important;
        }
        .auth-gateway-link {
            box-sizing: border-box;
            display: flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            min-height: 42px;
            padding: 0 16px;
            border: 1px solid var(--teal);
            border-radius: 7px;
            background: var(--teal);
            color: var(--ivory) !important;
            font-weight: 600;
            text-decoration: none !important;
        }
        .auth-gateway-link:hover {
            border-color: var(--teal-hover);
            background: var(--teal-hover);
        }
        .auth-gateway-link:focus-visible {
            outline: 3px solid rgba(53, 107, 104, .45);
            outline-offset: 2px;
        }
        .auth-gateway-link.secondary {
            border-color: #CFC3B2;
            background: var(--ivory);
            color: var(--espresso) !important;
        }
        .auth-gateway-link.secondary:hover {
            border-color: var(--teal);
            background: #F0E8DA;
        }
        .form-switch {
            margin-top: 16px;
            color: var(--muted);
            font-size: .9rem;
        }
        .auth-sign-out-link:hover {
            background: #F0E8DA;
            border-color: var(--teal);
        }
        .auth-sign-out-link:focus-visible {
            outline: 3px solid rgba(53, 107, 104, .45);
            outline-offset: 2px;
        }
        button:disabled { opacity: .58 !important; cursor: not-allowed !important; }
        .st-key-chat-heading,
        .st-key-chat-controls,
        .st-key-complaint-chat-history,
        .st-key-chat-composer {
            max-width: 800px;
            margin-left: auto;
            margin-right: auto;
        }
        .st-key-chat-composer { margin-top: 4px; }
        .st-key-chat-controls { margin-top: 4px; margin-bottom: 12px; }
        .st-key-chat-controls [data-testid="stButton"] > button {
            min-height: 34px;
            padding: 4px 9px;
            color: var(--muted) !important;
            background: transparent !important;
            border-color: transparent !important;
            font-size: .86rem;
        }
        .st-key-chat-controls [data-testid="stButton"] > button:hover {
            color: var(--teal) !important;
            background: rgba(104, 116, 91, .09) !important;
        }
        .st-key-complaint-chat-history [data-testid="stChatMessage"] {
            display: flex;
            justify-content: flex-start;
            width: 100%;
            background: transparent !important;
            border: 0 !important;
            border-radius: 0 !important;
            padding: 0 !important;
            margin: 0 0 10px !important;
            box-shadow: none !important;
        }
        .st-key-complaint-chat-history [data-testid="stChatMessageAvatarAssistant"],
        .st-key-complaint-chat-history [data-testid="stChatMessageAvatarUser"] {
            display: none !important;
        }
        .st-key-complaint-chat-history [data-testid="stChatMessageContent"] {
            flex: 0 1 auto !important;
            width: fit-content !important;
            max-width: min(78%, 680px) !important;
            margin: 0 !important;
            background: var(--ivory) !important;
            border: 1px solid rgba(222, 211, 193, .55) !important;
            border-radius: 4px 18px 18px 18px !important;
            padding: 12px 16px !important;
            box-shadow: 0 1px 4px rgba(73, 58, 45, .035);
        }
        .st-key-complaint-chat-history [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
            justify-content: flex-end;
        }
        .st-key-complaint-chat-history [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
            background: #E6EDE8 !important;
            border-color: transparent !important;
            border-radius: 18px 4px 18px 18px !important;
        }
        .st-key-complaint-chat-history [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) [data-testid="stChatMessageContent"]::before {
            content: "FIR Assistant";
            display: block;
            margin-bottom: 5px;
            color: var(--teal);
            font-size: .7rem;
            font-weight: 700;
            letter-spacing: .025em;
        }
        .st-key-complaint-chat-history [data-testid="stChatMessageContent"] p,
        .st-key-complaint-chat-history [data-testid="stChatMessageContent"] li {
            color: var(--espresso) !important;
        }
        [data-testid="stBottomBlockContainer"] {
            box-sizing: border-box;
            width: 100% !important;
            max-width: 800px !important;
            margin-left: auto !important;
            margin-right: auto !important;
            padding: 0 16px 12px !important;
        }
        .st-key-guided-complaint-form,
        .st-key-guided-form-feedback {
            max-width: 860px;
            margin-left: auto;
            margin-right: auto;
        }
        [data-testid="stChatInput"] {
            background: var(--ivory) !important;
            border: 1px solid #CFC4B3 !important;
            border-radius: 24px !important;
            padding: 4px 7px !important;
            box-shadow: 0 3px 14px rgba(73, 58, 45, .07);
        }
        [data-testid="stChatInput"]:focus-within {
            border-color: var(--teal) !important;
            box-shadow: 0 0 0 2px rgba(53, 107, 104, .14),
                0 3px 14px rgba(73, 58, 45, .07) !important;
        }
        [data-testid="stChatInput"] textarea {
            background: transparent !important;
            border: 0 !important;
            border-radius: 20px !important;
            box-shadow: none !important;
            padding: 10px 12px !important;
        }
        [data-testid="stChatInput"] button {
            min-width: 36px;
            min-height: 36px;
            border-radius: 50% !important;
            color: var(--ivory) !important;
            background: var(--teal) !important;
        }
        [data-testid="stChatInput"] button:disabled {
            color: #F5F2EA !important;
            background: #849D99 !important;
        }
        .status-pill {
            display: inline-block;
            padding: 5px 10px;
            border-radius: 5px;
            font-size: .79rem;
            font-weight: 700;
            line-height: 1.4;
        }
        .pill-submitted {
            background: #E6EDE8;
            color: #405C49 !important;
            border: 1px solid #C4D3C7;
        }
        .pill-review {
            background: #F8EFE4;
            color: #805523 !important;
            border: 1px solid #E8D3BA;
        }
        .pill-approved {
            background: #E2ECEB;
            color: #285B58 !important;
            border: 1px solid #ADC7C5;
        }
        .pill-returned {
            background: #FAECEB;
            color: #8C3832 !important;
            border: 1px solid #E4B5B1;
        }
        .pill-locked {
            background: #EDE8DE;
            color: #62594E !important;
            border: 1px solid #D5CCC0;
        }
        [data-testid="stAlert"] { border-radius: 8px !important; }
        [data-testid="stExpander"] {
            background: var(--ivory) !important;
            border: 1px solid var(--border) !important;
            border-radius: 8px !important;
        }
        [data-testid="stExpander"] summary {
            color: var(--espresso) !important;
            font-weight: 600 !important;
        }
        button[role="tab"] { color: var(--espresso) !important; }
        button[role="tab"][aria-selected="true"] {
            color: var(--teal) !important;
            border-bottom-color: var(--teal) !important;
        }
        [data-testid="stMetric"] {
            background: var(--ivory);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
        }
        [data-testid="stMetricLabel"],
        [data-testid="stMetricValue"] { color: var(--espresso) !important; }
        .hero-title {
            font-size: clamp(2.25rem, 4.5vw, 3.5rem);
            font-weight: 750;
            line-height: 1.12;
            letter-spacing: -.04em;
            color: var(--espresso);
            margin: 0 0 18px;
        }
        .hero-subtitle {
            font-size: clamp(1.02rem, 1.5vw, 1.2rem);
            line-height: 1.7;
            color: var(--muted);
            margin-bottom: 26px;
            max-width: 580px;
        }
        .editorial-disclaimer {
            font-size: .86rem;
            color: var(--muted);
            border-top: 1px solid var(--border);
            padding-top: 18px;
            margin-top: 42px;
            line-height: 1.7;
        }
        [data-testid="stMarkdownContainer"],
        [data-testid="stExpander"] { overflow-wrap: anywhere; }
        @media (max-width: 768px) {
            [data-testid="stMainBlockContainer"] { padding: 1rem 1rem 2rem; }
            .top-navbar { padding: 12px; margin-bottom: 18px; }
            .st-key-top-navbar { padding: 8px 10px; margin-bottom: 18px; }
            .editorial-card, .auth-container { padding: 18px !important; }
            .hero-title { font-size: 2.25rem; }
            [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [data-testid="stHorizontalBlock"] .brand-copy) {
                flex-wrap: wrap;
                gap: 10px 12px;
            }
            [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [data-testid="stHorizontalBlock"] .brand-copy) > [data-testid="stColumn"]:first-child {
                flex: 1 1 100%;
                width: 100% !important;
                min-width: 0;
            }
            [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [data-testid="stHorizontalBlock"] .brand-copy) > [data-testid="stColumn"]:not(:first-child) {
                flex: 1 1 40%;
                width: auto !important;
                min-width: 0;
            }
            [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] [data-testid="stImage"]) {
                flex-wrap: nowrap !important;
                align-items: center;
            }
            [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] [data-testid="stImage"]) > [data-testid="stColumn"]:first-child {
                flex: 0 0 72px !important;
                width: 72px !important;
                min-width: 72px !important;
            }
            [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] [data-testid="stImage"]) > [data-testid="stColumn"]:last-child {
                flex: 1 1 0 !important;
                width: 0 !important;
                min-width: 0 !important;
            }
            .brand-copy strong { font-size: 1rem; }
        }
        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after {
                transition: none !important;
                scroll-behavior: auto !important;
            }
        }
        </style>
        """,
    )


def render_top_navbar() -> None:
    """Renders the top navigation header with clean public-service actions."""
    auth_user = _current_user()

    with st.container(key="top-navbar"):
        if auth_user:
            nav_c1, nav_c2, nav_c3, nav_c4 = st.columns(
                [5.2, 1.35, 1.15, 1.05],
                vertical_alignment="center",
            )
        else:
            nav_c1, nav_c2, nav_c3, nav_c4 = st.columns(
                [4.6, 1.25, 1.05, 1.3],
                vertical_alignment="center",
            )

        with nav_c1:
            logo_col, brand_col = st.columns(
                [1, 5.8],
                vertical_alignment="center",
            )
            with logo_col:
                st.image("assets/logo.png", width=72)
            with brand_col:
                _render_html(
                    """
                    <div class="brand-copy">
                        <strong>FIR Assistance System</strong>
                        <span>Complaint support, with care</span>
                    </div>
                    """,
                )

        with nav_c2:
            if st.button(
                "Track Complaint",
                type="tertiary",
                use_container_width=True,
                key="navbar_track_complaint",
            ):
                navigate_to("auth_track")

        with nav_c3:
            if not auth_user:
                _render_html(
                    '<a class="auth-gateway-link" href="/auth/login" '
                    'target="_self">'
                    "Sign In</a>",
                )
            else:
                role_title = auth_user["role"].title()
                if st.button(
                    f"👤 {role_title}",
                    use_container_width=True,
                    key="navbar_role_dashboard",
                ):
                    role = auth_user["role"]
                    if role == "citizen":
                        navigate_to("citizen_dashboard")
                    elif role == "police":
                        navigate_to("police_dashboard")
                    elif role == "admin":
                        navigate_to("admin_dashboard")

        if auth_user:
            with nav_c4:
                _render_html(
                    '<a class="auth-sign-out-link" href="/auth/logout">'
                    "Sign out</a>",
                )
        else:
            with nav_c4:
                _render_html(
                    '<a class="auth-gateway-link secondary" '
                    'href="/auth/signup" target="_self">'
                    "Create Account</a>",
                )


# ==============================================================================
# LANDING PAGE
# ==============================================================================

def render_landing_page() -> None:
    """Renders the premium public landing page."""

    # Hero section styling
    _render_html(
        """
        <style>
        .premium-hero {
            padding: 52px 0 36px;
            max-width: 610px;
        }

        .hero-eyebrow {
            color: #68745B;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.18em;
            text-transform: uppercase;
            margin-bottom: 22px;
        }

        .premium-title {
            color: #493A2D;
            font-size: clamp(3rem, 5.2vw, 4.65rem);
            font-weight: 750;
            line-height: 1.02;
            letter-spacing: -0.055em;
            margin: 0;
        }

        .premium-subtitle {
            color: #6B5B4D;
            font-size: 1.05rem;
            line-height: 1.8;
            max-width: 490px;
            margin: 22px 0 30px;
        }

        .hero-note {
            color: #6B5B4D;
            font-size: 0.82rem;
            line-height: 1.6;
            margin-top: 12px;
        }

        .product-stage {
            position: relative;
            width: 100%;
            max-width: 720px;
            margin: 16px auto 36px;
            padding: 22px 26px 36px 0;
            box-sizing: border-box;
        }

        .product-window {
            position: relative;
            z-index: 1;
            overflow: hidden;
            border: 1px solid #DED3C1;
            border-radius: 14px;
            background: #FFFCF6;
            box-shadow: 0 24px 64px rgba(73, 58, 45, .14), 0 3px 10px rgba(73, 58, 45, .06);
        }

        .product-window-bar {
            display: flex;
            align-items: center;
            gap: 7px;
            height: 42px;
            padding: 0 15px;
            background: #F1EBDD;
            border-bottom: 1px solid #DED3C1;
        }

        .window-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #C9BDAA;
        }

        .window-address {
            margin-left: 12px;
            color: #75695B;
            font-size: .68rem;
            letter-spacing: .02em;
        }

        .product-body {
            display: grid;
            grid-template-columns: 150px minmax(0, 1fr);
            min-height: 365px;
        }

        .workflow-rail {
            padding: 24px 16px;
            background: #F8F4EB;
            border-right: 1px solid #E8DFD1;
        }

        .rail-label, .workflow-label {
            color: #81735F;
            font-size: .61rem;
            font-weight: 750;
            letter-spacing: .12em;
            text-transform: uppercase;
        }

        .workflow-step {
            display: flex;
            gap: 10px;
            align-items: flex-start;
            margin-top: 22px;
            color: #75695B;
        }

        .workflow-step-number {
            display: flex;
            align-items: center;
            justify-content: center;
            flex: 0 0 25px;
            height: 25px;
            border: 1px solid #D8CEBD;
            border-radius: 50%;
            color: #68745B;
            font-size: .67rem;
            font-weight: 700;
        }

        .workflow-step.active .workflow-step-number {
            color: #FFFCF6;
            border-color: #356B68;
            background: #356B68;
        }

        .workflow-step-copy {
            padding-top: 3px;
            font-size: .69rem;
            line-height: 1.45;
        }

        .workflow-step.active .workflow-step-copy {
            color: #493A2D;
            font-weight: 700;
        }

        .workflow-main {
            min-width: 0;
            padding: 24px 23px 20px;
        }

        .workflow-main-heading {
            margin: 8px 0 5px;
            color: #493A2D;
            font-size: 1.18rem;
            font-weight: 720;
            letter-spacing: -.035em;
        }

        .workflow-main-copy {
            margin: 0;
            color: #75695B;
            font-size: .75rem;
            line-height: 1.55;
        }

        .workflow-fields {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 9px;
            margin-top: 17px;
        }

        .workflow-field {
            min-width: 0;
            padding: 10px 11px;
            border: 1px solid #E4DACC;
            border-radius: 7px;
            background: #FFFCF6;
        }

        .workflow-field-label {
            color: #81735F;
            font-size: .59rem;
            font-weight: 700;
            letter-spacing: .08em;
            text-transform: uppercase;
        }

        .workflow-field-value {
            margin-top: 5px;
            color: #493A2D;
            font-size: .72rem;
            font-weight: 600;
            overflow-wrap: anywhere;
        }

        .workflow-description {
            margin-top: 9px;
            padding: 11px;
            border: 1px solid #E4DACC;
            border-radius: 7px;
            background: #FFFCF6;
        }

        .workflow-description p {
            margin: 6px 0 0;
            color: #75695B;
            font-size: .68rem;
            line-height: 1.5;
        }

        .draft-float {
            position: absolute;
            z-index: 2;
            right: 0;
            bottom: 0;
            width: 205px;
            padding: 15px 16px;
            border: 1px solid #E5DACA;
            border-radius: 10px;
            background: #FFFCF6;
            box-shadow: 0 12px 32px rgba(73, 58, 45, .13);
        }

        .draft-float-label {
            color: #81735F;
            font-size: .59rem;
            font-weight: 750;
            letter-spacing: .1em;
            text-transform: uppercase;
        }

        .draft-float-title {
            margin-top: 7px;
            color: #493A2D;
            font-size: .82rem;
            font-weight: 700;
        }

        .draft-float-status {
            display: inline-block;
            margin-top: 9px;
            padding: 5px 8px;
            border-radius: 5px;
            background: #E8EBDD;
            color: #566348;
            font-size: .61rem;
            font-weight: 700;
        }

        .draft-float-copy {
            margin-top: 8px;
            color: #75695B;
            font-size: .65rem;
            line-height: 1.45;
        }

        .process-section {
            border-top: 1px solid #DED3C1;
            border-bottom: 1px solid #DED3C1;
            padding: 30px 0;
            margin-top: 30px;
            margin-bottom: 28px;
        }

        .process-heading {
            color: #493A2D;
            font-size: 1.45rem;
            font-weight: 700;
            letter-spacing: -0.035em;
            margin-bottom: 24px;
        }

        .process-number {
            color: #68745B;
            font-size: 0.76rem;
            font-weight: 750;
            letter-spacing: 0.08em;
            margin-bottom: 10px;
        }

        .process-title {
            color: #493A2D;
            font-size: 0.95rem;
            font-weight: 700;
            margin-bottom: 8px;
        }

        .process-description {
            color: #6B5B4D;
            font-size: 0.84rem;
            line-height: 1.65;
        }

        .legal-note {
            color: #6B5B4D;
            font-size: 0.78rem;
            line-height: 1.7;
            border-left: 2px solid #68745B;
            padding: 5px 0 5px 14px;
            margin: 24px 0 10px 0;
        }

        /* Primary and secondary Streamlit buttons */
        div.stButton > button[kind="primary"] {
            background: #356B68;
            border: 1px solid #356B68;
            color: #FFFCF6;
            border-radius: 7px;
            min-height: 46px;
            font-weight: 600;
            transition: background 0.2s ease;
        }

        div.stButton > button[kind="primary"] [data-testid="stMarkdownContainer"] p {
            color: #FFFCF6 !important;
        }

        div.stButton > button[kind="primary"]:hover {
            background: #275250;
            border-color: #275250;
            color: #FFFFFF;
        }

        div.stButton > button[kind="secondary"] {
            background: transparent;
            border: 1px solid #CFC3B2;
            color: #493A2D;
            border-radius: 7px;
            min-height: 46px;
            font-weight: 550;
        }

        div.stButton > button[kind="secondary"]:hover {
            background: #EAE1D2;
            border-color: #356B68;
            color: #493A2D;
        }

        .hero-primary [data-testid="stMarkdownContainer"] p {
            color: #FFFCF6 !important;
        }

        @media (max-width: 768px) {
            [data-testid="stHorizontalBlock"]:has(.premium-hero) {
                flex-direction: column;
                gap: 1.5rem;
            }

            [data-testid="stHorizontalBlock"]:has(.premium-hero) > [data-testid="stColumn"] {
                width: 100% !important;
                flex: 1 1 auto;
                min-width: 0;
            }

            .premium-hero {
                padding-top: 28px;
            }

            .premium-title {
                font-size: clamp(2.5rem, 10vw, 3.8rem);
                overflow-wrap: anywhere;
            }

            .premium-subtitle {
                overflow-wrap: anywhere;
            }

            .product-stage {
                margin-top: 4px;
                padding: 10px 0 30px;
                max-width: 100%;
                overflow-wrap: anywhere;
            }

            .product-body {
                grid-template-columns: 1fr;
            }

            .workflow-rail {
                display: grid;
                grid-template-columns: 1fr 1fr 1fr;
                gap: 8px;
                padding: 14px;
                border-right: 0;
                border-bottom: 1px solid #E8DFD1;
            }

            .rail-label {
                grid-column: 1 / -1;
            }

            .workflow-step {
                gap: 6px;
                margin-top: 2px;
            }

            .workflow-step-copy {
                font-size: .63rem;
            }

            .workflow-main {
                padding: 20px 15px;
            }

            .draft-float {
                right: 8px;
                bottom: 0;
                width: min(205px, calc(100% - 32px));
            }
        }
        </style>
        """,
    )

    # Main hero
    left, right = st.columns([1.08, 0.92], gap="large")

    with left:
        _render_html(
            """
            <div class="premium-hero">
                <div class="hero-eyebrow">Complaint support, with care</div>
                <div class="premium-title">Justice begins<br>with being heard.</div>
                <div class="premium-subtitle">
                    Share what happened in your preferred language. Review every
                    detail before submitting, and keep the Malayalam FIR draft
                    pending human review.
                </div>
            </div>
            """,
        )
        if st.button(
            "Report an incident  →",
            type="primary",
            use_container_width=True,
            key="landing_report_incident",
        ):
            reset_intake()
            navigate_to("language_select")

        if st.button(
            "Track an existing complaint  ↗",
            type="secondary",
            use_container_width=True,
            key="landing_track_complaint",
        ):
            navigate_to("auth_track")

        _render_html(
            """
            <div class="hero-note">
                You can begin without creating an account.
                Keep your reference number after submission.
            </div>
            """,
        )

    with right:
        # Illustrative view of the complaint review and police draft workflow.
        _render_html(
            """
            <div class="product-stage">
                <div class="product-window">
                    <div class="product-window-bar">
                        <span class="window-dot"></span><span class="window-dot"></span><span class="window-dot"></span>
                        <span class="window-address">fir assistance system / complaint review</span>
                    </div>
                    <div class="product-body">
                        <div class="workflow-rail">
                            <div class="rail-label">Your complaint</div>
                            <div class="workflow-step">
                                <span class="workflow-step-number">01</span>
                                <span class="workflow-step-copy">Describe the incident</span>
                            </div>
                            <div class="workflow-step active">
                                <span class="workflow-step-number">02</span>
                                <span class="workflow-step-copy">Review your details</span>
                            </div>
                            <div class="workflow-step">
                                <span class="workflow-step-number">03</span>
                                <span class="workflow-step-copy">Police draft review</span>
                            </div>
                        </div>
                        <div class="workflow-main">
                            <div class="workflow-label">Step 02 · Citizen review</div>
                            <div class="workflow-main-heading">Review your complaint</div>
                            <p class="workflow-main-copy">Check the details you provided before submitting.</p>
                            <div class="workflow-fields">
                                <div class="workflow-field">
                                    <div class="workflow-field-label">Category</div>
                                    <div class="workflow-field-value">Your selected category</div>
                                </div>
                                <div class="workflow-field">
                                    <div class="workflow-field-label">Incident date</div>
                                    <div class="workflow-field-value">As provided</div>
                                </div>
                                <div class="workflow-field">
                                    <div class="workflow-field-label">Location</div>
                                    <div class="workflow-field-value">Your incident location</div>
                                </div>
                                <div class="workflow-field">
                                    <div class="workflow-field-label">Language</div>
                                    <div class="workflow-field-value">English · മലയാളം · हिन्दी</div>
                                </div>
                            </div>
                            <div class="workflow-description">
                                <div class="workflow-field-label">Original complaint</div>
                                <p>Your description remains available for review against the generated draft.</p>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="draft-float">
                    <div class="draft-float-label">After submission</div>
                    <div class="draft-float-title">Malayalam FIR draft</div>
                    <div class="draft-float-status">Pending police review</div>
                    <div class="draft-float-copy">Prepared from submitted details using a fixed template; reviewed before approval.</div>
                </div>
            </div>
            """,
        )

    # Three-step process
    _render_html(
        """
        <div class="process-section">
            <div class="process-heading">
                A clearer path, from the start.
            </div>
        </div>
        """,
    )

    step1, step2, step3 = st.columns(3, gap="large")

    with step1:
        _render_html(
            """
            <div class="process-number">01 / DESCRIBE</div>
            <div class="process-title">Tell us what happened</div>
            <div class="process-description">
                Explain the incident in your own words and
                choose your preferred language.
            </div>
            """,
        )

    with step2:
        _render_html(
            """
            <div class="process-number">02 / VERIFY</div>
            <div class="process-title">Review the details</div>
            <div class="process-description">
                Check the collected information and correct
                anything that is inaccurate.
            </div>
            """,
        )

    with step3:
        _render_html(
            """
            <div class="process-number">03 / FOLLOW</div>
            <div class="process-title">Track your complaint</div>
            <div class="process-description">
                Keep your reference number and follow the
                progress recorded by the system.
            </div>
            """,
        )

    # Important legal and emergency information
    _render_html(
        """
        <div class="legal-note">
            <strong>Research and evaluation:</strong> This application
            supports complaint intake and FIR draft preparation. Submissions
            are not transmitted to external police systems, and an approved
            draft is not an officially registered FIR.
            <br><br>
            If someone is in immediate danger, contact the appropriate
            emergency service or local police directly. This platform
            does not replace emergency services or official procedures.
        </div>
        """,
    )


# ==============================================================================
# LANGUAGE SELECTION
# ==============================================================================

LANGUAGES = {
    "English": "en",
    "മലയാളം": "ml",
    "हिन्दी": "hi",
}

LANGUAGE_LABELS = LANGUAGES


def render_language_select() -> None:
    """Lets the citizen select their preferred intake language."""
    current_language = st.session_state.get("selected_language", "en")
    language_change_from = st.session_state.get("language_change_from")
    language_options = list(LANGUAGE_LABELS)
    current_label = next(
        (label for label, code in LANGUAGE_LABELS.items() if code == current_language),
        language_options[0],
    )
    current_index = language_options.index(current_label)
    selected = st.radio(
        translate("language.label", current_language),
        language_options,
        index=current_index,
        horizontal=True,
        label_visibility="collapsed",
    )
    selected_language = LANGUAGE_LABELS.get(selected, "en")
    st.markdown(f"## {translate('language.title', selected_language)}")
    st.write(translate("language.subtitle", selected_language))

    if st.button(
        translate("continue", selected_language),
        type="primary",
        use_container_width=True,
    ):
        lang_code = selected_language
        st.session_state["selected_language"] = lang_code
        slots = _get_complaint_slots()
        slots["language"] = lang_code
        st.session_state["complaint_slots"] = slots

        if language_change_from:
            old_messages = st.session_state.get("chat_messages", [])
            user_answers = [
                message.get("content", "")
                for message in old_messages
                if message.get("role") == "user"
            ]
            step_index = int(st.session_state.get("chat_step_index", 0))
            rebuilt_messages = []
            for index, answer in enumerate(user_answers[:step_index]):
                step = CHAT_STEPS[index]
                rebuilt_messages.append(
                    {"role": "assistant", "content": conversation_prompt(step, lang_code)}
                )
                # Preserve the citizen's original answer exactly as entered.
                rebuilt_messages.append({"role": "user", "content": answer})
            st.session_state["chat_messages"] = rebuilt_messages
            st.session_state.pop("language_change_from", None)
            navigate_to(language_change_from)
        else:
            if "complaint_slots" not in st.session_state:
                st.session_state["complaint_slots"] = create_empty_complaint_slots(
                    lang_code
                )
            st.session_state["chat_messages"] = []
            st.session_state["chat_step_index"] = 0
            navigate_to("complaint_chat")

    if st.button(translate("back", selected_language), use_container_width=True):
        st.session_state.pop("language_change_from", None)
        navigate_to(language_change_from or "landing")


# ==============================================================================
# COMPLAINT INTAKE HELPERS
# ==============================================================================

def _t(key: str, **values: Any) -> str:
    """Returns a citizen-facing translation for the current intake language."""
    lang = st.session_state.get("selected_language", "en")
    return translate(key, lang, **values)


def _safe_display(value: Any) -> str:
    """Escapes user-supplied values before inserting them into HTML."""
    if value is None:
        return ""
    return escape(str(value))


def _display_value(value: Any, fallback: str = "Not provided") -> str:
    """Returns a safe, readable value for the verification screen."""
    if value is None or str(value).strip() == "":
        return fallback
    return str(value)


def _get_complaint_slots() -> Dict[str, Any]:
    """Returns the active complaint slot dictionary."""
    slots = st.session_state.get("complaint_slots")

    if not isinstance(slots, dict):
        slots = create_empty_complaint_slots(
            st.session_state.get("selected_language", "en")
        )
        st.session_state["complaint_slots"] = slots

    return slots


def _get_slot_label(slot_key: str) -> str:
    """Returns a readable label for common complaint fields."""
    labels = {
        "name": "Complainant name",
        "age": "Age",
        "gender": "Gender",
        "address": "Address",
        "contact": "Contact number",
        "category": "Complaint category",
        "incident_date": "Incident date",
        "last_seen_date": "Last seen date",
        "last_seen_location": "Last seen location",
        "location": "Incident location",
        "description": "Incident description",
        "height": "Height",
        "clothing": "Clothing",
        "identifying_marks": "Identifying marks",
        "person_description": "Person description",
    }
    return labels.get(slot_key, slot_key.replace("_", " ").title())


def _get_chat_steps() -> List[Any]:
    """Returns configured chat steps from complaint_manager."""
    steps = CHAT_STEPS

    if isinstance(steps, dict):
        lang = st.session_state.get("selected_language", "en")
        selected_steps = steps.get(lang, steps.get("en", []))
        return list(selected_steps)

    return list(steps)


def _extract_step_key(step: Any) -> str:
    """Extracts a field key from the configured chat step."""
    if isinstance(step, dict):
        return str(
            step.get("key")
            or step.get("field")
            or step.get("slot")
            or ""
        )

    if isinstance(step, (tuple, list)) and step:
        return str(step[0])

    return str(getattr(step, "key", ""))


def _extract_step_prompt(step: Any, lang: str) -> str:
    """Gets the prompt for a chat step with a safe fallback."""
    key = _extract_step_key(step)

    try:
        prompt = get_step_prompt(step, lang)
        if prompt:
            return str(prompt)
    except (TypeError, KeyError, AttributeError):
        pass

    if isinstance(step, dict):
        prompts = step.get("prompts", {})
        if isinstance(prompts, dict):
            return str(prompts.get(lang, prompts.get("en", key)))

        return str(step.get("prompt", key))

    if isinstance(step, (tuple, list)) and len(step) > 1:
        return str(step[1])

    return _get_slot_label(key)


def _validate_step(key: str, value: str) -> Tuple[bool, str, Dict[str, Any]]:
    """Validates one answer using the complaint manager's actual API."""
    result = validate_chat_step_input(key, value)
    valid, message = _validation_result(result)
    slot_updates = (
        result[2]
        if valid and isinstance(result, tuple) and len(result) > 2
        and isinstance(result[2], dict)
        else {}
    )
    return valid, message, slot_updates


def _validation_result(result: Any):
    """Normalizes different validator return formats."""
    if isinstance(result, tuple):
        if len(result) >= 2:
            return bool(result[0]), str(result[1])
        if len(result) == 1:
            return bool(result[0]), ""

    if isinstance(result, dict):
        valid = result.get("valid", result.get("success", False))
        message = result.get("message", result.get("error", ""))
        return bool(valid), str(message)

    if isinstance(result, bool):
        return result, ""

    return bool(result), ""


# ==============================================================================
# CONVERSATIONAL COMPLAINT INTAKE
# ==============================================================================

def render_complaint_chat() -> None:
    """Renders the guided conversational complaint intake interface."""
    lang = st.session_state.get("selected_language", "en")
    slots = _get_complaint_slots()
    steps = _get_chat_steps()

    with st.container(key="chat-heading"):
        st.markdown(f"## {_t('chat.title')}")
        st.write(_t("chat.instructions"))

    with st.container(key="chat-controls", horizontal=True, gap="small"):
        if st.button(
            _t("chat.change_language"),
            key="chat_change_language",
            type="tertiary",
            width="content",
        ):
            st.session_state["language_change_from"] = "complaint_chat"
            navigate_to("language_select")

        if st.button(
            _t("chat.use_form"),
            key="chat_use_guided_form",
            type="tertiary",
            width="content",
        ):
            navigate_to("complaint_guided_form")

        if st.button(
            _t("chat.start_over"),
            key="chat_start_over",
            type="tertiary",
            width="content",
        ):
            reset_intake()
            st.rerun()

    if not steps:
        st.warning(_t("chat.steps_missing"))
        if st.button(_t("chat.open_form"), type="primary"):
            navigate_to("complaint_guided_form")
        return

    messages = st.session_state.get("chat_messages", [])

    with st.container(key="complaint-chat-history", gap="small"):
        for message in messages:
            role = message.get("role", "assistant")
            content = message.get("content", "")
            with st.chat_message(role):
                st.markdown(content)

        step_index = int(st.session_state.get("chat_step_index", 0))

        if step_index < len(steps):
            current_step = steps[step_index]
            key = _extract_step_key(current_step)
            prompt = _extract_step_prompt(current_step, lang)

            if not messages or messages[-1].get("content") != prompt:
                messages.append({"role": "assistant", "content": prompt})
                st.session_state["chat_messages"] = messages
                with st.chat_message("assistant"):
                    st.markdown(prompt)

            if key == "category":
                category_labels = [
                    f"{index}. {translate_category(category, lang)}"
                    for index, category in enumerate(COMPLAINT_CATEGORIES[1:], start=1)
                ]
                st.caption(_t("chat.categories_intro"))
                st.write("\n".join(category_labels))

    if step_index < len(steps):
        with st.container(key="chat-composer"):
            answer = st.chat_input(
                _t("chat.answer_placeholder"),
                key=f"chat_answer_{step_index}",
            )

        if answer is not None:
            answer = answer.strip()

            if not answer:
                st.warning(_t("chat.empty_answer"))
                st.rerun()

            validation_answer = (
                category_value_from_label(answer, lang)
                if key == "category"
                else None
            ) or answer
            valid, message, slot_updates = _validate_step(key, validation_answer)

            if not valid:
                st.error(
                    translate_validation_message(
                        message or _t("chat.general_error"),
                        lang,
                    )
                )
                st.stop()

            slots.update(slot_updates)
            st.session_state["complaint_slots"] = slots

            messages.append({"role": "user", "content": answer})
            st.session_state["chat_messages"] = messages
            st.session_state["chat_step_index"] = step_index + 1
            st.rerun()
    else:
        st.success(_t("chat.complete"))

        if st.button(_t("chat.review"), type="primary"):
            navigate_to("complaint_verify")


# ==============================================================================
# GUIDED FORM FALLBACK
# ==============================================================================

def render_guided_form() -> None:
    """Provides a conventional form as a fallback to conversational intake."""
    slots = _get_complaint_slots()
    lang = st.session_state.get("selected_language", "en")

    st.markdown(f"## {_t('form.title')}")
    st.write(_t("form.instructions"))

    with st.container(key="guided-complaint-form"):
        with st.form("guided_complaint_form"):
            st.markdown(f"### {_t('form.complainant_section')}")
            name = st.text_input(
                _t("field.name"),
                value=str(slots.get("name", "")),
            )
            contact_number = st.text_input(
                _t("field.contact"),
                value=str(slots.get("contact_number", "")),
            )

            st.markdown(f"### {_t('form.incident_section')}")
            categories = list(COMPLAINT_CATEGORIES)
            if not categories:
                categories = ["Other"]

            current_category = str(slots.get("category", ""))
            category_index = (
                categories.index(current_category)
                if current_category in categories
                else 0
            )

            category = st.selectbox(
                _t("field.category"),
                categories,
                index=category_index,
                format_func=lambda value: translate_category(value, lang),
            )

            saved_incident_date = str(slots.get("incident_date", "")).strip()
            incident_date_unknown = st.checkbox(
                _t("field.date_unknown"),
                value=(
                    not bool(saved_incident_date)
                    or saved_incident_date.casefold() == "unknown"
                ),
            )

            incident_date_default: Any = saved_incident_date
            try:
                if isinstance(incident_date_default, str):
                    incident_date_default = date.fromisoformat(
                        incident_date_default
                    )
            except ValueError:
                incident_date_default = date.today()

            if not isinstance(incident_date_default, date):
                incident_date_default = date.today()

            incident_date_value = "Unknown"
            if not incident_date_unknown:
                selected_incident_date = st.date_input(
                    _t("field.date"),
                    value=incident_date_default,
                    max_value=date.today(),
                )
                incident_date_value = selected_incident_date.isoformat()

            incident_time = st.text_input(
                _t("field.time"),
                value=str(slots.get("incident_time", "")),
            )

            location = st.text_input(
                _t("field.location"),
                value=str(slots.get("location", "")),
            )

            st.markdown(f"### {_t('form.description_section')}")
            description = st.text_area(
                _t("field.description"),
                value=str(slots.get("description", "")),
                height=180,
            )

            additional_info = st.text_area(
                _t("field.additional"),
                value=str(slots.get("additional_info", "")),
            )

            review_column, back_column, language_column = st.columns(3)
            with review_column:
                submitted = st.form_submit_button(
                    _t("form.review"),
                    type="primary",
                    use_container_width=True,
                )
            with back_column:
                back_to_chat = st.form_submit_button(
                    _t("form.back_chat"),
                    type="secondary",
                    use_container_width=True,
                )
            with language_column:
                change_language = st.form_submit_button(
                    _t("form.change_language"),
                    type="secondary",
                    use_container_width=True,
                )

    if submitted or back_to_chat or change_language:
        updated = {
            "name": name.strip(),
            "contact_number": contact_number.strip(),
            "category": category,
            "incident_date": incident_date_value,
            "incident_time": incident_time.strip(),
            "location": location.strip(),
            "description": description.strip(),
            "additional_info": additional_info.strip(),
        }

        slots.update(updated)
        st.session_state["complaint_slots"] = slots

        if back_to_chat:
            navigate_to("complaint_chat")
            return

        if change_language:
            st.session_state["language_change_from"] = "complaint_guided_form"
            navigate_to("language_select")
            return

        valid, errors = validate_complaint_input(
            name=slots.get("name", ""),
            contact_number=slots.get("contact_number", ""),
            category=slots.get("category", ""),
            incident_date=slots.get("incident_date"),
            location=slots.get("location", ""),
            description=slots.get("description", ""),
            additional_info=slots.get("additional_info", ""),
        )
        if not valid:
            with st.container(key="guided-form-feedback"):
                st.markdown(f"**{_t('form.feedback_title')}**")
                for message in errors.values():
                    st.error(translate_validation_message(message, lang))
        else:
            navigate_to("complaint_verify")


# ==============================================================================
# COMPLAINT VERIFICATION
# ==============================================================================

def render_complaint_verify() -> None:
    """Displays complaint information for citizen verification."""
    slots = _get_complaint_slots()
    lang = st.session_state.get("selected_language", "en")

    st.markdown(f"## {_t('review.title')}")
    st.caption(_t("review.caption"))

    section_groups = [
        (
            "review.section_complainant",
            [
                ("name", "review.name"),
                ("contact_number", "review.contact"),
            ],
        ),
        (
            "review.section_incident",
            [
                ("category", "review.category"),
                ("incident_date", "review.date"),
                ("incident_time", "review.time"),
                ("location", "review.location"),
            ],
        ),
        (
            "review.section_description",
            [
                ("description", "review.description"),
                ("additional_info", "review.additional"),
            ],
        ),
    ]

    with st.container(border=True):
        for section_title, fields in section_groups:
            st.markdown(f"### {_t(section_title)}")
            for key, label_key in fields:
                value = _display_value(
                    slots.get(key),
                    fallback=_t("review.not_provided"),
                )
                if key == "category":
                    value = translate_category(value, lang)
                elif key == "incident_date" and value.casefold() == "unknown":
                    value = _t("review.unknown")
                st.markdown(f"**{_t(label_key)}:**")
                st.write(value)
            st.markdown("---")

    st.markdown(f"### {_t('review.section_actions')}")
    col1, col2, col3 = st.columns([1.05, 1.2, 1.05])

    with col1:
        if st.button(_t("review.edit"), type="secondary", use_container_width=True):
            st.session_state["complaint_submission_completed"] = False
            navigate_to("complaint_guided_form")

    with col2:
        if st.button(
            _t("review.submit"),
            type="primary",
            use_container_width=True,
        ):
            _submit_complaint(slots)

    with col3:
        if st.button(
            _t("review.cancel"),
            type="secondary",
            use_container_width=True,
        ):
            reset_intake()
            navigate_to("landing")


def _submit_complaint(slots: Dict[str, Any]) -> None:
    """Validates and stores a complaint using the database module."""
    lang = st.session_state.get("selected_language", "en")
    if st.session_state.get("complaint_submission_completed"):
        if st.session_state.get("last_submitted_ref"):
            navigate_to("complaint_confirmed")
            return
        st.error(_t("submit.duplicate"))
        return

    valid, errors = validate_complaint_input(
        name=slots.get("name", ""),
        contact_number=slots.get("contact_number", ""),
        category=slots.get("category", ""),
        incident_date=slots.get("incident_date"),
        location=slots.get("location", ""),
        description=slots.get("description", ""),
        additional_info=slots.get("additional_info", ""),
    )

    if not valid:
        for message in errors.values():
            st.error(translate_validation_message(message, lang))
        return

    user = _current_user()
    citizen_user_id = (
        user["id"] if user and user.get("role") == "citizen" else None
    )
    recovery_handle, recovery_handle_hash = otp_service.create_recovery_handle()
    draft = generate_malayalam_fir_draft(
        complainant_name=slots["name"].strip(),
        contact_number=slots["contact_number"].strip(),
        category=slots["category"].strip(),
        incident_date=str(slots["incident_date"]).strip(),
        incident_location=slots["location"].strip(),
        description=slots["description"].strip(),
        incident_time=str(slots.get("incident_time", "")).strip(),
        additional_info=str(slots.get("additional_info", "")).strip(),
    )

    try:
        success, message, record = database.save_complaint(
            complainant_name=slots["name"],
            contact_number=slots["contact_number"],
            category=slots["category"],
            incident_date=str(slots["incident_date"]),
            incident_location=slots["location"],
            description=slots["description"],
            additional_info=str(slots.get("additional_info", "")),
            incident_time=str(slots.get("incident_time", "")),
            intake_language=st.session_state.get("selected_language", "en"),
            citizen_user_id=citizen_user_id,
            draft_content_ml=draft,
            recovery_handle_hash=recovery_handle_hash,
        )
    except (sqlite3.Error, database.AuthorizationError) as exc:
        _LOGGER.exception("Complaint submission failed.")
        st.error(_t("submit.unavailable"))
        return

    if not success or not record.get("reference_no"):
        st.error(_t("submit.failed"))
        return

    st.session_state["last_submitted_ref"] = record["reference_no"]
    st.session_state["last_submitted_id"] = record["id"]
    st.session_state["last_submitted_recovery_handle"] = recovery_handle
    st.session_state["complaint_submission_completed"] = True
    navigate_to("complaint_confirmed")


# ==============================================================================
# COMPLAINT SUBMISSION CONFIRMATION
# ==============================================================================

def _send_confirmation_code(
    handle_hash: str,
    challenge: Dict[str, Any],
) -> str:
    """Reserves a rate-limited OTP and sends it through the configured provider."""
    secret = otp_service.get_otp_secret()
    provider = get_sms_provider()
    code = otp_service.create_otp()
    code_hash = otp_service.hash_otp(secret, handle_hash, code)
    phone_hash = otp_service.hash_phone_for_rate_limit(
        secret,
        challenge["contact_number"],
    )
    now = otp_service.current_utc_time()

    reserved, status = database.reserve_recovery_otp(
        handle_hash=handle_hash,
        phone_hash=phone_hash,
        otp_hash=code_hash,
        now=now,
        otp_ttl_seconds=otp_service.OTP_TTL_SECONDS,
        resend_cooldown_seconds=otp_service.OTP_RESEND_COOLDOWN_SECONDS,
        send_window_seconds=otp_service.OTP_SEND_WINDOW_SECONDS,
        max_sends_per_window=otp_service.OTP_MAX_SENDS_PER_WINDOW,
    )
    if not reserved:
        return status

    message = (
        f"Your FIR Assistance System confirmation code is {code}. "
        f"It expires in {otp_service.OTP_TTL_SECONDS // 60} minutes."
    )
    try:
        provider.send_sms(challenge["contact_number"], message)
    except SmsProviderError:
        database.cancel_recovery_otp(handle_hash, code_hash)
        raise

    return "sent"


def render_complaint_confirmed() -> None:
    """Shows the reference number for a successfully submitted complaint."""
    lang = st.session_state.get("selected_language", "en")
    clear_otp = st.session_state.pop("confirmation_otp_clear_pending", False)
    if st.session_state.get("confirmation_verified_handle") or clear_otp:
        st.session_state.pop("confirmation_otp", None)
    verification_feedback = st.session_state.pop(
        "confirmation_otp_feedback",
        None,
    )

    session_reference = st.session_state.get("last_submitted_ref")
    session_handle = st.session_state.get("last_submitted_recovery_handle")
    requested_handle = str(st.query_params.get("recovery", "")).strip()

    if (
        not requested_handle
        and st.session_state.get("complaint_submission_completed")
        and session_handle
    ):
        st.query_params["recovery"] = session_handle
        requested_handle = session_handle

    reference = None
    challenge: Optional[Dict[str, Any]] = None
    handle_hash: Optional[str] = None

    if requested_handle and 40 <= len(requested_handle) <= 50:
        handle_hash = otp_service.hash_recovery_handle(requested_handle)
        try:
            challenge = database.get_recovery_challenge(handle_hash)
        except (sqlite3.Error, database.AuthorizationError):
            _LOGGER.exception("Complaint confirmation could not be retrieved.")
            st.error(_t("confirm.service_unavailable"))

        if challenge:
            recovery_expires_at = challenge.get("recovery_expires_at")
            handle_expired = (
                not recovery_expires_at
                or otp_service.current_utc_time()
                >= datetime.fromisoformat(recovery_expires_at)
            )
            if challenge.get("revoked_at") or handle_expired:
                challenge = None

        if challenge:
            same_submission = (
                st.session_state.get("complaint_submission_completed")
                and session_handle == requested_handle
                and session_reference == challenge["reference_no"]
            )
            verified_in_session = (
                st.session_state.get("confirmation_verified_handle")
                == handle_hash
            )
            if same_submission or verified_in_session:
                reference = challenge["reference_no"]

    st.markdown(f"## {_t('confirm.title')}")
    st.info(_t("confirm.disclaimer"))
    if verification_feedback:
        st.error(translate_feedback(verification_feedback, lang))

    if reference:
        st.success(_t("confirm.success"))
        st.markdown(f"### {_t('confirm.reference_title')}")
        st.code(str(reference))
        st.write(_t("confirm.reference_help"))
        st.caption(_t("confirm.account_help"))
    else:
        if challenge and handle_hash:
            st.write(_t("confirm.recovery_help"))
            st.caption(
                _t(
                    "confirm.recovery_phone",
                    phone=otp_service.mask_phone_number(
                        challenge["contact_number"]
                    ),
                )
            )

            locked_until = challenge.get("locked_until")
            locked = False
            if locked_until:
                locked = otp_service.current_utc_time() < datetime.fromisoformat(
                    locked_until
                )

            if not locked:
                last_sent_at = challenge.get("last_sent_at")
                cooldown_active = False
                if last_sent_at:
                    elapsed = (
                        otp_service.current_utc_time()
                        - datetime.fromisoformat(last_sent_at)
                    ).total_seconds()
                    cooldown_active = (
                        elapsed < otp_service.OTP_RESEND_COOLDOWN_SECONDS
                    )

                with st.form("send_confirmation_code_form"):
                    send_submitted = st.form_submit_button(
                        _t("confirm.send_code"),
                        type="secondary",
                        disabled=cooldown_active,
                    )
                if cooldown_active:
                    st.caption(_t("confirm.wait_code"))

                if send_submitted:
                    try:
                        send_status = _send_confirmation_code(
                            handle_hash,
                            challenge,
                        )
                    except (ValueError, SmsProviderError) as exc:
                        _LOGGER.warning("Confirmation code delivery failed: %s", type(exc).__name__)
                        st.error(_t("confirm.sms_unavailable"))
                    except (sqlite3.Error, database.AuthorizationError):
                        _LOGGER.exception("Confirmation code request failed.")
                        st.error(_t("confirm.service_unavailable"))
                    else:
                        if send_status == "sent":
                            st.success(_t("confirm.code_sent"))
                            st.rerun()
                        elif send_status == "cooldown":
                            st.warning(_t("confirm.wait_code"))
                        elif send_status == "rate_limited":
                            st.error(_t("confirm.too_many_codes"))
                        elif send_status == "locked":
                            st.error(_t("confirm.locked"))
                        elif send_status == "already_verified":
                            st.error(_t("confirm.request_new_code"))
                        elif send_status in {"handle_expired", "revoked"}:
                            st.warning(_t("confirm.recovery_expired"))
                        else:
                            st.error(_t("confirm.recovery_unavailable"))

                try:
                    challenge = database.get_recovery_challenge(handle_hash)
                except (sqlite3.Error, database.AuthorizationError):
                    _LOGGER.exception("Complaint confirmation could not be retrieved.")
                    st.error(_t("confirm.service_unavailable"))
                    challenge = None
                if (
                    challenge
                    and challenge.get("otp_hash")
                    and challenge.get("expires_at")
                    and otp_service.current_utc_time()
                    < datetime.fromisoformat(challenge["expires_at"])
                ):
                    with st.form("verify_confirmation_code_form"):
                        code = st.text_input(
                            _t("confirm.code_label"),
                            max_chars=otp_service.OTP_LENGTH,
                            key="confirmation_otp",
                        )
                        verify_submitted = st.form_submit_button(
                            _t("confirm.verify_code"),
                            type="primary",
                        )
                    if verify_submitted:
                        try:
                            secret = otp_service.get_otp_secret()
                            candidate_hash = otp_service.hash_otp(
                                secret,
                                handle_hash,
                                code,
                            )
                            verify_status = database.verify_recovery_otp(
                                handle_hash=handle_hash,
                                candidate_hash=candidate_hash,
                                now=otp_service.current_utc_time(),
                                max_attempts=otp_service.OTP_MAX_ATTEMPTS,
                                lockout_seconds=otp_service.OTP_LOCKOUT_SECONDS,
                            )
                        except ValueError:
                            verification_feedback = _t("confirm.service_unavailable")
                            verify_status = "configuration_error"
                        except (sqlite3.Error, database.AuthorizationError):
                            verification_feedback = _t("confirm.service_unavailable")
                            verify_status = "database_error"
                        if verify_status == "verified":
                            st.session_state[
                                "confirmation_verified_handle"
                            ] = handle_hash
                            st.rerun()
                        if verify_status == "locked":
                            verification_feedback = _t("confirm.too_many_incorrect")
                        elif verify_status == "expired":
                            verification_feedback = _t("confirm.code_expired")
                        elif verify_status in {"handle_expired", "revoked"}:
                            verification_feedback = _t("confirm.recovery_expired")
                        elif verify_status == "invalid":
                            verification_feedback = _t("confirm.code_invalid")
                        elif verify_status == "already_verified":
                            verification_feedback = _t("confirm.code_used")
                        elif verify_status not in {
                            "configuration_error",
                            "database_error",
                        }:
                            verification_feedback = _t("confirm.code_invalid")
                        if verification_feedback:
                            st.session_state[
                                "confirmation_otp_feedback"
                            ] = verification_feedback
                            st.session_state[
                                "confirmation_otp_clear_pending"
                            ] = True
                            st.rerun()
            elif locked:
                st.error(_t("confirm.too_many_incorrect"))
        else:
            st.warning(_t("confirm.cannot_verify"))

    col1, col2, col3 = st.columns([1.2, 1.2, 1.2])

    with col1:
        _render_html(
            f'<a class="auth-gateway-link" href="/auth/login" '
            f'target="_self">{_t("confirm.sign_in")}</a> '
            f'<a class="auth-gateway-link" href="/auth/signup" '
            f'target="_self">{_t("confirm.create_account")}</a>'
        )

    with col2:
        if st.button(_t("confirm.track"), type="primary", use_container_width=True):
            navigate_to("auth_track")

    with col3:
        if st.button(_t("confirm.return_home"), use_container_width=True):
            navigate_to("landing")


# ==============================================================================
# AUTHENTICATION HELPERS
# ==============================================================================

def _current_user() -> Optional[Dict[str, Any]]:
    """Validates the request cookie and loads the user's current database role."""
    try:
        user = auth_sessions.current_user_from_cookies(st.context.cookies)
    except sqlite3.Error:
        st.error(
            "Your sign-in could not be verified right now. Refresh the page "
            "or try again later."
        )
        return None
    return user if isinstance(user, dict) else None


def _require_role(allowed_roles: List[str]) -> bool:
    """Checks whether the current session has an allowed role."""
    user = _current_user()

    if not user:
        st.warning("Please sign in to access this page.")
        _render_html(
            '<a class="auth-gateway-link" href="/auth/login" '
            'target="_self">Go to sign in</a>'
        )
        return False

    if user.get("role") not in allowed_roles:
        st.error("You do not have permission to access this page.")
        return False

    return True


def _safe_error_message(error: Exception) -> str:
    """Logs only an exception type and returns a path/record-safe message."""
    _LOGGER.warning("Request failed (%s).", type(error).__name__)
    return "Unable to complete the request right now. Please try again."


def render_application_root() -> None:
    """Routes a validated session from the root to its role dashboard."""
    user = _current_user()
    if user is None:
        render_landing_page()
        return

    dashboard_by_role = {
        "citizen": "citizen_dashboard",
        "police": "police_dashboard",
        "admin": "admin_dashboard",
    }
    dashboard = dashboard_by_role.get(user.get("role"))
    if dashboard is None:
        st.error("This account does not have an available dashboard.")
        _render_html(
            '<a class="auth-gateway-link" href="/auth/login" '
            'target="_self">Return to sign in</a>'
        )
        return

    navigate_to(dashboard)


# ==============================================================================
# SIGN-IN PAGE
# ==============================================================================

def render_auth_login() -> None:
    """Redirects the Streamlit login route to the same-origin auth gateway."""
    _render_html(
        '<meta http-equiv="refresh" content="0;url=/auth/login">'
        '<p>Opening the sign-in form…</p>'
        '<p><a href="/auth/login" target="_self">Continue to sign in</a></p>'
    )


# ==============================================================================
# ACCOUNT REGISTRATION
# ==============================================================================

def render_auth_signup() -> None:
    """Redirects the Streamlit registration route to the same-origin gateway."""
    _render_html(
        '<meta http-equiv="refresh" content="0;url=/auth/signup">'
        '<p>Opening the account registration form…</p>'
        '<p><a href="/auth/signup" target="_self">Continue to registration</a></p>'
    )


# ==============================================================================
# COMPLAINT TRACKING
# ==============================================================================

def _trusted_public_lookup_client_address(
    forwarded_for: Optional[str],
    trust_proxy: bool,
) -> str:
    """Returns a proxy-provided client IP, or a shared fail-closed identity."""
    if not trust_proxy or not forwarded_for:
        return "unattributed-client"

    # Caddy and the included Nginx config append the connecting peer to the
    # right of X-Forwarded-For. Only the final value is used, so a client
    # supplied value to the left cannot choose a fresh rate-limit bucket.
    candidate = forwarded_for.rsplit(",", 1)[-1].strip()
    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        return "unattributed-client"


def _public_lookup_client_key() -> str:
    """Builds a keyed digest from the trusted reverse-proxy client address."""
    trust_proxy = (
        os.environ.get("FIR_AUTH_TRUST_PROXY", "false").strip().lower()
        == "true"
    )
    forwarded_for = None
    if trust_proxy:
        try:
            forwarded_for = st.context.headers.get("X-Forwarded-For")
        except (AttributeError, RuntimeError):
            forwarded_for = None
    address = _trusted_public_lookup_client_address(
        forwarded_for,
        trust_proxy,
    )
    return otp_service.hash_public_lookup_client(
        otp_service.get_otp_secret(),
        address,
    )


def render_auth_track() -> None:
    """Allows a citizen to enter a complaint reference for tracking."""
    st.markdown(f"## {_t('track.title')}")
    st.write(_t("track.instructions"))

    with st.form("track_complaint_form"):
        reference = st.text_input(_t("track.reference"))
        contact = st.text_input(_t("track.contact"))

        submitted = st.form_submit_button(
            _t("track.check"),
            type="primary",
            use_container_width=True,
        )

    if submitted:
        if not reference.strip() or not contact.strip():
            st.error(_t("track.required"))
        else:
            try:
                retry_after = database.reserve_public_complaint_lookup(
                    _public_lookup_client_key()
                )
            except (sqlite3.Error, ValueError):
                _LOGGER.exception(
                    "Public complaint lookup limit could not be checked."
                )
                st.error(_t("track.unavailable"))
            else:
                if retry_after is not None:
                    st.error(
                        _t("track.limited", seconds=retry_after)
                    )
                else:
                    try:
                        complaint = database.get_complaint_by_reference(
                            reference,
                            contact,
                        )
                    except (sqlite3.Error, database.AuthorizationError):
                        _LOGGER.exception("Public complaint status lookup failed.")
                        st.error(_t("track.operation_failed"))
                    else:
                        if not complaint:
                            st.error(_t("track.no_match"))
                        else:
                            user = _current_user()
                            if user and user.get("role") == "citizen":
                                try:
                                    linked, link_message = database.link_complaint_to_citizen(
                                        reference_no=complaint["reference_no"],
                                        contact_number=contact,
                                        citizen_user_id=user["id"],
                                    )
                                except (sqlite3.Error, database.AuthorizationError):
                                    _LOGGER.exception("Complaint could not be linked to the signed-in citizen.")
                                    st.error(_t("track.operation_failed"))
                                else:
                                    if linked:
                                        st.info(_t("track.linked"))
                            st.success(_t("track.found"))
                            st.markdown(f"### {escape(complaint['reference_no'])}")
                            st.write(f"{_t('track.complaint_status')}: {translate_status(complaint['status'], st.session_state.get('selected_language', 'en'))}")
                            st.write(f"{_t('track.draft_status')}: {translate_status(complaint['fir_status'], st.session_state.get('selected_language', 'en'))}")
                            st.caption(_t("track.notice"))

    if st.button(_t("track.back"), use_container_width=True):
        navigate_to("landing")

# ==============================================================================
# CITIZEN DASHBOARD
# ==============================================================================

def render_citizen_dashboard() -> None:
    """Displays the citizen's dashboard."""
    lang = st.session_state.get("selected_language", "en")
    if not _require_role(["citizen"]):
        return

    user = _current_user()
    if user is None:
        st.error(_t("dashboard.unavailable"))
        return

    st.markdown(f"## {_t('dashboard.title')}")
    st.write(_t("dashboard.welcome", name=escape(str(user.get("full_name", "Citizen")))))
    if st.button(_t("dashboard.refresh")):
        st.rerun()

    try:
        try:
            complaints = database.get_complaints_for_citizen(
                user["id"],
                requesting_user_id=user["id"],
            )
        except database.AuthorizationError:
            st.error(_t("dashboard.revoked"))
            return
    except (sqlite3.Error, database.AuthorizationError) as exc:
        _LOGGER.exception("Citizen complaints could not be loaded.")
        st.error(_t("dashboard.operation_failed"))
        complaints = []

    if not complaints:
        st.info(_t("dashboard.empty"))
    else:
        st.markdown(f"### {_t('dashboard.complaints')}")
        for complaint in complaints:
            with st.container(border=True):
                reference = str(complaint["reference_no"])
                st.markdown(f"### {escape(reference)}")
                st.write(f"{_t('dashboard.category')}: {translate_category(complaint['category'], lang)}")
                st.write(f"{_t('dashboard.date')}: {complaint['incident_date']}")
                st.write(f"{_t('dashboard.location')}: {complaint['incident_location']}")
                st.write(f"{_t('dashboard.complaint_status')}: {translate_status(complaint['status'], lang)}")
                st.write(f"{_t('dashboard.draft_status')}: {translate_status(complaint['fir_status'], lang)}")

                try:
                    draft = database.get_latest_fir_draft(
                        complaint["id"],
                        actor_user_id=user["id"],
                    )
                except (sqlite3.Error, database.AuthorizationError):
                    _LOGGER.exception("Citizen draft could not be loaded.")
                    st.error(_t("dashboard.operation_failed"))
                    draft = None

                if draft:
                    st.caption(_t("dashboard.template_notice"))
                    with st.expander(_t("dashboard.view_draft")):
                        st.text(draft["draft_content_ml"])

                    try:
                        downloadable_draft = (
                            database.get_approved_fir_draft_for_citizen(
                                complaint_id=complaint["id"],
                                citizen_user_id=user["id"],
                            )
                        )
                    except (sqlite3.Error, database.AuthorizationError):
                        _LOGGER.exception("Approved citizen draft could not be loaded.")
                        st.error(_t("dashboard.operation_failed"))
                        downloadable_draft = None

                    if downloadable_draft:
                        st.download_button(
                            _t("dashboard.download"),
                            data=downloadable_draft["draft_content_ml"],
                            file_name=f"{reference}-fir-draft.txt",
                            mime="text/plain; charset=utf-8",
                            key=f"download_fir_{complaint['id']}",
                        )
                    else:
                        st.info(_t("dashboard.download_locked"))

    if st.button(_t("dashboard.submit_another"), type="primary"):
        reset_intake()
        navigate_to("language_select")


# ==============================================================================
# POLICE DASHBOARD
# ==============================================================================

def render_police_dashboard() -> None:
    """Displays the police complaint review workspace."""
    if not _require_role(["police"]):
        return

    reviewer = _current_user()
    if reviewer is None:
        st.error("The reviewer session is unavailable. Please sign in again.")
        return

    st.markdown("## Police review workspace")
    st.write(
        "Review submitted complaints and update Malayalam FIR drafts."
    )
    st.caption(
        "Reviewer identity and authority are not independently verified."
    )

    try:
        cases = database.get_all_complaints_for_police(
            police_user_id=reviewer["id"],
        )
    except (sqlite3.Error, database.AuthorizationError) as exc:
        st.error(_safe_error_message(exc))
        return

    review_feedback = st.session_state.pop("police_review_feedback", None)
    if review_feedback:
        st.error(review_feedback)

    tab_queue, tab_case, tab_fir = st.tabs(
        ["Complaint queue", "Case details", "FIR drafting"],
        key="police_dashboard_tabs",
        on_change="rerun",
    )

    with tab_queue:
        st.markdown("### Submitted complaints")
        if not cases:
            st.info("There are no submitted complaints to review.")
        else:
            queue_rows = [
                {
                    "Reference": case["reference_no"],
                    "Complainant": case["complainant_name"],
                    "Category": case["category"],
                    "Incident date": case["incident_date"],
                    "Status": case["status"],
                    "FIR draft": case["fir_status"],
                }
                for case in cases
            ]
            st.dataframe(
                queue_rows,
                use_container_width=True,
                hide_index=True,
            )

            case_by_label = {
                (
                    f"{case['reference_no']} — {case['complainant_name']} "
                    f"({case['category']})"
                ): case["id"]
                for case in cases
            }
            selected_label = st.selectbox(
                "Choose a complaint to inspect",
                list(case_by_label),
                index=None,
                placeholder="Select a submitted complaint",
                key="police_queue_selection",
            )
            st.button(
                "Inspect & Review",
                type="primary",
                key="inspect_police_case",
                on_click=_open_police_case,
                args=(case_by_label.get(selected_label),),
            )

    case_id = st.session_state.get("active_police_case_id")
    active_case = None
    case_lookup_failed = False
    if case_id is not None:
        try:
            active_case = database.get_complaint_by_id(
                int(case_id),
                actor_user_id=reviewer["id"],
            )
        except (sqlite3.Error, database.AuthorizationError) as exc:
            st.error(_safe_error_message(exc))
            case_lookup_failed = True
        if active_case is None and not case_lookup_failed:
            st.session_state["active_police_case_id"] = None
            st.error(
                "The selected complaint could not be found. Select another "
                "complaint from the queue."
            )

    with tab_case:
        st.markdown("### Case details")
        if not active_case:
            st.info(
                "Select a submitted complaint in the queue, then choose "
                "Inspect & Review."
            )
        else:
            _render_case_summary(active_case)
            st.markdown(f"**Complainant:** {escape(active_case['complainant_name'])}")
            st.markdown(f"**Contact:** {escape(active_case['contact_number'])}")
            st.markdown(f"**Incident time:** {escape(active_case['incident_time'] or 'Not provided')}")
            st.text_area(
                "Original complaint",
                value=active_case["description"],
                height=180,
                disabled=True,
                key=f"police_original_{active_case['id']}",
            )
            if active_case.get("additional_info"):
                st.text_area(
                    "Additional information",
                    value=active_case["additional_info"],
                    height=100,
                    disabled=True,
                    key=f"police_additional_{active_case['id']}",
                )

    with tab_fir:
        st.markdown("### Malayalam FIR draft")
        if not active_case:
            st.info(
                "Select a submitted complaint in the queue before reviewing "
                "its draft."
            )
        else:
            try:
                draft = database.get_latest_fir_draft(
                    active_case["id"],
                    actor_user_id=reviewer["id"],
                )
            except (sqlite3.Error, database.AuthorizationError) as exc:
                st.error(_safe_error_message(exc))
                draft = None

            if not draft:
                st.warning("No FIR draft is stored for this complaint.")
            else:
                approval_feedback = st.session_state.get(
                    "police_draft_action_feedback"
                )
                if (
                    approval_feedback
                    and approval_feedback.get("complaint_id")
                    == active_case["id"]
                ):
                    st.error(approval_feedback["message"])

                st.caption(
                    "Prepared from the submitted complaint using a fixed "
                    "template; no AI model is used."
                )
                _render_html(_status_pill(draft["status"]))
                st.write(f"Current draft status: {draft['status']}")
                is_approved = (
                    bool(active_case.get("is_approved"))
                    and draft.get("status") == "Approved"
                )
                if is_approved:
                    st.success(
                        "Draft approved in this application's review process. "
                        "This does not constitute official FIR registration."
                    )
                draft_text = st.text_area(
                    "Editable Malayalam FIR draft",
                    value=draft["draft_content_ml"],
                    height=420,
                    key=f"police_draft_{active_case['id']}_{draft['id']}",
                )
                reviewer_notes = st.text_area(
                    "Reviewer comments",
                    value=draft.get("reviewer_notes") or "",
                    key=f"police_notes_{active_case['id']}_{draft['id']}",
                )
                reviewer_id = reviewer["id"]
                review_confirmed = st.checkbox(
                    "I have reviewed the draft and its complaint facts.",
                    key=f"confirm_review_{active_case['id']}_{draft['id']}",
                )
                if not review_confirmed and not is_approved:
                    st.caption(
                        "Confirm your review before approving this draft."
                    )

                if st.button(
                    "Save Changes",
                    key=f"save_draft_{active_case['id']}",
                ):
                    try:
                        saved = database.review_fir_draft(
                            complaint_id=active_case["id"],
                            reviewer_user_id=reviewer_id,
                            decision="save",
                            draft_content_ml=draft_text,
                            reviewer_notes=reviewer_notes,
                        )
                    except (sqlite3.Error, database.AuthorizationError) as exc:
                        st.error(_safe_error_message(exc))
                    else:
                        if saved:
                            st.success("Draft changes saved; the draft remains pending review.")
                        else:
                            st.error("The draft could not be saved.")

                action_col1, action_col2 = st.columns(2)
                with action_col1:
                    if st.button(
                        "FIR Draft Approved" if is_approved else "Approve FIR Draft",
                        type="primary",
                        disabled=not review_confirmed or is_approved,
                        key=f"approve_draft_{active_case['id']}",
                    ):
                        st.session_state.pop(
                            "police_draft_action_feedback",
                            None,
                        )
                        try:
                            approved = database.review_fir_draft(
                                complaint_id=active_case["id"],
                                reviewer_user_id=reviewer_id,
                                decision="approve",
                                draft_content_ml=draft_text,
                                reviewer_notes=reviewer_notes
                                or "Approved in the application review process.",
                            )
                            approved_case = database.get_complaint_by_id(
                                active_case["id"],
                                actor_user_id=reviewer_id,
                            )
                            approved_draft = database.get_latest_fir_draft(
                                active_case["id"],
                                actor_user_id=reviewer_id,
                            )
                            approval_persisted = (
                                approved
                                and approved_case is not None
                                and bool(approved_case.get("is_approved"))
                                and approved_case.get("fir_status") == "Approved"
                                and approved_draft is not None
                                and approved_draft.get("status") == "Approved"
                            )
                            if not approval_persisted:
                                st.session_state[
                                    "police_draft_action_feedback"
                                ] = {
                                    "complaint_id": active_case["id"],
                                    "message": (
                                        "Approval was not saved. The current "
                                        "database status is not approved; "
                                        "check the status and try again."
                                    ),
                                }
                                st.rerun()
                        except (sqlite3.Error, database.AuthorizationError) as exc:
                            st.session_state[
                                "police_draft_action_feedback"
                            ] = {
                                "complaint_id": active_case["id"],
                                "message": (
                                    "Approval could not be confirmed. Check "
                                    "the current saved status before trying "
                                    "again. "
                                    f"{_safe_error_message(exc)}"
                                ),
                            }
                            st.rerun()
                        else:
                            st.rerun()

                with action_col2:
                    if st.button(
                        "Return for Correction",
                        key=f"return_draft_{active_case['id']}",
                    ):
                        if not reviewer_notes.strip():
                            st.error("Enter a reason before returning the draft.")
                        else:
                            try:
                                returned = database.review_fir_draft(
                                    complaint_id=active_case["id"],
                                    reviewer_user_id=reviewer_id,
                                    decision="return",
                                    draft_content_ml=draft_text,
                                    reviewer_notes=reviewer_notes,
                                )
                            except (sqlite3.Error, database.AuthorizationError) as exc:
                                st.error(_safe_error_message(exc))
                            else:
                                if returned:
                                    st.success("Draft returned for correction.")
                                    st.rerun()
                                else:
                                    st.error("The draft could not be returned.")


def _open_police_case(complaint_id: Optional[int]) -> None:
    """Stores the selected complaint and opens its case-detail tab."""
    if complaint_id is None:
        st.session_state["police_review_feedback"] = (
            "Select a submitted complaint before choosing Inspect & Review."
        )
        return

    st.session_state["active_police_case_id"] = complaint_id
    st.session_state["police_dashboard_tabs"] = "Case details"


# ==============================================================================
# POLICE REVIEW HELPERS
# ==============================================================================

def _format_case_status(status: Any) -> str:
    """Formats a case status for display."""
    if status is None:
        return "Unknown"

    value = str(status).strip().replace("_", " ").replace("-", " ")
    return value.title() if value else "Unknown"


def _status_pill(status: Any) -> str:
    """Returns a small HTML status label."""
    value = str(status or "").strip().lower()

    css_class = {
        "submitted": "pill-submitted",
        "pending": "pill-submitted",
        "under review": "pill-review",
        "under_review": "pill-review",
        "approved": "pill-approved",
        "fir approved": "pill-approved",
        "returned": "pill-returned",
        "returned for correction": "pill-returned",
        "rejected": "pill-returned",
        "pending police approval": "pill-review",
    }.get(value, "pill-locked")

    label = escape(_format_case_status(status))

    return (
        f'<span class="status-pill {css_class}">'
        f"{label}</span>"
    )


def _render_case_summary(case: Dict[str, Any]) -> None:
    """Renders a safe summary of a case record."""
    st.markdown("#### Complaint summary")

    fields = [
        ("reference_no", "Reference number"),
        ("category", "Category"),
        ("incident_date", "Incident date"),
        ("incident_location", "Location"),
        ("status", "Status"),
    ]

    for key, label in fields:
        value = case.get(key, "")
        st.markdown(f"**{label}:** {_safe_display(value)}")


# ==============================================================================
# ADMINISTRATOR DASHBOARD
# ==============================================================================

def _admin_role_update_feedback(
    user_id: int,
    requested_role: str,
    admin_user_id: int,
) -> Dict[str, str]:
    """Returns feedback only after reading the confirmed database role."""
    try:
        users = database.get_all_users(admin_user_id=admin_user_id)
        target = next((user for user in users if user["id"] == user_id), None)
        if target is None:
            return {
                "level": "error",
                "message": "The selected account could not be found.",
            }
        if target["role"] == requested_role:
            return {
                "level": "info",
                "message": (
                    "No role change was needed. The account already has the "
                    f"role: {target['role']}."
                ),
            }

        updated = database.update_user_role(
            user_id=user_id,
            new_role=requested_role,
            admin_user_id=admin_user_id,
        )
        confirmed_users = database.get_all_users(admin_user_id=admin_user_id)
        confirmed = next(
            (user for user in confirmed_users if user["id"] == user_id),
            None,
        )
        if confirmed is None:
            return {
                "level": "error",
                "message": "The role update could not be confirmed. Refresh and try again.",
            }
        if updated and confirmed["role"] == requested_role:
            return {
                "level": "success",
                "message": (
                    "Role updated successfully. The account now has the "
                    f"role: {confirmed['role']}."
                ),
            }
        if confirmed["role"] == requested_role:
            return {
                "level": "info",
                "message": (
                    "No role change was needed. The account already has the "
                    f"role: {confirmed['role']}."
                ),
            }
        return {
            "level": "error",
            "message": (
                "The role update was not applied. The account remains assigned "
                f"the role: {confirmed['role']}."
            ),
        }
    except (sqlite3.Error, database.AuthorizationError) as exc:
        return {"level": "error", "message": _safe_error_message(exc)}
    except Exception as exc:
        return {"level": "error", "message": _safe_error_message(exc)}


def render_admin_dashboard() -> None:
    """Displays administrative controls and system status."""
    if not _require_role(["admin"]):
        return

    admin = _current_user()
    if admin is None:
        st.error("The administrator session is unavailable. Please sign in again.")
        return

    st.markdown("## Administration")
    st.write(
        "Review user access, audit records, and application subsystem status."
    )

    tab_users, tab_audit, tab_health = st.tabs(
        ["User management", "Audit logs", "Platform health"]
    )

    with tab_users:
        st.markdown("### User management")
        try:
            users = database.get_all_users(admin_user_id=admin["id"])
        except (sqlite3.Error, database.AuthorizationError) as exc:
            st.error(_safe_error_message(exc))
            users = []

        if users:
            st.dataframe(
                [
                    {
                        "Email": user["email"],
                        "Name": user["full_name"],
                        "Contact": user["contact_number"],
                        "Role": user["role"],
                        "Created": user["created_at"],
                    }
                    for user in users
                ],
                use_container_width=True,
                hide_index=True,
            )
            user_labels = {
                f"{user['email']} — {user['full_name']}": user["id"]
                for user in users
            }
            selected_user = st.selectbox(
                "Select an account",
                list(user_labels),
                key="admin_selected_user",
            )
            selected_role = st.selectbox(
                "Assign role",
                ["citizen", "police", "admin"],
                key="admin_new_role",
            )
            if st.button("Update role", key="admin_update_role"):
                st.session_state.pop("admin_role_update_feedback", None)
                st.session_state["admin_role_update_feedback"] = (
                    _admin_role_update_feedback(
                        user_id=user_labels[selected_user],
                        requested_role=selected_role,
                        admin_user_id=admin["id"],
                    )
                )
                st.rerun()

            role_feedback = st.session_state.get(
                "admin_role_update_feedback"
            )
            if role_feedback:
                display_feedback = {
                    "success": st.success,
                    "info": st.info,
                    "error": st.error,
                }.get(role_feedback.get("level"), st.error)
                display_feedback(
                    role_feedback.get(
                        "message",
                        "Role update could not be confirmed.",
                    )
                )
        else:
            st.info("No user records are available.")

    with tab_audit:
        st.markdown("### Audit logs")
        try:
            audit_logs = database.get_audit_logs(
                admin_user_id=admin["id"],
                limit=100,
            )
        except (sqlite3.Error, database.AuthorizationError) as exc:
            st.error(_safe_error_message(exc))
        else:
            if audit_logs:
                st.dataframe(
                    audit_logs,
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No audit events have been recorded.")

    with tab_health:
        st.markdown("#### Platform Health & Subsystems")
        if st.button("Recheck platform health", key="admin_health_recheck") or (
            "admin_platform_health_results" not in st.session_state
        ):
            try:
                st.session_state["admin_platform_health_results"] = (
                    platform_health.run_platform_health_checks()
                )
            except Exception:
                st.session_state["admin_platform_health_results"] = [{
                    "component": "Platform checks",
                    "status": "Unknown",
                    "detail": "Health checks could not be completed.",
                    "checked_at": datetime.now().astimezone().isoformat(
                        timespec="seconds"
                    ),
                }]

        for check in st.session_state.get("admin_platform_health_results", []):
            with st.container(border=True):
                name_col, status_col = st.columns([3, 1])
                with name_col:
                    st.markdown(f"**{escape(check['component'])}**")
                    st.write(check["detail"])
                    st.caption(f"Last checked: {check['checked_at']}")
                with status_col:
                    st.markdown(f"**{escape(check['status'])}**")

        st.caption(
            "Missing-person records and CCTV video processing are later "
            "roadmap milestones. Do not treat these features as implemented "
            "until their modules are integrated and tested."
        )


# ==============================================================================
# MAIN APPLICATION ROUTER
# ==============================================================================

def main() -> None:
    """Main application routing controller."""
    st.set_page_config(
        page_title="Integrated AI Surveillance and FIR Assistance System",
        page_icon="⚖️",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    init_session_state()

    page_definitions = {
        "landing": ("FIR Assistance System", render_application_root),
        "language_select": ("Choose your language", render_language_select),
        "complaint_chat": ("Complaint conversation", render_complaint_chat),
        "complaint_guided_form": ("Complaint details", render_guided_form),
        "complaint_verify": ("Review complaint", render_complaint_verify),
        "complaint_confirmed": ("Complaint submitted", render_complaint_confirmed),
        "auth_login": ("Sign in", render_auth_login),
        "auth_signup": ("Create an account", render_auth_signup),
        "auth_track": ("Track complaint", render_auth_track),
        "citizen_dashboard": ("Citizen dashboard", render_citizen_dashboard),
        "police_dashboard": ("Police review", render_police_dashboard),
        "admin_dashboard": ("Administration", render_admin_dashboard),
    }
    global _APP_PAGE_OBJECTS
    _APP_PAGE_OBJECTS = {
        route: st.Page(
            renderer,
            title=title,
            url_path=None if route == "landing" else route,
            default=route == "landing",
        )
        for route, (title, renderer) in page_definitions.items()
    }
    active_page = st.navigation(
        list(_APP_PAGE_OBJECTS.values()),
        position="hidden",
    )
    current_page = next(
        route
        for route, page in _APP_PAGE_OBJECTS.items()
        if page is active_page
    )
    st.session_state["current_page"] = current_page

    apply_custom_styles()
    render_top_navbar()
    active_page.run()


if __name__ == "__main__":
    main()
