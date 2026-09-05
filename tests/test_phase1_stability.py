"""Phase 1 stability, session continuity, and authorization tests for MED-SETU.

Covers:
- Token roundtrip / tamper / expiry
- Role normalization & admin-role gating
- Staff login role mapping
- Doctor queue isolation
- Referral cross-facility denial
- Token generation on in-memory DB
- AppTest: login persists across rerun, nav/patient selection persists, URL-token restore, logout clears token

All DB tests use in-memory SQLite via tests.test_db_helper.create_isolated_test_db()
and never touch the production med_setu.db file.
"""
import os
import time
import pytest
from tests.test_db_helper import create_isolated_test_db
from services.session_service import (
    AuthSessionService,
    normalize_role,
    is_role_allowed,
    ADMIN_LIKE_ROLES,
    STAFF_ROLES,
    PARAM_KEY,
)
from services.auth_service import AuthService
from services.patient_service import PatientService
from services.visit_service import VisitService
from services.management_service import ManagementService
from services.token_service import TokenService
from database.models import User, Patient, Doctor, Facility, Department, UserRole


# ──────────────────────────────────────────────────────
# 1. Pure token unit tests
# ──────────────────────────────────────────────────────

class TestTokenRoundtrip:
    def test_valid_token_roundtrip(self):
        t = AuthSessionService.issue_token(user_id=42, role="receptionist")
        payload = AuthSessionService.validate_token(t)
        assert payload is not None
        assert payload["uid"] == 42
        assert payload["role"] == "receptionist"

    def test_tampered_token_rejected(self):
        t = AuthSessionService.issue_token(user_id=7, role="doctor")
        assert AuthSessionService.validate_token(t + "x") is None

    def test_expired_token_rejected(self):
        t = AuthSessionService.issue_token(user_id=7, role="doctor", ttl_seconds=-1)
        assert AuthSessionService.validate_token(t) is None

    def test_none_token_rejected(self):
        assert AuthSessionService.validate_token(None) is None

    def test_empty_string_rejected(self):
        assert AuthSessionService.validate_token("") is None

    def test_patient_portal_token(self):
        t = AuthSessionService.issue_token(patient_portal_id=99, role="patient")
        p = AuthSessionService.validate_token(t)
        assert p["pid"] == 99
        assert p["role"] == "patient"
        assert p["uid"] is None


# ──────────────────────────────────────────────────────
# 2. Role normalization & is_role_allowed
# ──────────────────────────────────────────────────────

class TestRoleNormalization:
    def test_plain_string(self):
        assert normalize_role("receptionist") == "receptionist"

    def test_enum_repr_with_dot(self):
        assert normalize_role("UserRole.Receptionist") == "receptionist"
        assert normalize_role("UserRole.HospitalAdmin") == "hospitaladmin"

    def test_none_returns_empty(self):
        assert normalize_role(None) == ""

    def test_whitespace_stripped(self):
        assert normalize_role("  doctor  ") == "doctor"

    def test_is_role_allowed_positive(self):
        assert is_role_allowed("receptionist", STAFF_ROLES) is True

    def test_is_role_allowed_negative(self):
        assert is_role_allowed("doctor", ADMIN_LIKE_ROLES) is False

    def test_enum_value_allowed(self):
        assert is_role_allowed("UserRole.HOSPITAL_ADMIN", ADMIN_LIKE_ROLES) is True


# ──────────────────────────────────────────────────────
# 3. Staff login role mapping
# ──────────────────────────────────────────────────────

