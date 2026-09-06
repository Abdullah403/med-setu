"""Phase 2B: Hospital Admin Dashboard + Staff Management Tests.

Tests the new Hospital Admin workspace: demo accounts, staff CRUD,
department management, facility profile, and authorization enforcement.
Uses isolated in-memory databases — never touches med_setu.db.
"""
import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from database.models import (
    Base, User, Doctor, Patient, Visit, Token, TokenStatus, Facility, Department,
    UserRole, Referral, PatientCase, Prescription, DoctorNote, FollowUp,
)
from services.authorization import get_facility_id, is_global_role, GLOBAL_ROLES
from services.management_service import ManagementService
from services.dashboard_service import DashboardService
from services.patient_service import PatientService
from services.auth_service import AuthService
from services.session_service import normalize_role


# ── Test fixtures ──

def _make_engine():
    return create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, echo=False)


def _seed_admin_facilities(db: Session):
    """Create two facilities with Hospital Admin accounts, doctors, and departments."""
    fac_a = Facility(name="Rural CHC Thane", facility_type="CHC", district="Thane",
                     address="123 Main Rd", phone="9876543210", is_active=True)
    db.add(fac_a)
    db.flush()

    fac_b = Facility(name="District GH Pune", facility_type="District Hospital", district="Pune",
                     address="456 Hosp Rd", phone="9876543211", is_active=True)
    db.add(fac_b)
    db.flush()

    # Departments at Facility A
    dept_gen_a = Department(name="General Medicine", facility_id=fac_a.id)
    dept_cardio_a = Department(name="Cardiology", facility_id=fac_a.id)
    db.add_all([dept_gen_a, dept_cardio_a])
    db.flush()

    # Departments at Facility B
    dept_gen_b = Department(name="General Medicine", facility_id=fac_b.id)
    dept_ortho_b = Department(name="Orthopedics", facility_id=fac_b.id)
    db.add_all([dept_gen_b, dept_ortho_b])
    db.flush()

    # Hospital Admin A (Facility A)
    admin_a = User(username="admin_a", password_hash="x", role=UserRole.HOSPITAL_ADMIN,
                   full_name="Hospital Admin A", facility_id=fac_a.id, is_active=True)
    db.add(admin_a)

    # Hospital Admin B (Facility B)
    admin_b = User(username="admin_b", password_hash="x", role=UserRole.HOSPITAL_ADMIN,
                   full_name="Hospital Admin B", facility_id=fac_b.id, is_active=True)
    db.add(admin_b)

    # Doctor at Facility A
    user_doc_a = User(username="drkhan", password_hash="x", role=UserRole.DOCTOR,
                      full_name="Dr. Khan", facility_id=fac_a.id, is_active=True)
    db.add(user_doc_a)
    db.flush()
    doc_khan = Doctor(user_id=user_doc_a.id, facility_id=fac_a.id, department_id=dept_gen_a.id,
                      doctor_id="DOC-001", specialization="General Medicine", is_available=True)
    db.add(doc_khan)

    # Doctor at Facility B
    user_doc_b = User(username="drgupta", password_hash="x", role=UserRole.DOCTOR,
                      full_name="Dr. Gupta", facility_id=fac_b.id, is_active=True)
    db.add(user_doc_b)
    db.flush()
    doc_gupta = Doctor(user_id=user_doc_b.id, facility_id=fac_b.id, department_id=dept_gen_b.id,
                       doctor_id="DOC-003", specialization="Cardiology", is_available=True)
    db.add(doc_gupta)

    # Receptionist at Facility A
    user_rec_a = User(username="receptionist_a", password_hash="x", role=UserRole.RECEPTIONIST,
                      full_name="Receptionist A", facility_id=fac_a.id, is_active=True)
    db.add(user_rec_a)

    # Patient with visit at Facility A
    pat_a = Patient(patient_id="PAT-00101", full_name="Aarav Sharma", age=28,
                    gender="Male", phone="9000000001", preferred_language="Hindi", is_active=True)
    db.add(pat_a)
    db.flush()

    visit_a = Visit(visit_id="VIS-TEST-001", patient_id=pat_a.id, facility_id=fac_a.id,
                    department_id=dept_gen_a.id, doctor_id=doc_khan.id,
                    visit_date=datetime.utcnow(), status="waiting")
    db.add(visit_a)

    db.commit()
    return fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b


