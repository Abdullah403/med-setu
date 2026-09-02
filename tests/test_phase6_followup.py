"""Tests for FollowUpService using isolated test database."""
from datetime import datetime, timedelta
import pytest
from tests.test_db_helper import create_isolated_test_db
from database.models import Patient, Visit
from services.followup_service import FollowUpService


@pytest.fixture
def test_db():
    db = create_isolated_test_db()
    yield db
    db.close()


def test_schedule_and_update_followup(test_db):
    patient = test_db.query(Patient).first()
    visit = test_db.query(Visit).filter(Visit.patient_id == patient.id).first()
    doctor = visit.doctor
    target_date = datetime.utcnow() + timedelta(days=7)

    followup = FollowUpService.schedule_followup(
        test_db,
        visit_id=visit.id,
        patient_id=patient.id,
        doctor_id=doctor.id,
        follow_up_date=target_date,
        reason="Review chest symptoms and repeat spirometry",
    )
    test_db.commit()

    assert followup.id is not None
    assert followup.status == "scheduled"
    assert followup.reason == "Review chest symptoms and repeat spirometry"

    # Patient follow-ups
    patient_fups = FollowUpService.get_followups_for_patient(test_db, patient.id)
    assert len(patient_fups) >= 1

    # Doctor upcoming follow-ups
    doc_fups = FollowUpService.get_upcoming_followups_for_doctor(test_db, doctor.id)
    assert len(doc_fups) >= 1

    # Update status
    success = FollowUpService.update_followup_status(test_db, followup.id, "completed")
    test_db.commit()
    assert success is True
    assert followup.status == "completed"
