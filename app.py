"""
app.py
------
Integrated AI Surveillance and FIR Assistance System
Public Safety Multi-Page Application

Features:
1. Landing Page (Default screen with system purpose, workflow, and action triggers).
2. Complaint-First Conversational Reporting (Multilingual chatbot flow: English, Malayalam, Hindi).
3. Incident Verification Screen (Document-like review before final confirmation).
4. Submission Confirmation & Account Creation Invitation.
5. Role-Based Login & Dashboards (Citizen, Police Officer, Administrator).
6. Strict adherence to BRAND_GUIDELINES.md and research prototype transparency.
"""

from datetime import date
from typing import List, Dict, Any, Optional
import streamlit as st

from complaint_manager import (
    SUPPORTED_CATEGORIES,
    COMPLAINT_CATEGORIES,
    CHAT_STEPS,
    create_empty_complaint_slots,
    get_step_prompt,
    validate_chat_step_input,
    validate_complaint_input,
    compute_submission_fingerprint,
    create_complaint_record,
)


def init_session_state() -> None:
    """Initializes session state keys for navigation, chat, and complaint tracking."""
    if "current_page" not in st.session_state:
        st.session_state["current_page"] = "landing"
    if "user_role" not in st.session_state:
        st.session_state["user_role"] = None
    if "complaints" not in st.session_state:
        st.session_state["complaints"] = []
    if "last_submission_id" not in st.session_state:
        st.session_state["last_submission_id"] = None
    if "last_submission_fingerprint" not in st.session_state:
        st.session_state["last_submission_fingerprint"] = None

    # Conversational chat state
    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = []
    if "chat_step_index" not in st.session_state:
        st.session_state["chat_step_index"] = 0
    if "complaint_slots" not in st.session_state:
        st.session_state["complaint_slots"] = create_empty_complaint_slots()
    if "is_editing_verification" not in st.session_state:
        st.session_state["is_editing_verification"] = False


def navigate_to(page_name: str) -> None:
    """Safely updates navigation page in session state."""
    st.session_state["current_page"] = page_name
    st.rerun()


def reset_chat_state() -> None:
    """Resets the complaint conversation slots and messages."""
    st.session_state["chat_messages"] = []
    st.session_state["chat_step_index"] = 0
    st.session_state["complaint_slots"] = create_empty_complaint_slots()
    st.session_state["is_editing_verification"] = False


