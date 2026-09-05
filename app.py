"""MED-SETU: Smart Healthcare Queue & Inter-Hospital Referral Platform
Smart India Hackathon (SIH 2026) Prototype
Unified, coherent healthcare workflows for Receptionists, Doctors, and Patients.
"""

import os
from datetime import datetime, timedelta
import streamlit as st

from database.db import init_db, get_session
from database.models import (
    User, Doctor, Patient, Visit, Token, TokenStatus, Facility, Department,
    Referral, ReferralDataPackage, Prescription, DoctorNote, FollowUp, PatientCase, MedicalDocument
)
from services.auth_service import AuthService
from services.dashboard_service import DashboardService
from services.patient_service import PatientService
from services.visit_service import VisitService
from services.token_service import TokenService
from services.doctor_service import DoctorService
from services.case_service import PatientCaseService
from services.document_service import DocumentService
from services.prescription_service import PrescriptionService
from services.doctor_note_service import DoctorNoteService
from services.followup_service import FollowUpService
from services.referral_service import ReferralService
from services.patient_history_service import PatientHistoryService
from services.management_service import ManagementService
from services.session_service import AuthSessionService, normalize_role
from services.navigation import DOCTOR_WORKFLOW, RECEPTIONIST_WORKFLOW, trail_text_with_current
from services.ui_helpers import set_page_style

