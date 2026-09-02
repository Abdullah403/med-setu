"""Tests for Clean, Professional SIH Demo Dataset."""
import pytest
from database.models import Patient, Visit, Token, TokenStatus, Facility, Doctor, Referral
from database.demo_dataset import reset_and_seed_demo_dataset
from tests.test_db_helper import create_isolated_test_db
from services.referral_service import ReferralService


def test_clean_sih_demo_dataset():
    """Verify reset and seed of the 5 official SIH demo patients."""
    db = create_isolated_test_db()

    # 1. Execute reset_and_seed_demo_dataset
    res = reset_and_seed_demo_dataset(db, user_role="hospital_admin", confirmed=True)
    assert res["success"] is True

    # 2. Exactly 5 primary demo patients
    patients = db.query(Patient).order_by(Patient.patient_id).all()
    assert len(patients) == 5
    p_names = [p.full_name for p in patients]
    assert "Aarav Sharma" in p_names
    assert "Fatima Khan" in p_names
    assert "Rahul Patil" in p_names
    assert "Meena Devi" in p_names
    assert "Imran Shaikh" in p_names

    # 3. Patient 1: Aarav Sharma (Primary Care)
    aarav = db.query(Patient).filter(Patient.phone == "9000000001").first()
    assert aarav.age == 28
    assert aarav.gender == "Male"
    assert len(aarav.visits) == 1
    assert len(aarav.prescriptions) == 2
    assert len(aarav.follow_ups) == 1
    assert aarav.visits[0].doctor_note.diagnosis.startswith("Acute Pharyngitis")

    # 4. Patient 2: Fatima Khan (Longitudinal History)
    fatima = db.query(Patient).filter(Patient.phone == "9000000002").first()
    assert fatima.age == 52
    assert len(fatima.visits) == 3
    assert len(fatima.prescriptions) == 4
    assert len(fatima.doctor_notes) == 3
    assert len(fatima.follow_ups) == 1

    # 5. Patient 3: Rahul Patil (Cardiology Referral to Pune)
    rahul = db.query(Patient).filter(Patient.phone == "9000000003").first()
    assert rahul.age == 61
    assert len(rahul.referrals) == 1
    ref_rahul = rahul.referrals[0]
    assert ref_rahul.receiving_facility.name == "District General Hospital"
    assert ref_rahul.receiving_department.name == "Cardiology"
    assert ref_rahul.receiving_doctor.doctor_id == "DOC-003"
    assert ref_rahul.verification_code == "MED-PUNE-CARDIO-881"
    assert ref_rahul.urgency == "urgent"
    assert rahul.cases[0].red_flag_detected is True

    # Secure lookup for Rahul Patil
    lookup_res = ReferralService.lookup_referral(
        db, phone="9000000003", verification_code="MED-PUNE-CARDIO-881", receiving_facility_id=ref_rahul.receiving_facility_id
    )
    assert lookup_res is not None
    assert lookup_res["referral"].id == ref_rahul.id

    # 6. Patient 4: Meena Devi (Orthopedics Referral to Pune)
    meena = db.query(Patient).filter(Patient.phone == "9000000004").first()
    assert len(meena.referrals) == 1
    ref_meena = meena.referrals[0]
    assert ref_meena.receiving_facility.name == "District General Hospital"
    assert ref_meena.receiving_department.name == "Orthopedics"
    assert ref_meena.receiving_doctor.doctor_id == "DOC-004"
    assert ref_meena.verification_code == "MED-PUNE-ORTHO-412"

    # 7. Patient 5: Imran Shaikh (Document/OCR/Continuity)
    imran = db.query(Patient).filter(Patient.phone == "9000000005").first()
    assert len(imran.visits) == 3
    assert len(imran.documents) == 1
    assert "THANE DIAGNOSTIC" in imran.documents[0].extracted_text

    # 8. Queue tokens check
    tokens = db.query(Token).all()
    today_tokens = {t.token_number: t for t in tokens if t.token_number.startswith("MED-10")}
    assert "MED-101" in today_tokens and today_tokens["MED-101"].status == TokenStatus.COMPLETED
    assert "MED-102" in today_tokens and today_tokens["MED-102"].status == TokenStatus.COMPLETED
    assert "MED-103" in today_tokens and today_tokens["MED-103"].status == TokenStatus.COMPLETED
    assert "MED-104" in today_tokens and today_tokens["MED-104"].status == TokenStatus.WAITING
    assert "MED-105" in today_tokens and today_tokens["MED-105"].status == TokenStatus.WAITING

    # 9. Facilities and Doctors intact
    facs = db.query(Facility).all()
    assert len(facs) >= 2
    docs = db.query(Doctor).all()
    assert len(docs) >= 4

    db.close()