def apply_custom_styles() -> None:
    """Applies clean, restrained CSS styling following BRAND_GUIDELINES.md."""
    st.markdown(
        """
        <style>
        /* Base typography */
        html, body, [class*="css"] {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, 
                         "Noto Sans Malayalam", "Noto Sans Devanagari", sans-serif;
            color: #1F2937;
        }

        /* Top disclaimer banner */
        .disclaimer-banner {
            background-color: #F4F6F8;
            border-left: 4px solid #17365D;
            border-top: 1px solid #D9E0E7;
            border-right: 1px solid #D9E0E7;
            border-bottom: 1px solid #D9E0E7;
            padding: 12px 16px;
            border-radius: 4px;
            font-size: 0.88rem;
            color: #1F2937;
            margin-bottom: 20px;
        }

        .disclaimer-banner strong {
            color: #17365D;
        }

        /* Content card styling */
        .app-card {
            background-color: #FFFFFF;
            border: 1px solid #D9E0E7;
            border-radius: 8px;
            padding: 22px;
            margin-bottom: 18px;
        }

        .app-card:hover {
            border-color: #315B86;
        }

        /* Hero banner on Landing Page */
        .hero-banner {
            background-color: #F8FAFC;
            border: 1px solid #D9E0E7;
            border-radius: 8px;
            padding: 28px;
            margin-bottom: 24px;
            border-top: 4px solid #17365D;
        }

        /* Workflow step box */
        .step-card {
            background-color: #FFFFFF;
            border: 1px solid #D9E0E7;
            border-radius: 6px;
            padding: 16px;
            height: 100%;
        }

        .step-number {
            display: inline-block;
            background-color: #17365D;
            color: #FFFFFF;
            font-weight: 700;
            border-radius: 50%;
            width: 26px;
            height: 26px;
            text-align: center;
            line-height: 26px;
            font-size: 0.82rem;
            margin-bottom: 8px;
        }

        /* Status badge */
        .status-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 0.82rem;
            font-weight: 600;
            margin-bottom: 8px;
        }

        .badge-pending {
            background-color: #FEF3C7;
            color: #B7791F;
            border: 1px solid #FCD34D;
        }

        .badge-info {
            background-color: #EFF6FF;
            color: #315B86;
            border: 1px solid #BFDBFE;
        }

        .badge-locked {
            background-color: #F3F4F6;
            color: #6B7280;
            border: 1px solid #E5E7EB;
        }

        /* Primary button styling */
        button[kind="primary"] {
            background-color: #17365D !important;
            border-color: #17365D !important;
            color: #FFFFFF !important;
        }
        button[kind="primary"]:hover {
            background-color: #10243A !important;
            border-color: #10243A !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header() -> None:
    """Renders the standard system header and research prototype disclaimer."""
    st.markdown(
        """
        <div style="border-bottom: 2px solid #17365D; padding-bottom: 8px; margin-bottom: 12px;">
            <h2 style="color: #17365D; margin-bottom: 2px;">
                Integrated AI Surveillance and FIR Assistance System
            </h2>
            <p style="color: #5B6573; margin-top: 0px; font-size: 0.95rem;">
                Public Safety Intelligence & Multilingual Complaint Management Platform
            </p>
        </div>
        <div class="disclaimer-banner">
            <strong>⚠️ Research Demonstration Prototype — Not an Official Police Portal</strong><br>
            This system is an operational research prototype. Submissions and AI drafts generated within this 
            environment do not represent officially registered First Information Reports (FIRs) or legal police records.
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> None:
    """Renders persistent sidebar navigation and role status."""
    with st.sidebar:
        st.markdown(
            """
            <div style="padding-bottom: 12px; border-bottom: 1px solid #D9E0E7; margin-bottom: 16px;">
                <h3 style="color: #17365D; margin-bottom: 2px;">FIR Assistance</h3>
                <span style="font-size: 0.80rem; color: #5B6573;">Integrated Surveillance & Reporting System</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("**Navigation**")
        if st.button("🏠 Home / Landing Page", use_container_width=True):
            navigate_to("landing")

        if st.button("📝 Start a Complaint (Direct Flow)", use_container_width=True):
            reset_chat_state()
            navigate_to("chat")

        if st.button("🔑 Portal Login", use_container_width=True):
            navigate_to("login")

        # Active role dashboard links
        user_role = st.session_state.get("user_role")
        if user_role:
            st.markdown("---")
            st.markdown(f"**Current Role:** `{user_role.title()}`")
            if user_role == "citizen":
                if st.button("👤 Citizen Dashboard", use_container_width=True):
                    navigate_to("citizen_dashboard")
            elif user_role == "police":
                if st.button("🛡️ Police Review Portal", use_container_width=True):
                    navigate_to("police_dashboard")
            elif user_role == "admin":
                if st.button("⚙️ Admin Dashboard", use_container_width=True):
                    navigate_to("admin_dashboard")

            if st.button("🚪 Sign Out", use_container_width=True):
                st.session_state["user_role"] = None
                navigate_to("landing")

        st.markdown("---")
        st.markdown(
            """
            <div style="font-size: 0.82rem; color: #5B6573; line-height: 1.4;">
                <p><strong>Supported Languages:</strong><br>English, മലയാളം, हिन्दी</p>
                <p><strong>FIR Download Policy:</strong><br>Available only after police review and approval.</p>
                <hr style="margin: 8px 0; border: none; border-top: 1px solid #D9E0E7;">
                <p style="font-size: 0.78rem;">
                    <em>Emergency Note:</em> In immediate life-threatening situations, dial <strong>112</strong>.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ==============================================================================
# 1. LANDING PAGE
# ==============================================================================
def render_landing_page() -> None:
    """Renders the comprehensive, user-friendly landing experience."""
    st.markdown(
        """
        <div class="hero-banner">
            <h1 style="color: #17365D; font-size: 2.1rem; margin-bottom: 8px;">
                Integrated AI Surveillance and FIR Assistance System
            </h1>
            <p style="color: #1F2937; font-size: 1.12rem; margin-bottom: 18px; line-height: 1.5;">
                A next-generation public safety platform that assists citizens in submitting structured, 
                multilingual complaints and empowers law enforcement personnel with automated 
                First Information Report (FIR) draft generation.
            </p>
            <p style="color: #5B6573; font-size: 0.95rem; margin-bottom: 0;">
                🌐 Seamlessly communicate in <strong>English</strong>, <strong>Malayalam (മലയാളം)</strong>, 
                or <strong>Hindi (हिन्दी)</strong>. No immediate account creation required for urgent reporting.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Urgent action cards
    col_start, col_login = st.columns([1.5, 1])
    with col_start:
        st.markdown(
            """
            <div class="app-card" style="border-left: 4px solid #17365D;">
                <h3 style="color: #17365D; margin-top: 0;">Report an Incident Immediately</h3>
                <p style="color: #5B6573; margin-bottom: 14px;">
                    Start our conversational complaint assistant right away. Describe what happened in your 
                    own words without waiting to create an account.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("🚀 Start a Complaint Now", type="primary", use_container_width=True):
            reset_chat_state()
            navigate_to("chat")

    with col_login:
        st.markdown(
            """
            <div class="app-card" style="border-left: 4px solid #315B86;">
                <h3 style="color: #17365D; margin-top: 0;">Portal Access</h3>
                <p style="color: #5B6573; margin-bottom: 14px;">
                    Log in as a citizen to track your case, or access authorized portals for police officers 
                    and system administrators.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        col_l1, col_l2 = st.columns(2)
        with col_l1:
            if st.button("🔑 Portal Login", use_container_width=True):
                navigate_to("login")
        with col_l2:
            if st.button("📝 Create Account", use_container_width=True):
                navigate_to("signup")

    st.markdown("---")
    st.markdown("### How the System Works")
    st.markdown(
        "A clear, 4-step workflow designed to ensure factual accuracy, citizen privacy, and police oversight:"
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            """
            <div class="step-card">
                <div class="step-number">1</div>
                <h4 style="color: #17365D; margin-top: 4px;">Conversational Intake</h4>
                <p style="font-size: 0.88rem; color: #5B6573;">
                    Explain what happened naturally. The assistant guides you step-by-step to gather critical details.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            """
            <div class="step-card">
                <div class="step-number">2</div>
                <h4 style="color: #17365D; margin-top: 4px;">Fact Verification</h4>
                <p style="font-size: 0.88rem; color: #5B6573;">
                    Inspect the gathered facts on a structured verification screen. You can edit any field before submitting.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            """
            <div class="step-card">
                <div class="step-number">3</div>
                <h4 style="color: #17365D; margin-top: 4px;">Police Review</h4>
                <p style="font-size: 0.88rem; color: #5B6573;">
                    Authorized station personnel inspect the complaint and oversee structured Malayalam FIR draft generation.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(
            """
            <div class="step-card">
                <div class="step-number">4</div>
                <h4 style="color: #17365D; margin-top: 4px;">FIR Approval & Download</h4>
                <p style="font-size: 0.88rem; color: #5B6573;">
                    Once reviewed and approved by police officers, the official FIR draft is unlocked for citizen download.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ==============================================================================
# 2. CONVERSATIONAL COMPLAINT CHAT
# ==============================================================================
def render_complaint_chat() -> None:
    """Renders the conversational complaint reporting interface."""
    col_nav, col_title = st.columns([1, 4])
    with col_nav:
        if st.button("⬅️ Home", use_container_width=True):
            navigate_to("landing")
    with col_title:
        st.subheader("Conversational Incident Reporting")

    st.caption(
        "Describe your incident naturally. The assistant will ask follow-up questions to gather necessary facts. "
        "Supports English, Malayalam (മലയാളം), and Hindi (हिन्दी)."
    )

    # Step progress tracking
    step_idx = st.session_state.get("chat_step_index", 0)
    total_steps = len(CHAT_STEPS)
    progress_val = min(1.0, max(0.0, step_idx / total_steps))

    current_step_name = CHAT_STEPS[step_idx] if step_idx < total_steps else "complete"
    step_labels = {
        "description": "Incident Description",
        "name": "Complainant Name",
        "contact": "Contact Number",
        "category": "Incident Category",
        "date_time": "Incident Date & Time",
        "location": "Incident Location",
        "additional_info": "Additional Information",
        "complete": "Ready for Verification",
    }

    st.progress(progress_val)
    st.markdown(
        f"<span style='font-size: 0.85rem; color: #5B6573;'>Progress: Step {min(step_idx + 1, total_steps)} of {total_steps} — <strong>{step_labels.get(current_step_name, '')}</strong></span>",
        unsafe_allow_html=True,
    )

    # Initialize first prompt if chat is fresh
    messages = st.session_state["chat_messages"]
    if not messages:
        first_prompt = get_step_prompt(CHAT_STEPS[0])
        messages.append({"role": "assistant", "content": first_prompt})

    # Render chat conversation
    for msg in messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # If all steps are complete, show prompt to proceed to verification
    if step_idx >= total_steps:
        st.success("✅ All required incident details have been collected!")
        st.info(
            "Please proceed to the **Incident Verification** screen to review your information and make any adjustments before confirming submission."
        )
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            if st.button("Proceed to Verify Details ➡️", type="primary", use_container_width=True):
                navigate_to("verify")
        with col_c2:
            if st.button("🔄 Restart Conversation", use_container_width=True):
                reset_chat_state()
                st.rerun()
        return

    # Category quick-select buttons if at category step
    if current_step_name == "category":
        st.markdown("💡 *Quick Select Category:*")
        cat_cols = st.columns(2)
        for i, cat in enumerate(SUPPORTED_CATEGORIES):
            target_col = cat_cols[i % 2]
            with target_col:
                if st.button(cat, key=f"quick_cat_{i}", use_container_width=True):
                    _handle_chat_input(cat)
                    st.rerun()

    # User input bar
    user_input = st.chat_input("Type your response here in English, മലയാളം, or हिन्दी...")
    if user_input:
        _handle_chat_input(user_input)
        st.rerun()

    # Conversation control options
    st.markdown("---")
    col_rst, col_skip = st.columns([1, 1])
    with col_rst:
        if st.button("🔄 Restart Conversation"):
            reset_chat_state()
            st.rerun()
    with col_skip:
        if current_step_name == "additional_info":
            if st.button("⏩ Skip Additional Details"):
                _handle_chat_input("None")
                st.rerun()


def _handle_chat_input(text: str) -> None:
    """Processes user response in the chat flow."""
    step_idx = st.session_state["chat_step_index"]
    current_step = CHAT_STEPS[step_idx]

    # Append user response to messages
    st.session_state["chat_messages"].append({"role": "user", "content": text})

    # Validate
    is_valid, err_msg, extracted_slots = validate_chat_step_input(current_step, text)
    if not is_valid:
        # Prompt user again with error
        reply = f"⚠️ **Please clarify:** {err_msg}"
        st.session_state["chat_messages"].append({"role": "assistant", "content": reply})
    else:
        # Update slots
        st.session_state["complaint_slots"].update(extracted_slots)
        next_step_idx = step_idx + 1
        st.session_state["chat_step_index"] = next_step_idx

        if next_step_idx < len(CHAT_STEPS):
            next_step_name = CHAT_STEPS[next_step_idx]
            next_prompt = get_step_prompt(next_step_name)
            st.session_state["chat_messages"].append({"role": "assistant", "content": next_prompt})
        else:
            final_msg = (
                "✅ Thank you! All essential details have been collected. "
                "Please click **'Proceed to Verify Details'** below to inspect and confirm your complaint."
            )
            st.session_state["chat_messages"].append({"role": "assistant", "content": final_msg})


# ==============================================================================
# 3. INCIDENT VERIFICATION SCREEN
# ==============================================================================
def render_incident_verification() -> None:
    """Renders structured review screen before saving complaint as confirmed."""
    st.subheader("Incident Verification & Review")
    st.markdown(
        "Please review the collected information below carefully. "
        "You can edit any field or confirm to submit your complaint for police review."
    )

    slots = st.session_state.get("complaint_slots", {})
    is_editing = st.session_state.get("is_editing_verification", False)

    if is_editing:
        st.markdown("#### Edit Incident Details")
        with st.form("edit_details_form"):
            new_name = st.text_input("Full Name *", value=slots.get("name", ""))
            new_contact = st.text_input("Contact Number *", value=slots.get("contact_number", ""))

            curr_cat = slots.get("category", "")
            cat_idx = SUPPORTED_CATEGORIES.index(curr_cat) if curr_cat in SUPPORTED_CATEGORIES else 0
            new_cat = st.selectbox("Category *", options=SUPPORTED_CATEGORIES, index=cat_idx)

            new_location = st.text_input("Incident Location *", value=slots.get("location", ""))
            new_desc = st.text_area("Incident Description *", value=slots.get("description", ""), height=120)
            new_extra = st.text_area("Additional Information", value=slots.get("additional_info", ""), height=80)

            saved = st.form_submit_button("Save Corrections", type="primary")
            if saved:
                is_valid, errors = validate_complaint_input(
                    name=new_name,
                    contact_number=new_contact,
                    category=new_cat,
                    incident_date=date.today(),
                    location=new_location,
                    description=new_desc,
                    additional_info=new_extra,
                )
                if not is_valid:
                    st.error("Please resolve errors:")
                    for f, err in errors.items():
                        st.write(f"- **{f}**: {err}")
                else:
                    slots["name"] = new_name.strip()
                    slots["contact_number"] = new_contact.strip()
                    slots["category"] = new_cat
                    slots["location"] = new_location.strip()
                    slots["description"] = new_desc.strip()
                    slots["additional_info"] = new_extra.strip()
                    st.session_state["complaint_slots"] = slots
                    st.session_state["is_editing_verification"] = False
                    st.success("Corrections saved!")
                    st.rerun()

    # Document-like summary card
    st.markdown(
        f"""
        <div class="app-card">
            <span class="status-badge badge-pending">Verification Pending Confirmation</span>
            <span class="status-badge badge-info">Multilingual Record</span>
            <div style="margin-top: 10px;">
                <p><strong>Complainant Name:</strong> {slots.get('name', 'N/A')}</p>
                <p><strong>Contact Number:</strong> {slots.get('contact_number', 'N/A')}</p>
                <p><strong>Complaint Category:</strong> {slots.get('category', 'N/A')}</p>
                <p><strong>Incident Date:</strong> {slots.get('incident_date', 'N/A')} {f"({slots.get('incident_time')})" if slots.get('incident_time') else ""}</p>
                <p><strong>Incident Location:</strong> {slots.get('location', 'N/A')}</p>
            </div>
            <div style="background-color: #F8FAFC; border: 1px solid #E2E8F0; padding: 12px; border-radius: 4px; margin-top: 12px;">
                <strong>Incident Description:</strong><br>
                <p style="white-space: pre-wrap; margin-top: 4px; color: #1F2937;">{slots.get('description', '')}</p>
            </div>
            {f'''<div style="margin-top: 10px; font-size: 0.9rem; color: #5B6573;">
                <strong>Additional Information:</strong> {slots.get('additional_info')}
            </div>''' if slots.get('additional_info') else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Actions: Confirm, Edit, Cancel
    col1, col2, col3 = st.columns([1.5, 1, 1])
    with col1:
        if st.button("✅ Confirm Details & Submit", type="primary", use_container_width=True):
            # Validate one last time before saving
            is_valid, validation_errors = validate_complaint_input(
                name=slots.get("name", ""),
                contact_number=slots.get("contact_number", ""),
                category=slots.get("category", ""),
                incident_date=date.today(),
                location=slots.get("location", ""),
                description=slots.get("description", ""),
                additional_info=slots.get("additional_info", ""),
            )
            if not is_valid:
                st.error("Cannot confirm complaint. Required fields are missing or invalid:")
                for field, err in validation_errors.items():
                    st.write(f"- **{field}**: {err}")
            else:
                record = create_complaint_record(
                    name=slots.get("name", ""),
                    contact_number=slots.get("contact_number", ""),
                    category=slots.get("category", ""),
                    incident_date=date.today(),
                    location=slots.get("location", ""),
                    description=slots.get("description", ""),
                    additional_info=slots.get("additional_info", ""),
                    incident_time=slots.get("incident_time", ""),
                )
                st.session_state["complaints"].append(record)
                st.session_state["last_submission_id"] = record["complaint_id"]
                reset_chat_state()
                navigate_to("confirmation")

    with col2:
        if st.button("✏️ Edit Details", use_container_width=True):
            st.session_state["is_editing_verification"] = True
            st.rerun()

    with col3:
        if st.button("❌ Cancel Complaint", use_container_width=True):
            reset_chat_state()
            st.info("Complaint cancelled. No information was saved.")
            navigate_to("landing")


# ==============================================================================
# 4. SUBMISSION CONFIRMATION
# ==============================================================================
def render_submission_confirmation() -> None:
    """Renders the confirmation screen with reference ID and account prompt."""
    sub_id = st.session_state.get("last_submission_id", "CMP-UNKNOWN")

    st.markdown(
        f"""
        <div class="app-card" style="border-left: 4px solid #237A4B;">
            <h3 style="color: #237A4B; margin-top: 0;">✅ Complaint Submitted Successfully</h3>
            <p style="font-size: 1.05rem; margin-bottom: 8px;">
                Your incident report has been logged with Reference ID: <strong>{sub_id}</strong>
            </p>
            <span class="status-badge badge-pending">Status: Complaint Submitted — Pending Police Review</span>
            <p style="color: #5B6573; margin-top: 10px;">
                Your report has been queued for station inspection. An authorized officer will review 
                the submitted facts and oversee the generation of the structured Malayalam FIR draft.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Important note on FIR download policy
    st.info(
        "ℹ️ **FIR Draft & Download Policy:**\n\n"
        "To ensure legal validity and prevent misinformation, **the official FIR draft download option "
        "will be unlocked only after police personnel have reviewed and approved this complaint.**"
    )

    st.markdown("---")
    st.markdown("### Track Your Complaint & Receive Case Updates")
    st.markdown(
        "Creating an account allows you to track review progress, communicate with investigating personnel, "
        "and download the approved FIR once authorized."
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("📝 Create Citizen Account", type="primary", use_container_width=True):
            navigate_to("signup")
    with col2:
        if st.button("🔑 Log In to Existing Account", use_container_width=True):
            navigate_to("login")
    with col3:
        if st.button("🏠 Return to Landing Page", use_container_width=True):
            navigate_to("landing")


# ==============================================================================
# 5. LOGIN & ROLE PROTOTYPE ACCESS
# ==============================================================================
def render_login_page() -> None:
    """Renders login and demonstration role access page."""
    col_nav, col_title = st.columns([1, 4])
    with col_nav:
        if st.button("⬅️ Home"):
            navigate_to("landing")
    with col_title:
        st.subheader("System Portal Login")

    st.caption(
        "Select your intended demonstration role below to access the role-specific dashboard."
    )

    st.markdown(
        """
        <div class="disclaimer-banner" style="margin-bottom: 20px;">
            <strong>Demonstration Access Notice:</strong> Real authentication credentials are not required. 
            Select one of the three profiles below to explore the interface.
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            """
            <div class="app-card">
                <h4 style="color: #17365D;">👤 Citizen Portal</h4>
                <p style="font-size: 0.88rem; color: #5B6573;">
                    Track your submitted complaints, view review status updates, and download approved FIR documents.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Log In as Citizen", use_container_width=True):
            st.session_state["user_role"] = "citizen"
            navigate_to("citizen_dashboard")

    with col2:
        st.markdown(
            """
            <div class="app-card">
                <h4 style="color: #17365D;">🛡️ Police Officer</h4>
                <p style="font-size: 0.88rem; color: #5B6573;">
                    Inspect incoming citizen complaints, review AI-drafted Malayalam FIRs, and update approval status.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Log In as Police Officer", type="primary", use_container_width=True):
            st.session_state["user_role"] = "police"
            navigate_to("police_dashboard")

    with col3:
        st.markdown(
            """
            <div class="app-card">
                <h4 style="color: #17365D;">⚙️ Administrator</h4>
                <p style="font-size: 0.88rem; color: #5B6573;">
                    System health monitoring, audit logs, model telemetry, and surveillance module controls.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Log In as Administrator", use_container_width=True):
            st.session_state["user_role"] = "admin"
            navigate_to("admin_dashboard")


# ==============================================================================
# 6. SIGN UP PLACEHOLDER
# ==============================================================================
def render_signup_page() -> None:
    """Renders citizen account registration placeholder."""
    col_nav, col_title = st.columns([1, 4])
    with col_nav:
        if st.button("⬅️ Back"):
            navigate_to("landing")
    with col_title:
        st.subheader("Create Citizen Account")

    st.markdown(
        """
        <div class="disclaimer-banner">
            <strong>Prototype Registration:</strong> Account creation enables case tracking and follow-up. 
            Real personal passwords are not stored.
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("signup_form"):
        st.text_input("Full Name", placeholder="e.g., Rajesh Kumar")
        st.text_input("Contact Phone Number", placeholder="e.g., +91 98765 43210")
        st.text_input("Email Address (Optional)", placeholder="e.g., citizen@example.com")
        st.text_input("Create Password", type="password", placeholder="Enter demo password")

        submitted = st.form_submit_button("Complete Registration", type="primary", use_container_width=True)
        if submitted:
            st.session_state["user_role"] = "citizen"
            st.success("Account created successfully in demonstration session!")
            navigate_to("citizen_dashboard")


# ==============================================================================
# 7. CITIZEN DASHBOARD
# ==============================================================================
def render_citizen_dashboard() -> None:
    """Renders citizen dashboard showing submitted complaints and FIR status."""
    col_out, col_title = st.columns([1, 4])
    with col_out:
        if st.button("🚪 Sign Out"):
            st.session_state["user_role"] = None
            navigate_to("landing")
    with col_title:
        st.subheader("Citizen Case Tracking Dashboard")

    st.caption("Track the status of incidents submitted during this demonstration session.")

    complaints = st.session_state.get("complaints", [])
    if not complaints:
        st.info("ℹ️ You have not submitted any complaints in this session yet.")
        if st.button("🚀 File a New Complaint Now", type="primary"):
            reset_chat_state()
            navigate_to("chat")
        return

    st.markdown(f"#### Your Active Reports ({len(complaints)})")
    for item in reversed(complaints):
        with st.expander(f"Reference ID: {item['complaint_id']} — {item['category']}"):
            st.write(f"**Incident Date:** {item['incident_date']}")
            st.write(f"**Location:** {item['incident_location']}")
            st.write("**Submitted Description:**")
            st.text_area(
                "Description",
                value=item["description"],
                height=80,
                disabled=True,
                key=f"cit_desc_{item['complaint_id']}",
            )
            st.write(f"**Current Status:** `{item['status']}`")

            # FIR download locked notice
            is_approved = item.get("is_approved", False)
            if not is_approved:
                st.markdown(
                    "<span class='status-badge badge-locked'>🔒 FIR Download Locked</span>",
                    unsafe_allow_html=True,
                )
                st.button(
                    "📥 Download Approved FIR (PDF)",
                    disabled=True,
                    key=f"dl_{item['complaint_id']}",
                    help="FIR draft must be reviewed and approved by police personnel before download is unlocked.",
                )
                st.caption("The official FIR draft download will be unlocked once station personnel review and approve the report.")
            else:
                st.success("✅ This FIR has been approved by station officers.")
                st.download_button(
                    "📥 Download Approved FIR (Text/PDF)",
                    data=f"FIRST INFORMATION REPORT\nReference: {item['complaint_id']}\nDetails: {item['description']}",
                    file_name=f"FIR_{item['complaint_id']}.txt",
                    key=f"dl_app_{item['complaint_id']}",
                )

    st.markdown("---")
    if st.button("📝 File Another Complaint", type="primary"):
        reset_chat_state()
        navigate_to("chat")


# ==============================================================================
# 8. POLICE OFFICER DASHBOARD & DRAFT REVIEW
# ==============================================================================
def render_police_dashboard() -> None:
    """Renders police review portal preserving existing draft review workflows."""
    col_out, col_title = st.columns([1, 4])
    with col_out:
        if st.button("🚪 Sign Out"):
            st.session_state["user_role"] = None
            navigate_to("landing")
    with col_title:
        st.subheader("Police Review & FIR Drafting Portal")

    st.caption("Authorized station review interface for inspecting citizen reports and FIR drafts.")

    st.markdown(
        """
        <div class="app-card" style="border-left: 4px solid #17365D;">
            <h4 style="color: #17365D; margin-top: 0;">ℹ️ Police Review & Draft Management</h4>
            <p style="color: #5B6573; margin-bottom: 0;">
                Inspect citizen-submitted reports. In subsequent stages, AI-assisted Malayalam FIR draft generation 
                will produce structured FIR drafts for each verified report. Reviewing personnel can inspect, 
                edit, and approve the draft before making it available to the citizen.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    complaints = st.session_state.get("complaints", [])
    if not complaints:
        st.info("No citizen complaints have been received in the current session yet.")
        return

    st.markdown(f"#### Incident Complaints for Review ({len(complaints)})")
    for item in reversed(complaints):
        with st.expander(
            f"Case {item['complaint_id']} — {item['category']} ({item['incident_date']})"
        ):
            c1, c2 = st.columns(2)
            with c1:
                st.write(f"**Complainant:** {item['complainant_name']}")
                st.write(f"**Contact Number:** {item['contact_number']}")
            with c2:
                st.write(f"**Incident Location:** {item['incident_location']}")
                st.write(f"**Incident Date:** {item['incident_date']}")

            st.write("**Citizen Incident Description (Original):**")
            st.text_area(
                "Original Description",
                value=item["description"],
                height=90,
                disabled=True,
                key=f"pol_desc_{item['complaint_id']}",
            )
            if item.get("additional_info"):
                st.write(f"**Additional Details:** {item['additional_info']}")

            st.write(f"**Current Review Status:** `{item['status']}`")

            # Demonstration review approval
            col_ap1, col_ap2 = st.columns(2)
            with col_ap1:
                if not item.get("is_approved", False):
                    if st.button(
                        f"Approve Case {item['complaint_id']} (Demo)",
                        key=f"btn_app_{item['complaint_id']}",
                        type="primary",
                    ):
                        item["is_approved"] = True
                        item["status"] = "Approved — FIR Draft Ready"
                        st.success(f"Case {item['complaint_id']} approved! Citizen can now download the FIR draft.")
                        st.rerun()
                else:
                    st.success("Case Approved by Station Reviewer.")
            with col_ap2:
                st.caption("AI FIR drafting model integration scheduled for subsequent project stages.")


# ==============================================================================
# 9. ADMINISTRATOR DASHBOARD
# ==============================================================================
def render_admin_dashboard() -> None:
    """Renders administrative system overview."""
    col_out, col_title = st.columns([1, 4])
    with col_out:
        if st.button("🚪 Sign Out"):
            st.session_state["user_role"] = None
            navigate_to("landing")
    with col_title:
        st.subheader("System Administration & Telemetry")

    st.caption("Administrative monitoring and module configuration overview.")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Session Complaints", len(st.session_state.get("complaints", [])))
    with col2:
        st.metric("Draft Engine Status", "Stage 2 Ready")
    with col3:
        st.metric("Surveillance Engine", "Inactive (Future Scope)")

    st.markdown("---")
    st.markdown("#### System Modules Overview")
    st.markdown(
        """
        - **FIR Assistance Module**: Active. Conversational complaint intake, validation, and review management.
        - **Multilingual Support**: Active. Unicode text processing for English, Malayalam, and Hindi.
        - **Face Detection & Missing Person Matching**: Future Scope (inactive).
        - **CCTV Video Ingestion**: Future Scope (inactive).
        """
    )


# ==============================================================================
# MAIN ROUTER
# ==============================================================================
def main() -> None:
    """Main application entry point and screen routing."""
    st.set_page_config(
        page_title="Integrated AI Surveillance and FIR Assistance System",
        page_icon="⚖️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    init_session_state()
    apply_custom_styles()
    render_sidebar()
    render_header()

    current_page = st.session_state.get("current_page", "landing")

    if current_page == "landing":
        render_landing_page()
    elif current_page == "chat":
        render_complaint_chat()
    elif current_page == "verify":
        render_incident_verification()
    elif current_page == "confirmation":
        render_submission_confirmation()
    elif current_page == "login":
        render_login_page()
    elif current_page == "signup":
        render_signup_page()
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
