from io import BytesIO

from database.db import get_session, init_db
from database.models import Patient, Visit, Token, Facility, TokenStatus
from services.case_service import PatientCaseService
from services.doctor_service import DoctorService
from services.document_service import DocumentService
from services.patient_service import PatientService
from services.token_service import TokenService
from services.visit_service import VisitService


from tests.test_db_helper import create_isolated_test_db


def get_seeded_context():
    db = create_isolated_test_db()
    facility = db.query(Facility).first()
    patient = db.query(Patient).first()
    visit = db.query(Visit).filter(Visit.patient_id == patient.id).first()
    token = db.query(Token).filter(Token.visit_id == visit.id).first()
    doctor = visit.doctor
    return db, facility, patient, visit, token, doctor


def test_doctor_queue_isolation():
    db, _, _, _, _, doctor = get_seeded_context()
    doctors = db.query(type(doctor)).all()
    if len(doctors) < 2:
        return

    first_id = doctors[0].id
    second_id = doctors[1].id
    queue_a = DoctorService.get_doctor_queue_data(db, first_id)
    queue_b = DoctorService.get_doctor_queue_data(db, second_id)
    assert set(item["patient_id"] for item in queue_a).isdisjoint(
        set(item["patient_id"] for item in queue_b)
    )


def test_patient_details_exposes_database_contract():
    db, _, patient, visit, token, doctor = get_seeded_context()
    details = DoctorService.get_patient_details(db, doctor.id, token.id)
    assert details is not None
    assert details["patient_pk_id"] == patient.id
    assert details["visit_db_id"] == visit.id
    assert details["token_number"] == token.token_number


def test_visit_token_linkage():
    db, _, patient, visit, token, _ = get_seeded_context()
    assert token.visit_id == visit.id
    assert visit.patient_id == patient.id


def test_queue_status_transitions():
    db, _, _, _, token, doctor = get_seeded_context()
    assert DoctorService.update_token_status(db, doctor.id, token.id, "CALLED") is True
    assert db.query(Token).filter(Token.id == token.id).first().status == TokenStatus.CALLED
    assert DoctorService.update_token_status(db, doctor.id, token.id, "WITH_DOCTOR") is True
    assert db.query(Token).filter(Token.id == token.id).first().status == TokenStatus.WITH_DOCTOR
    assert DoctorService.update_token_status(db, doctor.id, token.id, "COMPLETED") is True
    assert db.query(Token).filter(Token.id == token.id).first().status == TokenStatus.COMPLETED


def test_case_submission_and_red_flag_detection():
    db, _, patient, visit, _, _ = get_seeded_context()
    case = PatientCaseService.submit_case(
        db,
        patient_id=patient.id,
        visit_id=visit.id,
        chief_complaint="Difficulty breathing and chest pain",
        duration="2 hours",
        symptoms="Severe shortness of breath, chest pain",
        additional_notes="Feels faint",
    )
    assert case.red_flag_detected is True
    assert "difficulty breathing" in case.red_flags.lower() or "severe chest pain" in case.red_flags.lower()
    assert "AI-assisted summary" in case.ai_summary


def test_document_association_is_saved_to_visit():
    db, _, patient, visit, _, _ = get_seeded_context()
    upload = BytesIO(b"sample PDF content")
    upload.name = "report.pdf"
    saved = DocumentService.save_document(db, patient.id, visit.id, upload, upload.name)
    assert saved.patient_id == patient.id
    assert saved.visit_id == visit.id
    assert saved.file_name == "report.pdf"
    assert DocumentService.get_documents_for_visit(db, patient.id, visit.id)
