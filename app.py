"""
app.py
------
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
  1. Minimal, editorial Landing Page (Headline, CTA, Unsplash editorial photograph).
  2. Language selection -> Focused conversational intake assistant -> Guided form fallback.
  3. Structured fact verification -> Persistent save & reference number -> Account linking.
  4. Police Review Workspace: Complaint Queue + Side-by-side fact inspection & Malayalam FIR draft review.
  5. Citizen Dashboard: Linked complaints with locked FIR download policy until police approval.
  6. Administrator Portal: Role assignment, audit logs, and module telemetry.
"""

from datetime import date, datetime
import os
from typing import List, Dict, Any, Optional
import streamlit as st

import database
from complaint_manager import (
    SUPPORTED_CATEGORIES,
    COMPLAINT_CATEGORIES,
    CHAT_STEPS,
    create_empty_complaint_slots,
    get_step_prompt,
    validate_chat_step_input,
    validate_complaint_input,
    generate_malayalam_fir_draft,
)


# ==============================================================================
# SESSION STATE INITIALIZATION
# ==============================================================================
def init_session_state() -> None:
    """Initializes session state for persistent routing and user sessions."""
    if "current_page" not in st.session_state:
        st.session_state["current_page"] = "landing"
    if "auth_user" not in st.session_state:
        st.session_state["auth_user"] = None
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
    if "active_police_case_id" not in st.session_state:
        st.session_state["active_police_case_id"] = None


def navigate_to(page: str) -> None:
    """Safely transitions between pages and triggers a rerun."""
    st.session_state["current_page"] = page
    st.rerun()


def reset_intake() -> None:
    """Resets conversational slots and chat messages."""
    lang = st.session_state.get("selected_language", "en")
    st.session_state["complaint_slots"] = create_empty_complaint_slots(lang)
    st.session_state["chat_messages"] = []
    st.session_state["chat_step_index"] = 0