class TestStaffLogin:
    def test_receptionist_login(self):
        db = create_isolated_test_db()
        try:
            auth = AuthService.authenticate(db, "receptionist", "password123")
            assert auth is not None
            assert auth["role"] == "receptionist"
            assert auth["user_id"] is not None
        finally:
            db.close()

    def test_doctor_login(self):
        db = create_isolated_test_db()
        try:
            auth = AuthService.authenticate(db, "drkhan", "password123")
            assert auth is not None
            assert auth["role"] == "doctor"
            assert auth["doctor"] is not None
            assert auth["doctor"]["doctor_id"] is not None
        finally:
            db.close()

    def test_receptionist_b_login(self):
        db = create_isolated_test_db()
        try:
            auth = AuthService.authenticate(db, "receptionist_b", "password123")
            assert auth is not None
            assert auth["role"] == "receptionist"
        finally:
            db.close()

    def test_drgupta_login(self):
        db = create_isolated_test_db()
        try:
            auth = AuthService.authenticate(db, "drgupta", "password123")
            assert auth is not None
            assert auth["role"] == "doctor"
        finally:
            db.close()

    def test_wrong_password_returns_none(self):
        db = create_isolated_test_db()
        try:
            assert AuthService.authenticate(db, "receptionist", "wrongpassword") is None
        finally:
            db.close()


# ──────────────────────────────────────────────────────
# 4. Doctor queue isolation
# ──────────────────────────────────────────────────────

class TestDoctorQueueIsolation:
    def test_doctor_sees_only_own_tokens(self):
        from services.doctor_service import DoctorService
        db = create_isolated_test_db()
        try:
            auth_khan = AuthService.authenticate(db, "drkhan", "password123")
            auth_gupta = AuthService.authenticate(db, "drgupta", "password123")
            khan_doc_id = auth_khan["doctor"]["doctor_id"]
            gupta_doc_id = auth_gupta["doctor"]["doctor_id"]

            facility_id = auth_khan["facility"]["id"]
            dept_id = auth_khan["doctor"]["department_id"]
            patient = Patient(patient_id="TQI-001", full_name="Q Test", age=30, gender="Male",
                              phone="9999999999", preferred_language="English")
            db.add(patient)
            db.flush()

            v1 = VisitService.create_visit(db, patient.id, facility_id, dept_id, khan_doc_id)
            v2 = VisitService.create_visit(db, patient.id, facility_id, dept_id, gupta_doc_id)
            db.flush()
            t1 = TokenService.create_token(db, v1.id, khan_doc_id)
            t2 = TokenService.create_token(db, v2.id, gupta_doc_id)
            db.commit()

            khan_q = DoctorService.get_doctor_queue_data(db, khan_doc_id)
            gupta_q = DoctorService.get_doctor_queue_data(db, gupta_doc_id)

            khan_token_ids = {r["token_id"] for r in khan_q}
            gupta_token_ids = {r["token_id"] for r in gupta_q}
            assert t1.id in khan_token_ids
            assert t2.id not in khan_token_ids
            assert t2.id in gupta_token_ids
            assert t1.id not in gupta_token_ids
        finally:
            db.close()


# ──────────────────────────────────────────────────────
# 5. Referral cross-facility denial
# ──────────────────────────────────────────────────────

class TestReferralCrossFacilityDenial:
    def test_receptionist_b_cannot_retrieve_receptionist_a_referrals(self):
        from services.referral_service import ReferralService
        from database.models import Referral
        from datetime import datetime, timedelta
        db = create_isolated_test_db()
        try:
            auth_a = AuthService.authenticate(db, "receptionist", "password123")
            auth_b = AuthService.authenticate(db, "receptionist_b", "password123")
            fac_a_id = auth_a["facility"]["id"]
            fac_b_id = auth_b["facility"]["id"]

            patient = Patient(patient_id="XCF-001", full_name="XCF Test", age=40, gender="Female",
                              phone="8888888888", preferred_language="English")
            db.add(patient)
            db.flush()

            a_khan = db.query(User).filter(User.username == "drkhan").first()
            a_facility = a_khan.facility
            dept_a = a_khan.doctor.department
            b_gupta = db.query(User).filter(User.username == "drgupta").first()
            b_facility = b_gupta.facility
            dept_b = b_gupta.doctor.department
            if not all([a_khan.doctor, b_gupta.doctor]):
                pytest.skip("Seed data missing required doctor records")

            v = VisitService.create_visit(db, patient.id, a_facility.id, dept_a.id, a_khan.doctor.id)
            db.flush()
            referral = ReferralService.create_referral(
                db, v.id, patient.id, a_khan.doctor.id, a_facility.id,
                b_facility.id, dept_b.id, b_gupta.doctor.id,
                reason="Cross-facility test", urgency="urgent",
                appointment_date=datetime.utcnow() + timedelta(days=3),
            )
            ReferralService.build_data_package(db, referral.id)
            db.commit()
            code = referral.verification_code

            # Negative: receiving facility B finds it
            verified = ReferralService.lookup_referral(db, patient.phone, code, b_facility.id)
            assert verified is not None, "Facility B should be able to look up the referral"

            # Negative: source facility A must NOT retrieve B's referral
            denied = ReferralService.lookup_referral(db, patient.phone, code, a_facility.id)
            assert denied is None, "Source facility A must be denied access"
        finally:
            db.close()


