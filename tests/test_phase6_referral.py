"""Tests for ReferralService and inter-hospital data transfer."""
from datetime import datetime, timedelta
import pytest
from tests.test_db_helper import create_isolated_test_db
from database.models import Patient, Visit, Facility, Department, Doctor
from services.case_service import PatientCaseService
from services.prescription_service import PrescriptionService
from services.doctor_note_service import DoctorNoteService
from services.referral_service import ReferralService


@pytest.fixture
def test_db():
    db = create_isolated_test_db()
    yield db
    db.close()


def test_referral_workflow_and_package_creation(test_db):
    patient = test_db.query(Patient).filter(Patient.patient_id == "PAT-00184").first()
    visit = test_db.query(Visit).filter(Visit.patient_id == patient.id).first()
    ref_doctor = visit.doctor
    ref_facility = visit.facility

    # Prepare clinical context
    case = PatientCaseService.submit_case(
        test_db,
        patient_id=patient.id,
        visit_id=visit.id,
        chief_complaint="Chest pain radiating to left arm",
        duration="2 weeks",
        symptoms="Shortness of breath on exertion, chest tightness",
        additional_notes="Hypertension for 5 years",
    )
    DoctorNoteService.save_note(
        test_db,
        visit_id=visit.id,
        patient_id=patient.id,
        doctor_id=ref_doctor.id,
        diagnosis="Suspected Coronary Artery Disease",
        treatment_plan="Referral to Cardiology for Angiography",
    )
    PrescriptionService.create_prescription(
        test_db,
        visit_id=visit.id,
        patient_id=patient.id,
        doctor_id=ref_doctor.id,
        medication_name="Aspirin",
        dosage="75mg",
        frequency="Once daily",
        duration="30 days",
        instructions="After food",
    )
    test_db.commit()

    # Destination: Hospital B (District General Hospital)
    hospital_b = test_db.query(Facility).filter(Facility.name == "District General Hospital").first()
    assert hospital_b is not None
    assert hospital_b.id != ref_facility.id

    cardiology_b = (
        test_db.query(Department)
        .filter(Department.facility_id == hospital_b.id, Department.name == "Cardiology")
        .first()
    )
    assert cardiology_b is not None

    dr_gupta = (
        test_db.query(Doctor)
        .filter(Doctor.facility_id == hospital_b.id, Doctor.department_id == cardiology_b.id)
        .first()
    )
    assert dr_gupta is not None

    # 1. Create Referral
    referral = ReferralService.create_referral(
        test_db,
        visit_id=visit.id,
        patient_id=patient.id,
        referring_doctor_id=ref_doctor.id,
        referring_facility_id=ref_facility.id,
        receiving_facility_id=hospital_b.id,
        receiving_department_id=cardiology_b.id,
        receiving_doctor_id=dr_gupta.id,
        reason="Requires urgent coronary evaluation and specialist cardiology management",
        urgency="urgent",
        appointment_date=datetime.utcnow() + timedelta(days=5),
    )
    test_db.commit()

    assert referral.id is not None
    assert referral.referral_id.startswith("REF-")
    assert len(referral.verification_code) == 6
    assert referral.status == "pending"

    # 2. Build Data Package [Send Patient Data]
    package = ReferralService.build_data_package(test_db, referral.id)
    test_db.commit()

    assert package is not None
    assert package.referral_id == referral.id
    assert "PAT-00184" in package.patient_summary
    assert "Chest pain radiating to left arm" in package.clinical_summary
    assert "Aspirin" in package.prescription_data
    assert "Suspected Coronary Artery Disease" in package.visit_history
    assert "MED-SETU REFERRAL SUMMARY" in package.referral_summary

    # 3. PDF Generation
    pdf_path = ReferralService.generate_referral_pdf(test_db, referral.id)
    test_db.commit()
    assert pdf_path is not None


def test_referral_self_referral_blocked(test_db):
    patient = test_db.query(Patient).first()
    visit = test_db.query(Visit).first()
    hospital_a = visit.facility

    dept = test_db.query(Department).filter(Department.facility_id == hospital_a.id).first()

    with pytest.raises(ValueError, match="Cannot refer to the same facility"):
        ReferralService.create_referral(
            test_db,
            visit_id=visit.id,
            patient_id=patient.id,
            referring_doctor_id=visit.doctor_id,
            referring_facility_id=hospital_a.id,
            receiving_facility_id=hospital_a.id,
            receiving_department_id=dept.id,
            receiving_doctor_id=None,
            reason="Internal transfer",
        )
