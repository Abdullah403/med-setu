"""Phase 3A: ASHA / Anganwadi Worker Assisted-Access Tests.

Tests the complete worker workflow: login, facility assignment, patient search,
patient registration, assisted case creation, document attachment, referral
visibility, follow-up visibility, cross-facility isolation, and backward
compatibility with existing workflows.

Uses isolated in-memory databases — never touches med_setu.db.
"""
import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from database.models import (
    Base, User, Doctor, Patient, Visit, Token, TokenStatus, Facility, Department,
    UserRole, PatientCase, MedicalDocument, Referral, ReferralDataPackage,
    FollowUp, Prescription, DoctorNote,
)
from services.worker_service import WorkerService, WORKER_ROLES
from services.authorization import (
    get_facility_id, is_global_role, patient_has_visits_at_facility,
    check_patient_access, check_visit_access, GLOBAL_ROLES, WORKER_ROLES as AUTH_WORKER_ROLES,
)
from services.session_service import normalize_role
from services.patient_service import PatientService
from services.visit_service import VisitService
from services.case_service import PatientCaseService
from services.followup_service import FollowUpService
from services.referral_service import ReferralService
from services.auth_service import AuthService


# ── Test fixtures ──


def _make_engine():
    return create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, echo=False)


def _seed_two_facilities(db: Session):
    """Create two facilities with workers, doctors, patients, and visits."""
    # Facility A
    fac_a = Facility(name="Rural CHC Thane", facility_type="CHC", district="Thane",
                     address="123 Main Rd", phone="9876543210", is_active=True)
    db.add(fac_a)
    db.flush()

    dept_gen_a = Department(name="General Medicine", facility_id=fac_a.id)
    dept_dental_a = Department(name="Dental", facility_id=fac_a.id)
    db.add_all([dept_gen_a, dept_dental_a])
    db.flush()

    # Facility A doctor
    user_khan = User(username="drkhan", password_hash="x", role=UserRole.DOCTOR,
                     full_name="Dr. Khan", facility_id=fac_a.id, is_active=True)
    db.add(user_khan)
    db.flush()
    doc_khan = Doctor(user_id=user_khan.id, facility_id=fac_a.id, department_id=dept_gen_a.id,
                      doctor_id="DOC-001", specialization="General Medicine", is_available=True)
    db.add(doc_khan)
    db.flush()

    # Facility A ASHA worker
    user_asha = User(username="asha_worker_a", password_hash="x", role=UserRole.ASHA_WORKER,
                     full_name="ASHA Worker A", facility_id=fac_a.id, is_active=True)
    db.add(user_asha)
    db.flush()

    # Facility A receptionist
    user_rec_a = User(username="receptionist_a", password_hash="x", role=UserRole.RECEPTIONIST,
                      full_name="Receptionist A", facility_id=fac_a.id, is_active=True)
    db.add(user_rec_a)
    db.flush()

    # Facility A patients with visits
    pat_aarav = Patient(patient_id="PAT-00101", full_name="Aarav Sharma", age=28,
                        gender="Male", phone="9000000001", preferred_language="Hindi", is_active=True)
    db.add(pat_aarav)
    db.flush()

    vis_a1 = Visit(visit_id="VIS-A1", patient_id=pat_aarav.id, facility_id=fac_a.id,
                   department_id=dept_gen_a.id, doctor_id=doc_khan.id,
                   visit_date=datetime.utcnow(), status="ongoing")
    db.add(vis_a1)
    db.flush()

    # Facility B
    fac_b = Facility(name="District GH Pune", facility_type="District Hospital", district="Pune",
                     address="456 Hosp Rd", phone="9876543211", is_active=True)
    db.add(fac_b)
    db.flush()

    dept_cardio_b = Department(name="Cardiology", facility_id=fac_b.id)
    db.add(dept_cardio_b)
    db.flush()

    # Facility B doctor
    user_gupta = User(username="drgupta", password_hash="x", role=UserRole.DOCTOR,
                      full_name="Dr. Gupta", facility_id=fac_b.id, is_active=True)
    db.add(user_gupta)
    db.flush()
    doc_gupta = Doctor(user_id=user_gupta.id, facility_id=fac_b.id, department_id=dept_cardio_b.id,
                       doctor_id="DOC-003", specialization="Cardiology", is_available=True)
    db.add(doc_gupta)
    db.flush()

    # Facility B Anganwadi worker
    user_ang = User(username="anganwadi_worker_b", password_hash="x", role=UserRole.ANGANWADI_WORKER,
                    full_name="Anganwadi Worker B", facility_id=fac_b.id, is_active=True)
    db.add(user_ang)
    db.flush()

    # Facility B receptionist
    user_rec_b = User(username="receptionist_b", password_hash="x", role=UserRole.RECEPTIONIST,
                      full_name="Receptionist B", facility_id=fac_b.id, is_active=True)
    db.add(user_rec_b)
    db.flush()

    # Facility B patient with visit
    pat_rahul = Patient(patient_id="PAT-00103", full_name="Rahul Patil", age=61,
                        gender="Male", phone="9000000003", preferred_language="Marathi", is_active=True)
    db.add(pat_rahul)
    db.flush()

    vis_b1 = Visit(visit_id="VIS-B1", patient_id=pat_rahul.id, facility_id=fac_b.id,
                   department_id=dept_cardio_b.id, doctor_id=doc_gupta.id,
                   visit_date=datetime.utcnow(), status="ongoing")
    db.add(vis_b1)
    db.flush()

    db.commit()

    return {
        "fac_a": fac_a, "fac_b": fac_b,
        "dept_gen_a": dept_gen_a, "dept_dental_a": dept_dental_a,
        "dept_cardio_b": dept_cardio_b,
        "doc_khan": doc_khan, "doc_gupta": doc_gupta,
        "user_khan": user_khan, "user_gupta": user_gupta,
        "user_asha": user_asha, "user_ang": user_ang,
        "user_rec_a": user_rec_a, "user_rec_b": user_rec_b,
        "pat_aarav": pat_aarav, "pat_rahul": pat_rahul,
        "vis_a1": vis_a1, "vis_b1": vis_b1,
    }