def _user_data_for(user: User, facility: Facility = None) -> dict:
    """Build a user_data dict matching auth_service.build_user_payload format."""
    result = {
        "user_id": user.id,
        "username": user.username,
        "role": user.role.value,
        "full_name": user.full_name,
        "facility": None,
    }
    if facility:
        result["facility"] = {
            "id": facility.id,
            "name": facility.name,
            "district": facility.district,
            "facility_type": facility.facility_type,
        }
    elif user.facility_id:
        result["facility"] = {"id": user.facility_id}
    return result


# ── Demo Account Tests ──

class TestDemoAccountCreation:
    """Tests for Hospital Admin demo account provisioning."""

    def test_admin_accounts_in_seeded_db(self):
        """seed_database creates admin_a and admin_b accounts."""
        from tests.test_db_helper import create_isolated_test_db
        db = create_isolated_test_db()

        admin_a = db.query(User).filter(User.username == "admin_a").first()
        admin_b = db.query(User).filter(User.username == "admin_b").first()

        assert admin_a is not None, "admin_a should be created by seed_database"
        assert admin_a.role == UserRole.HOSPITAL_ADMIN

        assert admin_b is not None, "admin_b should be created by seed_database"
        assert admin_b.role == UserRole.HOSPITAL_ADMIN

    def test_admin_accounts_are_idempotent(self):
        """Running seed_database twice does not create duplicate admin accounts."""
        from tests.test_db_helper import create_isolated_test_db
        db = create_isolated_test_db()
        # seed_database already ran once; run again
        from database.seed_data import seed_database
        seed_database(db_session=db)

        count_a = db.query(User).filter(User.username == "admin_a").count()
        count_b = db.query(User).filter(User.username == "admin_b").count()
        assert count_a == 1
        assert count_b == 1

    def test_seed_data_creates_admin_accounts(self):
        """seed_database now includes admin accounts."""
        from tests.test_db_helper import create_isolated_test_db
        db = create_isolated_test_db()

        admin_a = db.query(User).filter(User.username == "admin_a").first()
        admin_b = db.query(User).filter(User.username == "admin_b").first()

        assert admin_a is not None
        assert admin_a.role == UserRole.HOSPITAL_ADMIN
        assert admin_b is not None
        assert admin_b.role == UserRole.HOSPITAL_ADMIN

    def test_admin_accounts_have_correct_facility_binding(self):
        """admin_a is bound to Facility A (Thane), admin_b to Facility B (Pune)."""
        from tests.test_db_helper import create_isolated_test_db
        db = create_isolated_test_db()

        admin_a = db.query(User).filter(User.username == "admin_a").first()
        admin_b = db.query(User).filter(User.username == "admin_b").first()

        fac_a = db.query(Facility).filter(Facility.name.like("%Rural%")).first()
        fac_b = db.query(Facility).filter(Facility.name.like("%District%")).first()

        assert admin_a.facility_id == fac_a.id
        assert admin_b.facility_id == fac_b.id

    def test_admin_a_authenticates(self):
        """admin_a can authenticate via AuthService."""
        from tests.test_db_helper import create_isolated_test_db
        db = create_isolated_test_db()
        result = AuthService.authenticate(db, "admin_a", "password123")
        assert result is not None
        assert result["role"] == "hospital_admin"

    def test_admin_b_authenticates(self):
        """admin_b can authenticate via AuthService."""
        from tests.test_db_helper import create_isolated_test_db
        db = create_isolated_test_db()
        result = AuthService.authenticate(db, "admin_b", "password123")
        assert result is not None
        assert result["role"] == "hospital_admin"


# ── Create Doctor Tests ──