# ==================== PAGE CONFIGURATION ====================
st.set_page_config(
    page_title="MED-SETU | Healthcare Platform",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== SESSION STATE INITIALIZATION ====================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_role" not in st.session_state:
    st.session_state.user_role = None
if "user_data" not in st.session_state:
    st.session_state.user_data = None
if "receptionist_nav" not in st.session_state:
    st.session_state.receptionist_nav = "Dashboard"
if "doctor_nav" not in st.session_state:
    st.session_state.doctor_nav = "My Queue"
if "selected_patient_id" not in st.session_state:
    st.session_state.selected_patient_id = None
if "selected_visit_id" not in st.session_state:
    st.session_state.selected_visit_id = None
if "generated_token_id" not in st.session_state:
    st.session_state.generated_token_id = None
if "selected_token_id" not in st.session_state:
    st.session_state.selected_token_id = None
if "patient_portal_id" not in st.session_state:
    st.session_state.patient_portal_id = None
if "patient_workflow_stage" not in st.session_state:
    st.session_state.patient_workflow_stage = "search"

# Apply UI styles and ensure database tables exist
set_page_style()
init_db()


# ==================== SESSION LIFECYCLE HELPERS ====================

def _establish_session(auth_result: dict = None, *, role: str = "", patient_portal_id=None):
    """Persist a login in session_state and attach a refresh-survival URL token.

    Used by every login path (staff form, demo quick-sign-in buttons, and the
    patient simulator) so they all behave identically.
    """
    if auth_result is not None:
        st.session_state.logged_in = True
        st.session_state.user_role = auth_result["role"]
        st.session_state.user_data = auth_result
        AuthSessionService.attach_token(auth_result.get("user_id"), auth_result["role"])
        _set_clean_nav(auth_result["role"])
    elif role == "patient":
        st.session_state.logged_in = True
        st.session_state.user_role = "patient"
        st.session_state.user_data = None
        st.session_state.patient_portal_id = patient_portal_id
        AuthSessionService.attach_token(None, "patient", patient_portal_id=patient_portal_id)
        _set_clean_nav("patient")


def _set_clean_nav(role: str):
    """Set the role-appropriate landing tab after a fresh login."""
    role_clean = normalize_role(role)
    if role_clean == "receptionist":
        st.session_state.receptionist_nav = "Dashboard"
    elif role_clean == "doctor":
        st.session_state.doctor_nav = "My Queue"


def _render_workflow_trail(workflow, step_key: str):
    """Show the canonical workflow path with the current step emphasized.

    Read-only breadcrumb (no widget interaction, no fake browser navigation):
    it simply states where the current screen sits in the role's workflow.
    """
    trail = trail_text_with_current(workflow, step_key)
    if trail:
        st.caption(f"🧭 Workflow: {trail}")
    else:
        st.caption(f"🧭 Workflow: **{step_key}**")


def _safe_render(step_name: str, render_fn, *args):
    """Render a screen with user-friendly error handling.

    Unexpected exceptions are logged to stderr for debugging but surfaced to
    the user as a clean message instead of a raw stack trace. Session state is
    preserved so the user can retry without being logged out.
    """
    import traceback
    try:
        render_fn(*args)
    except Exception as exc:  # noqa: BLE001 - intentional catch-all barrier
        traceback.print_exc()
        st.error(
            f"⚠️ **Something went wrong while loading the {step_name} screen.**\n\n"
            "Your session is safe and your data was not lost — please try the action again "
            "or refresh the page."
        )


# ==================== AUTHENTICATION & LOGIN ====================

def show_login_page(db):
    """Clean, unified login page with clear SIH demo credentials."""
    st.markdown("""
    <div style="text-align: center; padding: 15px 0 10px 0;">
        <h1 style="color: #1e3a8a; margin-bottom: 2px;">🏥 MED-SETU</h1>
        <p style="color: #475569; font-size: 16px; margin-bottom: 4px;">
            Smart Healthcare Queue & Inter-Hospital Referral Platform
        </p>
        <span style="background-color: #dbeafe; color: #1e40af; padding: 4px 12px; border-radius: 9999px; font-size: 12px; font-weight: 600;">
            Smart India Hackathon (SIH 2026) Prototype
        </span>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")

    col_login, col_demo = st.columns([1.1, 1.3])

    with col_login:
        st.markdown("### 🔐 Staff Sign In")
        st.caption("Sign in with your facility credentials.")

        with st.form("staff_login_form"):
            username_input = st.text_input("Username", placeholder="e.g. receptionist, drkhan, drgupta")
            password_input = st.text_input("Password", type="password", placeholder="password123")
            submit_login = st.form_submit_button("Sign In", use_container_width=True)

            if submit_login:
                if not username_input or not password_input:
                    st.error("Please enter both username and password.")
                else:
                    auth_result = AuthService.authenticate(db, username_input.strip(), password_input.strip())
                    if auth_result:
                        _establish_session(auth_result=auth_result)
                        st.rerun()
                    else:
                        st.error("Invalid username or password. Please check demo credentials.")

        st.markdown("---")
        st.markdown("#### 📱 Patient Simulator Access")
        st.caption("Experience the patient's WhatsApp interface for symptom triage and referral updates.")
        if st.button("💬 Open Patient WhatsApp Simulator (Rahim Shaikh)", use_container_width=True):
            st.session_state.patient_workflow_stage = "search"
            rahim = db.query(Patient).filter(Patient.patient_id == "PAT-00184").first()
            if not rahim:
                rahim = db.query(Patient).first()
            _establish_session(role="patient", patient_portal_id=rahim.id if rahim else 1)
            st.rerun()

    with col_demo:
        st.markdown("### 📋 SIH 2026 Demo Credentials")
        st.caption("Click any role to auto-sign in for live demonstration.")

        st.markdown("##### 🏥 Hospital A: Rural Community Health Centre (Thane)")
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("Receptionist A\n(Front Desk & Queue)", use_container_width=True):
                auth = AuthService.authenticate(db, "receptionist", "password123")
                if auth:
                    _establish_session(auth_result=auth)
                    st.rerun()
                else:
                    st.error("Demo account unavailable. Please check seed data.")
            st.caption("User: `receptionist` | Pass: `password123`")
        with c2:
            if st.button("Dr. Mohammad Khan\n(General Medicine)", use_container_width=True):
                auth = AuthService.authenticate(db, "drkhan", "password123")
                if auth:
                    _establish_session(auth_result=auth)
                    st.rerun()
                else:
                    st.error("Demo account unavailable. Please check seed data.")
            st.caption("User: `drkhan` | Pass: `password123`")
        with c3:
            if st.button("Dr. Priya Sharma\n(Dental)", use_container_width=True):
                auth = AuthService.authenticate(db, "drsharma", "password123")
                if auth:
                    _establish_session(auth_result=auth)
                    st.rerun()
                else:
                    st.error("Demo account unavailable. Please check seed data.")
            st.caption("User: `drsharma` | Pass: `password123`")

        st.markdown("---")
        st.markdown("##### 🏥 Hospital B: District General Hospital (Pune — Receiving Facility)")
        c4, c5 = st.columns(2)
        with c4:
            if st.button("Receptionist B\n(Referral Desk)", use_container_width=True):
                auth = AuthService.authenticate(db, "receptionist_b", "password123")
                if auth:
                    _establish_session(auth_result=auth)
                    st.session_state.receptionist_nav = "Referrals"
                    st.rerun()
                else:
                    st.error("Demo account unavailable. Please check seed data.")
            st.caption("User: `receptionist_b` | Pass: `password123`")
        with c5:
            if st.button("Dr. Anil Gupta\n(Cardiology Specialist)", use_container_width=True):
                auth = AuthService.authenticate(db, "drgupta", "password123")
                if auth:
                    _establish_session(auth_result=auth)
                    st.rerun()
                else:
                    st.error("Demo account unavailable. Please check seed data.")
            st.caption("User: `drgupta` | Pass: `password123`")


# ==============================================================================
# SECTION 2: RECEPTIONIST / FRONT DESK WORKFLOW
# Navigation: Dashboard | Patients | Queue | Referrals | Logout
# ==============================================================================

def render_receptionist_sidebar(facility_info: dict) -> str:
    """Render receptionist navigation sidebar."""
    st.sidebar.markdown("### MED-SETU")
    st.sidebar.markdown("**📋 Front Desk & Reception**")
    st.sidebar.markdown("---")

    nav_options = ["🏠 Dashboard", "👤 Patients", "🎫 Queue", "🔄 Referrals"]
    current_nav_index = 0
    clean_current = st.session_state.receptionist_nav
    for i, opt in enumerate(nav_options):
        if clean_current in opt:
            current_nav_index = i
            break

    nav = st.sidebar.radio(
        "Receptionist Navigation",
        nav_options,
        index=current_nav_index,
        label_visibility="collapsed"
    )
    if "Dashboard" in nav:
        clean_nav = "Dashboard"
    elif "Patient" in nav:
        clean_nav = "Patients"
    elif "Queue" in nav:
        clean_nav = "Queue"
    elif "Referral" in nav:
        clean_nav = "Referrals"
    else:
        clean_nav = "Dashboard"

    # Dismiss one-shot confirmation state only when the user actively switches
    # to a DIFFERENT sidebar section. The token confirmation card is a transient
    # result of the "Visit / Token" step; once the receptionist leaves the
    # Patients workflow it must not hijack the screen on their return. Selected
    # patient/visit/referral context is deliberately preserved.
    if st.session_state.get("receptionist_nav") != clean_nav:
        st.session_state.pop("generated_token_id", None)
    st.session_state.receptionist_nav = clean_nav

    if st.sidebar.button("🚪 Logout", use_container_width=True, key="rec_logout_btn"):
        AuthSessionService.logout()
        st.rerun()

    st.sidebar.markdown("---")
    if facility_info:
        st.sidebar.markdown(f"**{facility_info.get('name', 'Hospital')}**")
        st.sidebar.caption(f"📍 District: {facility_info.get('district', 'N/A')}")
        st.sidebar.caption(f"🏥 Type: {facility_info.get('facility_type', 'Hospital')}")

    return clean_nav


def show_receptionist_dashboard(db):
    """Main Receptionist router."""
    user_data = st.session_state.user_data or {}
    facility_info = user_data.get("facility") or DashboardService.get_facility_info(db)
    nav = render_receptionist_sidebar(facility_info)

    if nav == "Dashboard":
        show_receptionist_overview(db, facility_info)
    elif nav == "Patients":
        show_receptionist_patients(db, facility_info)
    elif nav == "Queue":
        show_receptionist_queue(db, facility_info)
    elif nav == "Referrals":
        show_receptionist_referrals(db, facility_info)
    else:
        show_receptionist_overview(db, facility_info)


def show_receptionist_overview(db, facility_info):
    """Dashboard view: KPIs and quick overview."""
    fac_name = facility_info.get("name", "Healthcare Facility") if facility_info else "Healthcare Facility"
    st.markdown(f"## 🏠 Front Desk Dashboard — {fac_name}")
    _render_workflow_trail(RECEPTIONIST_WORKFLOW, "dashboard")

    kpis = DashboardService.get_kpi_counts(db)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Today's Patients", kpis.get("total_patients", 0))
    with c2:
        st.metric("Waiting in Queue", kpis.get("waiting", 0))
    with c3:
        st.metric("Completed Visits", kpis.get("completed", 0))
    with c4:
        st.metric("Pending Referrals", kpis.get("pending_referrals", 0))

    st.markdown("---")

    # Quick action buttons
    c_btn1, c_btn2, c_btn3 = st.columns(3)
    with c_btn1:
        if st.button("➕ Register New Patient", use_container_width=True):
            st.session_state.pop("generated_token_id", None)
            st.session_state.patient_workflow_stage = "register"
            st.session_state.receptionist_nav = "Patients"
            st.rerun()
    with c_btn2:
        if st.button("🔍 Search Patient / Create Visit", use_container_width=True):
            st.session_state.pop("generated_token_id", None)
            st.session_state.patient_workflow_stage = "search"
            st.session_state.receptionist_nav = "Patients"
            st.rerun()
    with c_btn3:
        if st.button("🎫 Manage Queue", use_container_width=True):
            st.session_state.receptionist_nav = "Queue"
            st.rerun()

    st.markdown("### 📋 Today's Queue Overview")
    queue_data = DashboardService.get_queue_table_data(db)
    if queue_data:
        display_rows = [
            {
                "Token": q["token_number"],
                "Patient Name": q["patient_name"],
                "Age": q["age"],
                "Department": q["department"],
                "Assigned Doctor": q["doctor_name"],
                "Status": q["status"],
                "Time": q["token_date"],
            }
            for q in queue_data
        ]
        st.dataframe(display_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No patients queued today yet.")


def show_receptionist_patients(db, facility_info):
    """Patients workflow: Search, Register, and Create Visit -> Generate Token."""
    st.markdown("## 👤 Patient Management & Visit Check-In")

    # If a token was just generated, show the clean confirmation card
    if st.session_state.get("generated_token_id"):
        show_token_confirmation_card(db)
        return

    # If in visit creation mode for a selected patient
    if st.session_state.get("patient_workflow_stage") == "create_visit" and st.session_state.get("selected_patient_id"):
        show_visit_creation_workflow(db, facility_info)
        return

    # Primary mode selection: Search or Register
    _render_workflow_trail(RECEPTIONIST_WORKFLOW, "patients")
    mode = st.radio(
        "Patient Action",
        ["🔍 Search Existing Patient", "➕ Register New Patient"],
        horizontal=True,
        index=0 if st.session_state.get("patient_workflow_stage") != "register" else 1
    )

    if "Search" in mode:
        st.markdown("### Search Existing Patient")
        c_search, c_filter = st.columns([3.5, 1.5])
        with c_search:
            query = st.text_input("Search by Name, Phone Number, or Patient ID (e.g. Rahim or PAT-00184)", placeholder="Type name or 10-digit phone number...")
        with c_filter:
            st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
            include_inactive = st.checkbox("Include Deactivated", value=False)

        if query:
            results = PatientService.search_patients(db, query.strip(), include_deactivated=include_inactive)
            if results:
                st.markdown(f"Found **{len(results)}** matching patient(s):")
                for p in results:
                    with st.container():
                        full_name = getattr(p, "full_name", "Unknown Patient")
                        pat_id = getattr(p, "patient_id", "N/A")
                        age = getattr(p, "age", "N/A")
                        gender = getattr(p, "gender", "N/A")
                        phone_num = getattr(p, "phone", "N/A")
                        lang = getattr(p, "preferred_language", "English")
                        is_active = getattr(p, "is_active", True)
                        status_badge = "🟢 Active" if is_active else "🔴 Deactivated (Inactive)"

                        col_info, col_act = st.columns([3.6, 2.4])
                        with col_info:
                            st.markdown(f"**{full_name}** | ID: `{pat_id}` | Age: {age} ({gender}) | 📞 `{phone_num}` | Lang: {lang} | {status_badge}")
                        with col_act:
                            btn_c1, btn_c2, btn_c3, btn_c4 = st.columns([1.2, 0.9, 1.1, 0.9])
                            with btn_c1:
                                if st.button("🏥 Visit", key=f"start_vis_{p.id}", use_container_width=True, disabled=not is_active, help="Start Visit & Generate Token"):
                                    st.session_state.selected_patient_id = p.id
                                    st.session_state.patient_workflow_stage = "create_visit"
                                    st.rerun()
                            with btn_c2:
                                if st.button("✏️ Edit", key=f"edit_btn_{p.id}", use_container_width=True, help="Edit Patient Details"):
                                    st.session_state[f"edit_patient_{p.id}"] = not st.session_state.get(f"edit_patient_{p.id}", False)
                                    st.rerun()
                            with btn_c3:
                                if is_active:
                                    if st.button("⏸️ Deact", key=f"deact_btn_{p.id}", use_container_width=True, help="Deactivate Patient (Soft Archive)"):
                                        res = PatientService.deactivate_patient(db, p.id, user_role=normalize_role(st.session_state.get("user_role")) or "receptionist")
                                        if res["success"]:
                                            st.success(res["message"])
                                            st.rerun()
                                        else:
                                            st.error(res["error"])
                                else:
                                    if st.button("▶️ React", key=f"react_btn_{p.id}", use_container_width=True, help="Reactivate Patient"):
                                        res = PatientService.reactivate_patient(db, p.id, user_role=normalize_role(st.session_state.get("user_role")) or "receptionist")
                                        if res["success"]:
                                            st.success(res["message"])
                                            st.rerun()
                                        else:
                                            st.error(res["error"])
                            with btn_c4:
                                if st.button("🗑️ Del", key=f"del_btn_{p.id}", use_container_width=True, help="Permanent Delete (Admin)"):
                                    st.session_state[f"confirm_delete_{p.id}"] = not st.session_state.get(f"confirm_delete_{p.id}", False)
                                    st.rerun()

                        # --- Inline Demographic Edit Form ---
                        if st.session_state.get(f"edit_patient_{p.id}", False):
                            with st.form(key=f"form_edit_patient_{p.id}"):
                                st.markdown(f"##### ✏️ Edit Details for {full_name} (`{pat_id}`)")
                                ef1, ef2 = st.columns(2)
                                with ef1:
                                    edit_name = st.text_input("Full Name *", value=full_name)
                                    edit_age = st.number_input("Age *", min_value=0, max_value=125, value=int(age) if isinstance(age, int) else 30)
                                    edit_gender = st.selectbox("Gender *", ["Male", "Female", "Other"], index=["Male", "Female", "Other"].index(gender) if gender in ["Male", "Female", "Other"] else 0)
                                with ef2:
                                    edit_phone = st.text_input("Phone Number *", value=phone_num)
                                    lang_opts = ["Hindi", "English", "Marathi", "Gujarati", "Bengali", "Urdu"]
                                    edit_lang = st.selectbox("Preferred Language", lang_opts, index=lang_opts.index(lang) if lang in lang_opts else 0)

                                c_save, c_cancel = st.columns(2)
                                with c_save:
                                    submit_edit = st.form_submit_button("Save Changes", use_container_width=True)
                                with c_cancel:
                                    cancel_edit = st.form_submit_button("Cancel", use_container_width=True)

                                if submit_edit:
                                    edit_res = PatientService.edit_patient(
                                        db, p.id, edit_name, edit_age, edit_gender, edit_phone, edit_lang, user_role=normalize_role(st.session_state.get("user_role")) or "receptionist"
                                    )
                                    if edit_res["success"]:
                                        st.success(edit_res["message"])
                                        st.session_state[f"edit_patient_{p.id}"] = False
                                        st.rerun()
                                    else:
                                        st.error(edit_res["error"])
                                elif cancel_edit:
                                    st.session_state[f"edit_patient_{p.id}"] = False
                                    st.rerun()

                        # --- Explicit Permanent Deletion Confirmation ---
                        if st.session_state.get(f"confirm_delete_{p.id}", False):
                            st.warning(f"⚠️ **Permanent Deletion Warning: {full_name} (`{pat_id}`)**")
                            st.markdown(f"""
                            This will permanently delete patient **{full_name}** and cascade-delete all associated clinical records:
                            - **Visits:** {len(p.visits)}
                            - **Tokens:** {sum(len(v.tokens) for v in p.visits)}
                            - **Clinical Cases:** {len(p.cases)}
                            - **Documents:** {len(p.documents)}
                            - **Prescriptions:** {len(p.prescriptions)}
                            - **Doctor Notes:** {len(p.doctor_notes)}
                            - **Referrals:** {len(p.referrals)}
                            - **Follow-ups:** {len(p.follow_ups)}
                            """)
                            c_del_pass, c_del_check = st.columns(2)
                            with c_del_pass:
                                admin_pass = st.text_input("Administrator Passkey *", type="password", placeholder="Enter admin passkey (e.g. admin123)", key=f"pass_{p.id}")
                            with c_del_check:
                                confirm_check = st.checkbox(f"I confirm permanent deletion of {pat_id}", key=f"chk_{p.id}")

                            c_del_act, c_del_canc = st.columns(2)
                            with c_del_act:
                                if st.button("Permanently Delete Patient", key=f"do_del_{p.id}", type="primary", use_container_width=True):
                                    if not confirm_check:
                                        st.error("Please check the confirmation box to proceed.")
                                    elif admin_pass.strip() not in ["admin123", "admin", "hospital_admin", "password123"]:
                                        st.error("Unauthorized: Invalid administrator passkey. Permanent deletion is restricted. You can use Deactivate instead.")
                                    else:
                                        del_res = PatientService.delete_patient(db, p.id, user_role=normalize_role(st.session_state.get("user_role")) or "hospital_admin", confirmed=True)
                                        if del_res["success"]:
                                            st.success(f"✓ {del_res['message']}")
                                            st.session_state[f"confirm_delete_{p.id}"] = False
                                            if st.session_state.get("selected_patient_id") == p.id:
                                                st.session_state.selected_patient_id = None
                                            st.rerun()
                                        else:
                                            st.error(del_res["error"])
                            with c_del_canc:
                                if st.button("Cancel Deletion", key=f"canc_del_{p.id}", use_container_width=True):
                                    st.session_state[f"confirm_delete_{p.id}"] = False
                                    st.rerun()

                        st.markdown("---")
            else:
                st.warning("No matching patient found. You can register them below.")
                if st.button("Register as New Patient"):
                    st.session_state.patient_workflow_stage = "register"
                    st.rerun()
    else:
        st.markdown("### ➕ Register New Patient")
        with st.form("patient_registration_form"):
            c1, c2 = st.columns(2)
            with c1:
                full_name = st.text_input("Full Name *", placeholder="e.g. Rahim Shaikh")
                age = st.number_input("Age *", min_value=0, max_value=125, value=45)
                phone = st.text_input("Phone Number *", placeholder="10-digit mobile number")
            with c2:
                gender = st.selectbox("Gender *", ["Male", "Female", "Other"])
                language = st.selectbox("Preferred Language", ["Hindi", "English", "Marathi", "Gujarati", "Bengali", "Urdu"])

            submit_reg = st.form_submit_button("Register & Proceed to Visit", use_container_width=True)

            if submit_reg:
                if not full_name.strip() or not phone.strip() or age < 0:
                    st.error("Please fill all required fields correctly.")
                elif len(phone.strip()) < 10:
                    st.error("Phone number must contain at least 10 digits.")
                else:
                    try:
                        new_patient = PatientService.register_patient(
                            db, full_name.strip(), int(age), gender, phone.strip(), language
                        )
                        db.commit()
                        st.session_state.selected_patient_id = new_patient.id
                        st.session_state.patient_workflow_stage = "create_visit"
                        st.success(f"✓ Registered {new_patient.full_name} (`{new_patient.patient_id}`). Creating visit...")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

    st.markdown("---")
    # Contextual Demo Data Management Section
    with st.expander("🛠️ Controlled Demo Data & Facility Management", expanded=False):
        st.caption("Administrative tools for testing and demo data management. No destructive database wipes.")
        t_pat, t_staff, t_fac, t_vis, t_reset = st.tabs(["👥 Patients", "👨‍⚕️ Staff / Doctors", "🏥 Facilities", "🎫 Demo Visits", "🔄 Demo Reset"])

        with t_pat:
            all_patients = db.query(Patient).order_by(Patient.id.desc()).all()
            st.markdown(f"**Total Registered Patients:** {len(all_patients)}")
            pat_rows = [
                {
                    "ID": p.patient_id,
                    "Name": p.full_name,
                    "Age": p.age,
                    "Gender": p.gender,
                    "Phone": p.phone,
                    "Language": p.preferred_language,
                    "Status": "Active" if p.is_active else "Inactive",
                    "Visits": len(p.visits),
                }
                for p in all_patients
            ]
            st.dataframe(pat_rows, use_container_width=True, hide_index=True)

        with t_staff:
            staff_list = ManagementService.get_all_staff(db)
            st.markdown(f"**Total Staff Accounts:** {len(staff_list)}")
            st.dataframe(staff_list, use_container_width=True, hide_index=True)
            st.markdown("##### Staff Account Status Control")
            sc1, sc2, sc3 = st.columns([3, 1.5, 1.5])
            with sc1:
                staff_map = {f"{s['full_name']} ({s['username']} - {s['role']})": s for s in staff_list}
                sel_staff_label = st.selectbox("Select Staff Account", list(staff_map.keys()), key="sel_staff_mgr")
                sel_staff = staff_map[sel_staff_label] if sel_staff_label else None
            with sc2:
                st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
                if sel_staff and sel_staff["is_active"]:
                    if st.button("Deactivate Staff", key=f"deact_staff_{sel_staff['id']}", use_container_width=True):
                        res = ManagementService.deactivate_staff(db, sel_staff["id"], requester_role=normalize_role(st.session_state.get("user_role")) or "hospital_admin")
                        st.success(res["message"])
                        st.rerun()
            with sc3:
                st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
                if sel_staff and not sel_staff["is_active"]:
                    if st.button("Reactivate Staff", key=f"react_staff_{sel_staff['id']}", use_container_width=True):
                        res = ManagementService.reactivate_staff(db, sel_staff["id"], requester_role=normalize_role(st.session_state.get("user_role")) or "hospital_admin")
                        st.success(res["message"])
                        st.rerun()

        with t_fac:
            fac_list = ManagementService.get_all_facilities(db)
            st.markdown(f"**Registered Healthcare Facilities:** {len(fac_list)}")
            st.dataframe(fac_list, use_container_width=True, hide_index=True)
            st.markdown("##### Facility Status Control")
            fc1, fc2, fc3 = st.columns([3, 1.5, 1.5])
            with fc1:
                fac_map = {f"{f['name']} ({f['district']})": f for f in fac_list}
                sel_fac_label = st.selectbox("Select Facility", list(fac_map.keys()), key="sel_fac_mgr")
                sel_fac = fac_map[sel_fac_label] if sel_fac_label else None
            with fc2:
                st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
                if sel_fac and sel_fac["is_active"]:
                    if st.button("Deactivate Facility", key=f"deact_fac_{sel_fac['id']}", use_container_width=True):
                        res = ManagementService.deactivate_facility(db, sel_fac["id"], requester_role=normalize_role(st.session_state.get("user_role")) or "hospital_admin")
                        st.success(res["message"])
                        st.rerun()
            with sc3:
                st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
                if sel_fac and not sel_fac["is_active"]:
                    if st.button("Reactivate Facility", key=f"react_fac_{sel_fac['id']}", use_container_width=True):
                        res = ManagementService.reactivate_facility(db, sel_fac["id"], requester_role=normalize_role(st.session_state.get("user_role")) or "hospital_admin")
                        st.success(res["message"])
                        st.rerun()

        with t_vis:
            recent_visits = ManagementService.get_recent_visits(db, limit=30)
            st.markdown(f"**Recent Patient Visits (showing latest {len(recent_visits)}):**")
            st.dataframe(recent_visits, use_container_width=True, hide_index=True)
            st.markdown("##### Delete Demo/Test Visit (Controlled)")
            st.caption("Permanently deletes a demo visit and clears its queue tokens, cases, and notes safely.")
            vc1, vc2, vc3 = st.columns([3, 2, 2])
            with vc1:
                vis_map = {f"{v['visit_id']} — {v['patient_name']} ({v['date']})": v for v in recent_visits}
                sel_vis_label = st.selectbox("Select Demo Visit to Delete", ["-- None --"] + list(vis_map.keys()), key="sel_vis_del")
                sel_vis = vis_map.get(sel_vis_label)
            with vc2:
                admin_vis_pass = st.text_input("Admin Passkey", type="password", placeholder="admin123", key="vis_pass_in")
            with vc3:
                st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
                if st.button("Delete Demo Visit", disabled=sel_vis is None, key="btn_del_vis"):
                    if admin_vis_pass.strip() not in ["admin123", "admin", "hospital_admin", "password123"]:
                        st.error("Unauthorized: Valid admin passkey required.")
                    else:
                        v_res = VisitService.delete_visit(db, sel_vis["id"], user_role=normalize_role(st.session_state.get("user_role")) or "hospital_admin", confirmed=True)
                        if v_res["success"]:
                            st.success(v_res["message"])
                            st.rerun()
                        else:
                            st.error(v_res["error"])

        with t_reset:
            st.markdown("##### 🔄 Reset & Seed Clean SIH Demo Dataset")
            st.markdown("""
            <div style="background-color: #eff6ff; border-left: 4px solid #3b82f6; padding: 14px; border-radius: 6px; margin-bottom: 12px;">
                <strong>Controlled Demo Data Reset:</strong><br>
                Safely clears developmental test patient records and seeds the 5 official, coherent SIH demo patients:
                <ul>
                    <li><strong>Aarav Sharma</strong> (28M) — Acute Primary Care (Fever/Pharyngitis, Rx, Follow-up)</li>
                    <li><strong>Fatima Khan</strong> (52F) — Chronic Condition & Longitudinal History (Type-2 Diabetes, 3 Visits, Titrated Rx)</li>
                    <li><strong>Rahul Patil</strong> (61M) — <strong>Primary SIH Demo</strong>: Acute Chest Pain / ACS with Red Flags & Emergency Inter-Hospital Referral to Pune Cardiology</li>
                    <li><strong>Meena Devi</strong> (47F) — Orthopedic Specialist Referral to Pune Orthopedics (Knee Osteoarthritis)</li>
                    <li><strong>Imran Shaikh</strong> (36M) — Diagnostic Report / Document OCR & Care Continuity (USG Abdomen Report)</li>
                </ul>
                <em>Note: Healthcare facilities, clinical departments, doctor/receptionist accounts, and authentication credentials are 100% preserved.</em>
            </div>
            """, unsafe_allow_html=True)

            rc1, rc2 = st.columns(2)
            with rc1:
                reset_pass = st.text_input("Administrator Passkey *", type="password", placeholder="Enter admin passkey (e.g. admin123)", key="demo_reset_pass")
            with rc2:
                reset_confirm = st.checkbox("I confirm clearing test patients and loading clean SIH demo dataset", key="chk_demo_reset")

            if st.button("🔄 Reset Demo Dataset & Seed 5 Patients", type="primary", use_container_width=True, key="btn_execute_demo_reset"):
                if not reset_confirm:
                    st.error("Please check the confirmation box to proceed.")
                elif reset_pass.strip() not in ["admin123", "admin", "hospital_admin", "password123"]:
                    st.error("Unauthorized: Valid administrator passkey required.")
                else:
                    res = ManagementService.reset_and_seed_demo_dataset(db, requester_role=normalize_role(st.session_state.get("user_role")) or "hospital_admin", confirmed=True)
                    if res["success"]:
                        st.session_state.selected_patient_id = None
                        st.session_state.selected_visit_id = None
                        st.session_state.generated_token_id = None
                        st.session_state.patient_portal_id = None
                        st.success("✓ Demo dataset loaded successfully.")
                        st.rerun()
                    else:
                        st.error(res["error"])


def show_visit_creation_workflow(db, facility_info):
    """Step 2 of Patient flow: Select department, select doctor, generate queue token."""
    patient_id = st.session_state.get("selected_patient_id")
    patient = db.query(Patient).filter(Patient.id == patient_id).first() if patient_id else None

    if not patient:
        st.warning("No patient selected.")
        st.session_state.patient_workflow_stage = "search"
        st.rerun()
        return

    if not getattr(patient, "is_active", True):
        st.error(f"⚠️ Patient **{patient.full_name}** (`{patient.patient_id}`) is currently deactivated.")
        st.info("Visits cannot be scheduled for deactivated patients. Please reactivate the patient first.")
        c_react, c_back = st.columns(2)
        with c_react:
            if st.button("▶️ Reactivate Patient", use_container_width=True):
                PatientService.reactivate_patient(db, patient.id, user_role="receptionist")
                st.success("✓ Patient reactivated successfully!")
                st.rerun()
        with c_back:
            if st.button("Cancel & Return to Search", use_container_width=True):
                st.session_state.selected_patient_id = None
                st.session_state.patient_workflow_stage = "search"
                st.rerun()
        return

    st.markdown(f"### 🏥 Create Healthcare Visit for **{patient.full_name}**")
    st.markdown(f"**Patient ID:** `{patient.patient_id}` | Age: {patient.age} ({patient.gender}) | Phone: `{patient.phone}`")
    _render_workflow_trail(RECEPTIONIST_WORKFLOW, "visit_token")
    if st.button("← Back to Dashboard", use_container_width=False, key="btn_visit_dash_back"):
        st.session_state.selected_patient_id = None
        st.session_state.patient_workflow_stage = "search"
        st.session_state.receptionist_nav = "Dashboard"
        st.rerun()
    st.markdown("---")

    facility_id = facility_info.get("id") if facility_info else 1
    departments = VisitService.get_departments(db, facility_id=facility_id)
    if not departments:
        departments = VisitService.get_departments(db)

    dept_names = [d.name for d in departments]
    if not dept_names:
        st.error("No departments are configured for this facility.")
        if st.button("← Back to Dashboard", use_container_width=True, key="btn_vis_no_dept_back"):
            st.session_state.receptionist_nav = "Dashboard"
            st.session_state.patient_workflow_stage = "search"
            st.session_state.selected_patient_id = None
            st.rerun()
        return
    selected_dept_name = st.selectbox("Select Clinical Department *", dept_names)
    selected_dept = next((d for d in departments if d.name == selected_dept_name), None)

    doctors = VisitService.get_doctors_by_department(db, selected_dept.id) if selected_dept else []
    if doctors:
        doc_map = {f"{d.user.full_name} ({d.specialization})": d for d in doctors}
        selected_doc_label = st.selectbox("Assign Available Doctor *", list(doc_map.keys()))
        selected_doctor = doc_map.get(selected_doc_label)
    else:
        st.warning("No doctors currently available in this department.")
        selected_doctor = None

    c_gen, c_cancel = st.columns(2)
    with c_gen:
        if st.button("🎫 Generate Queue Token", use_container_width=True, disabled=selected_doctor is None):
            try:
                visit = VisitService.create_visit(
                    db,
                    patient_id=patient.id,
                    facility_id=facility_id,
                    department_id=selected_dept.id,
                    doctor_id=selected_doctor.id
                )
                db.flush()

                token = TokenService.create_token(db, visit.id, selected_doctor.id)
                db.commit()

                st.session_state.selected_visit_id = visit.id
                st.session_state.generated_token_id = token.id
                st.rerun()
            except Exception as e:
                st.error(f"Error creating visit or token: {e}")

    with c_cancel:
        if st.button("Cancel & Return to Search", use_container_width=True):
            st.session_state.selected_patient_id = None
            st.session_state.patient_workflow_stage = "search"
            st.rerun()


def show_token_confirmation_card(db):
    """Display generated queue token card cleanly."""
    token_id = st.session_state.get("generated_token_id")
    token_data = TokenService.get_token_display_details(db, token_id) if token_id else None

    if not token_data:
        st.warning("No token available.")
        st.session_state.generated_token_id = None
        st.session_state.patient_workflow_stage = "search"
        st.rerun()
        return

    st.markdown("## ✓ Token Generated Successfully")
    _render_workflow_trail(RECEPTIONIST_WORKFLOW, "visit_token")

    col_l, col_card, col_r = st.columns([1, 2, 1])
    with col_card:
        st.markdown(f"""
        <div style="
            background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%);
            color: white;
            padding: 28px;
            border-radius: 12px;
            text-align: center;
            box-shadow: 0 4px 15px rgba(37, 99, 235, 0.25);
        ">
            <div style="font-size: 14px; opacity: 0.9; text-transform: uppercase; letter-spacing: 1px;">Queue Token</div>
            <div style="font-size: 60px; font-weight: 800; letter-spacing: 2px; margin: 8px 0;">{token_data['token_number']}</div>
            <div style="font-size: 14px; opacity: 0.9;">Status: <strong>{token_data['status']}</strong></div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"**Patient Name:**\n{token_data['patient_name']}")
    with c2:
        st.markdown(f"**Patient ID:**\n`{token_data['patient_code']}`")
    with c3:
        st.markdown(f"**Department:**\n{token_data['department_name']}")
    with c4:
        st.markdown(f"**Doctor:**\n{token_data['doctor_name']}")

    st.markdown("---")
    c_hint, c_done = st.columns([2, 1])
    with c_hint:
        st.info("💡 Patient can now use the WhatsApp simulator to report symptoms or upload past prescriptions.")
    with c_done:
        if st.button("✓ Done & View Queue", use_container_width=True):
            st.session_state.generated_token_id = None
            st.session_state.selected_patient_id = None
            st.session_state.selected_visit_id = None
            st.session_state.patient_workflow_stage = "search"
            st.session_state.receptionist_nav = "Queue"
            st.rerun()

    c_back, c_home = st.columns(2)
    with c_back:
        if st.button("← Back to Patient Search", key="btn_token_back_search", use_container_width=True):
            st.session_state.generated_token_id = None
            st.session_state.selected_patient_id = None
            st.session_state.selected_visit_id = None
            st.session_state.patient_workflow_stage = "search"
            st.session_state.receptionist_nav = "Patients"
            st.rerun()
    with c_home:
        if st.button("🏠 Done & View Dashboard", use_container_width=True):
            st.session_state.generated_token_id = None
            st.session_state.selected_patient_id = None
            st.session_state.selected_visit_id = None
            st.session_state.patient_workflow_stage = "search"
            st.session_state.receptionist_nav = "Dashboard"
            st.rerun()


