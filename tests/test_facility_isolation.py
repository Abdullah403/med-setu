"""Phase 2A: Facility Isolation & Cross-Facility Authorization Tests.

Tests that users at one facility cannot access data belonging to another facility.
Uses isolated in-memory databases — never touches med_setu.db.
"""
import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from database.models import (
    Base, User, Doctor, Patient, Visit, Token, TokenStatus, Facility, Department,
    UserRole, Referral, ReferralDataPackage, PatientCase, Prescription, DoctorNote, FollowUp,
)
from services.authorization import (
    get_facility_id, get_doctor_id, is_global_role, patient_has_visits_at_facility,
    visit_belongs_to_facility, token_belongs_to_facility, doctor_belongs_to_facility,
    user_belongs_to_facility, check_patient_access, check_visit_access, check_token_access,
    check_doctor_access, check_staff_access, GLOBAL_ROLES,
)
from services.dashboard_service import DashboardService
from services.management_service import ManagementService
from services.patient_service import PatientService
from services.patient_history_service import PatientHistoryService
from services.doctor_service import DoctorService
from services.token_service import TokenService
from services.visit_service import VisitService
from services.referral_service import ReferralService
from services.auth_service import AuthService


# ── Test fixtures ──


def _make_engine():
    return create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, echo=False)


def _seed_two_facilities(db: Session):
    """Create two facilities with doctors, patients, and visits at each.

    Facility A (Rural CHC Thane):
        - Dr. Khan (General Medicine, DOC-001)
        - Patient: Aarav (PAT-00101) with visit VIS-A1 at Facility A
        - Patient: Fatima (PAT-00102) with visit VIS-A2 at Facility A

    Facility B (District GH Pune):
        - Dr. Gupta (Cardiology, DOC-003)
        - Patient: Rahul (PAT-00103) with visit VIS-B1 at Facility B
    """
    # Facility A
    fac_a = Facility(name="Rural CHC Thane", facility_type="CHC", district="Thane",
                     address="123 Main Rd", phone="9876543210", is_active=True)
    db.add(fac_a)
    db.flush()

    dept_gen_a = Department(name="General Medicine", facility_id=fac_a.id)
    db.add(dept_gen_a)
    db.flush()

    # Facility A doctor: Khan
    user_khan = User(username="drkhan", password_hash="x", role=UserRole.DOCTOR,
                     full_name="Dr. Khan", facility_id=fac_a.id, is_active=True)
    db.add(user_khan)
    db.flush()
    doc_khan = Doctor(user_id=user_khan.id, facility_id=fac_a.id, department_id=dept_gen_a.id,
                      doctor_id="DOC-001", specialization="General Medicine", is_available=True)
    db.add(doc_khan)
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

    tok_a1 = Token(token_number="MED-A01", visit_id=vis_a1.id, doctor_id=doc_khan.id,
                   token_date=datetime.utcnow(), status=TokenStatus.WAITING)
    db.add(tok_a1)

    pat_fatima = Patient(patient_id="PAT-00102", full_name="Fatima Khan", age=52,
                         gender="Female", phone="9000000002", preferred_language="Hindi", is_active=True)
    db.add(pat_fatima)
    db.flush()

    vis_a2 = Visit(visit_id="VIS-A2", patient_id=pat_fatima.id, facility_id=fac_a.id,
                   department_id=dept_gen_a.id, doctor_id=doc_khan.id,
                   visit_date=datetime.utcnow(), status="ongoing")
    db.add(vis_a2)
    db.flush()

    # Facility B
    fac_b = Facility(name="District GH Pune", facility_type="District Hospital", district="Pune",
                     address="456 Hosp Rd", phone="9876543211", is_active=True)
    db.add(fac_b)
    db.flush()

    dept_cardio_b = Department(name="Cardiology", facility_id=fac_b.id)
    db.add(dept_cardio_b)
    db.flush()

    # Facility B doctor: Gupta
    user_gupta = User(username="drgupta", password_hash="x", role=UserRole.DOCTOR,
                      full_name="Dr. Gupta", facility_id=fac_b.id, is_active=True)
    db.add(user_gupta)
    db.flush()
    doc_gupta = Doctor(user_id=user_gupta.id, facility_id=fac_b.id, department_id=dept_cardio_b.id,
                       doctor_id="DOC-003", specialization="Cardiology", is_available=True)
    db.add(doc_gupta)
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

    tok_b1 = Token(token_number="MED-B01", visit_id=vis_b1.id, doctor_id=doc_gupta.id,
                   token_date=datetime.utcnow(), status=TokenStatus.WAITING)
    db.add(tok_b1)

    db.commit()

    return {
        "fac_a": fac_a, "fac_b": fac_b,
        "dept_gen_a": dept_gen_a, "dept_cardio_b": dept_cardio_b,
        "doc_khan": doc_khan, "doc_gupta": doc_gupta,
        "user_khan": user_khan, "user_gupta": user_gupta,
        "user_rec_a": user_rec_a, "user_rec_b": user_rec_b,
        "pat_aarav": pat_aarav, "pat_fatima": pat_fatima, "pat_rahul": pat_rahul,
        "vis_a1": vis_a1, "vis_a2": vis_a2, "vis_b1": vis_b1,
        "tok_a1": tok_a1, "tok_b1": tok_b1,
    }