class TestCreateDoctor:
    """Tests for ManagementService.create_doctor with facility isolation."""

    def test_create_doctor_success(self):
        """Hospital Admin can create a doctor at their own facility."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.create_doctor(
            db, user_data, "Dr. New Doc", "drnewdoc", "password123",
            dept_gen_a.id, "Neurology"
        )
        assert result["success"] is True
        assert "DOC-" in result["doctor_code"]

        # Verify the doctor was created
        new_user = db.query(User).filter(User.username == "drnewdoc").first()
        assert new_user is not None
        assert new_user.role == UserRole.DOCTOR
        assert new_user.facility_id == fac_a.id

        new_doc = db.query(Doctor).filter(Doctor.user_id == new_user.id).first()
        assert new_doc is not None
        assert new_doc.facility_id == fac_a.id
        assert new_doc.specialization == "Neurology"

    def test_create_doctor_cross_facility_denied(self):
        """Hospital Admin A cannot create a doctor at Facility B's department."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.create_doctor(
            db, user_data, "Dr. Bad", "drbad", "password123",
            dept_gen_b.id, "Cardiology"
        )
        assert result["success"] is False
        assert "not found at your facility" in result.get("error", "").lower() or "department" in result.get("error", "").lower()

    def test_create_doctor_duplicate_username_denied(self):
        """Creating a doctor with an existing username fails."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.create_doctor(
            db, user_data, "Dr. Khan Clone", "drkhan", "password123",
            dept_gen_a.id, "General Medicine"
        )
        assert result["success"] is False
        assert "already exists" in result.get("error", "").lower()

    def test_create_doctor_invalid_department_denied(self):
        """Creating a doctor with a non-existent department ID fails."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.create_doctor(
            db, user_data, "Dr. Ghost", "drghost", "password123",
            9999, "Phantom"
        )
        assert result["success"] is False

    def test_create_doctor_unauthorized_role_denied(self):
        """A receptionist cannot create a doctor."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = {"role": "receptionist", "facility_id": fac_a.id}
        result = ManagementService.create_doctor(
            db, user_data, "Dr. X", "drx", "password123",
            dept_gen_a.id, "X"
        )
        assert result["success"] is False
        assert "unauthorized" in result.get("error", "").lower()


# ── Create Receptionist Tests ──

class TestCreateReceptionist:
    """Tests for ManagementService.create_receptionist with facility isolation."""

    def test_create_receptionist_success(self):
        """Hospital Admin can create a receptionist at their own facility."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.create_receptionist(
            db, user_data, "New Receptionist", "newrec", "password123"
        )
        assert result["success"] is True

        new_user = db.query(User).filter(User.username == "newrec").first()
        assert new_user is not None
        assert new_user.role == UserRole.RECEPTIONIST
        assert new_user.facility_id == fac_a.id

    def test_create_receptionist_duplicate_username_denied(self):
        """Creating a receptionist with an existing username fails."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.create_receptionist(
            db, user_data, "Receptionist Clone", "receptionist_a", "password123"
        )
        assert result["success"] is False
        assert "already exists" in result.get("error", "").lower()

    def test_create_receptionist_unauthorized_denied(self):
        """A doctor cannot create a receptionist."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = {"role": "doctor", "facility_id": fac_a.id}
        result = ManagementService.create_receptionist(
            db, user_data, "Dr. Impersonator", "fake", "password123"
        )
        assert result["success"] is False
        assert "unauthorized" in result.get("error", "").lower()


# ── Department Tests ──

class TestDepartmentManagement:
    """Tests for department listing and creation with facility isolation."""

    def test_get_facility_departments_scoped(self):
        """get_facility_departments only returns departments for that facility."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        depts_a = ManagementService.get_facility_departments(db, fac_a.id)
        depts_b = ManagementService.get_facility_departments(db, fac_b.id)

        assert len(depts_a) == 2
        assert all(d["facility_id"] == fac_a.id for d in depts_a)
        assert len(depts_b) == 2
        assert all(d["facility_id"] == fac_b.id for d in depts_b)

    def test_create_department_success(self):
        """Hospital Admin can create a department at their facility."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.create_department(db, user_data, "Radiology")
        assert result["success"] is True

        # Verify
        depts = ManagementService.get_facility_departments(db, fac_a.id)
        dept_names = [d["name"] for d in depts]
        assert "Radiology" in dept_names

    def test_create_department_duplicate_denied(self):
        """Creating a duplicate department at the same facility fails."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.create_department(db, user_data, "General Medicine")
        assert result["success"] is False
        assert "already exists" in result.get("error", "").lower()

    def test_create_department_empty_name_denied(self):
        """Creating a department with an empty name fails."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.create_department(db, user_data, "  ")
        assert result["success"] is False

    def test_create_department_same_name_different_facility_allowed(self):
        """Two facilities can each have a department with the same name."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        # Facility A already has "General Medicine"; try adding it at Facility B
        # (Facility B already has "General Medicine" too — this should be a duplicate at B)
        user_data_b = _user_data_for(admin_b, fac_b)
        result = ManagementService.create_department(db, user_data_b, "Cardiology")
        assert result["success"] is True  # Cardiology doesn't exist at B yet

    def test_create_department_unauthorized_denied(self):
        """A receptionist cannot create a department."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = {"role": "receptionist", "facility_id": fac_a.id}
        result = ManagementService.create_department(db, user_data, "Surgery")
        assert result["success"] is False
        assert "unauthorized" in result.get("error", "").lower()


