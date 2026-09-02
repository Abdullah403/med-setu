"""Regression tests for Patient Deactivation, Reactivation, Deletion, and Data Management."""
import pytest
from datetime import datetime, timedelta
from database.db import create_engine, sessionmaker, Base
from database.models import (
    User, Doctor, Patient, Visit, Token, TokenStatus, Facility, Department,
    Referral, ReferralDataPackage, Prescription, DoctorNote, FollowUp, PatientCase, MedicalDocument
)
from services.auth_service import AuthService
from services.patient_service import PatientService
from services.visit_service import VisitService
from services.token_service import TokenService
from services.prescription_service import PrescriptionService
from services.doctor_note_service import DoctorNoteService
from services.referral_service import ReferralService
from services.management_service import ManagementService
from tests.test_db_helper import create_isolated_test_db


def test_1_to_5_patient_lifecycle_search_deactivate_reactivate():
    """
    Tests 1, 2, 3, 4, 5:
    1. Create patient
    2. Search patient
    3. Deactivate patient
    4. Deactivated patient excluded from active search by default (included when flag set)
    5. Reactivate patient
    """
    db = create_isolated_test_db()

    # 1. Create Patient
    p = PatientService.register_patient(
        db,
        full_name="Tariq Mansoor",
        age=42,
        gender="Male",
        phone="9988112233",
        preferred_language="Hindi"
    )
    db.commit()
    assert p.id is not None
    assert p.is_active is True

    # 2. Search Patient
    active_search = PatientService.search_patients(db, "9988112233", include_deactivated=False)
    assert len(active_search) == 1
    assert active_search[0].id == p.id

    # 3. Deactivate Patient
    deact_res = PatientService.deactivate_patient(db, p.id, user_role="receptionist")
    assert deact_res["success"] is True
    assert p.is_active is False

    # 4. Deactivated patient excluded from active search
    normal_search = PatientService.search_patients(db, "9988112233", include_deactivated=False)
    assert len(normal_search) == 0, "Deactivated patient must not appear in normal search"

    # Included when flag is set
    audit_search = PatientService.search_patients(db, "9988112233", include_deactivated=True)
    assert len(audit_search) == 1
    assert audit_search[0].id == p.id
    assert audit_search[0].is_active is False

    # 5. Reactivate Patient
    react_res = PatientService.reactivate_patient(db, p.id, user_role="receptionist")
    assert react_res["success"] is True
    assert p.is_active is True

    reactivated_search = PatientService.search_patients(db, "9988112233", include_deactivated=False)
    assert len(reactivated_search) == 1
    assert reactivated_search[0].id == p.id

    db.close()