def _session_data(user_data, facility_id, role="receptionist", doctor_id=None):
    """Build a fake session user_data dict for authorization tests."""
    data = {
        "user_id": 1,
        "username": "test",
        "full_name": "Test User",
        "role": role,
        "facility": {"id": facility_id, "name": "Test", "facility_type": "CHC", "district": "X", "address": "Y"},
    }
    if doctor_id:
        data["doctor"] = {
            "id": doctor_id,
            "doctor_id": doctor_id,
            "doctor_code": f"DOC-{doctor_id:03d}",
            "specialization": "Medicine",
            "department_id": 1,
            "department_name": "General",
            "facility_id": facility_id,
            "facility_name": "Test",
            "facility_district": "X",
        }
    return data


# ── Authorization helper tests ──


class TestAuthorizationHelpers:
    """Test the authorization helper functions themselves."""

    def test_get_facility_id_from_session(self):
        data = {"facility": {"id": 42}}
        assert get_facility_id(data) == 42

    def test_get_facility_id_missing(self):
        assert get_facility_id(None) is None
        assert get_facility_id({}) is None
        assert get_facility_id({"facility": None}) is None

    def test_is_global_role(self):
        for role in GLOBAL_ROLES:
            assert is_global_role({"role": role}) is True
        assert is_global_role({"role": "receptionist"}) is False
        assert is_global_role({"role": "doctor"}) is False
        assert is_global_role(None) is False

    def test_patient_has_visits_at_facility(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        assert patient_has_visits_at_facility(db, data["pat_aarav"].id, data["fac_a"].id) is True
        assert patient_has_visits_at_facility(db, data["pat_aarav"].id, data["fac_b"].id) is False
        assert patient_has_visits_at_facility(db, data["pat_rahul"].id, data["fac_b"].id) is True
        assert patient_has_visits_at_facility(db, data["pat_rahul"].id, data["fac_a"].id) is False
        db.close()

    def test_visit_belongs_to_facility(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        assert visit_belongs_to_facility(db, data["vis_a1"].id, data["fac_a"].id) is True
        assert visit_belongs_to_facility(db, data["vis_a1"].id, data["fac_b"].id) is False
        assert visit_belongs_to_facility(db, data["vis_b1"].id, data["fac_b"].id) is True
        assert visit_belongs_to_facility(db, data["vis_b1"].id, data["fac_a"].id) is False
        db.close()

    def test_token_belongs_to_facility(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        assert token_belongs_to_facility(db, data["tok_a1"].id, data["fac_a"].id) is True
        assert token_belongs_to_facility(db, data["tok_a1"].id, data["fac_b"].id) is False
        assert token_belongs_to_facility(db, data["tok_b1"].id, data["fac_b"].id) is True
        assert token_belongs_to_facility(db, data["tok_b1"].id, data["fac_a"].id) is False
        db.close()

    def test_doctor_belongs_to_facility(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        assert doctor_belongs_to_facility(db, data["doc_khan"].id, data["fac_a"].id) is True
        assert doctor_belongs_to_facility(db, data["doc_khan"].id, data["fac_b"].id) is False
        assert doctor_belongs_to_facility(db, data["doc_gupta"].id, data["fac_b"].id) is True
        assert doctor_belongs_to_facility(db, data["doc_gupta"].id, data["fac_a"].id) is False
        db.close()

    def test_user_belongs_to_facility(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        assert user_belongs_to_facility(db, data["user_rec_a"].id, data["fac_a"].id) is True
        assert user_belongs_to_facility(db, data["user_rec_a"].id, data["fac_b"].id) is False
        assert user_belongs_to_facility(db, data["user_khan"].id, data["fac_a"].id) is True
        assert user_belongs_to_facility(db, data["user_khan"].id, data["fac_b"].id) is False
        db.close()


# ── Cross-facility access denial tests ──


class TestCrossFacilityPatientAccess:
    """Hospital A staff must not access Hospital B patients."""

    def test_facility_a_receptionist_cannot_access_facility_b_patient(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_a"].id, "receptionist")
        result = check_patient_access(db, data["pat_rahul"].id, user_data)
        assert result is not None
        assert result["success"] is False
        db.close()

    def test_facility_b_receptionist_cannot_access_facility_a_patient(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_b"].id, "receptionist")
        result = check_patient_access(db, data["pat_aarav"].id, user_data)
        assert result is not None
        assert result["success"] is False
        db.close()

    def test_facility_a_doctor_cannot_access_facility_b_patient(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_a"].id, "doctor", doctor_id=data["doc_khan"].id)
        result = check_patient_access(db, data["pat_rahul"].id, user_data)
        assert result is not None
        assert result["success"] is False
        db.close()

    def test_facility_b_doctor_cannot_access_facility_a_patient(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_b"].id, "doctor", doctor_id=data["doc_gupta"].id)
        result = check_patient_access(db, data["pat_aarav"].id, user_data)
        assert result is not None
        assert result["success"] is False
        db.close()

    def test_same_facility_patient_access_allowed(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_a"].id, "receptionist")
        result = check_patient_access(db, data["pat_aarav"].id, user_data)
        assert result is None
        db.close()


class TestCrossFacilityVisitAccess:
    """Staff must not access visits at other facilities."""

    def test_facility_a_cannot_access_facility_b_visit(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_a"].id, "receptionist")
        result = check_visit_access(db, data["vis_b1"].id, user_data)
        assert result is not None
        assert result["success"] is False
        db.close()

    def test_facility_b_cannot_access_facility_a_visit(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_b"].id, "receptionist")
        result = check_visit_access(db, data["vis_a1"].id, user_data)
        assert result is not None
        assert result["success"] is False
        db.close()


class TestCrossFacilityTokenAccess:
    """Staff must not access tokens at other facilities."""

    def test_facility_a_cannot_access_facility_b_token(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_a"].id, "receptionist")
        result = check_token_access(db, data["tok_b1"].id, user_data)
        assert result is not None
        assert result["success"] is False
        db.close()

    def test_facility_b_cannot_access_facility_a_token(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_b"].id, "receptionist")
        result = check_token_access(db, data["tok_a1"].id, user_data)
        assert result is not None
        assert result["success"] is False
        db.close()


class TestCrossFacilityDoctorAccess:
    """Staff must not access doctors at other facilities."""

    def test_facility_a_cannot_access_facility_b_doctor(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_a"].id, "receptionist")
        result = check_doctor_access(db, data["doc_gupta"].id, user_data)
        assert result is not None
        assert result["success"] is False
        db.close()

    def test_facility_b_cannot_access_facility_a_doctor(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_b"].id, "receptionist")
        result = check_doctor_access(db, data["doc_khan"].id, user_data)
        assert result is not None
        assert result["success"] is False
        db.close()


class TestCrossFacilityStaffManagement:
    """Hospital A admin must not manage Hospital B staff."""

    def test_facility_a_cannot_deactivate_facility_b_staff(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_a"].id, "hospital_admin")
        result = ManagementService.deactivate_staff(
            db, data["user_rec_b"].id,
            requester_role="hospital_admin",
            user_data=user_data,
        )
        assert result["success"] is False
        db.close()

    def test_facility_b_cannot_deactivate_facility_a_staff(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_b"].id, "hospital_admin")
        result = ManagementService.deactivate_staff(
            db, data["user_rec_a"].id,
            requester_role="hospital_admin",
            user_data=user_data,
        )
        assert result["success"] is False
        db.close()

    def test_facility_a_can_deactivate_own_staff(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_a"].id, "hospital_admin")
        result = ManagementService.deactivate_staff(
            db, data["user_rec_a"].id,
            requester_role="hospital_admin",
            user_data=user_data,
        )
        assert result["success"] is True
        db.close()

    def test_facility_a_cannot_manage_facility_b_facility(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_a"].id, "hospital_admin")
        result = ManagementService.deactivate_facility(
            db, data["fac_b"].id,
            requester_role="hospital_admin",
            user_data=user_data,
        )
        assert result["success"] is False
        db.close()


class TestCrossFacilityDashboard:
    """Dashboard data must be scoped to the user's facility."""

    def test_facility_a_dashboard_excludes_facility_b_visits(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        visits = DashboardService.get_today_visits(db, facility_id=data["fac_a"].id)
        visit_ids = {v.visit_id for v in visits}
        assert "VIS-A1" in visit_ids
        assert "VIS-B1" not in visit_ids
        db.close()

    def test_facility_b_dashboard_excludes_facility_a_visits(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        visits = DashboardService.get_today_visits(db, facility_id=data["fac_b"].id)
        visit_ids = {v.visit_id for v in visits}
        assert "VIS-B1" in visit_ids
        assert "VIS-A1" not in visit_ids
        db.close()

    def test_facility_a_kpi_excludes_facility_b(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        kpis_a = DashboardService.get_kpi_counts(db, facility_id=data["fac_a"].id)
        kpis_b = DashboardService.get_kpi_counts(db, facility_id=data["fac_b"].id)
        assert kpis_a["total_patients"] == 2  # Aarav + Fatima
        assert kpis_b["total_patients"] == 1  # Rahul only
        db.close()

    def test_facility_a_queue_excludes_facility_b(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        queue_a = DashboardService.get_queue_table_data(db, facility_id=data["fac_a"].id)
        queue_b = DashboardService.get_queue_table_data(db, facility_id=data["fac_b"].id)
        tokens_a = {q["token_number"] for q in queue_a}
        tokens_b = {q["token_number"] for q in queue_b}
        assert "MED-A01" in tokens_a
        assert "MED-B01" not in tokens_a
        assert "MED-B01" in tokens_b
        assert "MED-A01" not in tokens_b
        db.close()

    def test_facility_a_active_doctors_excludes_facility_b(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        docs_a = DashboardService.get_active_doctors(db, facility_id=data["fac_a"].id)
        docs_b = DashboardService.get_active_doctors(db, facility_id=data["fac_b"].id)
        doc_ids_a = {d.id for d in docs_a}
        doc_ids_b = {d.id for d in docs_b}
        assert data["doc_khan"].id in doc_ids_a
        assert data["doc_gupta"].id not in doc_ids_a
        assert data["doc_gupta"].id in doc_ids_b
        assert data["doc_khan"].id not in doc_ids_b
        db.close()

    def test_facility_a_departments_excludes_facility_b(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        depts_a = DashboardService.get_department_queue_counts(db, facility_id=data["fac_a"].id)
        dept_names_a = {d["name"] for d in depts_a}
        assert "General Medicine" in dept_names_a
        assert "Cardiology" not in dept_names_a
        db.close()


class TestCrossFacilityManagementScoping:
    """Management service queries must be facility-scoped."""

    def test_facility_a_staff_list_excludes_facility_b(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_a"].id, "hospital_admin")
        staff = ManagementService.get_all_staff(db, user_data=user_data)
        usernames = {s["username"] for s in staff}
        assert "receptionist_a" in usernames
        assert "drkhan" in usernames
        assert "receptionist_b" not in usernames
        assert "drgupta" not in usernames
        db.close()

    def test_facility_a_recent_visits_excludes_facility_b(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_a"].id, "hospital_admin")
        visits = ManagementService.get_recent_visits(db, limit=50, user_data=user_data)
        visit_ids = {v["visit_id"] for v in visits}
        assert "VIS-A1" in visit_ids
        assert "VIS-A2" in visit_ids
        assert "VIS-B1" not in visit_ids
        db.close()


class TestReferralCrossFacilityBehavior:
    """Referrals must still work across facilities, but only share the referral package."""

    def test_referral_lookup_requires_receiving_facility(self):
        """lookup_referral verifies the receiving_facility_id matches."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        # Create a referral from A to B
        ref = ReferralService.create_referral(
            db,
            visit_id=data["vis_a1"].id,
            patient_id=data["pat_aarav"].id,
            referring_doctor_id=data["doc_khan"].id,
            referring_facility_id=data["fac_a"].id,
            receiving_facility_id=data["fac_b"].id,
            receiving_department_id=data["dept_cardio_b"].id,
            receiving_doctor_id=data["doc_gupta"].id,
            reason="Cardiology evaluation",
            urgency="urgent",
        )
        db.flush()

        # Build data package
        ReferralService.build_data_package(db, ref.id)
        db.commit()

        # Correct facility can look up
        result = ReferralService.lookup_referral(
            db, "9000000001", ref.verification_code, data["fac_b"].id
        )
        assert result is not None

        # Wrong facility cannot look up
        result_wrong = ReferralService.lookup_referral(
            db, "9000000001", ref.verification_code, data["fac_a"].id
        )
        assert result_wrong is None
        db.close()

    def test_shared_patient_view_requires_facility_match(self):
        """get_shared_patient_view verifies receiving_facility_id."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        ref = ReferralService.create_referral(
            db,
            visit_id=data["vis_a1"].id,
            patient_id=data["pat_aarav"].id,
            referring_doctor_id=data["doc_khan"].id,
            referring_facility_id=data["fac_a"].id,
            receiving_facility_id=data["fac_b"].id,
            receiving_department_id=data["dept_cardio_b"].id,
            receiving_doctor_id=data["doc_gupta"].id,
            reason="Cardiology evaluation",
            urgency="urgent",
        )
        ReferralService.build_data_package(db, ref.id)
        db.commit()

        # Correct facility gets the shared view
        view = ReferralService.get_shared_patient_view(db, ref.id, data["fac_b"].id)
        assert view is not None
        assert "patient_summary" in view

        # Wrong facility gets nothing
        view_wrong = ReferralService.get_shared_patient_view(db, ref.id, data["fac_a"].id)
        assert view_wrong is None
        db.close()

    def test_referral_does_not_grant_full_patient_access(self):
        """Receiving facility can only access data in the referral package, not the full patient record."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        ref = ReferralService.create_referral(
            db,
            visit_id=data["vis_a1"].id,
            patient_id=data["pat_aarav"].id,
            referring_doctor_id=data["doc_khan"].id,
            referring_facility_id=data["fac_a"].id,
            receiving_facility_id=data["fac_b"].id,
            receiving_department_id=data["dept_cardio_b"].id,
            receiving_doctor_id=data["doc_gupta"].id,
            reason="Cardiology evaluation",
            urgency="urgent",
        )
        ReferralService.build_data_package(db, ref.id)
        db.commit()

        # Facility B staff cannot access the patient directly
        user_data_b = _session_data(None, data["fac_b"].id, "receptionist")
        result = check_patient_access(db, data["pat_aarav"].id, user_data_b)
        assert result is not None
        assert result["success"] is False
        db.close()


class TestGlobalRoleBypass:
    """Government/admin roles should bypass facility checks."""

    def test_global_role_can_access_any_patient(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        for role in GLOBAL_ROLES:
            user_data = _session_data(None, data["fac_a"].id, role)
            result = check_patient_access(db, data["pat_rahul"].id, user_data)
            assert result is None, f"Role {role} should bypass facility check"
        db.close()

    def test_global_role_can_access_any_visit(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_a"].id, "government_admin")
        result = check_visit_access(db, data["vis_b1"].id, user_data)
        assert result is None
        db.close()

    def test_global_role_staff_management_allowed(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        user_data = _session_data(None, data["fac_a"].id, "government_admin")
        result = ManagementService.deactivate_staff(
            db, data["user_rec_b"].id,
            requester_role="government_admin",
            user_data=user_data,
        )
        assert result["success"] is True
        db.close()


class TestDoctorAssignmentIntegrity:
    """Existing doctor assignment rules must still work."""

    def test_doctor_queue_is_own_tokens_only(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        queue = DoctorService.get_doctor_queue_data(db, data["doc_khan"].id)
        assert len(queue) == 1
        assert queue[0]["token_number"] == "MED-A01"

        queue_b = DoctorService.get_doctor_queue_data(db, data["doc_gupta"].id)
        assert len(queue_b) == 1
        assert queue_b[0]["token_number"] == "MED-B01"
        db.close()

    def test_doctor_token_update_restricted_to_own_tokens(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        # Dr. Khan cannot update Dr. Gupta's token
        result = DoctorService.update_token_status(
            db, data["doc_khan"].id, data["tok_b1"].id, "CALLED"
        )
        assert result is False

        # Dr. Khan can update own token
        result_own = DoctorService.update_token_status(
            db, data["doc_khan"].id, data["tok_a1"].id, "CALLED"
        )
        assert result_own is True
        db.close()

    def test_doctor_patient_details_restricted_to_own_tokens(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        # Dr. Khan cannot get patient details for Dr. Gupta's token
        details = DoctorService.get_patient_details(db, data["doc_khan"].id, data["tok_b1"].id)
        assert details is None

        # Dr. Khan can get patient details for own token
        details_own = DoctorService.get_patient_details(db, data["doc_khan"].id, data["tok_a1"].id)
        assert details_own is not None
        db.close()


class TestBackwardCompatibility:
    """Existing callers that don't pass user_data must still work."""

    def test_deactivate_staff_without_user_data(self):
        """Original test pattern: ManagementService.deactivate_staff(db, user_id, requester_role=...)"""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        result = ManagementService.deactivate_staff(db, data["user_rec_a"].id, requester_role="hospital_admin")
        assert result["success"] is True
        db.close()

    def test_dashboard_without_facility_id(self):
        """DashboardService methods without facility_id return global data."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        kpis = DashboardService.get_kpi_counts(db)
        assert kpis["total_patients"] == 3  # All patients
        db.close()

    def test_management_staff_list_without_user_data(self):
        """ManagementService.get_all_staff without user_data returns all staff."""
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        staff = ManagementService.get_all_staff(db)
        usernames = {s["username"] for s in staff}
        assert "receptionist_a" in usernames
        assert "receptionist_b" in usernames
        db.close()


class TestPatientHistoryFacilityScoping:
    """PatientHistoryService must scope to facility when provided."""

    def test_facility_a_history_excludes_facility_b_visits(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        # Aarav only has visits at Facility A
        history = PatientHistoryService.get_full_history(db, data["pat_aarav"].id, facility_id=data["fac_a"].id)
        assert len(history.get("visits", [])) == 1

        # Facility B view of Aarav returns no visits
        history_b = PatientHistoryService.get_full_history(db, data["pat_aarav"].id, facility_id=data["fac_b"].id)
        assert len(history_b.get("visits", [])) == 0
        db.close()

    def test_visit_detail_facility_check(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        # Facility A can see its own visit
        detail = PatientHistoryService.get_visit_detail(db, data["vis_a1"].id, facility_id=data["fac_a"].id)
        assert detail is not None

        # Facility B cannot see Facility A's visit
        detail_cross = PatientHistoryService.get_visit_detail(db, data["vis_a1"].id, facility_id=data["fac_b"].id)
        assert detail_cross is None
        db.close()


class TestSearchPatientFacilityFiltering:
    """PatientService.search_patients with facility_id filters results."""

    def test_search_at_facility_a_excludes_facility_b_patients(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        # Search for all patients at Facility A
        results = PatientService.search_patients(db, "PAT", facility_id=data["fac_a"].id)
        patient_ids = {p.patient_id for p in results}
        assert "PAT-00101" in patient_ids  # Aarav
        assert "PAT-00102" in patient_ids  # Fatima
        assert "PAT-00103" not in patient_ids  # Rahul (Facility B)
        db.close()

    def test_search_at_facility_b_excludes_facility_a_patients(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        Sess = sessionmaker(bind=engine)
        db = Sess()
        data = _seed_two_facilities(db)

        results = PatientService.search_patients(db, "PAT", facility_id=data["fac_b"].id)
        patient_ids = {p.patient_id for p in results}
        assert "PAT-00103" in patient_ids  # Rahul
        assert "PAT-00101" not in patient_ids  # Aarav (Facility A)
        assert "PAT-00102" not in patient_ids  # Fatima (Facility A)
        db.close()
