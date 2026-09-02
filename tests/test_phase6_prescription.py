"""Tests for PrescriptionService using isolated test database."""
import pytest
from tests.test_db_helper import create_isolated_test_db
from database.models import Patient, Visit, Doctor
from services.prescription_service import PrescriptionService


@pytest.fixture
def test_db():
    db = create_isolated_test_db()
    yield db
    db.close()


def test_create_and_get_prescriptions(test_db):
    patient = test_db.query(Patient).first()
    visit = test_db.query(Visit).filter(Visit.patient_id == patient.id).first()
    doctor = visit.doctor

    rx1 = PrescriptionService.create_prescription(
        test_db,
        visit_id=visit.id,
        patient_id=patient.id,
        doctor_id=doctor.id,
        medication_name="Amoxicillin",
        dosage="500mg",
        frequency="Three times daily",
        duration="7 days",
        instructions="After meals",
    )
    test_db.commit()

    assert rx1.id is not None
    assert rx1.medication_name == "Amoxicillin"

    rx2 = PrescriptionService.create_prescription(
        test_db,
        visit_id=visit.id,
        patient_id=patient.id,
        doctor_id=doctor.id,
        medication_name="Paracetamol",
        dosage="650mg",
        frequency="As needed for fever",
        duration="3 days",
        instructions="Max 3 tablets per day",
    )
    test_db.commit()

    visit_rxs = PrescriptionService.get_prescriptions_for_visit(test_db, visit.id)
    assert len(visit_rxs) == 2
    assert visit_rxs[0].medication_name == "Amoxicillin"
    assert visit_rxs[1].medication_name == "Paracetamol"

    history = PrescriptionService.get_patient_prescription_history(test_db, patient.id)
    assert len(history) == 2


def test_prescription_validation(test_db):
    patient = test_db.query(Patient).first()
    visit = test_db.query(Visit).filter(Visit.patient_id == patient.id).first()
    doctor = visit.doctor

    with pytest.raises(ValueError, match="Medication name is required"):
        PrescriptionService.create_prescription(
            test_db, visit.id, patient.id, doctor.id, "", "500mg", "Once", "5 days"
        )

    with pytest.raises(ValueError, match="Dosage is required"):
        PrescriptionService.create_prescription(
            test_db, visit.id, patient.id, doctor.id, "Aspirin", "", "Once", "5 days"
        )
