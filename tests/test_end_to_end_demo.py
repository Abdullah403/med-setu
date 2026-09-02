"""End-to-End master integration test executing the complete 25-step MED-SETU scenario.
Runs on an isolated test database to protect production med_setu.db.
"""
from datetime import datetime, timedelta
from io import BytesIO
import pytest
from tests.test_db_helper import create_isolated_test_db
from database.models import (
    Patient, Visit, Token, TokenStatus, Facility, Department, Doctor, UserRole
)
from services.auth_service import AuthService
from services.patient_service import PatientService
from services.visit_service import VisitService
from services.token_service import TokenService
from services.doctor_service import DoctorService
from services.case_service import PatientCaseService
from services.document_service import DocumentService
from services.prescription_service import PrescriptionService
from services.doctor_note_service import DoctorNoteService
from services.referral_service import ReferralService
from services.followup_service import FollowUpService
from services.patient_history_service import PatientHistoryService
from services.dashboard_service import DashboardService


@pytest.fixture
def test_db():
    db = create_isolated_test_db()
    yield db
    db.close()


def test_complete_25_step_demo_scenario(test_db):
    """
    Execute the full end-to-end Rahim Shaikh workflow across Hospital A and Hospital B.
    """
    # ── Step 1: Receptionist logs in ──
    rec_auth = AuthService.authenticate(test_db, "receptionist", "password123")
    assert rec_auth is not None
    assert rec_auth["role"] == "receptionist"
    assert rec_auth["facility"]["name"] == "Rural Community Health Centre"

    # ── Step 2: Register/Search Rahim Shaikh (Age 52) ──
    rahim = PatientService.get_patient_by_identifier(test_db, "9876543210")
    if not rahim:
        rahim = PatientService.register_patient(
            test_db, "Rahim Shaikh", 52, "Male", "9876543210", "Hindi", "Thane East"
        )
    assert rahim is not None
    assert rahim.full_name == "Rahim Shaikh"
    assert rahim.age == 52

    # ── Step 3: Create visit: General Medicine, Dr. Khan ──
    hospital_a = test_db.query(Facility).filter(Facility.id == rec_auth["facility"]["id"]).first()
    gen_med = (
        test_db.query(Department)
        .filter(Department.facility_id == hospital_a.id, Department.name == "General Medicine")
        .first()
    )
    dr_khan = (
        test_db.query(Doctor)
        .filter(Doctor.facility_id == hospital_a.id, Doctor.department_id == gen_med.id)
        .first()
    )
    assert dr_khan.user.username == "drkhan"

    visit = VisitService.create_visit(
        test_db,
        patient_id=rahim.id,
        facility_id=hospital_a.id,
        department_id=gen_med.id,
        doctor_id=dr_khan.id,
    )
    test_db.flush()
    assert visit.visit_id.startswith("VIS-")
    assert visit.status == "ongoing"

    # ── Step 4: Generate Token ──
    token = TokenService.create_token(test_db, visit.id, dr_khan.id)
    test_db.commit()
    assert token.token_number.startswith("MED-")
    assert token.status == TokenStatus.WAITING

    # ── Step 5: Patient opens WhatsApp simulator ──
    # Simulating patient interaction
    # ── Step 6: Patient submits symptoms ──
    patient_message = "I have fever for 3 days with cough and weakness."
    case = PatientCaseService.submit_case(
        test_db,
        patient_id=rahim.id,
        visit_id=visit.id,
        chief_complaint=patient_message,
        duration="3 days",
        symptoms="fever, cough, weakness",
        additional_notes="Submitted via WhatsApp simulator",
    )
    test_db.commit()
    assert case.chief_complaint == patient_message
    assert "AI-assisted summary" in case.ai_summary

    # ── Step 7: Patient uploads a sample medical report ──
    # ── Step 8: OCR / extraction runs ──
    sample_file = BytesIO(b"Chest X-Ray Report: Bilateral lung fields clear. No focal consolidation.")
    sample_file.name = "chest_xray_report.pdf"
    doc = DocumentService.save_document(test_db, rahim.id, visit.id, sample_file, sample_file.name)
    test_db.commit()
    assert doc.id is not None
    assert doc.file_name == "chest_xray_report.pdf"

    # ── Step 9: Doctor (Dr. Khan) logs in and opens the same token ──
    dr_auth = AuthService.authenticate(test_db, "drkhan", "password123")
    assert dr_auth is not None
    assert dr_auth["doctor"]["id"] == dr_khan.id

    details = DoctorService.get_patient_details(test_db, dr_khan.id, token.id)
    assert details is not None

    # ── Step 10: Doctor sees: Rahim Shaikh, Age 52, Token, Dept, Case, Report, History, AI Summary ──
    assert details["patient_name"] == "Rahim Shaikh"
    assert details["age"] == 52
    assert details["token_number"] == token.token_number
    assert details["department"] == "General Medicine"

    retrieved_case = PatientCaseService.get_case_for_visit(test_db, rahim.id, visit.id)
    assert retrieved_case.chief_complaint == patient_message
    assert "AI-assisted summary" in retrieved_case.ai_summary

    docs = DocumentService.get_documents_for_visit(test_db, rahim.id, visit.id)
    assert len(docs) >= 1
    assert docs[0].file_name == "chest_xray_report.pdf"

    # ── Step 11: Doctor changes queue state: WAITING -> CALLED -> WITH_DOCTOR ──
    assert DoctorService.update_token_status(test_db, dr_khan.id, token.id, "CALLED") is True
    assert test_db.query(Token).filter(Token.id == token.id).first().status == TokenStatus.CALLED

    assert DoctorService.update_token_status(test_db, dr_khan.id, token.id, "WITH_DOCTOR") is True
    assert test_db.query(Token).filter(Token.id == token.id).first().status == TokenStatus.WITH_DOCTOR

    # ── Step 12: Receptionist sees the updated state from same database ──
    receptionist_queue = DashboardService.get_queue_table_data(test_db)
    token_in_rec = next(item for item in receptionist_queue if item["token_number"] == token.token_number)
    assert token_in_rec["status"] == "WITH_DOCTOR"

    # ── Step 13: Doctor creates prescription ──
    rx1 = PrescriptionService.create_prescription(
        test_db,
        visit_id=visit.id,
        patient_id=rahim.id,
        doctor_id=dr_khan.id,
        medication_name="Aspirin",
        dosage="75mg",
        frequency="Once daily",
        duration="30 days",
        instructions="After breakfast",
    )
    rx2 = PrescriptionService.create_prescription(
        test_db,
        visit_id=visit.id,
        patient_id=rahim.id,
        doctor_id=dr_khan.id,
        medication_name="Nitroglycerin",
        dosage="0.5mg",
        frequency="As needed (SOS)",
        duration="15 days",
        instructions="Sublingually for severe chest discomfort",
    )
    DoctorNoteService.save_note(
        test_db,
        visit_id=visit.id,
        patient_id=rahim.id,
        doctor_id=dr_khan.id,
        diagnosis="Suspected Angina / Coronary Artery Disease",
        treatment_plan="Urgent Cardiology evaluation and TMT",
    )
    test_db.commit()

    prescriptions = PrescriptionService.get_prescriptions_for_visit(test_db, visit.id)
    assert len(prescriptions) == 2

    # ── Step 14 & 15: Doctor creates referral to Hospital B (District General Hospital, Cardiology, Dr. Gupta) ──
    hospital_b = test_db.query(Facility).filter(Facility.name == "District General Hospital").first()
    assert hospital_b is not None

    cardiology_b = (
        test_db.query(Department)
        .filter(Department.facility_id == hospital_b.id, Department.name == "Cardiology")
        .first()
    )
    dr_gupta = (
        test_db.query(Doctor)
        .filter(Doctor.facility_id == hospital_b.id, Doctor.department_id == cardiology_b.id)
        .first()
    )

    referral = ReferralService.create_referral(
        test_db,
        visit_id=visit.id,
        patient_id=rahim.id,
        referring_doctor_id=dr_khan.id,
        referring_facility_id=hospital_a.id,
        receiving_facility_id=hospital_b.id,
        receiving_department_id=cardiology_b.id,
        receiving_doctor_id=dr_gupta.id,
        reason="Suspected angina requiring specialist cardiology evaluation and angiography",
        urgency="urgent",
        appointment_date=datetime.utcnow() + timedelta(days=7),
    )
    test_db.commit()

    # ── Step 16 & 17: Click [Send Patient Data] -> Referral package is created ──
    package = ReferralService.build_data_package(test_db, referral.id)
    test_db.commit()

    assert package is not None
    assert package.referral_id == referral.id
    assert "Aspirin" in package.prescription_data
    assert "Suspected Angina" in package.visit_history
    assert "chest_xray_report.pdf" in package.document_references
    verification_code = referral.verification_code
    assert len(verification_code) == 6

    # ── Step 18: Generate Referral PDF ──
    pdf_path = ReferralService.generate_referral_pdf(test_db, referral.id)
    test_db.commit()
    assert pdf_path is not None

    # Doctor completes visit
    assert DoctorService.update_token_status(test_db, dr_khan.id, token.id, "COMPLETED") is True
    assert test_db.query(Visit).filter(Visit.id == visit.id).first().status == "completed"

    # ── Step 19: Open Receiving Hospital / Referral Desk at Hospital B ──
    rec_b_auth = AuthService.authenticate(test_db, "receptionist_b", "password123")
    assert rec_b_auth["facility"]["id"] == hospital_b.id

    # ── Step 20 & 21: Enter registered phone number + referral verification -> Hospital B finds referral ──
    lookup_result = ReferralService.lookup_referral(
        test_db,
        phone="9876543210",
        verification_code=verification_code,
        receiving_facility_id=hospital_b.id,
    )
    assert lookup_result is not None
    assert lookup_result["referral"].id == referral.id
    assert lookup_result["patient"].full_name == "Rahim Shaikh"

    # ── Step 22: Receiving doctor / hospital sees authorized shared data ──
    shared_view = ReferralService.get_shared_patient_view(
        test_db, referral_id=referral.id, receiving_facility_id=hospital_b.id
    )
    assert shared_view is not None
    assert shared_view["patient_summary"]["full_name"] == "Rahim Shaikh"
    assert shared_view["clinical_summary"]["chief_complaint"] == patient_message
    assert len(shared_view["prescription_data"]) == 2
    assert shared_view["prescription_data"][0]["medication_name"] == "Aspirin"
    assert len(shared_view["document_references"]) >= 1
    assert "Aspirin" in shared_view["referral_summary"]

    # ── Step 23: Patient does NOT need to repeat entire history ──
    # Receiving hospital can access the shared data directly
    assert shared_view["clinical_summary"]["duration"] == "3 days"

    # ── Step 24: Doctor creates follow-up ──
    followup = FollowUpService.schedule_followup(
        test_db,
        visit_id=visit.id,
        patient_id=rahim.id,
        doctor_id=dr_khan.id,
        follow_up_date=datetime.utcnow() + timedelta(days=14),
        reason="Follow up after cardiology consultation at Hospital B",
    )
    test_db.commit()
    assert followup.id is not None
    assert followup.status == "scheduled"

    # ── Step 25: Patient sees follow-up and reminders in WhatsApp simulator ──
    patient_followups = FollowUpService.get_followups_for_patient(test_db, rahim.id)
    assert len(patient_followups) >= 1
    assert any(f.reason == "Follow up after cardiology consultation at Hospital B" for f in patient_followups)

    patient_referrals = ReferralService.get_referrals_for_patient(test_db, rahim.id)
    assert len(patient_referrals) >= 1
    assert any(r.referral_id == referral.referral_id for r in patient_referrals)
