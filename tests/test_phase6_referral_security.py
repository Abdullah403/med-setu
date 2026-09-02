"""Security and authorization tests for inter-hospital referral lookup."""
from datetime import datetime, timedelta
import pytest
from tests.test_db_helper import create_isolated_test_db
from database.models import Patient, Visit, Facility, Department
from services.referral_service import ReferralService


@pytest.fixture
def test_db():
    db = create_isolated_test_db()
    yield db
    db.close()


def test_referral_security_boundary(test_db):
    patient = test_db.query(Patient).filter(Patient.patient_id == "PAT-00184").first()
    visit = test_db.query(Visit).filter(Visit.patient_id == patient.id).first()
    hospital_a = visit.facility
    hospital_b = test_db.query(Facility).filter(Facility.name == "District General Hospital").first()
    cardiology_b = (
        test_db.query(Department)
        .filter(Department.facility_id == hospital_b.id, Department.name == "Cardiology")
        .first()
    )

    referral = ReferralService.create_referral(
        test_db,
        visit_id=visit.id,
        patient_id=patient.id,
        referring_doctor_id=visit.doctor_id,
        referring_facility_id=hospital_a.id,
        receiving_facility_id=hospital_b.id,
        receiving_department_id=cardiology_b.id,
        receiving_doctor_id=None,
        reason="Specialist consultation",
        urgency="urgent",
    )
    test_db.commit()
    code = referral.verification_code

    # 1. Successful lookup with correct phone, verification code, and destination facility
    result = ReferralService.lookup_referral(
        test_db,
        phone=patient.phone,
        verification_code=code,
        receiving_facility_id=hospital_b.id,
    )
    assert result is not None
    assert result["referral"].id == referral.id
    assert result["patient"].id == patient.id

    # 2. SECURITY TEST: Phone number ALONE must NOT grant access
    result_wrong_code = ReferralService.lookup_referral(
        test_db,
        phone=patient.phone,
        verification_code="WRONG1",
        receiving_facility_id=hospital_b.id,
    )
    assert result_wrong_code is None

    # 3. SECURITY TEST: Verification code with WRONG phone must NOT grant access
    result_wrong_phone = ReferralService.lookup_referral(
        test_db,
        phone="0000000000",
        verification_code=code,
        receiving_facility_id=hospital_b.id,
    )
    assert result_wrong_phone is None

    # 4. SECURITY TEST: Unauthorized facility (e.g. Hospital A trying to lookup Hospital B's incoming referral)
    result_wrong_facility = ReferralService.lookup_referral(
        test_db,
        phone=patient.phone,
        verification_code=code,
        receiving_facility_id=hospital_a.id,
    )
    assert result_wrong_facility is None

    # 5. SECURITY TEST: Cancelled referral must NOT grant access
    referral.status = "cancelled"
    test_db.commit()
    result_cancelled = ReferralService.lookup_referral(
        test_db,
        phone=patient.phone,
        verification_code=code,
        receiving_facility_id=hospital_b.id,
    )
    assert result_cancelled is None