# ──────────────────────────────────────────────────────
# 6. Token generation (in-memory DB)
# ──────────────────────────────────────────────────────

class TestTokenGeneration:
    def test_token_creation_and_retrieval(self):
        db = create_isolated_test_db()
        try:
            auth = AuthService.authenticate(db, "receptionist", "password123")
            facility_id = auth["facility"]["id"]
            doc = db.query(Doctor).filter(Doctor.facility_id == facility_id).first()
            assert doc is not None, "Seed data missing doctor"
            patient = db.query(Patient).first()
            v = VisitService.create_visit(db, patient.id, facility_id, doc.department_id, doc.id)
            db.flush()
            t = TokenService.create_token(db, v.id, doc.id)
            db.commit()
            assert t.token_number is not None
            display = TokenService.get_token_display_details(db, t.id)
            assert display is not None
            assert display["patient_name"] == patient.full_name
        finally:
            db.close()


# ──────────────────────────────────────────────────────
# 7. Patient role guards (patient_service/visit_service reject "patient")
# ──────────────────────────────────────────────────────

class TestRoleGuards:
    def test_patient_role_cannot_deactivate_patient(self):
        db = create_isolated_test_db()
        try:
            p = db.query(Patient).first()
            res = PatientService.deactivate_patient(db, p.id, user_role="patient")
            assert res["success"] is False
        finally:
            db.close()

    def test_patient_role_cannot_reactivate_patient(self):
        db = create_isolated_test_db()
        try:
            p = db.query(Patient).first()
            res = PatientService.deactivate_patient(db, p.id, user_role="hospital_admin")
            assert res["success"]
            res2 = PatientService.reactivate_patient(db, p.id, user_role="patient")
            assert res2["success"] is False
        finally:
            db.close()

    def test_doctor_role_cannot_edit_patient_demographics(self):
        db = create_isolated_test_db()
        try:
            p = db.query(Patient).first()
            res = PatientService.edit_patient(db, p.id, "H", 99, "Male", "1234567890", "English", user_role="doctor")
            assert res["success"] is False
        finally:
            db.close()

    def test_doctor_role_cannot_delete_patient(self):
        db = create_isolated_test_db()
        try:
            p = db.query(Patient).first()
            res = PatientService.delete_patient(db, p.id, user_role="doctor", confirmed=True)
            assert res["success"] is False
        finally:
            db.close()

    def test_patient_role_cannot_delete_patient(self):
        db = create_isolated_test_db()
        try:
            p = db.query(Patient).first()
            res = PatientService.delete_patient(db, p.id, user_role="patient", confirmed=True)
            assert res["success"] is False
        finally:
            db.close()


# ──────────────────────────────────────────────────────
# 8. Management service admin-role gating
# ──────────────────────────────────────────────────────