def show_receptionist_queue(db, facility_info):
    """Interactive queue management: Call, mark with doctor, complete."""
    fac_name = facility_info.get("name", "Facility") if facility_info else "Facility"
    st.markdown(f"## 🎫 Live Patient Queue — {fac_name}")
    _render_workflow_trail(RECEPTIONIST_WORKFLOW, "queue")
    st.caption("Manage patient queue transitions and token statuses in real time.")

    queue_data = DashboardService.get_queue_table_data(db)

    if not queue_data:
        st.markdown(f"""
        <div style="
            background-color: #f8fafc;
            border: 2px dashed #cbd5e1;
            border-radius: 12px;
            padding: 36px 20px;
            text-align: center;
            margin: 16px 0 20px 0;
        ">
            <div style="font-size: 44px; margin-bottom: 8px;">🎫</div>
            <h3 style="color: #1e293b; margin-bottom: 6px; font-weight: 700;">No Patients in Queue Today</h3>
            <p style="color: #64748b; font-size: 14px; max-width: 480px; margin: 0 auto 16px auto; line-height: 1.5;">
                Queue is clear. Register a new patient or search an existing patient under <strong>Patients</strong> to generate queue tokens.
            </p>
        </div>
        """, unsafe_allow_html=True)
        col_s1, col_btn, col_s2 = st.columns([1.5, 1, 1.5])
        with col_btn:
            if st.button("➕ Go to Patients Check-In", use_container_width=True):
                st.session_state.receptionist_nav = "Patients"
                st.session_state.patient_workflow_stage = "search"
                st.rerun()
        return

    for item in queue_data:
        token_id = item["token_id"]
        status = item["status"]

        with st.container():
            c_tok, c_pat, c_dept, c_doc, c_status, c_act = st.columns([1.5, 3, 2, 2.5, 1.8, 2.2])

            with c_tok:
                st.markdown(f"### `{item['token_number']}`")
            with c_pat:
                st.markdown(f"**{item['patient_name']}** (`{item.get('patient_id', 'N/A')}`)")
                st.caption(f"Age: {item['age']} | Time: {item['token_date']}")
            with c_dept:
                st.markdown(f"**{item['department']}**")
            with c_doc:
                st.markdown(f"**{item['doctor_name']}**")
            with c_status:
                color = "#3b82f6" if status == "WAITING" else "#eab308" if status == "CALLED" else "#10b981" if status == "WITH_DOCTOR" else "#6b7280"
                st.markdown(f"<span style='background-color:{color};color:white;padding:3px 8px;border-radius:6px;font-size:12px;font-weight:600;'>{status}</span>", unsafe_allow_html=True)

            with c_act:
                if status == "WAITING":
                    if st.button("📞 Call", key=f"call_{token_id}", use_container_width=True):
                        TokenService.update_token_status(db, token_id, TokenStatus.CALLED)
                        db.commit()
                        st.rerun()
                elif status == "CALLED":
                    if st.button("🏥 In Doctor Room", key=f"withdoc_{token_id}", use_container_width=True):
                        TokenService.update_token_status(db, token_id, TokenStatus.WITH_DOCTOR)
                        db.commit()
                        st.rerun()
                elif status == "WITH_DOCTOR":
                    if st.button("✓ Complete", key=f"comp_{token_id}", use_container_width=True):
                        TokenService.update_token_status(db, token_id, TokenStatus.COMPLETED)
                        db.commit()
                        st.rerun()
                else:
                    st.caption("Completed")

            st.markdown("---")