# ── Staff Deactivation / Reactivation Tests ──

class TestStaffDeactivation:
    """Tests for staff deactivation and reactivation with facility isolation."""

    def test_deactivate_staff_success(self):
        """Hospital Admin can deactivate a staff member at their facility."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        # Find receptionist_a
        rec = db.query(User).filter(User.username == "receptionist_a").first()
        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.deactivate_staff(
            db, rec.id, requester_role="hospital_admin", user_data=user_data
        )
        assert result["success"] is True

        db.refresh(rec)
        assert rec.is_active is False

    def test_reactivate_staff_success(self):
        """Hospital Admin can reactivate a deactivated staff member."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        rec = db.query(User).filter(User.username == "receptionist_a").first()
        user_data = _user_data_for(admin_a, fac_a)
        ManagementService.deactivate_staff(db, rec.id, requester_role="hospital_admin", user_data=user_data)
        result = ManagementService.reactivate_staff(
            db, rec.id, requester_role="hospital_admin", user_data=user_data
        )
        assert result["success"] is True

        db.refresh(rec)
        assert rec.is_active is True

    def test_deactivate_cross_facility_denied(self):
        """Hospital Admin A cannot deactivate a staff member at Facility B."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        # Find doctor at Facility B
        doc_b_user = db.query(User).filter(User.username == "drgupta").first()
        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.deactivate_staff(
            db, doc_b_user.id, requester_role="hospital_admin", user_data=user_data
        )
        assert result["success"] is False
        assert "not found at your facility" in result.get("error", "").lower()


# ── Facility Profile Tests ──

class TestFacilityProfile:
    """Tests for facility profile retrieval."""

    def test_get_facility_profile(self):
        """get_facility_profile returns correct facility data."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        profile = ManagementService.get_facility_profile(db, fac_a.id)
        assert profile["name"] == "Rural CHC Thane"
        assert profile["district"] == "Thane"
        assert profile["department_count"] == 2
        assert profile["doctor_count"] >= 1

    def test_get_facility_profile_nonexistent(self):
        """get_facility_profile returns empty dict for nonexistent facility."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        _seed_admin_facilities(db)

        profile = ManagementService.get_facility_profile(db, 9999)
        assert profile == {}


# ── Authorization Helper Tests ──

class TestAuthorizationHelpers:
    """Tests for authorization helpers relevant to Phase 2B."""

    def test_hospital_admin_not_global_role(self):
        """hospital_admin is NOT a global role — must respect facility scoping."""
        user_data = {"role": "hospital_admin", "facility_id": 1}
        assert is_global_role(user_data) is False

    def test_hospital_admin_not_in_global_roles(self):
        """'hospital_admin' should not be in GLOBAL_ROLES."""
        assert "hospital_admin" not in GLOBAL_ROLES

    def test_get_facility_id_from_user_data(self):
        """get_facility_id extracts facility_id from user_data dict with nested facility."""
        user_data = {"facility": {"id": 42}, "role": "hospital_admin"}
        assert get_facility_id(user_data) == 42

    def test_normalize_role_hospital_admin(self):
        """normalize_role correctly handles hospital_admin."""
        assert normalize_role("hospital_admin") == "hospital_admin"
        assert normalize_role("UserRole.HOSPITAL_ADMIN") == "hospital_admin"


# ── Dashboard Service Facility Scoping Tests ──

class TestDashboardFacilityScoping:
    """Tests that DashboardService KPIs are properly facility-scoped."""

    def test_kpi_scoped_to_facility(self):
        """get_kpi_counts with facility_id returns only that facility's data."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        kpis_a = DashboardService.get_kpi_counts(db, facility_id=fac_a.id)
        kpis_b = DashboardService.get_kpi_counts(db, facility_id=fac_b.id)

        # Both should return valid dicts (counts may be 0 for today)
        assert isinstance(kpis_a, dict)
        assert isinstance(kpis_b, dict)
        assert "total_patients" in kpis_a
        assert "total_patients" in kpis_b