class TestManagementAdminGating:
    def test_doctor_cannot_deactivate_staff(self):
        db = create_isolated_test_db()
        try:
            target = db.query(User).filter(User.username == "receptionist_b").first()
            res = ManagementService.deactivate_staff(db, target.id, requester_role="doctor")
            assert res["success"] is False
        finally:
            db.close()

    def test_doctor_cannot_reactivate_staff(self):
        db = create_isolated_test_db()
        try:
            target = db.query(User).filter(User.username == "receptionist_b").first()
            ManagementService.deactivate_staff(db, target.id, requester_role="hospital_admin")
            res = ManagementService.reactivate_staff(db, target.id, requester_role="doctor")
            assert res["success"] is False
        finally:
            db.close()

    def test_doctor_cannot_deactivate_facility(self):
        db = create_isolated_test_db()
        try:
            fac = db.query(Facility).first()
            res = ManagementService.deactivate_facility(db, fac.id, requester_role="doctor")
            assert res["success"] is False
        finally:
            db.close()

    def test_hospital_admin_can_deactivate_staff(self):
        db = create_isolated_test_db()
        try:
            target = db.query(User).filter(User.username == "receptionist_b").first()
            res = ManagementService.deactivate_staff(db, target.id, requester_role="hospital_admin")
            assert res["success"] is True
        finally:
            db.close()


# ──────────────────────────────────────────────────────
# 9. AppTest: Streamlit session persistence & URL-token restore
# ──────────────────────────────────────────────────────

class TestStreamlitSession:
    APP_PATH = os.path.join(os.path.dirname(__file__), "..", "app.py")
    LOGIN_USER = "receptionist"
    LOGIN_PASS = "password123"

    @staticmethod
    def _ss(at, key, default=None):
        return at.session_state[key] if key in at.session_state else default

    @staticmethod
    def _button_by_label(at, substring):
        matches = [b for b in at.button if substring.lower() in b.label.lower()]
        assert matches, f"No button found containing {substring!r}; labels={[b.label for b in at.button]}"
        return matches[0]

    def _login(self, at) -> None:
        at.text_input[0].set_value(self.LOGIN_USER)
        at.text_input[1].set_value(self.LOGIN_PASS)
        self._button_by_label(at, "Sign In").click()
        at.run()

    def test_login_persists_across_rerun(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(self.APP_PATH, default_timeout=60)
        at.run()
        assert self._ss(at, "logged_in") is False

        self._login(at)
        assert self._ss(at, "logged_in") is True
        assert self._ss(at, "user_role") == "receptionist"

        at.run()
        assert self._ss(at, "logged_in") is True

    def test_nav_and_patient_selection_persist(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(self.APP_PATH, default_timeout=60)
        at.run()
        self._login(at)

        at.session_state["receptionist_nav"] = "Patients"
        at.session_state["selected_patient_id"] = 42
        at.run()
        assert self._ss(at, "receptionist_nav") == "Patients"
        assert self._ss(at, "selected_patient_id") == 42

    def test_url_token_restores_session_after_fresh_app(self):
        from streamlit.testing.v1 import AppTest
        from database.db import get_session
        db = get_session()
        try:
            auth = AuthService.authenticate(db, self.LOGIN_USER, self.LOGIN_PASS)
            assert auth is not None, "Seed login must exist in the primary database"
            token = AuthSessionService.issue_token(auth["user_id"], auth["role"])
        finally:
            db.close()

        at = AppTest.from_file(self.APP_PATH, default_timeout=60)
        at.query_params[PARAM_KEY] = token
        at.run()
        assert self._ss(at, "logged_in") is True
        assert self._ss(at, "user_role") == "receptionist"

    def test_logout_clears_token(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(self.APP_PATH, default_timeout=60)
        at.run()
        self._login(at)
        assert self._ss(at, "logged_in") is True

        at.button(key="rec_logout_btn").click()
        at.run()
        assert self._ss(at, "logged_in") is False
        assert PARAM_KEY not in at.query_params

    def test_patient_simulator_login(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(self.APP_PATH, default_timeout=60)
        at.run()
        self._button_by_label(at, "Patient WhatsApp Simulator").click()
        at.run()
        assert self._ss(at, "logged_in") is True
        assert self._ss(at, "user_role") == "patient"

    def test_patient_exit_clears_session(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(self.APP_PATH, default_timeout=60)
        at.run()
        self._button_by_label(at, "Patient WhatsApp Simulator").click()
        at.run()
        assert self._ss(at, "logged_in") is True

        self._button_by_label(at, "Exit Patient View").click()
        at.run()
        assert self._ss(at, "logged_in") is False