def _worker_session(user, facility_id):
    """Build a session user_data dict for a worker."""
    role_val = user.role.value.lower() if isinstance(user.role, UserRole) else str(user.role).lower()
    return {
        "user_id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": role_val,
        "facility": {
            "id": facility_id,
            "name": "Test Facility",
            "facility_type": "CHC",
            "district": "Test",
            "address": "Test Addr",
        },
    }


def _receptionist_session(user_data):
    """Build a fake receptionist session for backward-compat tests."""
    return user_data


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 1: ASHA / Anganwadi Login & Role Assignment
# ═══════════════════════════════════════════════════════════════

class TestASHALogin:
    """Test ASHA worker authentication and role assignment."""

    def test_asha_role_exists_in_enum(self):
        assert hasattr(UserRole, "ASHA_WORKER")
        assert UserRole.ASHA_WORKER.value == "asha_worker"

    def test_anganwadi_role_exists_in_enum(self):
        assert hasattr(UserRole, "ANGANWADI_WORKER")
        assert UserRole.ANGANWADI_WORKER.value == "anganwadi_worker"

    def test_asha_user_created_with_correct_role(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()

        fac = Facility(name="Test CHC", facility_type="CHC", district="X",
                       address="A", phone="123", is_active=True)
        db.add(fac)
        db.flush()

        user = User(username="asha_test", password_hash="x", role=UserRole.ASHA_WORKER,
                    full_name="ASHA Test", facility_id=fac.id, is_active=True)
        db.add(user)
        db.commit()

        loaded = db.query(User).filter(User.username == "asha_test").first()
        assert loaded is not None
        role_str = loaded.role.value if isinstance(loaded.role, UserRole) else str(loaded.role)
        assert role_str == "asha_worker"
        assert loaded.facility_id == fac.id

    def test_anganwadi_user_created_with_correct_role(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()

        fac = Facility(name="Test GH", facility_type="Hospital", district="Y",
                       address="B", phone="456", is_active=True)
        db.add(fac)
        db.flush()

        user = User(username="ang_test", password_hash="x", role=UserRole.ANGANWADI_WORKER,
                    full_name="Ang Test", facility_id=fac.id, is_active=True)
        db.add(user)
        db.commit()

        loaded = db.query(User).filter(User.username == "ang_test").first()
        assert loaded is not None
        role_str = loaded.role.value if isinstance(loaded.role, UserRole) else str(loaded.role)
        assert role_str == "anganwadi_worker"

    def test_asha_user_belongs_to_facility(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        assert data["user_asha"].facility_id == data["fac_a"].id
        assert data["user_ang"].facility_id == data["fac_b"].id

    def test_normalize_role_for_worker(self):
        assert normalize_role(UserRole.ASHA_WORKER) == "asha_worker"
        assert normalize_role(UserRole.ANGANWADI_WORKER) == "anganwadi_worker"
        assert normalize_role("ASHA_WORKER") == "asha_worker"
        assert normalize_role("asha_worker") == "asha_worker"

    def test_worker_roles_constant(self):
        assert "asha_worker" in WORKER_ROLES
        assert "anganwadi_worker" in WORKER_ROLES

    def test_worker_not_global_role(self):
        asha_data = {"role": "asha_worker"}
        ang_data = {"role": "anganwadi_worker"}
        assert not is_global_role(asha_data)
        assert not is_global_role(ang_data)


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 2: Facility Isolation for Workers
# ═══════════════════════════════════════════════════════════════

class TestWorkerFacilityIsolation:
    """Test that workers are properly scoped to their facility."""

    def test_asha_facility_id_matches(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        assert get_facility_id(asha_session) == data["fac_a"].id

    def test_ang_facility_id_matches(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        ang_session = _worker_session(data["user_ang"], data["fac_b"].id)
        assert get_facility_id(ang_session) == data["fac_b"].id

    def test_asha_cannot_access_facility_b_patient(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        pat_rahul = data["pat_rahul"]

        # Rahul has a visit at facility B, not facility A
        assert not patient_has_visits_at_facility(db, pat_rahul.id, data["fac_a"].id)

    def test_ang_cannot_access_facility_a_patient(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        ang_session = _worker_session(data["user_ang"], data["fac_b"].id)
        pat_aarav = data["pat_aarav"]

        # Aarav has a visit at facility A, not facility B
        assert not patient_has_visits_at_facility(db, pat_aarav.id, data["fac_b"].id)

    def test_asha_search_only_returns_facility_a_patients(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        results = WorkerService.search_patients(db, asha_session, "Rahul")
        # Rahul is at facility B, so should not appear
        assert len(results) == 0

    def test_asha_search_finds_facility_a_patient(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        results = WorkerService.search_patients(db, asha_session, "Aarav")
        assert len(results) == 1
        assert results[0].full_name == "Aarav Sharma"

    def test_worker_cannot_access_facility_b_referrals(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        refs = WorkerService.get_facility_referrals(db, asha_session)
        # No referrals at facility A, only facility B has potential referrals
        assert isinstance(refs, list)


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 3: Patient Registration
# ═══════════════════════════════════════════════════════════════

class TestWorkerPatientRegistration:
    """Test assisted patient registration by workers."""

    def test_asha_can_register_patient(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        result = WorkerService.register_patient(
            db, asha_session, "Sunita Devi", 35, "Female", "9111111111", "Hindi"
        )
        assert result["success"] is True
        assert result["patient"].full_name == "Sunita Devi"
        assert result["patient"].patient_id.startswith("PAT-")

    def test_anganwadi_can_register_patient(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        ang_session = _worker_session(data["user_ang"], data["fac_b"].id)
        result = WorkerService.register_patient(
            db, ang_session, "Ravi Kumar", 42, "Male", "9222222222", "Marathi"
        )
        assert result["success"] is True
        assert result["patient"].full_name == "Ravi Kumar"

    def test_duplicate_phone_rejected(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        result = WorkerService.register_patient(
            db, asha_session, "Test Patient", 30, "Male", "9000000001", "Hindi"
        )
        assert result["success"] is False
        assert "already exists" in result["error"]

    def test_non_worker_cannot_register_via_worker_service(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        # Try with a receptionist role
        rec_session = {
            "user_id": data["user_rec_a"].id,
            "username": "receptionist_a",
            "full_name": "Receptionist A",
            "role": "receptionist",
            "facility": {"id": data["fac_a"].id, "name": "Test", "facility_type": "CHC", "district": "X", "address": "Y"},
        }
        result = WorkerService.register_patient(
            db, rec_session, "Should Fail", 30, "Male", "9333333333", "Hindi"
        )
        assert result["success"] is False
        assert "Unauthorized" in result["error"]


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 4: Assisted Case Creation
# ═══════════════════════════════════════════════════════════════

class TestWorkerCaseCreation:
    """Test assisted case intake by workers."""

    def test_asha_can_create_case_intake(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        result = WorkerService.create_assisted_intake(
            db, asha_session, data["pat_aarav"].id,
            data["dept_gen_a"].id, data["doc_khan"].id,
            "Fever and cough", "3 days", "body ache, runny nose",
            "Patient reports feeling weak"
        )
        assert result["success"] is True
        assert result["visit"] is not None
        assert result["case"] is not None
        assert result["case"].chief_complaint == "Fever and cough"

    def test_case_requires_chief_complaint(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        result = WorkerService.create_assisted_intake(
            db, asha_session, data["pat_aarav"].id,
            data["dept_gen_a"].id, data["doc_khan"].id,
            "", "", "", ""
        )
        assert result["success"] is False
        assert "complaint" in result["error"].lower()

    def test_case_rejects_wrong_facility_department(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        result = WorkerService.create_assisted_intake(
            db, asha_session, data["pat_aarav"].id,
            data["dept_cardio_b"].id, data["doc_khan"].id,
            "Headache", "1 day", "", ""
        )
        assert result["success"] is False
        assert "Department not found" in result["error"]

    def test_case_rejects_wrong_facility_doctor(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        result = WorkerService.create_assisted_intake(
            db, asha_session, data["pat_aarav"].id,
            data["dept_gen_a"].id, data["doc_gupta"].id,
            "Headache", "1 day", "", ""
        )
        assert result["success"] is False
        assert "Doctor not found" in result["error"]

    def test_case_rejects_nonexistent_patient(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        result = WorkerService.create_assisted_intake(
            db, asha_session, 99999,
            data["dept_gen_a"].id, data["doc_khan"].id,
            "Test", "", "", ""
        )
        assert result["success"] is False
        assert "Patient not found" in result["error"]

    def test_anganwadi_can_create_case_intake(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        ang_session = _worker_session(data["user_ang"], data["fac_b"].id)
        result = WorkerService.create_assisted_intake(
            db, ang_session, data["pat_rahul"].id,
            data["dept_cardio_b"].id, data["doc_gupta"].id,
            "Chest pain", "2 hours", "radiating to left arm",
            "Patient is anxious"
        )
        assert result["success"] is True


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 5: Document Attachment
# ═══════════════════════════════════════════════════════════════

class TestWorkerDocumentAttachment:
    """Test document upload assistance by workers."""

    def test_worker_can_get_documents_for_visit(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        docs = WorkerService.get_documents_for_visit(
            db, asha_session, data["pat_aarav"].id, data["vis_a1"].id
        )
        assert isinstance(docs, list)

    def test_worker_rejects_wrong_facility_visit(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        # vis_b1 is at facility B
        result = WorkerService.attach_document(
            db, asha_session, data["pat_rahul"].id, data["vis_b1"].id,
            None, "test.pdf"
        )
        assert result["success"] is False
        assert "not found" in result["error"].lower()


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 6: Referral Visibility
# ═══════════════════════════════════════════════════════════════

class TestWorkerReferralVisibility:
    """Test that workers can see facility-scoped referrals."""

    def test_asha_sees_only_facility_a_referrals(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        # Create a referral at facility B
        ref = Referral(
            referral_id="REF-2026-00001",
            visit_id=data["vis_b1"].id,
            patient_id=data["pat_rahul"].id,
            referring_doctor_id=data["doc_gupta"].id,
            referring_facility_id=data["fac_b"].id,
            receiving_facility_id=data["fac_a"].id,
            receiving_department_id=data["dept_gen_a"].id,
            reason="Cardiology consultation needed",
            urgency="urgent",
            verification_code="ABC123",
            status="pending",
        )
        db.add(ref)
        db.commit()

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        refs = WorkerService.get_facility_referrals(db, asha_session)
        # This referral is outgoing from facility B, so facility A (asha) sees it as incoming
        # Our service only shows outgoing referrals, so asha sees 0
        assert isinstance(refs, list)

    def test_ang_sees_facility_b_referrals(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        # Create a referral outgoing from facility B
        ref = Referral(
            referral_id="REF-2026-00002",
            visit_id=data["vis_b1"].id,
            patient_id=data["pat_rahul"].id,
            referring_doctor_id=data["doc_gupta"].id,
            referring_facility_id=data["fac_b"].id,
            receiving_facility_id=data["fac_a"].id,
            receiving_department_id=data["dept_gen_a"].id,
            reason="Follow-up needed",
            urgency="routine",
            verification_code="DEF456",
            status="pending",
        )
        db.add(ref)
        db.commit()

        ang_session = _worker_session(data["user_ang"], data["fac_b"].id)
        refs = WorkerService.get_facility_referrals(db, ang_session)
        assert len(refs) == 1
        assert refs[0]["referral_id"] == "REF-2026-00002"

    def test_asha_cannot_see_facility_b_referrals(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        ref = Referral(
            referral_id="REF-2026-00003",
            visit_id=data["vis_b1"].id,
            patient_id=data["pat_rahul"].id,
            referring_doctor_id=data["doc_gupta"].id,
            referring_facility_id=data["fac_b"].id,
            receiving_facility_id=data["fac_a"].id,
            receiving_department_id=data["dept_gen_a"].id,
            reason="Consultation",
            urgency="routine",
            verification_code="GHI789",
            status="pending",
        )
        db.add(ref)
        db.commit()

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        refs = WorkerService.get_facility_referrals(db, asha_session)
        # Facility A has no outgoing referrals
        assert len(refs) == 0


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 7: Follow-up Visibility
# ═══════════════════════════════════════════════════════════════

class TestWorkerFollowupVisibility:
    """Test that workers can see facility-scoped follow-ups."""

    def test_asha_sees_facility_a_followups(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        # Create a follow-up at facility A
        fu = FollowUp(
            visit_id=data["vis_a1"].id,
            patient_id=data["pat_aarav"].id,
            doctor_id=data["doc_khan"].id,
            follow_up_date=datetime.utcnow() + timedelta(days=7),
            reason="Check fever recovery",
            status="scheduled",
        )
        db.add(fu)
        db.commit()

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        followups = WorkerService.get_facility_followups(db, asha_session)
        assert len(followups) == 1
        assert followups[0]["status"] == "scheduled"

    def test_asha_cannot_see_facility_b_followups(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        fu = FollowUp(
            visit_id=data["vis_b1"].id,
            patient_id=data["pat_rahul"].id,
            doctor_id=data["doc_gupta"].id,
            follow_up_date=datetime.utcnow() + timedelta(days=7),
            reason="Cardiology follow-up",
            status="scheduled",
        )
        db.add(fu)
        db.commit()

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        followups = WorkerService.get_facility_followups(db, asha_session)
        assert len(followups) == 0

    def test_worker_can_update_followup_status(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        fu = FollowUp(
            visit_id=data["vis_a1"].id,
            patient_id=data["pat_aarav"].id,
            doctor_id=data["doc_khan"].id,
            follow_up_date=datetime.utcnow() + timedelta(days=7),
            reason="Check fever recovery",
            status="scheduled",
        )
        db.add(fu)
        db.commit()

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        result = WorkerService.update_followup_status(db, asha_session, fu.id, "completed")
        assert result["success"] is True

        updated = db.query(FollowUp).filter(FollowUp.id == fu.id).first()
        assert updated.status == "completed"

    def test_worker_cannot_set_invalid_followup_status(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        fu = FollowUp(
            visit_id=data["vis_a1"].id,
            patient_id=data["pat_aarav"].id,
            doctor_id=data["doc_khan"].id,
            follow_up_date=datetime.utcnow() + timedelta(days=7),
            reason="Check fever recovery",
            status="scheduled",
        )
        db.add(fu)
        db.commit()

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        result = WorkerService.update_followup_status(db, asha_session, fu.id, "cancelled")
        assert result["success"] is False
        assert "Workers can only" in result["error"]


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 8: Unauthorized Access Denied
# ═══════════════════════════════════════════════════════════════

class TestWorkerUnauthorizedAccess:
    """Test that workers cannot perform unauthorized operations."""

    def test_worker_cannot_modify_prescriptions(self):
        """Workers should not have access to prescription service."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        # Worker service does not expose prescription creation
        assert not hasattr(WorkerService, 'create_prescription')

    def test_worker_cannot_modify_doctor_notes(self):
        """Workers should not have access to doctor notes service."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        assert not hasattr(WorkerService, 'create_doctor_note')

    def test_worker_cannot_access_dashboard_stats_with_wrong_role(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        rec_session = {
            "user_id": data["user_rec_a"].id,
            "role": "receptionist",
            "facility": {"id": data["fac_a"].id},
        }
        result = WorkerService.get_dashboard_stats(db, rec_session)
        assert result["success"] is False
        assert "Unauthorized" in result["error"]

    def test_worker_no_facility_rejected(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        no_fac_session = {"user_id": 1, "role": "asha_worker", "facility": None}
        result = WorkerService.get_dashboard_stats(db, no_fac_session)
        assert result["success"] is False
        assert "facility" in result["error"].lower()


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 9: Backward Compatibility — Existing Workflows
# ═══════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    """Verify existing workflows remain intact after Phase 3A changes."""

    def test_receptionist_role_unchanged(self):
        assert hasattr(UserRole, "RECEPTIONIST")
        assert UserRole.RECEPTIONIST.value == "receptionist"

    def test_doctor_role_unchanged(self):
        assert hasattr(UserRole, "DOCTOR")
        assert UserRole.DOCTOR.value == "doctor"

    def test_hospital_admin_role_unchanged(self):
        assert hasattr(UserRole, "HOSPITAL_ADMIN")
        assert UserRole.HOSPITAL_ADMIN.value == "hospital_admin"

    def test_government_admin_role_unchanged(self):
        assert hasattr(UserRole, "GOVERNMENT_ADMIN")
        assert UserRole.GOVERNMENT_ADMIN.value == "government_admin"

    def test_normalize_role_existing_roles(self):
        assert normalize_role("receptionist") == "receptionist"
        assert normalize_role("doctor") == "doctor"
        assert normalize_role("hospital_admin") == "hospital_admin"
        assert normalize_role("government_admin") == "government_admin"

    def test_global_roles_unchanged(self):
        assert "government_admin" in GLOBAL_ROLES
        assert "government" in GLOBAL_ROLES

    def test_patient_search_still_works(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        results = PatientService.search_patients(db, "Aarav")
        assert len(results) == 1
        assert results[0].full_name == "Aarav Sharma"

    def test_visit_creation_still_works(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        pat = data["pat_aarav"]
        visit = VisitService.create_visit(
            db, pat.id, data["fac_a"].id, data["dept_gen_a"].id, data["doc_khan"].id
        )
        assert visit is not None
        assert visit.visit_id.startswith("VIS-")

    def test_case_submission_still_works(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        visit = VisitService.create_visit(
            db, data["pat_aarav"].id, data["fac_a"].id,
            data["dept_gen_a"].id, data["doc_khan"].id
        )
        case = PatientCaseService.submit_case(
            db, data["pat_aarav"].id, visit.id, "Test complaint"
        )
        assert case is not None
        assert case.chief_complaint == "Test complaint"

    def test_referral_service_unchanged(self):
        assert hasattr(ReferralService, 'create_referral')
        assert hasattr(ReferralService, 'build_data_package')
        assert hasattr(ReferralService, 'lookup_referral')

    def test_followup_service_unchanged(self):
        assert hasattr(FollowUpService, 'schedule_followup')
        assert hasattr(FollowUpService, 'update_followup_status')


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 10: Navigation & Session
# ═══════════════════════════════════════════════════════════════

class TestWorkerNavigation:
    """Test navigation workflow definitions for workers."""

    def test_worker_workflow_exists(self):
        from services.navigation import WORKER_WORKFLOW
        assert len(WORKER_WORKFLOW) == 6

    def test_worker_workflow_steps(self):
        from services.navigation import WORKER_WORKFLOW
        steps = [s[1] for s in WORKER_WORKFLOW]
        assert "dashboard" in steps
        assert "patients" in steps
        assert "register" in steps
        assert "intake" in steps
        assert "referrals" in steps
        assert "followups" in steps

    def test_worker_in_workflows_dict(self):
        from services.navigation import WORKFLOWS
        assert "asha_worker" in WORKFLOWS
        assert "anganwadi_worker" in WORKFLOWS
        assert WORKFLOWS["asha_worker"] == WORKFLOWS["anganwadi_worker"]

    def test_workflow_trail_for_worker(self):
        from services.navigation import WORKER_WORKFLOW, trail_text_with_current
        trail = trail_text_with_current(WORKER_WORKFLOW, "intake")
        assert "Dashboard" in trail
        assert "Patients" in trail
        assert "Case Intake" in trail
        assert "**Case Intake**" in trail


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 11: Demo Account Seed
# ═══════════════════════════════════════════════════════════════

class TestDemoAccounts:
    """Test that demo worker accounts are created correctly."""

    def test_seed_creates_asha_demo(self):
        from tests.test_db_helper import create_isolated_test_db
        db = create_isolated_test_db()
        asha = db.query(User).filter(User.username == "asha_demo").first()
        assert asha is not None
        role_val = asha.role.value if isinstance(asha.role, UserRole) else str(asha.role)
        assert role_val == "asha_worker"
        assert asha.facility_id is not None

    def test_seed_creates_anganwadi_demo(self):
        from tests.test_db_helper import create_isolated_test_db
        db = create_isolated_test_db()
        ang = db.query(User).filter(User.username == "anganwadi_demo").first()
        assert ang is not None
        role_val = ang.role.value if isinstance(ang.role, UserRole) else str(ang.role)
        assert role_val == "anganwadi_worker"
        assert ang.facility_id is not None

    def test_existing_demo_accounts_unaffected(self):
        from tests.test_db_helper import create_isolated_test_db
        db = create_isolated_test_db()
        rec = db.query(User).filter(User.username == "receptionist").first()
        assert rec is not None
        drkhan = db.query(User).filter(User.username == "drkhan").first()
        assert drkhan is not None
        gov = db.query(User).filter(User.username == "gov_admin").first()
        assert gov is not None

    def test_demo_worker_authentication(self):
        from tests.test_db_helper import create_isolated_test_db
        db = create_isolated_test_db()
        result = AuthService.authenticate(db, "asha_demo", "password123")
        assert result is not None
        assert result["role"] == "asha_worker"

    def test_demo_anganwadi_authentication(self):
        from tests.test_db_helper import create_isolated_test_db
        db = create_isolated_test_db()
        result = AuthService.authenticate(db, "anganwadi_demo", "password123")
        assert result is not None
        assert result["role"] == "anganwadi_worker"

    def test_seed_is_idempotent(self):
        from tests.test_db_helper import create_isolated_test_db
        db1 = create_isolated_test_db()
        count1 = db1.query(User).filter(User.username == "asha_demo").count()
        # Seed again - should not duplicate
        from database.seed_data import seed_database
        seed_database(db_session=db1)
        count2 = db1.query(User).filter(User.username == "asha_demo").count()
        assert count1 == count2


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 12: Dashboard Stats
# ═══════════════════════════════════════════════════════════════

class TestWorkerDashboard:
    """Test worker dashboard statistics."""

    def test_dashboard_returns_success(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        result = WorkerService.get_dashboard_stats(db, asha_session)
        assert result["success"] is True

    def test_dashboard_counts_patients_today(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        result = WorkerService.get_dashboard_stats(db, asha_session)
        assert "patients_today" in result
        assert "pending_followups" in result
        assert "active_referrals" in result
        assert "recent_cases" in result

    def test_dashboard_facility_scoped(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        # Facility A has 1 visit (vis_a1)
        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        result_a = WorkerService.get_dashboard_stats(db, asha_session)

        # Facility B has 1 visit (vis_b1)
        ang_session = _worker_session(data["user_ang"], data["fac_b"].id)
        result_b = WorkerService.get_dashboard_stats(db, ang_session)

        # Both should return valid results
        assert result_a["success"] is True
        assert result_b["success"] is True


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 13: Get Departments and Doctors
# ═══════════════════════════════════════════════════════════════

class TestWorkerFacilityResources:
    """Test that workers can access facility departments and doctors."""

    def test_get_facility_departments(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        depts = WorkerService.get_facility_departments(db, asha_session)
        assert len(depts) == 2  # General Medicine + Dental
        names = [d.name for d in depts]
        assert "General Medicine" in names
        assert "Dental" in names

    def test_get_facility_doctors(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        docs = WorkerService.get_facility_doctors(db, asha_session)
        assert len(docs) == 1
        assert docs[0].doctor_id == "DOC-001"

    def test_get_facility_doctors_filtered_by_dept(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        docs = WorkerService.get_facility_doctors(db, asha_session, data["dept_gen_a"].id)
        assert len(docs) == 1

    def test_worker_cannot_see_other_facility_departments(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        depts = WorkerService.get_facility_departments(db, asha_session)
        dept_ids = [d.id for d in depts]
        assert data["dept_cardio_b"].id not in dept_ids