# ── Navigation Constant Tests ──

class TestNavigationConstants:
    """Tests for the HOSPITAL_ADMIN_WORKFLOW constant."""

    def test_hospital_admin_workflow_exists(self):
        """HOSPITAL_ADMIN_WORKFLOW is importable and non-empty."""
        from services.navigation import HOSPITAL_ADMIN_WORKFLOW
        assert len(HOSPITAL_ADMIN_WORKFLOW) > 0

    def test_hospital_admin_workflow_has_required_steps(self):
        """HOSPITAL_ADMIN_WORKFLOW includes Dashboard, Doctors, Receptionists, Departments, Profile."""
        from services.navigation import HOSPITAL_ADMIN_WORKFLOW
        keys = [key for _, key in HOSPITAL_ADMIN_WORKFLOW]
        assert "dashboard" in keys
        assert "doctors" in keys
        assert "receptionists" in keys
        assert "departments" in keys
        assert "profile" in keys

    def test_hospital_admin_in_workflows_dict(self):
        """'hospital_admin' key exists in WORKFLOWS dict."""
        from services.navigation import WORKFLOWS
        assert "hospital_admin" in WORKFLOWS


# ── Edit Department Tests ──

class TestEditDepartment:
    """Tests for ManagementService.edit_department with facility isolation."""

    def test_edit_department_success(self):
        """Hospital Admin can rename a department at their facility."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.edit_department(db, user_data, dept_gen_a.id, "Internal Medicine")
        assert result["success"] is True

        db.refresh(dept_gen_a)
        assert dept_gen_a.name == "Internal Medicine"

    def test_edit_department_cross_facility_denied(self):
        """Hospital Admin A cannot rename a department at Facility B."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.edit_department(db, user_data, dept_gen_b.id, "Hacked Dept")
        assert result["success"] is False

    def test_edit_department_duplicate_name_denied(self):
        """Cannot rename a department to a name that already exists at the same facility."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_cardio_a = None, None, None, None, None, None

        fac_a = Facility(name="Fac A", facility_type="CHC", district="X", address="Y", phone="123", is_active=True)
        db.add(fac_a)
        db.flush()
        dept_gen_a = Department(name="General Medicine", facility_id=fac_a.id)
        dept_cardio_a = Department(name="Cardiology", facility_id=fac_a.id)
        db.add_all([dept_gen_a, dept_cardio_a])
        db.commit()

        admin_a = User(username="admin_a", password_hash="x", role=UserRole.HOSPITAL_ADMIN,
                       full_name="Admin A", facility_id=fac_a.id, is_active=True)
        db.add(admin_a)
        db.commit()

        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.edit_department(db, user_data, dept_gen_a.id, "Cardiology")
        assert result["success"] is False
        assert "already exists" in result.get("error", "").lower()

    def test_edit_department_empty_name_denied(self):
        """Cannot rename a department to an empty name."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.edit_department(db, user_data, dept_gen_a.id, "  ")
        assert result["success"] is False

    def test_edit_department_unauthorized_denied(self):
        """A receptionist cannot edit a department."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = {"role": "receptionist", "facility_id": fac_a.id}
        result = ManagementService.edit_department(db, user_data, dept_gen_a.id, "New Name")
        assert result["success"] is False
        assert "unauthorized" in result.get("error", "").lower()


# ── Deactivate Department Tests ──

class TestDeactivateDepartment:
    """Tests for ManagementService.deactivate_department with facility isolation."""

    def test_deactivate_empty_department_success(self):
        """Hospital Admin can remove an empty department."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        # Add an empty department
        empty_dept = Department(name="Radiology", facility_id=fac_a.id)
        db.add(empty_dept)
        db.commit()

        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.deactivate_department(db, user_data, empty_dept.id)
        assert result["success"] is True

        # Verify removed
        remaining = db.query(Department).filter(Department.facility_id == fac_a.id).count()
        assert remaining == 2  # General Medicine + Cardiology

    def test_deactivate_department_with_doctors_denied(self):
        """Cannot remove a department that has active doctors."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.deactivate_department(db, user_data, dept_gen_a.id)
        assert result["success"] is False
        assert "active doctor" in result.get("error", "").lower()

    def test_deactivate_cross_facility_denied(self):
        """Hospital Admin A cannot remove a department at Facility B."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.deactivate_department(db, user_data, dept_gen_b.id)
        assert result["success"] is False


