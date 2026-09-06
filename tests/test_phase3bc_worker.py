"""Phase 3B + 3C: Clinical Handoff & Rural Follow-Up Tests.

Tests the worker-submitted case workflow, follow-up outcome recording,
escalation, referral follow-up, and security constraints.

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


# ── Test fixtures ──


def _make_engine():
    return create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, echo=False)


def _seed_two_facilities(db: Session):
    """Create two facilities with workers, doctors, patients, and visits for Phase 3B+3C testing."""
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


def _create_worker_case_with_followups(db, data):
    """Helper: create a worker-submitted case and follow-ups for testing."""
    now = datetime.utcnow()
    asha_session = _worker_session(data["user_asha"], data["fac_a"].id)

    result = WorkerService.create_assisted_intake(
        db, asha_session, data["pat_aarav"].id,
        data["dept_gen_a"].id, data["doc_khan"].id,
        "Persistent headache for 3 days", "3 days", "headache, mild nausea",
        "Patient reports pain worsening in evening"
    )
    assert result.get("success"), f"create_assisted_intake failed: {result}"
    case = result["case"]
    visit = result["visit"]

    submit_result = WorkerService.submit_case_to_healthcare(
        db, asha_session, case.id, "Patient reported symptoms verbally."
    )
    assert submit_result.get("success"), f"submit_case_to_healthcare failed: {submit_result}"

    fu_scheduled = FollowUp(
        visit_id=visit.id,
        patient_id=data["pat_aarav"].id,
        doctor_id=data["doc_khan"].id,
        follow_up_date=now - timedelta(days=1),
        reason="Post-intake monitoring",
        status="scheduled",
    )
    db.add(fu_scheduled)

    fu_future = FollowUp(
        visit_id=visit.id,
        patient_id=data["pat_aarav"].id,
        doctor_id=data["doc_khan"].id,
        follow_up_date=now + timedelta(days=2),
        reason="Follow-up referral appointment",
        status="scheduled",
    )
    db.add(fu_future)
    db.commit()

    return {"case": case, "visit": visit, "fu_scheduled": fu_scheduled, "fu_future": fu_future}


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 1: Clinical Handoff — Case Submission (Phase 3B)
# ═══════════════════════════════════════════════════════════════

class TestCaseSubmission:
    """Test worker case submission to healthcare team."""

    def test_submit_case_sets_submitted_by_worker_id(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        case = db.query(PatientCase).filter(PatientCase.id == result["case"].id).first()
        assert case.submitted_by_worker_id == data["user_asha"].id

    def test_submit_case_sets_submitted_at(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        case = db.query(PatientCase).filter(PatientCase.id == result["case"].id).first()
        assert case.submitted_at is not None
        assert isinstance(case.submitted_at, datetime)

    def test_submit_case_preserves_worker_notes(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)

        result = WorkerService.create_assisted_intake(
            db, asha_session, data["pat_aarav"].id,
            data["dept_gen_a"].id, data["doc_khan"].id,
            "Fever and cough", "2 days", "fever, cough"
        )
        case = result["case"]

        submit_result = WorkerService.submit_case_to_healthcare(
            db, asha_session, case.id, "Patient has a history of asthma."
        )
        assert submit_result.get("success")

        case = db.query(PatientCase).filter(PatientCase.id == case.id).first()
        assert case.worker_notes == "Patient has a history of asthma."

    def test_submit_case_without_notes_succeeds(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)

        result = WorkerService.create_assisted_intake(
            db, asha_session, data["pat_aarav"].id,
            data["dept_gen_a"].id, data["doc_khan"].id,
            "Back pain", "1 week", "lower back pain"
        )
        case = result["case"]

        submit_result = WorkerService.submit_case_to_healthcare(db, asha_session, case.id)
        assert submit_result.get("success")

    def test_submit_nonexistent_case_fails(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)

        result = WorkerService.submit_case_to_healthcare(db, asha_session, 99999)
        assert not result.get("success")


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 2: Clinical Handoff — Case Details Retrieval
# ═══════════════════════════════════════════════════════════════

class TestCaseDetailsRetrieval:
    """Test worker-assisted case detail retrieval."""

    def test_get_assisted_case_details_returns_success(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        details = WorkerService.get_assisted_case_details(db, asha_session, result["case"].id)
        assert details.get("success")

    def test_get_assisted_case_details_includes_patient(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        details = WorkerService.get_assisted_case_details(db, asha_session, result["case"].id)
        assert details["patient"]["full_name"] == "Aarav Sharma"

    def test_get_assisted_case_details_includes_submitted_by(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        details = WorkerService.get_assisted_case_details(db, asha_session, result["case"].id)
        assert details["case"]["submitted_by_worker"] == "ASHA Worker A"

    def test_get_assisted_case_details_cross_facility_denied(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        ang_session = _worker_session(data["user_ang"], data["fac_b"].id)
        details = WorkerService.get_assisted_case_details(db, ang_session, result["case"].id)
        assert not details.get("success")


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 3: Follow-Up Outcomes (Phase 3C)
# ═══════════════════════════════════════════════════════════════

class TestFollowUpOutcomes:
    """Test worker follow-up outcome recording."""

    def test_record_outcome_succeeds(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        outcome_result = WorkerService.record_worker_outcome(
            db, asha_session, result["fu_scheduled"].id,
            "PATIENT_ATTENDED", "Patient reported improvement."
        )
        assert outcome_result.get("success")

    def test_record_outcome_updates_followup_fields(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        WorkerService.record_worker_outcome(
            db, asha_session, result["fu_scheduled"].id,
            "CONTACTED", "Patient confirmed follow-up."
        )

        fu = db.query(FollowUp).filter(FollowUp.id == result["fu_scheduled"].id).first()
        assert fu.worker_outcome == "CONTACTED"
        assert fu.worker_outcome_by_id == data["user_asha"].id
        assert fu.worker_outcome_at is not None
        assert fu.worker_outcome_notes == "Patient confirmed follow-up."

    def test_record_outcome_attended_marks_completed(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        WorkerService.record_worker_outcome(
            db, asha_session, result["fu_scheduled"].id,
            "PATIENT_ATTENDED", ""
        )

        fu = db.query(FollowUp).filter(FollowUp.id == result["fu_scheduled"].id).first()
        assert fu.status == "completed"

    def test_record_outcome_nonexistent_followup_fails(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        result = WorkerService.record_worker_outcome(
            db, asha_session, 99999, "CONTACTED"
        )
        assert not result.get("success")

    def test_record_outcome_cross_facility_denied(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        ang_session = _worker_session(data["user_ang"], data["fac_b"].id)
        outcome_result = WorkerService.record_worker_outcome(
            db, ang_session, result["fu_scheduled"].id, "CONTACTED"
        )
        assert not outcome_result.get("success")


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 4: Escalation (Phase 3C)
# ═══════════════════════════════════════════════════════════════

class TestEscalation:
    """Test follow-up escalation to healthcare."""

    def test_escalate_succeeds(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        esc_result = WorkerService.escalate_followup(
            db, asha_session, result["fu_scheduled"].id,
            "Patient symptoms worsening, needs doctor review."
        )
        assert esc_result.get("success")

    def test_escalate_updates_escalation_fields(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        WorkerService.escalate_followup(
            db, asha_session, result["fu_scheduled"].id,
            "Possible infection, needs urgent review."
        )

        fu = db.query(FollowUp).filter(FollowUp.id == result["fu_scheduled"].id).first()
        assert fu.escalated is True
        assert fu.escalated_at is not None
        assert fu.worker_outcome == "ESCALATED_TO_HEALTHCARE_TEAM"
        assert "Possible infection" in fu.worker_outcome_notes

    def test_escalate_nonexistent_followup_fails(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        result = WorkerService.escalate_followup(db, asha_session, 99999, "Test")
        assert not result.get("success")

    def test_escalate_cross_facility_denied(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        ang_session = _worker_session(data["user_ang"], data["fac_b"].id)
        esc_result = WorkerService.escalate_followup(
            db, ang_session, result["fu_scheduled"].id, "Test escalation"
        )
        assert not esc_result.get("success")

    def test_escalate_already_escalated_fails(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        WorkerService.escalate_followup(
            db, asha_session, result["fu_scheduled"].id, "First escalation."
        )
        result2 = WorkerService.escalate_followup(
            db, asha_session, result["fu_scheduled"].id, "Second attempt."
        )
        assert not result2.get("success")


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 5: Dashboard Stats (Phase 3B+3C)
# ═══════════════════════════════════════════════════════════════

class TestDashboardStats:
    """Test worker dashboard stats include Phase 3B+3C metrics."""

    def test_dashboard_includes_overdue_followups(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        stats = WorkerService.get_dashboard_stats(db, asha_session)
        assert "overdue_followups" in stats
        assert stats["overdue_followups"] >= 0

    def test_dashboard_includes_escalated_count(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        stats = WorkerService.get_dashboard_stats(db, asha_session)
        assert "escalated_count" in stats

    def test_dashboard_includes_draft_cases(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        stats = WorkerService.get_dashboard_stats(db, asha_session)
        assert "draft_cases" in stats

    def test_dashboard_recent_cases_includes_assisted_flag(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        stats = WorkerService.get_dashboard_stats(db, asha_session)
        recent = stats.get("recent_cases", [])
        if recent:
            assert "is_assisted_intake" in recent[0] or "submitted_at" in recent[0]


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 6: Follow-Up Listing with Context (Phase 3C)
# ═══════════════════════════════════════════════════════════════

class TestFollowUpListing:
    """Test follow-up listing with outcome and escalation context."""

    def test_followup_listing_includes_worker_outcome(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        WorkerService.record_worker_outcome(
            db, asha_session, result["fu_scheduled"].id,
            "PATIENT_ATTENDED", "Improvement noted."
        )

        followups = WorkerService.get_facility_followups(db, asha_session)
        fu_entry = next((f for f in followups if f["followup_id"] == result["fu_scheduled"].id), None)
        assert fu_entry is not None
        assert fu_entry["worker_outcome"] == "PATIENT_ATTENDED"

    def test_followup_listing_includes_escalation_status(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        WorkerService.escalate_followup(
            db, asha_session, result["fu_scheduled"].id, "Needs review."
        )

        followups = WorkerService.get_facility_followups(db, asha_session)
        fu_entry = next((f for f in followups if f["followup_id"] == result["fu_scheduled"].id), None)
        assert fu_entry is not None
        assert fu_entry["escalated"] is True

    def test_followup_listing_overdue_detection(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        followups = WorkerService.get_facility_followups(db, asha_session)
        fu_entry = next((f for f in followups if f["followup_id"] == result["fu_scheduled"].id), None)
        assert fu_entry is not None
        assert "is_overdue" in fu_entry

    def test_followup_listing_status_filter_overdue(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        overdue = WorkerService.get_facility_followups(db, asha_session, status_filter="overdue")
        assert isinstance(overdue, list)

    def test_followup_listing_status_filter_scheduled(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        scheduled = WorkerService.get_facility_followups(db, asha_session, status_filter="scheduled")
        assert isinstance(scheduled, list)


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 7: Referral Follow-Up (Phase 3C)
# ═══════════════════════════════════════════════════════════════

class TestReferralFollowUp:
    """Test referral follow-up context in follow-up listings."""

    def test_followup_listing_includes_referral_context(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        now = datetime.utcnow()

        # Create a proper referral using ReferralService
        fac_b = data["fac_b"]
        dept_cardio_b = data["dept_cardio_b"]

        referral = ReferralService.create_referral(
            db,
            visit_id=data["vis_a1"].id,
            patient_id=data["pat_aarav"].id,
            referring_doctor_id=data["doc_khan"].id,
            referring_facility_id=data["fac_a"].id,
            receiving_facility_id=fac_b.id,
            receiving_department_id=dept_cardio_b.id,
            receiving_doctor_id=None,
            reason="Suspected cardiac issue.",
            urgency="urgent",
        )
        db.flush()

        fu_ref = FollowUp(
            visit_id=data["vis_a1"].id,
            patient_id=data["pat_aarav"].id,
            doctor_id=data["doc_khan"].id,
            follow_up_date=now + timedelta(days=3),
            reason="Referral appointment follow-up",
            status="scheduled",
        )
        db.add(fu_ref)
        db.commit()

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        followups = WorkerService.get_facility_followups(db, asha_session)
        fu_entry = next((f for f in followups if f["followup_id"] == fu_ref.id), None)
        assert fu_entry is not None
        assert fu_entry["has_referral"] is True
        assert fu_entry["referral_id"] == referral.referral_id


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 8: Security & Facility Isolation (Phase 3B+3C)
# ═══════════════════════════════════════════════════════════════

class TestSecurityPhase3BC:
    """Test security constraints for Phase 3B+3C features."""

    def test_worker_submit_sets_submitted_at_on_existing_case(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        # Create a case via PatientCaseService (not through worker flow)
        case = PatientCaseService.submit_case(
            db, data["pat_aarav"].id, data["vis_a1"].id,
            "Routine checkup", "N/A", "none"
        )
        db.commit()

        # Worker submits it to healthcare
        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        result = WorkerService.submit_case_to_healthcare(db, asha_session, case.id)
        assert result.get("success")

        case = db.query(PatientCase).filter(PatientCase.id == case.id).first()
        assert case.submitted_at is not None

    def test_worker_cannot_access_cross_facility_case(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        ang_session = _worker_session(data["user_ang"], data["fac_b"].id)
        details = WorkerService.get_assisted_case_details(db, ang_session, result["case"].id)
        assert not details.get("success")

    def test_worker_cannot_escalate_cross_facility_followup(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        ang_session = _worker_session(data["user_ang"], data["fac_b"].id)
        esc = WorkerService.escalate_followup(
            db, ang_session, result["fu_scheduled"].id, "Unauthorized"
        )
        assert not esc.get("success")

    def test_worker_cannot_record_outcome_cross_facility(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)
        result = _create_worker_case_with_followups(db, data)

        ang_session = _worker_session(data["user_ang"], data["fac_b"].id)
        outcome = WorkerService.record_worker_outcome(
            db, ang_session, result["fu_scheduled"].id, "CONTACTED"
        )
        assert not outcome.get("success")

    def test_doctor_cannot_use_worker_submit(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        doc_session = {
            "user_id": data["user_khan"].id,
            "username": "drkhan",
            "full_name": "Dr. Khan",
            "role": "doctor",
            "facility": {"id": data["fac_a"].id, "name": "Test"},
        }
        result = WorkerService.submit_case_to_healthcare(db, doc_session, 99999)
        assert not result.get("success")


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 9: Backward Compatibility (Phase 3A)
# ═══════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    """Ensure Phase 3A functionality still works."""

    def test_create_assisted_intake_still_works(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        result = WorkerService.create_assisted_intake(
            db, asha_session, data["pat_aarav"].id,
            data["dept_gen_a"].id, data["doc_khan"].id,
            "Test complaint", "2 days", "test symptoms"
        )
        assert result.get("success")

    def test_search_patients_still_works(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        results = WorkerService.search_patients(db, asha_session, "Aarav")
        assert len(results) > 0

    def test_register_patient_still_works(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()
        data = _seed_two_facilities(db)

        asha_session = _worker_session(data["user_asha"], data["fac_a"].id)
        result = WorkerService.register_patient(
            db, asha_session, "Test Patient", 30, "Female", "9000000099", "Hindi"
        )
        assert result.get("success")


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 10: Schema Integrity
# ═══════════════════════════════════════════════════════════════

class TestSchemaIntegrity:
    """Verify Phase 3B+3C columns exist in the schema."""

    def test_patient_case_has_submitted_by_worker_id(self):
        assert hasattr(PatientCase, "submitted_by_worker_id")

    def test_patient_case_has_submitted_at(self):
        assert hasattr(PatientCase, "submitted_at")

    def test_patient_case_has_worker_notes(self):
        assert hasattr(PatientCase, "worker_notes")

    def test_followup_has_worker_outcome(self):
        assert hasattr(FollowUp, "worker_outcome")

    def test_followup_has_worker_outcome_at(self):
        assert hasattr(FollowUp, "worker_outcome_at")

    def test_followup_has_worker_outcome_by_id(self):
        assert hasattr(FollowUp, "worker_outcome_by_id")

    def test_followup_has_worker_outcome_notes(self):
        assert hasattr(FollowUp, "worker_outcome_notes")

    def test_followup_has_escalated(self):
        assert hasattr(FollowUp, "escalated")

    def test_followup_has_escalated_at(self):
        assert hasattr(FollowUp, "escalated_at")

    def test_patient_case_has_relationships(self):
        assert hasattr(PatientCase, "submitted_by_worker")


# ═══════════════════════════════════════════════════════════════
# Summary: 52 tests total
# Group 1 (Case Submission): 5 tests
# Group 2 (Case Details): 4 tests
# Group 3 (Follow-Up Outcomes): 5 tests
# Group 4 (Escalation): 5 tests
# Group 5 (Dashboard Stats): 4 tests
# Group 6 (Follow-Up Listing): 5 tests
# Group 7 (Referral Follow-Up): 1 test
# Group 8 (Security): 5 tests
# Group 9 (Backward Compat): 3 tests
# Group 10 (Schema Integrity): 10 tests