def show_receptionist_referrals(db, facility_info):
    """Receptionist referral management: Verify incoming referrals & view outgoing referrals."""
    facility_id = facility_info.get("id") if facility_info else 1
    fac_name = facility_info.get("name", "Facility")

    st.markdown(f"## 🔄 Referral Desk — {fac_name}")
    _render_workflow_trail(RECEPTIONIST_WORKFLOW, "referrals")
    st.caption("Secure inter-hospital referral intake, patient verification, and facility referral tracking.")

    tabs = st.tabs(["🔍 Verify Incoming Referral (Referral Desk)", "📤 Facility Outgoing Referrals"])

    # Tab 1: Verify incoming referral
    with tabs[0]:
        st.markdown("#### Verify Incoming Referral")
        st.caption("Authorized receiving hospital desk: verify incoming patient using Phone + 6-character Verification Code.")

        default_phone = st.session_state.pop("quick_fill_phone", "")
        default_code = st.session_state.pop("quick_fill_code", "")

        with st.form("referral_lookup_form"):
            c_p, c_c = st.columns(2)
            with c_p:
                phone_input = st.text_input("Patient Phone Number *", value=default_phone, placeholder="10-digit mobile number")
            with c_c:
                code_input = st.text_input("Verification Code *", value=default_code, placeholder="6-character code (e.g. X7K9M2)").upper()

            lookup_btn = st.form_submit_button("🔍 Verify & Retrieve Referral", use_container_width=True)

            if lookup_btn:
                if not phone_input or not code_input:
                    st.error("Both phone number and verification code are required.")
                else:
                    verified = ReferralService.lookup_referral(db, phone_input.strip(), code_input.strip(), facility_id)
                    if verified:
                        st.session_state["verified_referral_id"] = verified["referral"].id
                        st.success("✓ Identity and authorization verified. Access granted to shared patient package.")
                    else:
                        st.error("Referral not found or not authorized for this facility. Please check phone number and code.")

        # If a referral is verified, display the shared patient context
        verified_ref_id = st.session_state.get("verified_referral_id")
        if verified_ref_id:
            shared = ReferralService.get_shared_patient_view(db, verified_ref_id, facility_id)
            if shared:
                ref = shared["referral"]
                patient = shared["patient_summary"]
                clinical = shared["clinical_summary"]
                prescriptions = shared["prescription_data"]

                st.markdown("---")
                st.markdown(f"### 📋 Shared Patient Package: **{patient['full_name']}**")

                c1, c2, c3 = st.columns(3)
                with c1:
                    st.markdown(f"**Patient ID:** `{patient['patient_id']}`")
                    st.markdown(f"**Age / Gender:** {patient['age']} / {patient['gender']}")
                with c2:
                    st.markdown(f"**Referring Hospital:** {ref.referring_facility.name}")
                    st.markdown(f"**Referring Doctor:** {ref.referring_doctor.user.full_name}")
                with c3:
                    st.markdown(f"**Urgency:** `{ref.urgency.upper()}`")
                    st.markdown(f"**Status:** `{ref.status}`")

                st.markdown("##### Referral Reason & Justification:")
                st.info(ref.reason)

                if clinical.get("chief_complaint"):
                    st.markdown("##### Clinical Presentation at Referring Facility:")
                    st.markdown(f"- **Complaint:** {clinical.get('chief_complaint')}")
                    st.markdown(f"- **Duration:** {clinical.get('duration')}")
                    st.markdown(f"- **Symptoms:** {clinical.get('symptoms')}")

                if prescriptions:
                    st.markdown("##### Active Prescriptions:")
                    for rx in prescriptions:
                        st.markdown(f"- **{rx['medication_name']}** {rx['dosage']} ({rx['frequency']} for {rx['duration']})")

                if ref.status == "pending":
                    if st.button("✓ Accept Referral & Create Local Visit / Token", use_container_width=True):
                        ReferralService.update_referral_status(db, ref.id, "accepted")
                        db.commit()
                        st.success(f"✓ Referral {ref.referral_id} accepted. Patient does NOT need to repeat medical history.")
                        st.rerun()

        # Display incoming referrals for this facility
        incoming_refs = ReferralService.get_incoming_referrals_for_facility(db, facility_id)
        if incoming_refs:
            st.markdown("---")
            st.markdown("##### 📥 Incoming Referrals Awaiting Intake at this Facility:")
            for inc in incoming_refs:
                c_inf, c_btn = st.columns([3.5, 1.2])
                with c_inf:
                    st.markdown(f"**{inc.referral_id}** — **{inc.patient.full_name}** (`{inc.patient.patient_id}`) | Status: `{inc.status}`")
                    st.caption(f"From: {inc.referring_facility.name} | Dept: {inc.receiving_department.name} | Code: `{inc.verification_code}` | Phone: `{inc.patient.phone}`")
                with c_btn:
                    if st.button("Quick Fill", key=f"qf_{inc.id}", use_container_width=True):
                        st.session_state["quick_fill_phone"] = inc.patient.phone
                        st.session_state["quick_fill_code"] = inc.verification_code
                        st.rerun()
                st.markdown("---")

    # Tab 2: Outgoing referrals sent from this facility
    with tabs[1]:
        st.markdown("#### Referrals Sent from this Facility")
        sent_referrals = ReferralService.get_outgoing_referrals_for_facility(db, facility_id)
        if sent_referrals:
            for r in sent_referrals:
                with st.container():
                    col_r1, col_r2 = st.columns([3.5, 1.5])
                    with col_r1:
                        st.markdown(f"**{r.referral_id}** — **{r.patient.full_name}** (`{r.patient.patient_id}`)")
                        st.caption(f"Referred to: {r.receiving_facility.name} ({r.receiving_department.name}) | Urgency: `{r.urgency.upper()}` | Status: `{r.status}`")
                        st.markdown(f"Verification Code: `{r.verification_code}` | Date: {r.created_at.strftime('%Y-%m-%d') if r.created_at else ''}")
                    with col_r2:
                        if r.data_package and r.data_package.pdf_path and os.path.exists(r.data_package.pdf_path):
                            with open(r.data_package.pdf_path, "rb") as pf:
                                st.download_button(
                                    label="📄 Download PDF",
                                    data=pf.read(),
                                    file_name=os.path.basename(r.data_package.pdf_path),
                                    mime="application/pdf",
                                    key=f"dl_rec_ref_{r.id}",
                                    use_container_width=True
                                )
                    st.markdown("---")
        else:
            st.info("No outgoing referrals created from this facility yet.")


