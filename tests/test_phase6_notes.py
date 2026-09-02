"""Tests for DoctorNoteService using isolated test database."""
import pytest
from tests.test_db_helper import create_isolated_test_db
from database.models import Patient, Visit
from services.doctor_note_service import DoctorNoteService


@pytest.fixture
def test_db():
    db = create_isolated_test_db()
    yield db
    db.close()


def test_save_and_update_doctor_note(test_db):
    patient = test_db.query(Patient).first()
    visit = test_db.query(Visit).filter(Visit.patient_id == patient.id).first()
    doctor = visit.doctor

    note = DoctorNoteService.save_note(
        test_db,
        visit_id=visit.id,
        patient_id=patient.id,
        doctor_id=doctor.id,
        diagnosis="Acute Bronchitis",
        examination_findings="Bilateral rhonchi, clear chest X-ray",
        treatment_plan="Course of antibiotics, bronchodilator",
        notes="Patient advised bed rest for 3 days",
    )
    test_db.commit()

    assert note.id is not None
    assert note.diagnosis == "Acute Bronchitis"

    # Verify get_note_for_visit
    fetched = DoctorNoteService.get_note_for_visit(test_db, visit.id)
    assert fetched is not None
    assert fetched.diagnosis == "Acute Bronchitis"

    # Update note for same visit (should update existing rather than creating duplicate)
    updated = DoctorNoteService.save_note(
        test_db,
        visit_id=visit.id,
        patient_id=patient.id,
        doctor_id=doctor.id,
        diagnosis="Acute Bronchitis with Mild Asthma Exacerbation",
        examination_findings="Improved rhonchi",
        treatment_plan="Continue regimen",
        notes="Follow-up in 1 week",
    )
    test_db.commit()

    assert updated.id == note.id
    assert updated.diagnosis == "Acute Bronchitis with Mild Asthma Exacerbation"

    history = DoctorNoteService.get_patient_notes_history(test_db, patient.id)
    assert len(history) == 1