# ==============================================================================
# DESIGN SYSTEM & GLOBAL CSS
# ==============================================================================
def apply_custom_styles() -> None:
    """
    Applies strict Warm Beige / Ivory / Dark Espresso / Deep Teal design tokens.
    Guarantees readable contrast everywhere and eliminates dark-mode bleed-through.
    """
    st.markdown(
        """
        <style>
        /* -------------------------------------------------------------
           1. Global Base Typography & Colors
           ------------------------------------------------------------- */
        html, body, [class*="css"], .stApp {
            background-color: #F3EBDD !important;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, 
                         "Noto Sans Malayalam", "Noto Sans Devanagari", sans-serif !important;
            color: #493A2D !important;
        }

        /* Enforce Dark Espresso on all standard textual elements */
        p, span, div, li, h1, h2, h3, h4, h5, h6, label {
            color: #493A2D !important;
        }

        /* Secondary text color */
        .text-secondary, .stCaption, small {
            color: #6B5B4D !important;
        }

        /* -------------------------------------------------------------
           2. Top Navigation Bar
           ------------------------------------------------------------- */
        .top-navbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 18px;
            background-color: #FFFCF6;
            border-bottom: 1px solid #E2D7C3;
            margin-bottom: 24px;
            border-radius: 6px;
        }

        /* -------------------------------------------------------------
           3. Content Surfaces & Cards
           ------------------------------------------------------------- */
        .editorial-card {
            background-color: #FFFCF6 !important;
            border: 1px solid #E2D7C3 !important;
            border-radius: 6px !important;
            padding: 26px !important;
            margin-bottom: 20px !important;
        }

        .auth-container {
            max-width: 460px;
            margin: 20px auto;
            background-color: #FFFCF6;
            border: 1px solid #E2D7C3;
            border-radius: 6px;
            padding: 32px;
        }

        /* -------------------------------------------------------------
           4. Form Controls & Inputs (Ivory background with dark text)
           ------------------------------------------------------------- */
        label, [data-testid="stWidgetLabel"] p, [data-testid="stWidgetLabel"] span {
            color: #493A2D !important;
            font-weight: 600 !important;
            font-size: 0.92rem !important;
        }

        .stTextInput input, 
        .stTextArea textarea, 
        .stSelectbox div[data-baseweb="select"] > div,
        input[type="text"],
        input[type="password"],
        input[type="email"] {
            background-color: #FFFCF6 !important;
            color: #493A2D !important;
            border: 1px solid #D5CCC0 !important;
            border-radius: 4px !important;
            font-size: 0.95rem !important;
        }

        .stTextInput input:focus, 
        .stTextArea textarea:focus,
        .stSelectbox div[data-baseweb="select"] > div:focus-within {
            border-color: #356B68 !important;
            box-shadow: 0 0 0 1px #356B68 !important;
            outline: none !important;
        }

        input::placeholder, textarea::placeholder {
            color: #8C7B6D !important;
            opacity: 1 !important;
        }

        /* -------------------------------------------------------------
           5. Buttons (Deep Teal Primary & Ivory Secondary)
           ------------------------------------------------------------- */
        /* Primary buttons: Deep Teal */
        button[data-testid="baseButton-primary"],
        button[data-testid="stBaseButton-primary"],
        button[kind="primary"],
        .stButton > button[kind="primary"],
        div[data-testid="stFormSubmitButton"] > button[kind="primary"],
        div[data-testid="stFormSubmitButton"] > button {
            background-color: #356B68 !important;
            border: 1px solid #356B68 !important;
            color: #FFFCF6 !important;
            font-weight: 600 !important;
            border-radius: 4px !important;
            padding: 8px 18px !important;
        }

        button[data-testid="baseButton-primary"] *,
        button[data-testid="stBaseButton-primary"] *,
        button[kind="primary"] *,
        div[data-testid="stFormSubmitButton"] > button * {
            color: #FFFCF6 !important;
        }

        button[data-testid="baseButton-primary"]:hover,
        button[data-testid="stBaseButton-primary"]:hover,
        button[kind="primary"]:hover,
        div[data-testid="stFormSubmitButton"] > button:hover {
            background-color: #275250 !important;
            border-color: #275250 !important;
            color: #FFFCF6 !important;
        }

        /* Secondary buttons: Ivory surface with espresso text */
        button[data-testid="baseButton-secondary"],
        button[data-testid="stBaseButton-secondary"],
        button[kind="secondary"],
        .stButton > button {
            background-color: #FFFCF6 !important;
            border: 1px solid #D5CCC0 !important;
            color: #493A2D !important;
            font-weight: 500 !important;
            border-radius: 4px !important;
        }

        button[data-testid="baseButton-secondary"] *,
        button[data-testid="stBaseButton-secondary"] *,
        .stButton > button * {
            color: #493A2D !important;
        }

        button[data-testid="baseButton-secondary"]:hover,
        button[data-testid="stBaseButton-secondary"]:hover,
        .stButton > button:hover {
            background-color: #F3EBDD !important;
            border-color: #356B68 !important;
            color: #356B68 !important;
        }

        /* -------------------------------------------------------------
           6. Chat Conversation Bubbles & Input
           ------------------------------------------------------------- */
        [data-testid="stChatMessage"] {
            background-color: #FFFCF6 !important;
            border: 1px solid #E2D7C3 !important;
            border-radius: 8px !important;
            padding: 14px 18px !important;
            margin-bottom: 12px !important;
        }

        [data-testid="stChatMessage"] * {
            color: #493A2D !important;
        }

        [data-testid="stChatInput"] {
            background-color: #FFFCF6 !important;
            border: 1px solid #C4B6A3 !important;
            border-radius: 6px !important;
        }

        [data-testid="stChatInput"] textarea {
            background-color: #FFFCF6 !important;
            color: #493A2D !important;
            font-size: 0.95rem !important;
        }

        [data-testid="stChatInput"] textarea::placeholder {
            color: #8C7B6D !important;
        }

        [data-testid="stChatInput"] button {
            color: #356B68 !important;
        }

        /* -------------------------------------------------------------
           7. Status Indicators, Callouts & Expanders
           ------------------------------------------------------------- */
        .status-pill {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 0.82rem;
            font-weight: 600;
        }
        .pill-submitted { background-color: #E6EDE8; color: #68745B !important; border: 1px solid #C4D3C7; }
        .pill-review { background-color: #F8EFE4; color: #A66E38 !important; border: 1px solid #E8D3BA; }
        .pill-approved { background-color: #E2ECEB; color: #356B68 !important; border: 1px solid #ADC7C5; }
        .pill-returned { background-color: #FAECEB; color: #A64B43 !important; border: 1px solid #E4B5B1; }
        .pill-locked { background-color: #EDE8DE; color: #73695C !important; border: 1px solid #D5CCC0; }

        div[data-testid="stAlert"] {
            border-radius: 6px !important;
            padding: 12px 16px !important;
        }

        [data-testid="stExpander"] {
            background-color: #FFFCF6 !important;
            border: 1px solid #E2D7C3 !important;
            border-radius: 6px !important;
            margin-bottom: 12px !important;
        }

        [data-testid="stExpander"] summary {
            color: #493A2D !important;
            font-weight: 600 !important;
        }

        /* -------------------------------------------------------------
           8. Editorial Hero Layout
           ------------------------------------------------------------- */
        .hero-title {
            font-size: 2.5rem;
            font-weight: 800;
            line-height: 1.15;
            color: #493A2D;
            margin-bottom: 14px;
            letter-spacing: -0.5px;
        }

        .hero-subtitle {
            font-size: 1.15rem;
            color: #493A2D;
            line-height: 1.55;
            margin-bottom: 24px;
        }

        .editorial-disclaimer {
            font-size: 0.82rem;
            color: #6B5B4D;
            border-top: 1px solid #E2D7C3;
            padding-top: 16px;
            margin-top: 40px;
            line-height: 1.45;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ==============================================================================
# COMPACT TOP NAVIGATION HEADER
# ==============================================================================
def render_top_navbar() -> None:
    """Renders the top navigation header with clean public-service actions."""
    auth_user = st.session_state.get("auth_user")

    nav_c1, nav_c2, nav_c3, nav_c4 = st.columns([3.8, 1.3, 1.2, 1.3])
    with nav_c1:
        st.markdown(
            """
            <div style="padding-top: 6px;">
                <span style="font-size: 1.25rem; font-weight: 800; color: #493A2D; letter-spacing: -0.5px;">
                    ⚖️ FIR Assistance System
                </span>
                <span style="font-size: 0.82rem; color: #68745B; margin-left: 8px; font-weight: 500;">
                    Public Safety Platform
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with nav_c2:
        if st.button("Track Complaint", use_container_width=True):
            navigate_to("auth_track")

    with nav_c3:
        if not auth_user:
            if st.button("Sign in", use_container_width=True):
                navigate_to("auth_login")
        else:
            role_title = auth_user["role"].title()
            if st.button(f"👤 {role_title}", use_container_width=True):
                role = auth_user["role"]
                if role == "citizen":
                    navigate_to("citizen_dashboard")
                elif role == "police":
                    navigate_to("police_dashboard")
                elif role == "admin":
                    navigate_to("admin_dashboard")

    with nav_c4:
        if not auth_user:
            if st.button("Sign up", use_container_width=True):
                navigate_to("auth_signup")
        else:
            if st.button("Sign out", use_container_width=True):
                st.session_state["auth_user"] = None
                navigate_to("landing")


# ==============================================================================
# 1. LANDING PAGE (Minimal & Editorial Hero)
# ==============================================================================
def render_landing_page() -> None:
    """Renders the minimal, editorial two-column hero landing page."""
    col_text, col_photo = st.columns([1.1, 0.9], gap="large")

    with col_text:
        st.markdown(
            """
            <div style="padding-top: 36px;">
                <h1 class="hero-title">Your voice deserves to be heard.</h1>
                <p class="hero-subtitle">
                    Get guided assistance to prepare and submit your complaint, step by step.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Primary prominent CTA in Deep Teal
        if st.button("Register Your Complaint", type="primary", use_container_width=False):
            navigate_to("language_select")

        st.markdown(
            """
            <p style="font-size: 0.90rem; color: #6B5B4D; margin-top: 14px; margin-bottom: 0;">
                You can begin without creating an account.
            </p>
            """,
            unsafe_allow_html=True,
        )

    with col_photo:
        # Editorial photograph illustrating accessible public assistance
        img_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "editorial_hero.jpg")
        if os.path.exists(img_path):
            st.image(
                img_path,
                caption="Accessible public service consultation desk.",
                use_container_width=True,
            )
        else:
            st.markdown(
                """
                <div class="editorial-card" style="text-align: center; padding: 40px 20px;">
                    <span style="font-size: 2rem;">🏛️</span>
                    <h3 style="color: #493A2D; margin-top: 8px;">Public Service Support</h3>
                    <p style="color: #6B5B4D; font-size: 0.92rem;">
                        Providing guided incident reporting and factual assistance.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown(
        """
        <div class="editorial-disclaimer">
            <strong>Operational Notice:</strong> This platform assists citizens in preparing structured complaint documentation 
            and aids authorized personnel in review. Documents generated within this system do not constitute legally filed First 
            Information Reports (FIRs) until reviewed, verified, and officially acted upon by authorized law enforcement personnel.
        </div>
        """,
        unsafe_allow_html=True,
    )


# ==============================================================================
# 2. CITIZEN COMPLAINT INTAKE WORKFLOW
# ==============================================================================
def render_language_select() -> None:
    """Step 1: Language selection before starting intake conversation."""
    col_nav, _ = st.columns([1, 4])
    with col_nav:
        if st.button("⬅️ Back"):
            navigate_to("landing")

    st.markdown(
        """
        <div class="auth-container" style="text-align: center;">
            <h2 style="color: #493A2D; margin-top: 0;">Select Your Preferred Language</h2>
            <p style="color: #6B5B4D; font-size: 0.95rem; margin-bottom: 24px;">
                Choose the language you feel most comfortable using to explain the incident.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        if st.button("English\n\n(Standard English)", use_container_width=True):
            st.session_state["selected_language"] = "en"
            reset_intake()
            navigate_to("complaint_chat")
    with c2:
        if st.button("മലയാളം\n\n(Malayalam)", use_container_width=True):
            st.session_state["selected_language"] = "ml"
            reset_intake()
            navigate_to("complaint_chat")
    with c3:
        if st.button("हिन्दी\n\n(Hindi)", use_container_width=True):
            st.session_state["selected_language"] = "hi"
            reset_intake()
            navigate_to("complaint_chat")


def render_complaint_chat() -> None:
    """Step 2: Full-screen conversational intake assistant with dark legible bubbles and fallback."""
    col_nav, col_mid, col_fallback = st.columns([1, 3, 2])
    with col_nav:
        if st.button("⬅️ Home"):
            navigate_to("landing")
    with col_mid:
        lang_names = {"en": "English", "ml": "മലയാളം (Malayalam)", "hi": "हिन्दी (Hindi)"}
        curr_lang = st.session_state.get("selected_language", "en")
        st.markdown(
            f"<div style='padding-top: 6px; font-size: 0.90rem; color: #6B5B4D;'>Language: <strong>{lang_names.get(curr_lang, 'English')}</strong></div>",
            unsafe_allow_html=True,
        )
    with col_fallback:
        # Styled as a secondary fallback action
        if st.button("Guided Form Fallback 📋", help="Switch directly to a structured form while preserving your entered facts"):
            navigate_to("complaint_guided_form")

    lang = st.session_state.get("selected_language", "en")
    step_idx = st.session_state.get("chat_step_index", 0)
    total_steps = len(CHAT_STEPS)

    # Initialize welcome message if conversation is clean
    messages = st.session_state.get("chat_messages", [])
    if not messages:
        welcome_text = get_step_prompt("welcome", lang)
        messages.append({"role": "assistant", "content": welcome_text})
        st.session_state["chat_messages"] = messages

    # Render conversation bubbles
    for msg in messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # If all steps are complete, provide clear progression
    if step_idx >= total_steps:
        st.markdown(
            """
            <div class="editorial-card" style="border-left: 4px solid #356B68; margin-top: 14px;">
                <h4 style="color: #356B68; margin-top: 0;">✅ Incident Details Gathered</h4>
                <p style="font-size: 0.92rem; color: #493A2D; margin-bottom: 12px;">
                    All required factual items have been gathered. Please proceed to the verification screen 
                    to review your facts before final confirmation.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Proceed to Review & Confirm Facts ➡️", type="primary", use_container_width=True):
            navigate_to("complaint_verify")
        return

    current_step_name = CHAT_STEPS[step_idx]

    # Category quick-select buttons if currently on the category step
    if current_step_name == "category":
        st.markdown("<p style='font-size: 0.90rem; color: #6B5B4D; margin: 8px 0 4px 0;'>Select Category:</p>", unsafe_allow_html=True)
        cat_c1, cat_c2 = st.columns(2)
        for i, cat in enumerate(SUPPORTED_CATEGORIES):
            target = cat_c1 if i % 2 == 0 else cat_c2
            with target:
                if st.button(cat, key=f"chat_cat_{i}", use_container_width=True):
                    _handle_chat_turn(cat)
                    st.rerun()

    # User message composer
    user_reply = st.chat_input("Type your response here...")
    if user_reply:
        _handle_chat_turn(user_reply)
        st.rerun()


def _handle_chat_turn(text: str) -> None:
    """Processes conversational response, validates, and updates slots."""
    step_idx = st.session_state["chat_step_index"]
    current_step = CHAT_STEPS[step_idx]
    lang = st.session_state.get("selected_language", "en")

    # Append citizen message
    st.session_state["chat_messages"].append({"role": "user", "content": text})

    # Validate step input
    is_valid, err_msg, extracted_slots = validate_chat_step_input(current_step, text)
    if not is_valid:
        err_reply = f"⚠️ {err_msg}"
        st.session_state["chat_messages"].append({"role": "assistant", "content": err_reply})
    else:
        st.session_state["complaint_slots"].update(extracted_slots)
        next_step_idx = step_idx + 1
        st.session_state["chat_step_index"] = next_step_idx

        if next_step_idx < len(CHAT_STEPS):
            next_step_name = CHAT_STEPS[next_step_idx]
            prompt = get_step_prompt(next_step_name, lang)
            st.session_state["chat_messages"].append({"role": "assistant", "content": prompt})
        else:
            done_msg = get_step_prompt("completed", lang)
            st.session_state["chat_messages"].append({"role": "assistant", "content": done_msg})


# ==============================================================================
# 3. GUIDED FORM FALLBACK (Step 3)
# ==============================================================================
def render_guided_form() -> None:
    """Renders structured fallback form that preserves any input entered in chat."""
    col_nav, _ = st.columns([1, 4])
    with col_nav:
        if st.button("⬅️ Back to Chat"):
            navigate_to("complaint_chat")

    st.markdown(
        """
        <div class="editorial-card">
            <h3 style="color: #493A2D; margin-top: 0;">Guided Complaint Form (Direct Submission)</h3>
            <p style="color: #6B5B4D; font-size: 0.92rem; margin-bottom: 0;">
                Provide the incident details below directly. Information already collected in your conversation 
                has been preserved.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    slots = st.session_state.get("complaint_slots", {})

    with st.form("guided_complaint_form"):
        st.markdown("#### 1. Complainant Details")
        c1, c2 = st.columns(2)
        with c1:
            name_val = st.text_input("Full Name *", value=slots.get("name", ""))
        with c2:
            phone_val = st.text_input("Contact Phone Number *", value=slots.get("contact_number", ""))

        st.markdown("#### 2. Incident Details")
        c3, c4 = st.columns(2)
        with c3:
            curr_cat = slots.get("category", "")
            cat_idx = SUPPORTED_CATEGORIES.index(curr_cat) if curr_cat in SUPPORTED_CATEGORIES else 0
            cat_val = st.selectbox("Category *", options=SUPPORTED_CATEGORIES, index=cat_idx)
        with c4:
            date_val = st.date_input("Date of Incident *", value=date.today(), max_value=date.today())

        loc_val = st.text_input("Incident Location *", value=slots.get("location", ""))
        desc_val = st.text_area("Detailed Description *", value=slots.get("description", ""), height=140)
        extra_val = st.text_area("Additional Information (Optional)", value=slots.get("additional_info", ""), height=80)

        submitted = st.form_submit_button("Proceed to Review Facts ➡️", type="primary", use_container_width=True)
        if submitted:
            is_valid, errors = validate_complaint_input(
                name=name_val,
                contact_number=phone_val,
                category=cat_val,
                incident_date=date_val,
                location=loc_val,
                description=desc_val,
                additional_info=extra_val,
            )
            if not is_valid:
                st.error("Please correct the following fields:")
                for k, err in errors.items():
                    st.write(f"- **{k.title()}**: {err}")
            else:
                slots["name"] = name_val.strip()
                slots["contact_number"] = phone_val.strip()
                slots["category"] = cat_val
                slots["incident_date"] = date_val.isoformat()
                slots["location"] = loc_val.strip()
                slots["description"] = desc_val.strip()
                slots["additional_info"] = extra_val.strip()
                st.session_state["complaint_slots"] = slots
                navigate_to("complaint_verify")


# ==============================================================================
# 4. REVIEW & VERIFICATION SCREEN (Step 4)
# ==============================================================================
def render_complaint_verify() -> None:
    """Renders structured, editable review screen before persisting complaint."""
    st.markdown(
        """
        <div style="margin-bottom: 16px;">
            <h2 style="color: #493A2D; margin-bottom: 4px;">Review & Verify Incident Facts</h2>
            <p style="color: #6B5B4D; font-size: 0.95rem; margin-top: 0;">
                Please verify that the information below accurately reflects the incident. You can edit any field 
                before confirming submission.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    slots = st.session_state.get("complaint_slots", {})

    with st.form("verify_and_confirm_form"):
        st.markdown("#### Complainant Particulars")
        col1, col2 = st.columns(2)
        with col1:
            ver_name = st.text_input("Complainant Name *", value=slots.get("name", ""))
        with col2:
            ver_contact = st.text_input("Contact Number *", value=slots.get("contact_number", ""))

        st.markdown("#### Incident Particulars")
        col3, col4 = st.columns(2)
        with col3:
            curr_cat = slots.get("category", "")
            cat_idx = SUPPORTED_CATEGORIES.index(curr_cat) if curr_cat in SUPPORTED_CATEGORIES else 0
            ver_cat = st.selectbox("Category *", options=SUPPORTED_CATEGORIES, index=cat_idx)
        with col4:
            ver_loc = st.text_input("Incident Location *", value=slots.get("location", ""))

        ver_desc = st.text_area("Incident Description *", value=slots.get("description", ""), height=130)
        ver_extra = st.text_area("Additional Details", value=slots.get("additional_info", ""), height=70)

        c_submit, c_cancel = st.columns([2, 1])
        with c_submit:
            confirmed = st.form_submit_button("Confirm & Submit Complaint 🏛️", type="primary", use_container_width=True)
        with c_cancel:
            cancelled = st.form_submit_button("Cancel & Discard ❌", use_container_width=True)

    if cancelled:
        reset_intake()
        st.info("Complaint discarded. No information was persisted.")
        navigate_to("landing")

    if confirmed:
        is_valid, errors = validate_complaint_input(
            name=ver_name,
            contact_number=ver_contact,
            category=ver_cat,
            incident_date=date.today(),
            location=ver_loc,
            description=ver_desc,
            additional_info=ver_extra,
        )
        if not is_valid:
            st.error("Please correct the following fields before confirming:")
            for k, err in errors.items():
                st.write(f"- **{k.title()}**: {err}")
        else:
            ml_draft = generate_malayalam_fir_draft(
                complainant_name=ver_name.strip(),
                contact_number=ver_contact.strip(),
                category=ver_cat,
                incident_date=date.today().isoformat(),
                incident_location=ver_loc.strip(),
                description=ver_desc.strip(),
                additional_info=ver_extra.strip(),
            )

            auth_user = st.session_state.get("auth_user")
            user_id = auth_user["id"] if auth_user else None

            success, msg, saved_record = database.save_complaint(
                complainant_name=ver_name.strip(),
                contact_number=ver_contact.strip(),
                category=ver_cat,
                incident_date=date.today().isoformat(),
                incident_location=ver_loc.strip(),
                description=ver_desc.strip(),
                additional_info=ver_extra.strip(),
                intake_language=st.session_state.get("selected_language", "en"),
                citizen_user_id=user_id,
                draft_content_ml=ml_draft,
            )

            if success:
                st.session_state["last_submitted_ref"] = saved_record["reference_no"]
                st.session_state["last_submitted_id"] = saved_record["id"]
                reset_intake()
                navigate_to("complaint_confirmed")
            else:
                st.error(f"Persistence error: {msg}")


# ==============================================================================
# 5. SUBMISSION CONFIRMATION & ACCOUNT LINKING (Steps 5 & 6)
# ==============================================================================
def render_complaint_confirmed() -> None:
    """Renders success confirmation screen with unique reference number and account creation invite."""
    ref_no = st.session_state.get("last_submitted_ref", "CMP-UNKNOWN")

    st.markdown(
        f"""
        <div class="editorial-card" style="border-top: 4px solid #356B68;">
            <span class="status-pill pill-submitted">COMPLAINT PERSISTED</span>
            <h2 style="color: #493A2D; margin: 10px 0 6px 0;">Complaint Successfully Submitted</h2>
            <p style="font-size: 1.05rem; color: #493A2D; margin-bottom: 14px;">
                Your incident has been securely recorded with Reference Number:
            </p>
            <div style="background-color: #F3EBDD; border: 1px dashed #356B68; padding: 14px; border-radius: 4px; font-family: monospace; font-size: 1.35rem; font-weight: 700; color: #356B68; margin-bottom: 14px;">
                {ref_no}
            </div>
            <p style="font-size: 0.90rem; color: #6B5B4D; line-height: 1.45; margin-bottom: 0;">
                <strong>Important Notice:</strong> This reference identifies your submitted complaint. It does not mean an official FIR 
                has been registered. An authorized police officer will inspect the facts, verify the Malayalam FIR draft, 
                and determine formal registration.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    auth_user = st.session_state.get("auth_user")
    if not auth_user:
        st.markdown(
            """
            <div class="editorial-card">
                <h3 style="color: #493A2D; margin-top: 0;">Track Your Complaint & Receive Updates</h3>
                <p style="color: #6B5B4D; font-size: 0.92rem; margin-bottom: 18px;">
                    Create a citizen account or sign in now to link this complaint to your profile. 
                    This enables authorized case tracking, responses to officer questions, and access to approved documents.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("Create Citizen Account 📝", type="primary", use_container_width=True):
                navigate_to("auth_signup")
        with c2:
            if st.button("Sign in to Existing Account 🔑", use_container_width=True):
                navigate_to("auth_login")
        with c3:
            if st.button("Return to Home 🏠", use_container_width=True):
                navigate_to("landing")
    else:
        st.success(f"This complaint is automatically linked to your authenticated account ({auth_user['email']}).")
        if st.button("Go to Citizen Dashboard 👤", type="primary"):
            navigate_to("citizen_dashboard")


# ==============================================================================
# 6. AUTHENTICATION & SECURE COMPLAINT LINKING (Section 7)
# ==============================================================================
def render_auth_login() -> None:
    """Renders focused, professional sign-in screen without exposed credentials."""
    col_nav, _ = st.columns([1, 4])
    with col_nav:
        if st.button("⬅️ Home"):
            navigate_to("landing")

    st.markdown(
        """
        <div class="auth-container">
            <h2 style="color: #493A2D; margin-top: 0; margin-bottom: 6px;">Sign in to Your Account</h2>
            <p style="color: #6B5B4D; font-size: 0.90rem; margin-bottom: 22px;">
                Enter your registered credentials to access your authorized portal.
            </p>
        """,
        unsafe_allow_html=True,
    )

    with st.form("login_form"):
        email = st.text_input("Email Address", placeholder="Enter your registered email")
        password = st.text_input("Password", type="password", placeholder="Enter your password")

        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if submitted:
            success, msg, user = database.authenticate_user(email, password)
            if success and user:
                st.session_state["auth_user"] = user
                role = user["role"]
                st.success(f"Welcome back, {user['full_name']}!")
                if role == "citizen":
                    navigate_to("citizen_dashboard")
                elif role == "police":
                    navigate_to("police_dashboard")
                elif role == "admin":
                    navigate_to("admin_dashboard")
            else:
                st.error(msg)

    st.markdown("</div>", unsafe_allow_html=True)

    # Clean registration link
    c_link1, c_link2 = st.columns([1, 1])
    with c_link1:
        if st.button("Don't have an account? Sign up 📝"):
            navigate_to("auth_signup")
    with c_link2:
        if st.button("Need to track by reference? 🔍"):
            navigate_to("auth_track")


def render_auth_signup() -> None:
    """Renders clean, focused citizen registration screen."""
    col_nav, _ = st.columns([1, 4])
    with col_nav:
        if st.button("⬅️ Home"):
            navigate_to("landing")

    st.markdown(
        """
        <div class="auth-container">
            <h2 style="color: #493A2D; margin-top: 0; margin-bottom: 6px;">Create Citizen Account</h2>
            <p style="color: #6B5B4D; font-size: 0.90rem; margin-bottom: 22px;">
                Register to track complaints and receive authorized case status updates.
            </p>
        """,
        unsafe_allow_html=True,
    )

    with st.form("signup_form"):
        full_name = st.text_input("Full Name", placeholder="e.g., Rajesh Kumar")
        email = st.text_input("Email Address", placeholder="e.g., citizen@example.com")
        phone = st.text_input("Contact Phone Number", placeholder="e.g., +91 9447123456")
        password = st.text_input("Create Password", type="password", placeholder="Minimum 6 characters")

        submitted = st.form_submit_button("Register Account", type="primary", use_container_width=True)
        if submitted:
            success, msg, user = database.create_user(
                email=email,
                full_name=full_name,
                password=password,
                contact_number=phone,
                role="citizen",
            )
            if success and user:
                st.session_state["auth_user"] = user

                # Link last complaint if phone numbers match
                last_ref = st.session_state.get("last_submitted_ref")
                if last_ref:
                    database.link_complaint_to_citizen(last_ref, phone, user["id"])

                st.success("Account created successfully!")
                navigate_to("citizen_dashboard")
            else:
                st.error(msg)

    st.markdown("</div>", unsafe_allow_html=True)

    if st.button("Already have an account? Sign in 🔑"):
        navigate_to("auth_login")


def render_auth_track() -> None:
    """Direct complaint tracking screen requiring authentication or reference verification."""
    col_nav, _ = st.columns([1, 4])
    with col_nav:
        if st.button("⬅️ Home"):
            navigate_to("landing")

    auth_user = st.session_state.get("auth_user")
    if auth_user:
        navigate_to("citizen_dashboard")
        return

    st.markdown(
        """
        <div class="editorial-card" style="max-width: 600px; margin: 0 auto;">
            <h2 style="color: #493A2D; margin-top: 0;">Track Complaint Status</h2>
            <p style="color: #6B5B4D; font-size: 0.92rem; margin-bottom: 20px;">
                To protect citizen privacy, confidential case information is not displayed publicly. 
                Please sign in to your citizen account, or verify ownership with your registered contact number.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c_sign, c_link = st.columns(2)
    with c_sign:
        st.markdown("#### Option 1: Sign In")
        st.write("View all your linked complaints in your personal dashboard.")
        if st.button("Sign in with Password 🔑", type="primary", use_container_width=True):
            navigate_to("auth_login")

    with c_link:
        st.markdown("#### Option 2: Verify by Phone")
        with st.form("lookup_form"):
            ref_input = st.text_input("Complaint Reference No.", placeholder="e.g., CMP-20261024-XXXX")
            phone_input = st.text_input("Registered Phone Number", placeholder="e.g., +91 9447123456")
            checked = st.form_submit_button("Verify & Check Status")
            if checked:
                record = database.get_complaint_by_reference(ref_input)
                if not record:
                    st.error("Complaint reference number not found.")
                else:
                    if database.re_clean_phone(phone_input) != database.re_clean_phone(record["contact_number"]):
                        st.error("Ownership verification failed: Phone number does not match record.")
                    else:
                        st.success("Ownership verified!")
                        st.markdown(
                            f"""
                            <div class="editorial-card">
                                <h4>Reference: {record['reference_no']}</h4>
                                <p><strong>Category:</strong> {record['category']}</p>
                                <p><strong>Date:</strong> {record['incident_date']} | <strong>Location:</strong> {record['incident_location']}</p>
                                <p><strong>Current Status:</strong> <span class="status-pill pill-review">{record['status']}</span></p>
                                <p><strong>FIR Status:</strong> <span class="status-pill pill-locked">{record['fir_status']}</span></p>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )


# ==============================================================================
# 7. CITIZEN DASHBOARD (Section 7)
# ==============================================================================
def render_citizen_dashboard() -> None:
    """Renders citizen personal dashboard showing linked complaints."""
    auth_user = st.session_state.get("auth_user")
    if not auth_user or auth_user["role"] != "citizen":
        st.warning("Please sign in as a citizen to view this dashboard.")
        if st.button("Go to Sign In"):
            navigate_to("auth_login")
        return

    st.markdown(
        f"""
        <div style="margin-bottom: 20px;">
            <h2 style="color: #493A2D; margin-bottom: 4px;">Citizen Case Dashboard</h2>
            <p style="color: #6B5B4D; font-size: 0.95rem; margin-top: 0;">
                Logged in as <strong>{auth_user['full_name']}</strong> ({auth_user['email']})
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("🔗 Link an Unlinked Complaint by Reference Number"):
        with st.form("link_form"):
            l_ref = st.text_input("Complaint Reference No.", placeholder="e.g., CMP-20261024-XXXX")
            l_phone = st.text_input("Registered Contact Phone", value=auth_user.get("contact_number", ""))
            if st.form_submit_button("Verify & Link to My Account"):
                success, msg = database.link_complaint_to_citizen(l_ref, l_phone, auth_user["id"])
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    complaints = database.get_complaints_for_citizen(auth_user["id"])
    if not complaints:
        st.markdown(
            """
            <div class="editorial-card" style="text-align: center; padding: 40px;">
                <h3 style="color: #493A2D;">No Linked Complaints Found</h3>
                <p style="color: #6B5B4D; font-size: 0.92rem; margin-bottom: 20px;">
                    You do not currently have any complaints associated with this account.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Register a New Complaint 🚀", type="primary"):
            navigate_to("language_select")
        return

    st.markdown(f"#### Your Registered Cases ({len(complaints)})")
    for item in complaints:
        with st.expander(f"Case {item['reference_no']} — {item['category']} ({item['incident_date']})"):
            c1, c2 = st.columns(2)
            with c1:
                st.write(f"**Complainant:** {item['complainant_name']}")
                st.write(f"**Contact Number:** {item['contact_number']}")
            with c2:
                st.write(f"**Incident Date:** {item['incident_date']}")
                st.write(f"**Incident Location:** {item['incident_location']}")

            st.write("**Submitted Facts:**")
            st.text_area("Description", value=item["description"], height=80, disabled=True, key=f"cit_desc_{item['id']}")

            st.write(f"**Current Status:** `{item['status']}`")
            st.write(f"**FIR Status:** `{item['fir_status']}`")

            # FIR Download policy
            if not item.get("is_approved"):
                st.markdown(
                    "<span class='status-pill pill-locked'>🔒 FIR Download Locked</span>",
                    unsafe_allow_html=True,
                )
                st.button(
                    "Download Official FIR (PDF)",
                    disabled=True,
                    key=f"dl_locked_{item['id']}",
                    help="The official FIR draft download will be unlocked only after police review and approval.",
                )
                st.caption("Official FIR download requires station review and approval.")
            else:
                st.markdown(
                    "<span class='status-pill pill-approved'>✅ FIR Approved by Police</span>",
                    unsafe_allow_html=True,
                )
                draft = database.get_latest_fir_draft(item["id"])
                draft_content = draft["draft_content_ml"] if draft else "FIR Record"
                st.download_button(
                    "📥 Download Approved FIR (Official Document)",
                    data=draft_content,
                    file_name=f"Approved_FIR_{item['reference_no']}.txt",
                    key=f"dl_app_{item['id']}",
                )

    st.markdown("---")
    if st.button("Register Another Incident 🚀", type="primary"):
        navigate_to("language_select")


# ==============================================================================
# 8. POLICE REVIEW PORTAL (Sections 8 & 9)
# ==============================================================================
def render_police_dashboard() -> None:
    """Renders police officer complaint queue and side-by-side FIR review."""
    auth_user = st.session_state.get("auth_user")
    if not auth_user or auth_user["role"] != "police":
        st.warning("Authorized police credentials required to access this portal.")
        if st.button("Go to Sign In"):
            navigate_to("auth_login")
        return

    active_case_id = st.session_state.get("active_police_case_id")
    if active_case_id:
        render_police_fir_review(active_case_id, auth_user)
        return

    st.markdown(
        """
        <div style="margin-bottom: 16px;">
            <h2 style="color: #493A2D; margin-bottom: 2px;">Police Complaint Queue</h2>
            <p style="color: #6B5B4D; font-size: 0.95rem; margin-top: 0;">
                Prioritized queue of citizen complaints awaiting review, fact inspection, and FIR drafting.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_search, col_status, col_cat = st.columns([2, 1, 1])
    with col_search:
        search_kw = st.text_input("🔍 Search Reference, Name, Location", placeholder="e.g., CMP- or Aluva")
    with col_status:
        status_opts = ["All Statuses", "Submitted", "Pending Review", "Under Review", "More Information Required", "Accepted for Further Processing", "Closed"]
        sel_status = st.selectbox("Status Filter", options=status_opts)
    with col_cat:
        cat_opts = ["All Categories"] + SUPPORTED_CATEGORIES
        sel_cat = st.selectbox("Category Filter", options=cat_opts)

    complaints = database.get_all_complaints_for_police(
        status_filter=sel_status,
        category_filter=sel_cat,
        search_query=search_kw,
    )

    if not complaints:
        st.info("No complaint records match the selected queue criteria.")
        return

    st.markdown(f"**Cases in Queue:** {len(complaints)}")
    for case in complaints:
        with st.container():
            st.markdown(
                f"""
                <div class="editorial-card" style="padding: 16px; margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: 700; color: #493A2D; font-size: 1.05rem;">
                            Case {case['reference_no']} — {case['category']}
                        </span>
                        <span>
                            <span class="status-pill pill-review">{case['status']}</span>
                            <span class="status-pill pill-locked">{case['fir_status']}</span>
                        </span>
                    </div>
                    <div style="margin-top: 8px; font-size: 0.90rem; color: #493A2D;">
                        <strong>Complainant:</strong> {case['complainant_name']} ({case['contact_number']}) | 
                        <strong>Date:</strong> {case['incident_date']} | 
                        <strong>Location:</strong> {case['incident_location']}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            col_rev, _ = st.columns([1.5, 4])
            with col_rev:
                if st.button("Inspect & Review FIR Draft 🔍", key=f"rev_{case['id']}", type="primary"):
                    st.session_state["active_police_case_id"] = case["id"]
                    st.rerun()


def render_police_fir_review(complaint_id: int, officer_user: Dict[str, Any]) -> None:
    """Side-by-side review layout (Left: Confirmed facts, Right: Editable Malayalam FIR draft)."""
    case = database.get_complaint_by_id(complaint_id)
    if not case:
        st.error("Case not found.")
        st.session_state["active_police_case_id"] = None
        st.rerun()
        return

    col_back, col_title = st.columns([1, 4])
    with col_back:
        if st.button("⬅️ Back to Queue"):
            st.session_state["active_police_case_id"] = None
            st.rerun()
    with col_title:
        st.subheader(f"Case Review: {case['reference_no']}")

    latest_draft = database.get_latest_fir_draft(complaint_id)
    current_ml_draft = latest_draft["draft_content_ml"] if latest_draft else generate_malayalam_fir_draft(
        complainant_name=case["complainant_name"],
        contact_number=case["contact_number"],
        category=case["category"],
        incident_date=case["incident_date"],
        incident_location=case["incident_location"],
        description=case["description"],
        incident_time=case.get("incident_time", ""),
        additional_info=case.get("additional_info", ""),
        reference_no=case["reference_no"],
    )

    col_facts, col_draft = st.columns([1, 1], gap="medium")

    with col_facts:
        st.markdown(
            f"""
            <div class="editorial-card">
                <h4 style="color: #493A2D; margin-top: 0; border-bottom: 1px solid #E2D7C3; padding-bottom: 8px;">
                    Left Panel: Confirmed Citizen Facts
                </h4>
                <p><strong>Complainant:</strong> {case['complainant_name']}</p>
                <p><strong>Contact Phone:</strong> {case['contact_number']}</p>
                <p><strong>Category:</strong> {case['category']}</p>
                <p><strong>Incident Date & Time:</strong> {case['incident_date']} {f"({case['incident_time']})" if case.get('incident_time') else ""}</p>
                <p><strong>Incident Location:</strong> {case['incident_location']}</p>
                <div style="background-color: #F3EBDD; padding: 10px; border-radius: 4px; margin-top: 10px;">
                    <strong>Citizen Incident Statement (Original):</strong><br>
                    <p style="white-space: pre-wrap; margin-top: 4px; font-size: 0.92rem; color: #493A2D;">{case['description']}</p>
                </div>
                {f"<p style='margin-top: 8px;'><strong>Additional Details:</strong> {case['additional_info']}</p>" if case.get('additional_info') else ""}
                <hr style="border: none; border-top: 1px solid #E2D7C3; margin: 12px 0;">
                <p><strong>Case Status:</strong> <span class="status-pill pill-review">{case['status']}</span></p>
                <p><strong>FIR Status:</strong> <span class="status-pill pill-locked">{case['fir_status']}</span></p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.expander("📜 Case Audit Trail"):
            logs = database.get_audit_logs(complaint_id=case["id"])
            for lg in logs:
                st.caption(f"{lg['timestamp']} — **{lg['action']}** by {lg.get('actor_email', 'System')}: {lg.get('details', '')}")

    with col_draft:
        st.markdown(
            """
            <div class="editorial-card">
                <h4 style="color: #356B68; margin-top: 0; border-bottom: 1px solid #E2D7C3; padding-bottom: 8px;">
                    Right Panel: Editable Malayalam FIR Draft
                </h4>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form("fir_draft_edit_form"):
            edited_ml = st.text_area(
                "Malayalam FIR Draft Content (Unicode)",
                value=current_ml_draft,
                height=340,
                help="Inspect and edit the generated Malayalam FIR draft. Names, dates, and material facts must remain consistent.",
            )
            reviewer_note = st.text_input("Reviewer Notes / Justification", placeholder="e.g., Verified statement with station duty officer.")

            c_save, c_return, c_approve = st.columns([1, 1.2, 1.2])
            with c_save:
                save_clicked = st.form_submit_button("Save Draft 💾")
            with c_return:
                return_clicked = st.form_submit_button("Return for Correction ↩️")
            with c_approve:
                approve_clicked = st.form_submit_button("Approve FIR Draft ✅", type="primary")

        if save_clicked:
            database.update_fir_draft(
                complaint_id=case["id"],
                draft_content_ml=edited_ml,
                reviewer_user_id=officer_user["id"],
                reviewer_notes=reviewer_note,
                status="Pending Police Approval",
            )
            st.success("Draft edits saved successfully.")
            st.rerun()

        if return_clicked:
            if not reviewer_note.strip():
                st.error("Please provide a reason in Reviewer Notes when returning a complaint for correction.")
            else:
                database.return_complaint_for_correction(
                    complaint_id=case["id"],
                    officer_user_id=officer_user["id"],
                    reason=reviewer_note.strip(),
                )
                st.warning("Complaint returned for correction.")
                st.rerun()

        if approve_clicked:
            database.update_fir_draft(
                complaint_id=case["id"],
                draft_content_ml=edited_ml,
                reviewer_user_id=officer_user["id"],
                reviewer_notes=reviewer_note,
                status="Approved",
            )
            database.approve_fir_draft(
                complaint_id=case["id"],
                officer_user_id=officer_user["id"],
                officer_notes=reviewer_note if reviewer_note.strip() else "Approved by Station Reviewer",
            )
            st.success("FIR draft approved! Citizen download has been unlocked.")
            st.rerun()


# ==============================================================================
# 9. ADMINISTRATOR DASHBOARD (Section 10)
# ==============================================================================
def render_admin_dashboard() -> None:
    """Renders administrative portal: role management, system telemetry, audit logs."""
    auth_user = st.session_state.get("auth_user")
    if not auth_user or auth_user["role"] != "admin":
        st.warning("Administrator credentials required.")
        if st.button("Go to Sign In"):
            navigate_to("auth_login")
        return

    st.markdown(
        """
        <div style="margin-bottom: 16px;">
            <h2 style="color: #493A2D; margin-bottom: 2px;">Administrator Control & Audit Portal</h2>
            <p style="color: #6B5B4D; font-size: 0.95rem; margin-top: 0;">
                User role governance, system telemetry, and centralized audit trail monitoring.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_users, tab_audit, tab_health = st.tabs(["User Role Management", "System Audit Logs", "Module Telemetry"])

    with tab_users:
        st.markdown("#### User Accounts & Role Assignment")
        users = database.get_all_users()
        for u in users:
            col_u1, col_u2, col_u3 = st.columns([2, 1, 1])
            with col_u1:
                st.write(f"**{u['full_name']}** ({u['email']})")
                st.caption(f"Phone: {u.get('contact_number') or 'N/A'}")
            with col_u2:
                st.write(f"Role: `{u['role']}`")
            with col_u3:
                if u["id"] != auth_user["id"]:
                    new_r = st.selectbox(
                        "Change Role",
                        options=["citizen", "police", "admin"],
                        index=["citizen", "police", "admin"].index(u["role"]),
                        key=f"role_sel_{u['id']}",
                    )
                    if st.button("Update Role", key=f"up_r_{u['id']}"):
                        database.update_user_role(u["id"], new_r, auth_user["id"])
                        st.success(f"Updated role for {u['email']} to {new_r}.")
                        st.rerun()

    with tab_audit:
        st.markdown("#### Centralized Audit Trail")
        all_logs = database.get_audit_logs(limit=100)
        for lg in all_logs:
            ref_badge = f" [Case: {lg['reference_no']}]" if lg.get("reference_no") else ""
            st.markdown(
                f"""
                <div style="background-color: #FFFCF6; border-left: 3px solid #356B68; padding: 8px 12px; margin-bottom: 8px; border-radius: 4px; font-size: 0.88rem;">
                    <strong>{lg['timestamp']}</strong> — <code>{lg['action']}</code>{ref_badge}<br>
                    <span style="color: #6B5B4D;">Actor: {lg.get('actor_email', 'System')} ({lg.get('actor_role', 'N/A')})</span><br>
                    {lg.get('details', '')}
                </div>
                """,
                unsafe_allow_html=True,
            )

    with tab_health:
        st.markdown("#### Platform Health & Subsystems")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Database Storage", "SQLite Relational (Operational)")
        with c2:
            st.metric("Complaint Intake Engine", "Multilingual Chat & Form Fallback (Operational)")
        with c3:
            st.metric("Malayalam FIR Engine", "Fact-Faithful Generator (Operational)")

        st.info("Phase 2 (Missing Person Records) and Phase 3 (CCTV Video Processing) are scheduled for subsequent roadmap milestones.")


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
    apply_custom_styles()
    render_top_navbar()

    current_page = st.session_state.get("current_page", "landing")

    if current_page == "landing":
        render_landing_page()
    elif current_page == "language_select":
        render_language_select()
    elif current_page == "complaint_chat":
        render_complaint_chat()
    elif current_page == "complaint_guided_form":
        render_guided_form()
    elif current_page == "complaint_verify":
        render_complaint_verify()
    elif current_page == "complaint_confirmed":
        render_complaint_confirmed()
    elif current_page == "auth_login":
        render_auth_login()
    elif current_page == "auth_signup":
        render_auth_signup()
    elif current_page == "auth_track":
        render_auth_track()
    elif current_page == "citizen_dashboard":
        render_citizen_dashboard()
    elif current_page == "police_dashboard":
        render_police_dashboard()
    elif current_page == "admin_dashboard":
        render_admin_dashboard()
    else:
        render_landing_page()


if __name__ == "__main__":
    main()
