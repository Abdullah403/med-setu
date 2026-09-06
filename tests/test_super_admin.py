"""Phase 2C: Super Admin / Government Admin Workspace Tests.

Tests the Super Admin workspace: global facility management, facility CRUD,
network overview, and authorization enforcement. Uses isolated in-memory
databases — never touches med_setu.db.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from database.models import (
    Base, User, Doctor, Patient, Visit, Token, TokenStatus, Facility, Department,
    UserRole,
)
from services.authorization import (
    get_facility_id, is_global_role, GLOBAL_ROLES, check_staff_access,
)
from services.management_service import ManagementService
from services.session_service import normalize_role
from services.navigation import (
    GOVERNMENT_ADMIN_WORKFLOW, WORKFLOWS, workflow_index,
)


# ── Test fixtures ──

def _make_engine():
    return create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, echo=False)


def _seed_gov_facilities(db: Session):
    """Create two facilities with staff, plus a government admin user."""
    # Facility A
    fac_a = Facility(
        name="Rural CHC Thane",
        facility_type="Community Health Centre",
        district="Thane",
        address="123 Main Road, Thane",
        phone="9876543210",
        is_active=True,
    )
    db.add(fac_a)
    db.flush()

    dept_gen_a = Department(name="General Medicine", facility_id=fac_a.id)
    dept_cardio_a = Department(name="Cardiology", facility_id=fac_a.id)
    db.add_all([dept_gen_a, dept_cardio_a])
    db.flush()

    user_khan = User(
        username="drkhan", password_hash="x", role=UserRole.DOCTOR,
        full_name="Dr. Khan", facility_id=fac_a.id, is_active=True,
    )
    db.add(user_khan)
    db.flush()
    doctor_khan = Doctor(
        user_id=user_khan.id, facility_id=fac_a.id, department_id=dept_gen_a.id,
        doctor_id="DOC-001", specialization="General Medicine", is_available=True,
    )
    db.add(doctor_khan)

    rec_a = User(
        username="receptionist_a", password_hash="x", role=UserRole.RECEPTIONIST,
        full_name="Receptionist A", facility_id=fac_a.id, is_active=True,
    )
    db.add(rec_a)

    admin_a = User(
        username="admin_a", password_hash="x", role=UserRole.HOSPITAL_ADMIN,
        full_name="Hospital Admin A", facility_id=fac_a.id, is_active=True,
    )
    db.add(admin_a)

    # Facility B
    fac_b = Facility(
        name="District GH Pune",
        facility_type="District Hospital",
        district="Pune",
        address="456 Hospital Road, Pune",
        phone="9876543211",
        is_active=True,
    )
    db.add(fac_b)
    db.flush()

    dept_gen_b = Department(name="General Medicine", facility_id=fac_b.id)
    dept_ortho_b = Department(name="Orthopedics", facility_id=fac_b.id)
    db.add_all([dept_gen_b, dept_ortho_b])
    db.flush()

    user_gupta = User(
        username="drgupta", password_hash="x", role=UserRole.DOCTOR,
        full_name="Dr. Gupta", facility_id=fac_b.id, is_active=True,
    )
    db.add(user_gupta)
    db.flush()
    doctor_gupta = Doctor(
        user_id=user_gupta.id, facility_id=fac_b.id, department_id=dept_gen_b.id,
        doctor_id="DOC-003", specialization="Cardiology", is_available=True,
    )
    db.add(doctor_gupta)

    rec_b = User(
        username="receptionist_b", password_hash="x", role=UserRole.RECEPTIONIST,
        full_name="Receptionist B", facility_id=fac_b.id, is_active=True,
    )
    db.add(rec_b)

    admin_b = User(
        username="admin_b", password_hash="x", role=UserRole.HOSPITAL_ADMIN,
        full_name="Hospital Admin B", facility_id=fac_b.id, is_active=True,
    )
    db.add(admin_b)

    # Government Admin (global, no facility)
    gov_admin = User(
        username="gov_admin", password_hash="x", role=UserRole.GOVERNMENT_ADMIN,
        full_name="Super Admin", facility_id=None, is_active=True,
    )
    db.add(gov_admin)

    db.flush()
    return fac_a, fac_b, gov_admin, admin_a, admin_b, dept_gen_a, dept_gen_b


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


# ── Navigation Tests ──

class TestGovernmentAdminNavigation:
    """Verify the government admin workflow constants."""

    def test_workflow_defined(self):
        assert GOVERNMENT_ADMIN_WORKFLOW is not None

    def test_workflow_has_required_steps(self):
        step_keys = [k for _, k in GOVERNMENT_ADMIN_WORKFLOW]
        assert "dashboard" in step_keys
        assert "hospitals" in step_keys
        assert "hospital_details" in step_keys
        assert "network" in step_keys

    def test_workflow_in_workflows_dict(self):
        assert "government_admin" in WORKFLOWS

    def test_workflow_step_count(self):
        assert len(GOVERNMENT_ADMIN_WORKFLOW) == 4

    def test_workflow_index_lookup(self):
        idx = workflow_index(GOVERNMENT_ADMIN_WORKFLOW, "hospitals")
        assert idx is not None
        assert idx >= 0

    def test_hospital_admin_workflow_not_changed(self):
        step_keys = [k for _, k in WORKFLOWS["hospital_admin"]]
        assert "dashboard" in step_keys
        assert "doctors" in step_keys
        assert "receptionists" in step_keys
        assert "departments" in step_keys
        assert "profile" in step_keys


# ── Authorization Tests ──

class TestSuperAdminAuthorization:
    """Verify government_admin is global and bypasses facility checks."""

    def test_government_admin_is_global_role(self):
        """government_admin must be in GLOBAL_ROLES."""
        assert "government_admin" in GLOBAL_ROLES

    def test_is_global_role_for_gov_admin(self):
        user_data = {"role": "government_admin", "facility": None, "user_id": 99}
        assert is_global_role(user_data) is True

    def test_hospital_admin_is_not_global_role(self):
        user_data = {"role": "hospital_admin", "facility": {"id": 1}, "user_id": 1}
        assert is_global_role(user_data) is False

    def test_doctor_is_not_global_role(self):
        user_data = {"role": "doctor", "facility": {"id": 1}, "user_id": 2}
        assert is_global_role(user_data) is False

    def test_receptionist_is_not_global_role(self):
        user_data = {"role": "receptionist", "facility": {"id": 1}, "user_id": 3}
        assert is_global_role(user_data) is False

    def test_gov_admin_facility_id_is_none(self):
        """Government admin has no facility binding."""
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(gov_admin)
        assert get_facility_id(user_data) is None
        db.close()


# ── Facility Management Tests ──

class TestFacilityListing:
    """Super Admin can see all facilities."""

    def test_get_all_facilities(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        facilities = ManagementService.get_all_facilities(db)
        assert len(facilities) >= 2
        names = [f["name"] for f in facilities]
        assert "Rural CHC Thane" in names
        assert "District GH Pune" in names
        db.close()

    def test_facility_fields(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        facilities = ManagementService.get_all_facilities(db)
        f = facilities[0]
        assert "id" in f
        assert "name" in f
        assert "district" in f
        assert "is_active" in f
        assert "doctor_count" in f
        db.close()


class TestFacilityCreation:
    """Super Admin can create new facilities."""

    def test_create_facility_success(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(gov_admin)
        result = ManagementService.create_facility(
            db, user_data, "PHC Navi Mumbai", "Primary Health Centre",
            "Thane", "789 Market Road", "9876543212"
        )
        assert result["success"] is True
        assert "facility_id" in result
        fac = db.query(Facility).filter(Facility.id == result["facility_id"]).first()
        assert fac is not None
        assert fac.name == "PHC Navi Mumbai"
        assert fac.is_active is True
        db.close()

    def test_create_facility_empty_name_denied(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(gov_admin)
        result = ManagementService.create_facility(db, user_data, "  ", "Hospital")
        assert result["success"] is False
        db.close()

    def test_create_facility_duplicate_name_denied(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(gov_admin)
        result = ManagementService.create_facility(
            db, user_data, "Rural CHC Thane", "Hospital"
        )
        assert result["success"] is False
        assert "already exists" in result["error"]
        db.close()

    def test_create_facility_hospital_admin_denied(self):
        """Hospital Admin cannot create facilities."""
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, admin_a, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.create_facility(
            db, user_data, "Unauthorized Hospital", "Hospital"
        )
        assert result["success"] is False
        assert "Unauthorized" in result["error"]
        db.close()

    def test_create_facility_new_is_active(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(gov_admin)
        result = ManagementService.create_facility(
            db, user_data, "Active Hospital", "Hospital", "Pune"
        )
        assert result["success"] is True
        fac = db.query(Facility).filter(Facility.id == result["facility_id"]).first()
        assert fac.is_active is True
        db.close()


class TestFacilityEdit:
    """Super Admin can edit any facility."""

    def test_edit_facility_success(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(gov_admin)
        result = ManagementService.edit_facility_by_id(
            db, user_data, fac_a.id, name="Updated CHC Thane"
        )
        assert result["success"] is True
        db.refresh(fac_a)
        assert fac_a.name == "Updated CHC Thane"
        db.close()

    def test_edit_facility_address(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(gov_admin)
        result = ManagementService.edit_facility_by_id(
            db, user_data, fac_a.id, address="New Address 123", phone="1112223333"
        )
        assert result["success"] is True
        db.refresh(fac_a)
        assert fac_a.address == "New Address 123"
        assert fac_a.phone == "1112223333"
        db.close()

    def test_edit_facility_empty_name_denied(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(gov_admin)
        result = ManagementService.edit_facility_by_id(
            db, user_data, fac_a.id, name="  "
        )
        assert result["success"] is False
        db.close()

    def test_edit_facility_duplicate_name_denied(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(gov_admin)
        result = ManagementService.edit_facility_by_id(
            db, user_data, fac_a.id, name="District GH Pune"
        )
        assert result["success"] is False
        assert "already exists" in result["error"]
        db.close()

    def test_edit_facility_nonexistent_denied(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(gov_admin)
        result = ManagementService.edit_facility_by_id(
            db, user_data, 9999, name="Ghost Hospital"
        )
        assert result["success"] is False
        db.close()

    def test_edit_facility_hospital_admin_denied(self):
        """Hospital Admin cannot edit other facilities."""
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, admin_a, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.edit_facility_by_id(
            db, user_data, fac_b.id, name="Hacked Name"
        )
        assert result["success"] is False
        assert "Unauthorized" in result["error"]
        db.close()


class TestFacilityActivation:
    """Super Admin can activate and deactivate facilities."""

    def test_deactivate_facility_success(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(gov_admin)
        result = ManagementService.deactivate_facility(db, fac_a.id, "government_admin", user_data)
        assert result["success"] is True
        db.refresh(fac_a)
        assert fac_a.is_active is False
        db.close()

    def test_reactivate_facility_success(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(gov_admin)
        ManagementService.deactivate_facility(db, fac_a.id, "government_admin", user_data)
        result = ManagementService.reactivate_facility(db, fac_a.id, "government_admin", user_data)
        assert result["success"] is True
        db.refresh(fac_a)
        assert fac_a.is_active is True
        db.close()

    def test_deactivate_preserves_data(self):
        """Deactivation must not delete the facility or its records."""
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(gov_admin)
        fac_a_id = fac_a.id
        ManagementService.deactivate_facility(db, fac_a_id, "government_admin", user_data)
        fac = db.query(Facility).filter(Facility.id == fac_a_id).first()
        assert fac is not None
        assert fac.name == "Rural CHC Thane"
        depts = db.query(Department).filter(Department.facility_id == fac_a_id).count()
        assert depts >= 2
        db.close()

    def test_hospital_admin_cannot_deactivate_other_facility(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, admin_a, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.deactivate_facility(db, fac_b.id, "hospital_admin", user_data)
        assert result["success"] is False
        assert "Unauthorized" in result["error"]
        db.close()


class TestFacilityDetail:
    """Super Admin can view facility details."""

    def test_get_facility_profile(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        profile = ManagementService.get_facility_profile(db, fac_a.id)
        assert profile["name"] == "Rural CHC Thane"
        assert profile["district"] == "Thane"
        assert profile["is_active"] is True
        assert profile["doctor_count"] >= 1
        assert profile["department_count"] >= 2
        db.close()

    def test_get_facility_departments(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        depts = ManagementService.get_facility_departments(db, fac_a.id)
        assert len(depts) >= 2
        names = [d["name"] for d in depts]
        assert "General Medicine" in names
        assert "Cardiology" in names
        db.close()

    def test_nonexistent_facility_returns_empty(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        profile = ManagementService.get_facility_profile(db, 9999)
        assert profile == {}
        db.close()


# ── Cross-Role Authorization Tests ──

class TestCrossRoleAccess:
    """Verify other roles cannot access Super Admin operations."""

    def test_hospital_admin_cannot_create_facility(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, admin_a, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.create_facility(db, user_data, "Sneaky Hospital")
        assert result["success"] is False

    def test_hospital_admin_cannot_edit_other_facility(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, admin_a, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.edit_facility_by_id(db, user_data, fac_b.id, name="Hacked")
        assert result["success"] is False

    def test_doctor_cannot_create_facility(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        doctor = db.query(User).filter(User.username == "drkhan").first()
        user_data = _user_data_for(doctor, fac_a)
        result = ManagementService.create_facility(db, user_data, "Doctor Hospital")
        assert result["success"] is False

    def test_receptionist_cannot_create_facility(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        rec = db.query(User).filter(User.username == "receptionist_a").first()
        user_data = _user_data_for(rec, fac_a)
        result = ManagementService.create_facility(db, user_data, "Rec Hospital")
        assert result["success"] is False

    def test_doctor_cannot_deactivate_facility(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        doctor = db.query(User).filter(User.username == "drkhan").first()
        user_data = _user_data_for(doctor, fac_a)
        result = ManagementService.deactivate_facility(db, fac_a.id, "doctor", user_data)
        assert result["success"] is False

    def test_receptionist_cannot_deactivate_facility(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        rec = db.query(User).filter(User.username == "receptionist_a").first()
        user_data = _user_data_for(rec, fac_a)
        result = ManagementService.deactivate_facility(db, fac_a.id, "receptionist", user_data)
        assert result["success"] is False


# ── Network Counts Tests ──

class TestNetworkCounts:
    """Verify global counts used in network overview."""

    def test_total_facilities(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        facilities = ManagementService.get_all_facilities(db)
        assert len(facilities) == 2

    def test_active_facilities(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        facilities = ManagementService.get_all_facilities(db)
        active = [f for f in facilities if f["is_active"]]
        assert len(active) == 2

    def test_total_departments_across_facilities(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        total = db.query(Department).count()
        assert total >= 4

    def test_total_doctors_across_facilities(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        total = db.query(Doctor).filter(Doctor.is_available == True).count()
        assert total >= 2

    def test_total_receptionists_across_facilities(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        total = db.query(User).filter(
            User.role == UserRole.RECEPTIONIST, User.is_active == True
        ).count()
        assert total >= 2

    def test_total_hospital_admins(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, admin_a, admin_b, _, _ = _seed_gov_facilities(db)
        total = db.query(User).filter(
            User.role == UserRole.HOSPITAL_ADMIN, User.is_active == True
        ).count()
        assert total >= 2

    def test_gov_admin_not_counted_as_hospital_admin(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        gov_count = db.query(User).filter(
            User.role == UserRole.GOVERNMENT_ADMIN, User.is_active == True
        ).count()
        assert gov_count == 1


# ── Role Normalize Tests ──

class TestRoleNormalization:
    """Verify role normalization works for government_admin."""

    def test_normalize_government_admin(self):
        assert normalize_role("government_admin") == "government_admin"

    def test_normalize_userrole_variant(self):
        assert normalize_role("UserRole.Government_Admin") == "government_admin"

    def test_normalize_lowercase(self):
        assert normalize_role("GOVERNMENT_ADMIN") == "government_admin"


# ── Existing Workflow Regression Tests ──

class TestExistingWorkflowRegression:
    """Verify existing workflows are not broken by Phase 2C changes."""

    def test_hospital_admin_workflow_unchanged(self):
        assert len(WORKFLOWS["hospital_admin"]) == 5
        step_keys = [k for _, k in WORKFLOWS["hospital_admin"]]
        assert "doctors" in step_keys
        assert "receptionists" in step_keys

    def test_doctor_workflow_unchanged(self):
        assert len(WORKFLOWS["doctor"]) == 4

    def test_receptionist_workflow_unchanged(self):
        assert len(WORKFLOWS["receptionist"]) == 5

    def test_all_roles_have_workflows(self):
        for role in ["doctor", "receptionist", "hospital_admin", "government_admin"]:
            assert role in WORKFLOWS

    def test_hospital_admin_still_facility_scoped(self):
        """Hospital Admin must NOT be in GLOBAL_ROLES."""
        assert "hospital_admin" not in GLOBAL_ROLES

    def test_staff_still_cannot_access_facility_management(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, _, _, _, _ = _seed_gov_facilities(db)
        doctor = db.query(User).filter(User.username == "drkhan").first()
        user_data = _user_data_for(doctor, fac_a)
        assert is_global_role(user_data) is False

    def test_facility_isolation_preserved_for_hospital_admin(self):
        engine = _make_engine()
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        fac_a, fac_b, gov_admin, admin_a, _, _, _ = _seed_gov_facilities(db)
        user_data = _user_data_for(admin_a, fac_a)
        result = ManagementService.edit_facility_by_id(db, user_data, fac_b.id, name="X")
        assert result["success"] is False