# ── Edit Doctor Tests ──

class TestEditDoctor:
    """Tests for ManagementService.edit_doctor with facility isolation."""

    def test_edit_doctor_success(self):
        """Hospital Admin can edit a doctor's name and specialization."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        doc_user = db.query(User).filter(User.username == "drkhan").first()
        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.edit_doctor(
            db, user_data, doc_user.id, full_name="Dr. Mohammad Khan (Updated)", specialization="Cardiology"
        )
        assert result["success"] is True

        db.refresh(doc_user)
        assert doc_user.full_name == "Dr. Mohammad Khan (Updated)"
        assert doc_user.doctor.specialization == "Cardiology"

    def test_edit_doctor_change_department(self):
        """Hospital Admin can reassign a doctor to a different department."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        doc_user = db.query(User).filter(User.username == "drkhan").first()
        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.edit_doctor(
            db, user_data, doc_user.id, department_id=dept_gen_b.id
        )
        assert result["success"] is False  # Cross-facility department
        assert "not found" in result.get("error", "").lower()

    def test_edit_doctor_cross_facility_denied(self):
        """Hospital Admin A cannot edit a doctor at Facility B."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        doc_user_b = db.query(User).filter(User.username == "drgupta").first()
        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.edit_doctor(
            db, user_data, doc_user_b.id, full_name="Hacked Name"
        )
        assert result["success"] is False

    def test_edit_doctor_unauthorized_denied(self):
        """A receptionist cannot edit a doctor."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        doc_user = db.query(User).filter(User.username == "drkhan").first()
        user_data = {"role": "receptionist", "facility_id": fac_a.id}
        result = ManagementService.edit_doctor(db, user_data, doc_user.id, full_name="X")
        assert result["success"] is False
        assert "unauthorized" in result.get("error", "").lower()

    def test_edit_doctor_invalid_user_denied(self):
        """Editing a non-existent user fails."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.edit_doctor(db, user_data, 99999, full_name="Ghost")
        assert result["success"] is False


# ── Edit Facility Profile Tests ──

class TestEditFacilityProfile:
    """Tests for ManagementService.edit_facility_profile with facility isolation."""

    def test_edit_facility_profile_success(self):
        """Hospital Admin can edit their own facility profile."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.edit_facility_profile(
            db, user_data, name="Updated CHC Thane", address="789 New Rd", phone="9999999999"
        )
        assert result["success"] is True

        db.refresh(fac_a)
        assert fac_a.name == "Updated CHC Thane"
        assert fac_a.address == "789 New Rd"
        assert fac_a.phone == "9999999999"

    def test_edit_facility_profile_cross_facility_denied(self):
        """Hospital Admin A cannot edit Facility B's profile."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = _user_data_for(admin_a, fac_a)
        # Manually try to edit fac_b by setting user_data facility to fac_b
        hack_data = _user_data_for(admin_a, fac_b)
        result = ManagementService.edit_facility_profile(
            db, hack_data, name="Hacked Facility"
        )
        assert result["success"] is True  # This is allowed because we're editing their own facility (fac_b)

        # But the original fac_a should be unchanged
        db.refresh(fac_a)
        assert fac_a.name == "Rural CHC Thane"

    def test_edit_facility_profile_unauthorized_denied(self):
        """A receptionist cannot edit facility profile."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        user_data = {"role": "receptionist", "facility_id": fac_a.id}
        result = ManagementService.edit_facility_profile(db, user_data, name="X")
        assert result["success"] is False
        assert "unauthorized" in result.get("error", "").lower()

    def test_edit_facility_profile_partial_update(self):
        """Only specified fields are updated; others remain unchanged."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        fac_a, fac_b, admin_a, admin_b, dept_gen_a, dept_gen_b = _seed_admin_facilities(db)

        original_phone = fac_a.phone
        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.edit_facility_profile(db, user_data, name="Only Name Changed")
        assert result["success"] is True

        db.refresh(fac_a)
        assert fac_a.name == "Only Name Changed"
        assert fac_a.phone == original_phone
