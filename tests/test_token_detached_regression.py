"""Regression test verifying Token and Visit lifecycle across session boundaries.
Guarantees that token creation, commit, session close, and subsequent attribute/relationship
access never raise DetachedInstanceError.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base, Patient, Visit, Token, Doctor, Department, Facility, User, UserRole
from services.token_service import TokenService
from services.visit_service import VisitService
from database.seed_data import hash_password


def test_token_creation_and_detached_access_regression():
    """Verify that token generation and attribute access remain safe after commit and session close."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)

    # Setup test data in Session 1
    db1 = Session()

    fac = Facility(name="Clinic A", facility_type="Clinic", district="District A", address="Road 1", phone="1234567890")
    db1.add(fac)
    db1.flush()

    dept = Department(name="General Medicine", facility_id=fac.id)
    db1.add(dept)
    db1.flush()

    doc_user = User(
        username="testdoc",
        password_hash=hash_password("pw"),
        role=UserRole.DOCTOR,
        full_name="Dr. Test",
        facility_id=fac.id,
    )
    db1.add(doc_user)
    db1.flush()

    doc = Doctor(user_id=doc_user.id, facility_id=fac.id, department_id=dept.id, doctor_id="DOC-999", specialization="General")
    db1.add(doc)
    db1.flush()

    patient = Patient(
        patient_id="PAT-99999",
        full_name="Rahim Shaikh",
        age=52,
        gender="Male",
        phone="9876543210",
        preferred_language="Hindi"
    )
    db1.add(patient)
    db1.flush()

    from datetime import datetime
    visit = VisitService.create_visit(
        db1,
        patient_id=patient.id,
        facility_id=fac.id,
        department_id=dept.id,
        doctor_id=doc.id
    )
    db1.flush()

    # 1. Create Token
    token = TokenService.create_token(db1, visit.id, doc.id)
    db1.commit()

    # Close session 1 to simulate end of request / st.rerun()
    db1.close()

    # 2. CRITICAL REGRESSION CHECK:
    # Accessing column attributes on the returned token object from the closed session must NOT raise DetachedInstanceError
    assert token.id is not None
    assert token.token_number == "MED-001"
    assert token.status.value == "WAITING"
    assert token.visit_id == visit.id
    assert token.doctor_id == doc.id

    # 3. CRITICAL REGRESSION CHECK:
    # On the next request (Session 2), loading token display details using the active session
    # must retrieve full patient, visit, and doctor details safely
    db2 = Session()

    token_data = TokenService.get_token_display_details(db2, token.id)
    assert token_data is not None
    assert token_data["token_number"] == "MED-001"
    assert token_data["status"] == "WAITING"
    assert token_data["patient_name"] == "Rahim Shaikh"
    assert token_data["department_name"] == "General Medicine"
    assert token_data["doctor_name"] == "Dr. Test"
    assert token_data["visit_id_str"] == "VIS-2026-00001"

    # 4. Check format_token_for_display works with and without session
    display_info = TokenService.format_token_for_display(token, db2)
    assert display_info is not None
    assert display_info["token_number"] == "MED-001"

    db2.close()