# ==============================================================================
# SECTION 3 & 4: DOCTOR WORKSPACE
# Navigation: My Queue | Patient Case | Prescription & Notes | Referrals | Logout
# ==============================================================================

def render_doctor_sidebar(doc_info: dict) -> str:
    """Render doctor workspace sidebar with strictly 4 views."""
    st.sidebar.markdown("### MED-SETU")
    st.sidebar.markdown("**👨‍⚕️ Clinical Workspace**")
    st.sidebar.markdown("---")

    nav_options = ["🏠 My Queue", "👤 Patient Case", "💊 Prescription & Notes", "🔄 Referrals"]
    current_index = 0
    clean_current = st.session_state.doctor_nav
    for i, opt in enumerate(nav_options):
        if clean_current in opt:
            current_index = i
            break

    nav = st.sidebar.radio(
        "Doctor Navigation",
        nav_options,
        index=current_index,
        label_visibility="collapsed"
    )
    # Normalize unambiguously by keyword from full selection label
    if "Queue" in nav:
        clean_nav = "My Queue"
    elif "Case" in nav:
        clean_nav = "Patient Case"
    elif "Prescription" in nav:
        clean_nav = "Prescription & Notes"
    elif "Referral" in nav:
        clean_nav = "Referrals"
    else:
        clean_nav = "My Queue"

    st.session_state.doctor_nav = clean_nav

    if st.sidebar.button("🚪 Logout", use_container_width=True, key="doc_logout_btn"):
        AuthSessionService.logout()
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**{doc_info.get('full_name', 'Doctor')}**")
    st.sidebar.caption(f"🩺 {doc_info.get('specialization', 'General')}")
    st.sidebar.caption(f"🏥 {doc_info.get('facility_name', 'Hospital')}")
    st.sidebar.caption(f"📍 {doc_info.get('facility_district', '')}")

    return clean_nav


def show_doctor_dashboard(db):
    """Main Doctor Router."""
    user_data = st.session_state.user_data or {}
    doctor_meta = user_data.get("doctor") or {}
    doctor_id = doctor_meta.get("id") or doctor_meta.get("doctor_id")

    # Fallback if doctor_id wasn't in doctor_meta dict directly
    if not doctor_id and user_data.get("user_id"):
        doc_record = db.query(Doctor).filter(Doctor.user_id == user_data["user_id"]).first()
        if doc_record:
            doctor_id = doc_record.id

    if not doctor_id:
        st.error("Doctor profile not found for this account. Please verify credentials.")
        return

    doc_info = DoctorService.get_doctor_by_id(db, doctor_id) or doctor_meta
    nav = render_doctor_sidebar(doc_info)

    if nav == "My Queue":
        show_doctor_my_queue(db, doctor_id, doc_info)
    elif nav == "Patient Case":
        show_doctor_patient_case(db, doctor_id)
    elif nav == "Prescription & Notes":
        show_doctor_prescription_and_notes(db, doctor_id)
    elif nav == "Referrals":
        show_doctor_referrals(db, doctor_id)
    else:
        # Default safety fallback ensures doctor dashboard NEVER renders blank
        show_doctor_my_queue(db, doctor_id, doc_info)


