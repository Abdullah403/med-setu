"""Tests for PatientHistoryService chronological timeline aggregation."""
import pytest
from tests.test_db_helper import create_isolated_test_db
from database.models import Patient, Visit
from services.prescription_service import PrescriptionService
from services.doctor_note_service import DoctorNoteService
from services.case_service import PatientCaseService
from services.patient_history_service import PatientHistoryService


@pytest.fixture
def test_db():
    db = create_isolated_test_db()
    yield db
    db.close()


def test_patient_history_aggregation(test_db):
    patient = test_db.query(Patient).filter(Patient.patient_id == "PAT-00184").first()
    visit = test_db.query(Visit).filter(Visit.patient_id == patient.id).first()
    doctor = visit.doctor

    # Add clinical records
    PatientCaseService.submit_case(
        test_db,
        patient_id=patient.id,
        visit_id=visit.id,
        chief_complaint="Persistent headache and fatigue",
        duration="5 days",
        symptoms="Throbbing pain, photophobia",
        additional_notes="",
    )
    DoctorNoteService.save_note(
        test_db,
        visit_id=visit.id,
        patient_id=patient.id,
        doctor_id=doctor.id,
        diagnosis="Tension Headache",
        treatment_plan="Hydration, NSAIDs",
    )
    PrescriptionService.create_prescription(
        test_db,
        visit_id=visit.id,
        patient_id=patient.id,
        doctor_id=doctor.id,
        medication_name="Ibuprofen",
        dosage="400mg",
        frequency="Twice daily",
        duration="5 days",
    )
    test_db.commit()

    # Query full history
    history = PatientHistoryService.get_full_history(test_db, patient.id)
    assert history["patient"].patient_id == "PAT-00184"
    assert len(history["visits"]) >= 1

    first_v = history["visits"][0]
    assert len(first_v["cases"]) >= 1
    assert len(first_v["prescriptions"]) >= 1
    assert first_v["doctor_note"] is not None
    assert first_v["doctor_note"].diagnosis == "Tension Headache"