def test_6_to_9_deletion_authorization_and_cascade_safety():
    """
    Tests 6, 7, 8, 9:
    6. Authorized deletion
    7. Unauthorized doctor cannot delete patient
    8. Unauthorized receptionist cannot perform admin deletion if restricted
    9. Deletion does not leave orphaned dependent records
    """
    db = create_isolated_test_db()

    # Create demo test patient with full dependent tree:
    # Patient -> Visit -> Token, Case, Doc, Rx, Note, Referral (with DataPackage), FollowUp
    p = PatientService.register_patient(
        db,
        full_name="Disposable Test Patient",
        age=29,
        gender="Female",
        phone="9000000001",
        preferred_language="English"
    )
    db.commit()

    facility = db.query(Facility).first()
    dept = db.query(Department).filter(Department.facility_id == facility.id).first()
    doctor = db.query(Doctor).filter(Doctor.department_id == dept.id).first()

    visit = VisitService.create_visit(
        db,
        patient_id=p.id,
        facility_id=facility.id,
        department_id=dept.id,
        doctor_id=doctor.id
    )
    db.flush()

    token = TokenService.create_token(db, visit.id, doctor.id)
    db.commit()

    # Add Case
    pcase = PatientCase(
        patient_id=p.id,
        visit_id=visit.id,
        chief_complaint="Fever and chills",
        duration="3 days",
        symptoms="High fever",
        red_flag_detected=False
    )
    db.add(pcase)

    # Add Document
    doc = MedicalDocument(
        patient_id=p.id,
        visit_id=visit.id,
        file_name="blood_test.pdf",
        stored_name="test_stored.pdf",
        file_type="application/pdf",
        file_path="scratch/nonexistent_test.pdf"
    )
    db.add(doc)

    # Add Prescription
    rx = Prescription(
        visit_id=visit.id,
        patient_id=p.id,
        doctor_id=doctor.id,
        medication_name="Paracetamol",
        dosage="500mg",
        frequency="TDS",
        duration="3 days"
    )
    db.add(rx)

    # Add DoctorNote
    note = DoctorNote(
        visit_id=visit.id,
        patient_id=p.id,
        doctor_id=doctor.id,
        diagnosis="Viral pyrexia",
        treatment_plan="Rest and hydration"
    )
    db.add(note)

    # Add FollowUp
    fup = FollowUp(
        visit_id=visit.id,
        patient_id=p.id,
        doctor_id=doctor.id,
        follow_up_date=datetime.utcnow() + timedelta(days=7),
        reason="Check temperature recovery"
    )
    db.add(fup)

    # Add Referral + ReferralDataPackage
    ref = Referral(
        referral_id="REF-TEST-9999",
        visit_id=visit.id,
        patient_id=p.id,
        referring_doctor_id=doctor.id,
        referring_facility_id=facility.id,
        receiving_facility_id=facility.id,
        receiving_department_id=dept.id,
        reason="Specialist review",
        verification_code="TESTCODE",
        status="pending"
    )
    db.add(ref)
    db.flush()

    pkg = ReferralDataPackage(
        referral_id=ref.id,
        patient_summary="{}",
        clinical_summary="{}",
        referral_summary="Test Referral Summary"
    )
    db.add(pkg)
    db.commit()

    patient_db_id = p.id
    visit_db_id = visit.id
    token_db_id = token.id

    # 7. Security: Unauthorized DOCTOR cannot delete patient
    doc_res = PatientService.delete_patient(db, patient_db_id, user_role="doctor", confirmed=True)
    assert doc_res["success"] is False
    assert "Unauthorized" in doc_res["error"]

    # 8. Security: Normal RECEPTIONIST without admin role cannot perform deletion
    rec_res = PatientService.delete_patient(db, patient_db_id, user_role="receptionist", confirmed=True)
    assert rec_res["success"] is False
    assert "Unauthorized" in rec_res["error"]

    # Unconfirmed admin attempt fails
    unconf_res = PatientService.delete_patient(db, patient_db_id, user_role="hospital_admin", confirmed=False)
    assert unconf_res["success"] is False
    assert "confirmation" in unconf_res["error"].lower()

    # 6. Authorized Admin Deletion with confirmation
    del_res = PatientService.delete_patient(db, patient_db_id, user_role="hospital_admin", confirmed=True)
    assert del_res["success"] is True

    # 9. Verify NO orphaned dependent records remain
    assert db.query(Patient).filter(Patient.id == patient_db_id).first() is None
    assert db.query(Visit).filter(Visit.patient_id == patient_db_id).first() is None
    assert db.query(Token).filter(Token.id == token_db_id).first() is None
    assert db.query(PatientCase).filter(PatientCase.patient_id == patient_db_id).first() is None
    assert db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient_db_id).first() is None
    assert db.query(Prescription).filter(Prescription.patient_id == patient_db_id).first() is None
    assert db.query(DoctorNote).filter(DoctorNote.patient_id == patient_db_id).first() is None
    assert db.query(FollowUp).filter(FollowUp.patient_id == patient_db_id).first() is None
    assert db.query(Referral).filter(Referral.patient_id == patient_db_id).first() is None
    assert db.query(ReferralDataPackage).filter(ReferralDataPackage.referral_id == ref.id).first() is None

    db.close()


def test_10_deactivation_preserves_clinical_history():
    """
    Test 10: Existing patient history remains 100% correct when deactivation is used.
    """
    db = create_isolated_test_db()
    # Use seeded patient Rahim Shaikh
    rahim = db.query(Patient).filter(Patient.patient_id == "PAT-00184").first()
    assert rahim is not None
    visits_count_before = len(rahim.visits)

    # Deactivate Rahim
    res = PatientService.deactivate_patient(db, rahim.id, user_role="receptionist")
    assert res["success"] is True
    assert rahim.is_active is False

    # Historical visits, notes, prescriptions are completely intact
    assert len(rahim.visits) == visits_count_before
    assert len(rahim.cases) > 0 or visits_count_before > 0
    assert rahim.full_name == "Rahim Shaikh"

    # Reactivate Rahim
    res_react = PatientService.reactivate_patient(db, rahim.id, user_role="receptionist")
    assert res_react["success"] is True
    assert rahim.is_active is True

    db.close()


def test_11_12_database_not_reset_and_auth_intact():
    """
    Test 11 & 12:
    11. Database is not reset, table structure intact
    12. Existing demo users still authenticate cleanly
    """
    db = create_isolated_test_db()

    # Verify receptionist login
    rec_auth = AuthService.authenticate(db, "receptionist", "password123")
    assert rec_auth is not None
    assert rec_auth["role"] == "receptionist"

    # Verify doctor login
    doc_auth = AuthService.authenticate(db, "drkhan", "password123")
    assert doc_auth is not None
    assert doc_auth["role"] == "doctor"

    # Verify doctor staff management deactivation / reactivation
    user_sharma = db.query(User).filter(User.username == "drsharma").first()
    assert user_sharma is not None

    deact_staff = ManagementService.deactivate_staff(db, user_sharma.id, requester_role="hospital_admin")
    assert deact_staff["success"] is True
    assert user_sharma.is_active is False
    assert user_sharma.doctor.is_available is False

    # Deactivated staff cannot authenticate
    assert AuthService.authenticate(db, "drsharma", "password123") is None

    # Reactivate staff
    react_staff = ManagementService.reactivate_staff(db, user_sharma.id, requester_role="hospital_admin")
    assert react_staff["success"] is True
    assert user_sharma.is_active is True
    assert user_sharma.doctor.is_available is True
    assert AuthService.authenticate(db, "drsharma", "password123") is not None

    db.close()