def show_doctor_my_queue(db, doctor_id: int, doc_info: dict):
    """Doctor's Queue: View assigned patients and select to open Patient Case."""
    st.markdown(f"## 🏠 My Patient Queue — {doc_info.get('full_name', 'Doctor')}")
    _render_workflow_trail(DOCTOR_WORKFLOW, "queue")
    st.caption(f"{doc_info.get('specialization', '')} | {doc_info.get('facility_name', '')}")

    kpis = DoctorService.get_doctor_kpi_counts(db, doctor_id)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Today's Assigned", kpis.get("total_patients", 0))
    with c2:
        st.metric("Waiting", kpis.get("waiting", 0))
    with c3:
        st.metric("In Consultation", kpis.get("with_doctor", 0))
    with c4:
        st.metric("Completed", kpis.get("completed", 0))

    st.markdown("---")
    st.markdown("### Patients Assigned for Consultation")

    queue_data = DoctorService.get_doctor_queue_data(db, doctor_id)

    if not queue_data:
        st.markdown(f"""
        <div style="
            background-color: #f8fafc;
            border: 2px dashed #cbd5e1;
            border-radius: 12px;
            padding: 36px 20px;
            text-align: center;
            margin: 16px 0 20px 0;
        ">
            <div style="font-size: 46px; margin-bottom: 10px;">🩺</div>
            <h3 style="color: #1e293b; margin-bottom: 6px; font-weight: 700;">No Patients in Queue Today</h3>
            <p style="color: #64748b; font-size: 15px; max-width: 520px; margin: 0 auto 16px auto; line-height: 1.5;">
                Your consultation queue is currently clear. When the front desk registers a patient or generates a queue token for <strong>{doc_info.get('specialization', 'your department')}</strong>, they will appear here automatically.
            </p>
            <div style="display: inline-flex; gap: 12px; background: white; border: 1px solid #e2e8f0; padding: 6px 14px; border-radius: 8px; font-size: 13px; color: #475569;">
                <span>🟢 <strong>Status:</strong> Available</span>
                <span>•</span>
                <span>🏥 <strong>Facility:</strong> {doc_info.get('facility_name', 'Healthcare Facility')}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        col_s1, col_btn, col_s2 = st.columns([2, 1, 2])
        with col_btn:
            if st.button("🔄 Refresh Queue", use_container_width=True):
                st.rerun()
        return

    for item in queue_data:
        token_id = item["token_id"]
        status = item["status"]

        with st.container():
            c_tok, c_pat, c_age, c_dept, c_status, c_act = st.columns([1.5, 3, 1, 2, 1.8, 2.2])

            with c_tok:
                st.markdown(f"### `{item['token_number']}`")
            with c_pat:
                st.markdown(f"**{item['patient_name']}** (`{item['patient_id']}`)")
                st.caption(f"Phone: `{item['phone']}`")
            with c_age:
                st.markdown(f"{item['age']}")
            with c_dept:
                st.markdown(f"{item['department']}")
            with c_status:
                color = "#3b82f6" if status == "WAITING" else "#eab308" if status == "CALLED" else "#10b981" if status == "WITH_DOCTOR" else "#6b7280"
                st.markdown(f"<span style='background-color:{color};color:white;padding:3px 8px;border-radius:6px;font-size:12px;font-weight:600;'>{status}</span>", unsafe_allow_html=True)
            with c_act:
                if status != "COMPLETED":
                    if st.button("👨‍⚕️ Open Case", key=f"open_case_{token_id}", use_container_width=True):
                        st.session_state.selected_token_id = token_id
                        # If waiting/called, advance to with_doctor
                        if status in ("WAITING", "CALLED"):
                            DoctorService.update_token_status(db, doctor_id, token_id, "WITH_DOCTOR")
                            db.commit()
                        st.session_state.doctor_nav = "Patient Case"
                        st.rerun()
                else:
                    if st.button("👁️ View Record", key=f"view_rec_{token_id}", use_container_width=True):
                        st.session_state.selected_token_id = token_id
                        st.session_state.doctor_nav = "Patient Case"
                        st.rerun()

            st.markdown("---")


def show_doctor_patient_case(db, doctor_id: int):
    """
    ONE coherent, unified clinical workspace.
    Sections:
    1. Patient Top Bar
    2. Current Case (complaint, symptoms, voice, AI summary, deterministic red flags)
    3. Medical History (past visits, diagnoses, prescriptions)
    4. Reports & OCR
    5. Timeline
    """
    token_id = st.session_state.get("selected_token_id")
    if not token_id:
        st.markdown("""
        <div style="
            background-color: #f8fafc;
            border: 2px dashed #cbd5e1;
            border-radius: 12px;
            padding: 40px 20px;
            text-align: center;
            margin: 20px 0;
        ">
            <div style="font-size: 48px; margin-bottom: 12px;">👤</div>
            <h3 style="color: #1e293b; margin-bottom: 8px; font-weight: 700;">No Patient Currently Selected</h3>
            <p style="color: #64748b; font-size: 15px; max-width: 520px; margin: 0 auto 20px auto; line-height: 1.5;">
                Please select a patient from <strong>My Queue</strong> to open their clinical presentation, past medical history, uploaded lab reports, and longitudinal timeline.
            </p>
        </div>
        """, unsafe_allow_html=True)
        col_s1, col_btn, col_s2 = st.columns([1.5, 1, 1.5])
        with col_btn:
            if st.button("← Go to My Queue", use_container_width=True, key="btn_case_go_queue"):
                st.session_state.doctor_nav = "My Queue"
                st.rerun()
        return

    patient_details = DoctorService.get_patient_details(db, doctor_id, token_id)
    if not patient_details:
        st.error("Access denied or patient details could not be retrieved.")
        return

    patient_pk_id = patient_details["patient_pk_id"]
    visit_db_id = patient_details["visit_db_id"]

    # --- TOP PATIENT BAR ---
    c_back, c_title, c_status = st.columns([1.2, 3.8, 2])
    with c_back:
        if st.button("← My Queue"):
            st.session_state.doctor_nav = "My Queue"
            st.rerun()
    with c_title:
        st.markdown(f"### **{patient_details['patient_name']}** (`{patient_details['patient_id']}`)")
        st.caption(f"Age: {patient_details['age']} | Phone: `{patient_details['phone']}` | Lang: {patient_details.get('preferred_language', 'Hindi')}")
    with c_status:
        st.markdown(f"**Token:** `{patient_details['token_number']}` | Dept: {patient_details['department']}")
        st.markdown(f"**Status:** `{patient_details['token_status']}` | Visit ID: `{patient_details.get('visit_id', '')}`")

    _render_workflow_trail(DOCTOR_WORKFLOW, "case")
    st.markdown("---")

    # --- SECTION 1: CURRENT CASE ---
    st.markdown("#### 📋 Current Clinical Presentation")
    case = PatientCaseService.get_case_for_visit(db, patient_pk_id, visit_db_id)

    if case:
        # Red Flags check
        if case.red_flag_detected:
            st.error(f"🚨 **Acute Clinical Red Flag Detected:** {case.red_flags}\n\nImmediate clinical attention recommended.")
        else:
            st.success("✓ No acute red flags identified in patient submission.")

        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.markdown(f"**Chief Complaint:**\n{case.chief_complaint}")
            st.markdown(f"**Duration:** {case.duration}")
            st.markdown(f"**Symptoms:** {case.symptoms}")
        with col_c2:
            if case.ai_summary:
                st.markdown("**AI-Assisted Clinical Summary:**")
                st.info(case.ai_summary)
            if case.additional_notes:
                st.markdown(f"**Additional Notes / Voice Input:**\n{case.additional_notes}")
    else:
        st.info("No preliminary case submitted by patient via WhatsApp.")
        with st.expander("➕ Record Chief Complaint & Symptoms for Current Visit"):
            with st.form("doc_case_entry"):
                cc_in = st.text_input("Chief Complaint *", placeholder="e.g. Chest discomfort radiating to left arm")
                dur_in = st.text_input("Duration *", placeholder="e.g. 2 hours, 3 days")
                sym_in = st.text_input("Symptoms *", placeholder="e.g. pain, shortness of breath, diaphoresis")
                sub_cc = st.form_submit_button("Save Case")
                if sub_cc:
                    if not cc_in:
                        st.error("Chief complaint is required.")
                    else:
                        PatientCaseService.submit_case(db, patient_pk_id, visit_db_id, cc_in, dur_in, sym_in)
                        db.commit()
                        st.success("Case recorded successfully.")
                        st.rerun()

    st.markdown("---")

    # --- SECTION 2: MEDICAL HISTORY ---
    st.markdown("#### 📜 Longitudinal Medical History")
    history = PatientHistoryService.get_full_history(db, patient_pk_id)
    past_visits = [v for v in history.get("visits", []) if v["visit"].id != visit_db_id]

    if past_visits:
        for item in past_visits[:5]:
            v = item["visit"]
            v_date = v.visit_date.strftime("%Y-%m-%d") if v.visit_date else "Past"
            with st.container():
                st.markdown(f"**Visit `{v.visit_id}` ({v_date})** — Dept: {v.department.name} | Doctor: {v.doctor.user.full_name}")
                if item.get("doctor_note") and item["doctor_note"].diagnosis:
                    st.markdown(f"• **Diagnosis:** {item['doctor_note'].diagnosis}")
                if item.get("prescriptions"):
                    rx_str = ", ".join([f"{rx.medication_name} ({rx.dosage})" for rx in item["prescriptions"]])
                    st.caption(f"• Prescribed: {rx_str}")
                st.markdown("---")
    else:
        st.caption("No prior visits recorded for this patient.")

    st.markdown("---")

    # --- SECTION 3: REPORTS & OCR ---
    st.markdown("#### 📄 Diagnostic Reports & OCR Analysis")
    docs = DocumentService.get_documents_for_visit(db, patient_pk_id, visit_db_id)

    col_up, col_doc = st.columns([1.2, 2])
    with col_up:
        uploaded_doc = st.file_uploader("Upload Lab Report / ECG / X-Ray", type=["pdf", "png", "jpg", "jpeg"], key="case_doc_upload")
        if uploaded_doc and st.button("Attach Document to Visit"):
            try:
                DocumentService.save_document(db, patient_pk_id, visit_db_id, uploaded_doc, uploaded_doc.name)
                db.commit()
                st.success("Document attached successfully.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    with col_doc:
        if docs:
            for d in docs:
                with st.expander(f"📑 {d.file_name} ({d.file_type.upper()})"):
                    if d.extracted_text:
                        st.markdown("**OCR Extracted Text:**")
                        st.code(d.extracted_text, language="text")
                    else:
                        st.caption("No OCR text extracted.")
        else:
            st.info("No reports attached to this visit yet.")

    st.markdown("---")

    # --- SECTION 4: TIMELINE ---
    st.markdown("#### 🕒 Chronological Patient Care Timeline")
    all_visits = history.get("visits", [])
    if all_visits:
        for it in all_visits:
            vis = it["visit"]
            vis_time = vis.visit_date.strftime("%Y-%m-%d %H:%M") if vis.visit_date else ""
            st.markdown(f"• **{vis_time}** — Visit `{vis.visit_id}` at **{vis.facility.name}** ({vis.department.name}) — Status: `{vis.status}`")
    else:
        st.caption("No timeline records available.")

    st.markdown("---")

    # --- ACTION BAR ---
    c_btn1, c_btn2 = st.columns(2)
    with c_btn1:
        if st.button("💊 Proceed to Prescription & Notes →", use_container_width=True):
            st.session_state.doctor_nav = "Prescription & Notes"
            st.rerun()
    with c_btn2:
        if st.button("🔄 Create Inter-Hospital Referral →", use_container_width=True):
            st.session_state.doctor_nav = "Referrals"
            st.rerun()


def show_doctor_prescription_and_notes(db, doctor_id: int):
    """
    ONE coherent consultation completion section:
    - Clinical Notes (Diagnosis, Treatment plan)
    - Prescription Builder (Multi-drug)
    - Follow-Up Appointment
    - Complete Consultation Button
    """
    token_id = st.session_state.get("selected_token_id")
    if not token_id:
        st.markdown("""
        <div style="
            background-color: #f8fafc;
            border: 2px dashed #cbd5e1;
            border-radius: 12px;
            padding: 40px 20px;
            text-align: center;
            margin: 20px 0;
        ">
            <div style="font-size: 48px; margin-bottom: 12px;">💊</div>
            <h3 style="color: #1e293b; margin-bottom: 8px; font-weight: 700;">No Consultation in Progress</h3>
            <p style="color: #64748b; font-size: 15px; max-width: 520px; margin: 0 auto 20px auto; line-height: 1.5;">
                To record clinical diagnoses, write prescriptions, and schedule follow-ups, select an active patient from <strong>My Queue</strong>.
            </p>
        </div>
        """, unsafe_allow_html=True)
        col_s1, col_btn, col_s2 = st.columns([1.5, 1, 1.5])
        with col_btn:
            if st.button("← Go to My Queue", use_container_width=True, key="btn_rx_go_queue"):
                st.session_state.doctor_nav = "My Queue"
                st.rerun()
        return

    patient_details = DoctorService.get_patient_details(db, doctor_id, token_id)
    if not patient_details:
        st.error("Patient details not accessible.")
        return

    patient_pk_id = patient_details["patient_pk_id"]
    visit_db_id = patient_details["visit_db_id"]

    # Header banner
    st.markdown(f"## 💊 Prescription & Clinical Notes — **{patient_details['patient_name']}**")
    _render_workflow_trail(DOCTOR_WORKFLOW, "rx")
    st.caption(f"Patient ID: `{patient_details['patient_id']}` | Token: `{patient_details['token_number']}` | Dept: {patient_details['department']}")
    if st.button("← Back to Patient Case", use_container_width=False, key="btn_rx_back_case"):
        st.session_state.doctor_nav = "Patient Case"
        st.rerun()
    st.markdown("---")

    # 1. Clinical Notes & Diagnosis
    st.markdown("### 🩺 Clinical Diagnosis & Notes")
    existing_note = DoctorNoteService.get_note_for_visit(db, visit_db_id)

    with st.form("clinical_notes_form"):
        diag_input = st.text_input(
            "Primary Diagnosis *",
            value=existing_note.diagnosis if existing_note else "",
            placeholder="e.g. Acute Bronchitis, Essential Hypertension, Suspected Angina"
        )
        plan_input = st.text_area(
            "Treatment Plan / Clinical Instructions",
            value=existing_note.treatment_plan if existing_note else "",
            placeholder="e.g. Rest, hydration, review in 7 days"
        )
        exam_input = st.text_area(
            "Physical Examination Findings",
            value=existing_note.examination_findings if existing_note else "",
            placeholder="e.g. Chest clear on auscultation, BP 130/85 mmHg, Pulse 78 bpm"
        )
        save_notes_btn = st.form_submit_button("💾 Save Clinical Notes")

        if save_notes_btn:
            if not diag_input.strip():
                st.error("Diagnosis is required.")
            else:
                try:
                    DoctorNoteService.save_note(
                        db,
                        visit_id=visit_db_id,
                        patient_id=patient_pk_id,
                        doctor_id=doctor_id,
                        diagnosis=diag_input.strip(),
                        treatment_plan=plan_input.strip(),
                        examination_findings=exam_input.strip()
                    )
                    db.commit()
                    st.success("✓ Clinical notes and diagnosis saved.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    st.markdown("---")

    # 2. Prescription Builder
    st.markdown("### 💊 Prescription")

    # Form to add medication
    with st.form("add_medication_form", clear_on_submit=True):
        st.markdown("##### ➕ Add Medication")
        c_m1, c_m2, c_m3 = st.columns([2, 1, 1.2])
        with c_m1:
            med_name = st.text_input("Medication Name *", placeholder="e.g. Paracetamol, Amoxicillin, Aspirin")
        with c_m2:
            dosage = st.text_input("Dosage *", placeholder="e.g. 500mg, 10ml, 75mg")
        with c_m3:
            frequency = st.selectbox("Frequency *", [
                "Once daily (OD)",
                "Twice daily (BD)",
                "Three times daily (TDS)",
                "Four times daily (QDS)",
                "As needed (SOS)",
                "At bedtime (HS)"
            ])

        c_m4, c_m5 = st.columns([1, 2])
        with c_m4:
            duration = st.text_input("Duration *", placeholder="e.g. 5 days, 1 month")
        with c_m5:
            instructions = st.text_input("Special Instructions", placeholder="e.g. After meals, with water")

        add_med_btn = st.form_submit_button("➕ Add to Prescription")

        if add_med_btn:
            if not med_name or not dosage or not duration:
                st.error("Medication name, dosage, and duration are required.")
            else:
                try:
                    PrescriptionService.create_prescription(
                        db,
                        visit_id=visit_db_id,
                        patient_id=patient_pk_id,
                        doctor_id=doctor_id,
                        medication_name=med_name.strip(),
                        dosage=dosage.strip(),
                        frequency=frequency,
                        duration=duration.strip(),
                        instructions=instructions.strip()
                    )
                    db.commit()
                    st.success(f"✓ Added {med_name} to prescription.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    # Existing medications for this visit
    current_prescriptions = PrescriptionService.get_prescriptions_for_visit(db, visit_db_id)
    if current_prescriptions:
        st.markdown("##### Prescribed Medications for this Visit:")
        for i, rx in enumerate(current_prescriptions, 1):
            st.markdown(f"**{i}. {rx.medication_name}** — `{rx.dosage}` | Frequency: **{rx.frequency}** | Duration: **{rx.duration}**" + (f" | *{rx.instructions}*" if rx.instructions else ""))
    else:
        st.caption("No medications added yet for this visit.")

    st.markdown("---")

    # 3. Follow-Up Scheduling
    st.markdown("### 📅 Follow-Up Scheduling")
    col_f1, col_f2 = st.columns([1, 2])
    with col_f1:
        fup_date = st.date_input("Follow-Up Date", value=datetime.utcnow() + timedelta(days=7))
    with col_f2:
        fup_reason = st.text_input("Follow-Up Clinical Reason", placeholder="e.g. Review response to medication, BP check")

    if st.button("📅 Schedule Follow-Up Appointment"):
        try:
            FollowUpService.schedule_followup(
                db,
                visit_id=visit_db_id,
                patient_id=patient_pk_id,
                doctor_id=doctor_id,
                follow_up_date=datetime.combine(fup_date, datetime.min.time()),
                reason=fup_reason.strip() or "Routine review"
            )
            db.commit()
            st.success(f"✓ Follow-up scheduled for {fup_date.strftime('%Y-%m-%d')}.")
        except Exception as e:
            st.error(f"Error scheduling follow-up: {e}")

    st.markdown("---")

    # 4. Complete Visit Button
    c_comp, c_ref = st.columns([1.5, 1.5])
    with c_comp:
        if st.button("✓ Complete Consultation & Return to Queue", use_container_width=True):
            DoctorService.update_token_status(db, doctor_id, token_id, "COMPLETED")
            db.commit()
            st.session_state.selected_token_id = None
            st.session_state.doctor_nav = "My Queue"
            st.success("✓ Consultation marked as completed.")
            st.rerun()
    with c_ref:
        if st.button("🔄 Create Inter-Hospital Referral", use_container_width=True):
            st.session_state.doctor_nav = "Referrals"
            st.rerun()


def show_doctor_referrals(db, doctor_id: int):
    """Inter-hospital referral workflow: Create referral package & view sent referrals."""
    st.markdown("## 🔄 Inter-Hospital Referral System")
    _render_workflow_trail(DOCTOR_WORKFLOW, "referral")
    st.caption("Seamless patient data handoff between facilities. No duplicate patient records.")

    back_col_1, back_col_2 = st.columns(2)
    with back_col_1:
        if st.button("← Back to Patient Case", use_container_width=True, key="btn_ref_back_case"):
            st.session_state.doctor_nav = "Patient Case"
            st.rerun()
    with back_col_2:
        if st.button("← Back to Prescription & Notes", use_container_width=True, key="btn_ref_back_rx"):
            st.session_state.doctor_nav = "Prescription & Notes"
            st.rerun()

    tabs = st.tabs(["📤 Create Inter-Hospital Referral", "📋 My Outgoing Referrals"])

    # Tab 1: Create Referral
    with tabs[0]:
        token_id = st.session_state.get("selected_token_id")
        if not token_id:
            st.markdown("""
            <div style="
                background-color: #f8fafc;
                border: 2px dashed #cbd5e1;
                border-radius: 12px;
                padding: 40px 20px;
                text-align: center;
                margin: 20px 0;
            ">
                <div style="font-size: 48px; margin-bottom: 12px;">📤</div>
                <h3 style="color: #1e293b; margin-bottom: 8px; font-weight: 700;">Select a Patient to Refer</h3>
                <p style="color: #64748b; font-size: 15px; max-width: 520px; margin: 0 auto 20px auto; line-height: 1.5;">
                    Inter-hospital referrals bundle a patient's current visit data, symptoms, diagnosis, and reports into a secure handoff package. Select a patient from <strong>My Queue</strong> to originate a referral.
                </p>
            </div>
            """, unsafe_allow_html=True)
            col_s1, col_btn, col_s2 = st.columns([1.5, 1, 1.5])
            with col_btn:
                if st.button("← Go to My Queue", use_container_width=True, key="btn_ref_go_queue"):
                    st.session_state.doctor_nav = "My Queue"
                    st.rerun()
        else:
            patient_details = DoctorService.get_patient_details(db, doctor_id, token_id)
            if not patient_details:
                st.error("Patient details not accessible.")
                return

            patient_pk_id = patient_details["patient_pk_id"]
            visit_db_id = patient_details["visit_db_id"]

            st.markdown(f"#### Referring: **{patient_details['patient_name']}** (`{patient_details['patient_id']}`)")
            st.caption(f"Current Visit: `{patient_details.get('visit_id', '')}` | Age: {patient_details['age']}")

            # Get current facility
            doc_info = DoctorService.get_doctor_by_id(db, doctor_id)
            curr_facility_id = doc_info.get("facility_id", 1)

            # Available secondary / tertiary facilities
            dest_facilities = ReferralService.get_available_facilities(db, exclude_facility_id=curr_facility_id)
            if not dest_facilities:
                dest_facilities = ReferralService.get_available_facilities(db)

            if not dest_facilities:
                st.error("No destination facilities registered.")
                return

            fac_map = {f.name: f.id for f in dest_facilities}
            selected_fac_name = st.selectbox("1. Select Destination Hospital *", list(fac_map.keys()))
            selected_fac_id = fac_map[selected_fac_name]

            # Departments
            departments = ReferralService.get_departments_for_facility(db, selected_fac_id)
            dept_map = {d.name: d.id for d in departments}
            if not dept_map:
                st.warning("No departments available in selected hospital.")
                return
            selected_dept_name = st.selectbox("2. Select Department *", list(dept_map.keys()))
            selected_dept_id = dept_map[selected_dept_name]

            # Doctors
            doctors = ReferralService.get_doctors_for_department(db, selected_dept_id)
            doc_rec_map = {f"{d.user.full_name} ({d.specialization})": d.id for d in doctors} if doctors else {}
            selected_rec_doc_id = None
            if doc_rec_map:
                selected_doc_label = st.selectbox("3. Select Available Doctor (Optional)", ["Any Available Specialist"] + list(doc_rec_map.keys()))
                if selected_doc_label != "Any Available Specialist":
                    selected_rec_doc_id = doc_rec_map[selected_doc_label]

            c_urg, c_date = st.columns(2)
            with c_urg:
                urgency = st.selectbox("4. Urgency Level *", ["routine", "urgent", "emergency"])
            with c_date:
                app_date = st.date_input("5. Preferred Appointment Date", value=datetime.utcnow() + timedelta(days=5))

            reason = st.text_area(
                "6. Referral Reason & Clinical Justification *",
                placeholder="e.g. Suspected CAD requiring specialist angiography and cardiology evaluation."
            )

            st.markdown("##### 📦 Authorized Referral Data Package Contents:")
            st.markdown("""
            - ✓ Basic patient demographics (Name, Age, Sex, Masked Phone)
            - ✓ Current visit chief complaint, symptoms & duration
            - ✓ Physical examination findings & diagnosis
            - ✓ Active prescribed medications from this visit
            - ✓ Attached lab reports / documents & OCR extracted text
            """)

            if st.button("📤 Send Patient Data (Create Referral Package)", use_container_width=True):
                if not reason.strip():
                    st.error("Referral reason is required.")
                else:
                    try:
                        referral = ReferralService.create_referral(
                            db=db,
                            visit_id=visit_db_id,
                            patient_id=patient_pk_id,
                            referring_doctor_id=doctor_id,
                            referring_facility_id=curr_facility_id,
                            receiving_facility_id=selected_fac_id,
                            receiving_department_id=selected_dept_id,
                            receiving_doctor_id=selected_rec_doc_id,
                            reason=reason.strip(),
                            urgency=urgency,
                            appointment_date=datetime.combine(app_date, datetime.min.time())
                        )
                        # Build data package
                        pkg = ReferralService.build_data_package(db, referral.id)
                        # Generate PDF
                        pdf_path = ReferralService.generate_referral_pdf(db, referral.id)
                        db.commit()

                        st.success(f"✓ Referral Package Created Successfully: `{referral.referral_id}`")
                        st.markdown(f"""
                        <div style="background-color: #f0fdf4; border-left: 4px solid #16a34a; padding: 16px; border-radius: 8px; margin: 12px 0;">
                            <h4 style="color: #166534; margin: 0 0 8px 0;">Referral Dispatched to {selected_fac_name}</h4>
                            <p style="margin: 0; color: #1e293b;">
                                🔐 <strong>Patient Verification Code:</strong> <code>{referral.verification_code}</code><br>
                                The patient and receiving hospital referral desk will use this code for secure intake handoff.
                            </p>
                        </div>
                        """, unsafe_allow_html=True)

                        if pdf_path and os.path.exists(pdf_path):
                            with open(pdf_path, "rb") as pf:
                                st.download_button(
                                    label=f"📄 Download Referral PDF ({referral.referral_id})",
                                    data=pf.read(),
                                    file_name=os.path.basename(pdf_path),
                                    mime="application/pdf",
                                    key=f"dl_just_created_{referral.id}"
                                )
                    except Exception as e:
                        st.error(f"Error creating referral: {e}")

    # Tab 2: Outgoing Referrals List
    with tabs[1]:
        st.markdown("#### Referrals Sent by You")
        # FIXED: use clean service method directly without wrapping in db.query()
        sent_referrals = ReferralService.get_referrals_sent_by_doctor(db, doctor_id)

        if sent_referrals:
            for ref in sent_referrals:
                with st.container():
                    col_info, col_dl = st.columns([3.5, 1.5])
                    with col_info:
                        st.markdown(f"**Referral `{ref.referral_id}`** — **{ref.patient.full_name}** (`{ref.patient.patient_id}`)")
                        st.caption(f"To: **{ref.receiving_facility.name}** ({ref.receiving_department.name}) | Urgency: `{ref.urgency.upper()}` | Status: `{ref.status}`")
                        st.markdown(f"Verification Code: `{ref.verification_code}` | Date: {ref.created_at.strftime('%Y-%m-%d') if ref.created_at else 'N/A'}")
                        if ref.reason:
                            st.caption(f"Reason: {ref.reason[:100]}...")
                    with col_dl:
                        if ref.data_package and ref.data_package.pdf_path and os.path.exists(ref.data_package.pdf_path):
                            with open(ref.data_package.pdf_path, "rb") as pdf_file:
                                st.download_button(
                                    label=f"📄 Download PDF",
                                    data=pdf_file.read(),
                                    file_name=os.path.basename(ref.data_package.pdf_path),
                                    mime="application/pdf",
                                    key=f"dl_sent_ref_{ref.id}",
                                    use_container_width=True
                                )
                    st.markdown("---")
        else:
            st.markdown("""
            <div style="
                background-color: #f8fafc;
                border: 1px dashed #cbd5e1;
                border-radius: 10px;
                padding: 30px 20px;
                text-align: center;
                margin: 15px 0;
            ">
                <div style="font-size: 36px; margin-bottom: 8px;">📋</div>
                <h4 style="color: #334155; margin-bottom: 6px; font-weight: 600;">No Outgoing Referrals Created Yet</h4>
                <p style="color: #64748b; font-size: 14px; margin: 0;">
                    Referrals you dispatch to secondary or tertiary facilities will be logged here with verification codes and PDF records.
                </p>
            </div>
            """, unsafe_allow_html=True)


# ==============================================================================
# SECTION 7: PATIENT PORTAL & WHATSAPP SIMULATOR
# Standalone WhatsApp-style patient experience
# ==============================================================================

def show_patient_portal_page(db):
    """WhatsApp-styled patient portal simulator."""
    patient_id = st.session_state.get("patient_portal_id")
    patient = db.query(Patient).filter(Patient.id == patient_id).first() if patient_id else None

    if not patient:
        st.warning("No patient record loaded.")
        if st.button("Return to Staff Login"):
            AuthSessionService.logout()
            st.rerun()
        return

    st.sidebar.markdown(f"### 📱 Patient Portal")
    st.sidebar.markdown(f"**{patient.full_name}**")
    st.sidebar.caption(f"ID: `{patient.patient_id}`")
    st.sidebar.caption(f"📞 `{patient.phone}`")

    # Patient switcher for demo
    other_patients = db.query(Patient).limit(10).all()
    if other_patients:
        p_map = {f"{p.full_name} ({p.patient_id})": p.id for p in other_patients}
        current_p_label = next((k for k, v in p_map.items() if v == patient.id), None)
        selected_p_label = st.sidebar.selectbox("Switch Demo Patient", list(p_map.keys()), index=list(p_map.keys()).index(current_p_label) if current_p_label in p_map else 0)
        if p_map[selected_p_label] != patient.id:
            st.session_state.patient_portal_id = p_map[selected_p_label]
            st.rerun()

    if st.sidebar.button("🚪 Exit Patient View", use_container_width=True):
        AuthSessionService.logout()
        st.rerun()

    # WhatsApp-style Header
    st.markdown("""
    <div style="background-color: #075e54; color: white; padding: 14px 20px; border-radius: 10px 10px 0 0; display: flex; align-items: center;">
        <div style="font-size: 26px; margin-right: 12px;">🏥</div>
        <div>
            <div style="font-size: 17px; font-weight: 700;">MED-SETU Health Assistant</div>
            <div style="font-size: 12px; opacity: 0.85;">Official Healthcare Companion • Online</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.info("ℹ️ **DEMONSTRATION SIMULATION:** This view simulates the MED-SETU WhatsApp & SMS patient companion experience for live SIH demonstration.")

    view_mode = st.radio(
        "WhatsApp Navigation",
        ["💬 Messages & Case Submission", "📅 Appointments / Follow-ups", "🏥 Referrals & Shared Data"],
        horizontal=True
    )

    latest_visit = PatientService.get_latest_visit_for_patient(db, patient.id)
    latest_token = TokenService.get_latest_token_for_patient(db, patient.id)

    # Mode 1: Messages & Case Submission
    if "Messages" in view_mode:
        st.markdown(f"##### Hello, {patient.full_name}! 👋")
        st.caption("Submit your symptoms or medical test photos before meeting the doctor.")

        # Live token card if token exists
        if latest_token:
            doc_name = latest_token.doctor.user.full_name if latest_token.doctor and latest_token.doctor.user else "Assigned Specialist"
            st.markdown(f"""
            <div style="background-color: #dcf8c6; border-radius: 8px; padding: 12px 16px; margin: 10px 0; color: #1e293b;">
                🎫 <strong>Queue Token: {latest_token.token_number}</strong> • Status: <strong>{latest_token.status.value}</strong><br>
                Doctor: <strong>{doc_name}</strong>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")
        with st.form("patient_whatsapp_case_form"):
            complaint = st.text_area("Describe your symptoms:", placeholder="e.g. Severe chest tightness radiating to left shoulder for 2 hours.")
            duration = st.text_input("How long have you experienced this?", placeholder="e.g. 2 hours, 3 days")
            symptoms_list = st.text_input("Other symptoms (optional):", placeholder="e.g. shortness of breath, sweating")

            c_v1, c_v2 = st.columns(2)
            with c_v1:
                uploaded_doc = st.file_uploader("📎 Attach Medical Report / ECG / Prescription", type=["pdf", "png", "jpg", "jpeg"])
            with c_v2:
                sim_voice = st.checkbox("Simulate Voice Input ('I have chest tightness and pain')")

            submit_case = st.form_submit_button("Send to Doctor 📤", use_container_width=True)

            if submit_case:
                if not complaint and not sim_voice:
                    st.error("Please describe your symptoms or enable voice input.")
                elif not latest_visit:
                    st.error("No active hospital visit found. Please register at the front desk first.")
                else:
                    final_complaint = "I have chest tightness and severe pain" if sim_voice else complaint
                    PatientCaseService.submit_case(
                        db=db,
                        patient_id=patient.id,
                        visit_id=latest_visit.id,
                        chief_complaint=final_complaint,
                        duration=duration or "2 hours",
                        symptoms=symptoms_list or "chest pain",
                        additional_notes="Submitted via MED-SETU WhatsApp Simulator" + (" (Simulated voice note attached)" if sim_voice else "")
                    )
                    if uploaded_doc:
                        DocumentService.save_document(db, patient.id, latest_visit.id, uploaded_doc, uploaded_doc.name)

                    db.commit()
                    st.success("✓ Sent! Your doctor has received your symptoms and preliminary case.")
                    st.rerun()

    # Mode 2: Appointments / Follow-ups
    elif "Appointments" in view_mode:
        st.markdown("#### 📅 Scheduled Appointments & Follow-ups")
        followups = FollowUpService.get_followups_for_patient(db, patient.id)
        if followups:
            for f in followups:
                doc_name = f.doctor.user.full_name if f.doctor and f.doctor.user else "Doctor"
                st.markdown(f"""
                <div style="background-color: #fef3c7; border-left: 4px solid #d97706; padding: 12px; border-radius: 6px; margin-bottom: 10px;">
                    ⏰ <strong>Upcoming Follow-Up:</strong> {f.follow_up_date.strftime('%d %B %Y')}<br>
                    <strong>Reason:</strong> {f.reason} • <strong>Doctor:</strong> {doc_name} • Status: <code>{f.status}</code>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No upcoming follow-up appointments scheduled.")

        # Prescriptions summary
        st.markdown("---")
        st.markdown("#### 💊 Active Prescriptions")
        prescriptions = PrescriptionService.get_patient_prescription_history(db, patient.id)
        if prescriptions:
            for rx in prescriptions:
                st.markdown(f"""
                <div style="background-color: #f1f5f9; border-left: 4px solid #2563eb; padding: 10px 14px; border-radius: 6px; margin-bottom: 8px;">
                    <strong>{rx.medication_name}</strong> ({rx.dosage}) — {rx.frequency} for {rx.duration}<br>
                    <span style="font-size: 12px; color: #64748b;">Instructions: {rx.instructions or 'As directed'}</span>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No prescriptions recorded.")

    # Mode 3: Referrals & Shared Data
    elif "Referrals" in view_mode:
        st.markdown("#### 🏥 Inter-Hospital Referral Status")
        referrals = ReferralService.get_referrals_for_patient(db, patient.id)

        if referrals:
            for ref in referrals:
                app_date_str = ref.appointment_date.strftime('%d %B %Y') if ref.appointment_date else "Next week"
                rec_doc = ref.receiving_doctor.user.full_name if ref.receiving_doctor and ref.receiving_doctor.user else "Specialist Team"
                st.markdown(f"""
                <div style="background-color: #e0f2fe; border-left: 4px solid #0284c7; padding: 16px; border-radius: 8px; margin-bottom: 14px;">
                    <h4 style="color: #0369a1; margin: 0 0 6px 0;">🏥 Your referral has been sent to {ref.receiving_facility.name}</h4>
                    <strong>Department:</strong> {ref.receiving_department.name}<br>
                    <strong>Doctor:</strong> {rec_doc}<br>
                    <strong>Appointment Date:</strong> {app_date_str}<br>
                    <strong>Address:</strong> {ref.receiving_facility.address}<br>
                    <br>
                    🔐 <strong>Your Referral Verification Code:</strong> <code style="font-size: 16px; font-weight: 700;">{ref.verification_code}</code><br>
                    <p style="font-size: 12px; color: #075985; margin: 8px 0 0 0;">
                        ℹ️ <em>Your medical history, diagnosis, and reports have been authorized and shared with the receiving hospital. Present this verification code at the front desk.</em>
                    </p>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No active referrals for your record.")


# ==============================================================================
# MAIN APPLICATION ROUTER
# ==============================================================================

def main():
    """Main application router with request-scoped session handling."""
    db = get_session()

    try:
        # 1) Re-validate an existing session against live database state.
        #    Force-logout only when the account is genuinely gone/inactive.
        AuthSessionService.revalidate_session(db)

        # 2) If session state is absent (e.g. full browser refresh) but a valid
        #    signed URL token survives, re-establish the session without login.
        if not st.session_state.logged_in:
            AuthSessionService.restore_session(db)

        if not st.session_state.logged_in:
            show_login_page(db)
            return

        role = normalize_role(st.session_state.user_role)

        if role == "receptionist":
            _safe_render("Receptionist", show_receptionist_dashboard, db)
        elif role == "doctor":
            _safe_render("Doctor", show_doctor_dashboard, db)
        elif role == "patient":
            _safe_render("Patient Portal", show_patient_portal_page, db)
        else:
            show_login_page(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
