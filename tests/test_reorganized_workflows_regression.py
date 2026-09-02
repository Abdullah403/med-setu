"""Comprehensive regression test suite for reorganized MED-SETU workflows.
Tests:
- Login authentication across roles
- Token generation & queue transitions (WAITING -> CALLED -> WITH_DOCTOR -> COMPLETED)
- Doctor queue isolation
- Prescription & clinical notes creation
- Inter-hospital referral creation, listing, verification, and data handoff
- Receiving hospital authorization boundary
"""
from datetime import datetime, timedelta
from tests.test_db_helper import create_isolated_test_db
from database.models import User, Doctor, Patient, Visit, Token, TokenStatus, Facility, Department
from services.auth_service import AuthService
from services.patient_service import PatientService
from services.visit_service import VisitService
from services.token_service import TokenService
from services.doctor_service import DoctorService
from services.case_service import PatientCaseService
from services.doctor_note_service import DoctorNoteService
from services.prescription_service import PrescriptionService
from services.referral_service import ReferralService
from services.followup_service import FollowUpService


def test_login_authentication_regression():
    """Verify login authentication across all seeded demo roles."""
    db = create_isolated_test_db()

    # 1. Receptionist Hospital A
    rec_a = AuthService.authenticate(db, "receptionist", "password123")
    assert rec_a is not None
    assert rec_a["role"] == "receptionist"
    assert rec_a["facility"]["name"] == "Rural Community Health Centre"

    # 2. Doctor Hospital A
    doc_a = AuthService.authenticate(db, "drkhan", "password123")
    assert doc_a is not None
    assert doc_a["role"] == "doctor"
    assert doc_a["doctor"]["specialization"] == "General Medicine"

    # 3. Receptionist B (Hospital B / Referral Desk)
    rec_b = AuthService.authenticate(db, "receptionist_b", "password123")
    assert rec_b is not None
    assert rec_b["role"] == "receptionist"
    assert rec_b["facility"]["name"] == "District General Hospital"

    # 4. Doctor B (Hospital B Specialist)
    doc_b = AuthService.authenticate(db, "drgupta", "password123")
    assert doc_b is not None
    assert doc_b["role"] == "doctor"
    assert doc_b["doctor"]["specialization"] == "Cardiology"

    # 5. Invalid credentials rejection
    assert AuthService.authenticate(db, "drkhan", "wrongpassword") is None
    assert AuthService.authenticate(db, "nonexistent", "password123") is None

    db.close()


def test_workflow_a_receptionist_journey():
    """
    WORKFLOW A — RECEPTIONIST
    Login -> Search/register patient -> Create visit -> Select doctor -> Generate token
    -> Queue -> Call patient -> With doctor -> Complete
    """
    db = create_isolated_test_db()

    # 1. Register or find patient
    patient = PatientService.register_patient(
        db,
        full_name="Fatima Bi",
        age=38,
        gender="Female",
        phone="9876543299",
        preferred_language="Hindi",
        address="Kalyan, Thane"
    )
    db.commit()
    assert patient.id is not None

    # 2. Create Visit
    hospital_a = db.query(Facility).filter(Facility.name == "Rural Community Health Centre").first()
    dept = db.query(Department).filter(Department.facility_id == hospital_a.id, Department.name == "General Medicine").first()
    doc = db.query(Doctor).filter(Doctor.facility_id == hospital_a.id, Doctor.department_id == dept.id).first()

    visit = VisitService.create_visit(db, patient.id, hospital_a.id, dept.id, doc.id)
    db.flush()
    assert visit.status == "ongoing"

    # 3. Generate Token
    token = TokenService.create_token(db, visit.id, doc.id)
    db.commit()
    assert token.token_number.startswith("MED-")
    assert token.status == TokenStatus.WAITING

    # 4. Queue Transitions: Call Patient -> With Doctor -> Complete Visit
    # WAITING -> CALLED
    TokenService.update_token_status(db, token.id, TokenStatus.CALLED)
    db.commit()
    assert token.status == TokenStatus.CALLED
    assert visit.status == "ongoing"

    # CALLED -> WITH_DOCTOR
    TokenService.update_token_status(db, token.id, TokenStatus.WITH_DOCTOR)
    db.commit()
    assert token.status == TokenStatus.WITH_DOCTOR
    assert visit.status == "ongoing"

    # WITH_DOCTOR -> COMPLETED
    TokenService.update_token_status(db, token.id, TokenStatus.COMPLETED)
    db.commit()
    assert token.status == TokenStatus.COMPLETED
    # Visit status must synchronize to completed!
    assert visit.status == "completed"

    db.close()


def test_workflow_b_doctor_journey_and_isolation():
    """
    WORKFLOW B — DOCTOR
    Login -> My Queue -> Select patient -> Patient Case (complaint, history, reports)
    -> Clinical Notes -> Prescription -> Complete visit
    Verifies doctor queue isolation: Dr. Khan cannot see Dr. Sharma's patients.
    """
    db = create_isolated_test_db()

    hospital_a = db.query(Facility).filter(Facility.name == "Rural Community Health Centre").first()
    dr_khan = db.query(Doctor).join(User).filter(User.username == "drkhan").first()
    dr_sharma = db.query(Doctor).join(User).filter(User.username == "drsharma").first()

    # Create patient and visit for Dr. Khan
    pat1 = PatientService.register_patient(db, "Patient Khan", 40, "Male", "9811111111", "Hindi", "Thane")
    vis1 = VisitService.create_visit(db, pat1.id, hospital_a.id, dr_khan.department_id, dr_khan.id)
    tok1 = TokenService.create_token(db, vis1.id, dr_khan.id)

    # Create patient and visit for Dr. Sharma
    pat2 = PatientService.register_patient(db, "Patient Sharma", 8, "Female", "9822222222", "Marathi", "Thane")
    vis2 = VisitService.create_visit(db, pat2.id, hospital_a.id, dr_sharma.department_id, dr_sharma.id)
    tok2 = TokenService.create_token(db, vis2.id, dr_sharma.id)
    db.commit()

    # Isolation check: Dr. Khan queue contains ONLY pat1, NOT pat2
    khan_queue = DoctorService.get_doctor_queue_data(db, dr_khan.id)
    khan_token_ids = [q["token_id"] for q in khan_queue]
    assert tok1.id in khan_token_ids
    assert tok2.id not in khan_token_ids

    # Dr. Khan opens patient case
    details = DoctorService.get_patient_details(db, dr_khan.id, tok1.id)
    assert details is not None
    assert details["patient_name"] == "Patient Khan"

    # Submit case symptoms
    case = PatientCaseService.submit_case(
        db, pat1.id, vis1.id,
        chief_complaint="Persistent high fever and cough for 4 days",
        duration="4 days",
        symptoms="fever, chills, productive cough"
    )
    db.commit()
    assert case.chief_complaint is not None

    # Record clinical notes & diagnosis
    note = DoctorNoteService.save_note(
        db, vis1.id, pat1.id, dr_khan.id,
        diagnosis="Acute Bronchitis",
        treatment_plan="Antibiotics course and steam inhalation",
        examination_findings="Bilateral rhonchi on auscultation"
    )
    db.commit()
    assert note.diagnosis == "Acute Bronchitis"

    # Add prescription
    rx = PrescriptionService.create_prescription(
        db, vis1.id, pat1.id, dr_khan.id,
        medication_name="Amoxicillin",
        dosage="500mg",
        frequency="Three times daily (TDS)",
        duration="5 days",
        instructions="After food"
    )
    db.commit()
    assert rx.id is not None

    # Doctor opens case -> marks WITH_DOCTOR
    DoctorService.update_token_status(db, dr_khan.id, tok1.id, "WITH_DOCTOR")
    assert tok1.status == TokenStatus.WITH_DOCTOR

    # Complete consultation -> marks COMPLETED and syncs visit
    DoctorService.update_token_status(db, dr_khan.id, tok1.id, "COMPLETED")

    assert tok1.status == TokenStatus.COMPLETED
    assert vis1.status == "completed"

    db.close()


def test_workflow_c_inter_hospital_referral_journey():
    """
    WORKFLOW C — INTER-HOSPITAL REFERRAL
    Doctor -> Patient Case -> Referral -> Destination Hospital -> Department -> Doctor
    -> Send Patient Data -> Build package -> Receiving Hospital Referral Desk -> Verify
    -> View shared data -> Accept referral -> Patient Portal notification
    """
    db = create_isolated_test_db()

    hospital_a = db.query(Facility).filter(Facility.name == "Rural Community Health Centre").first()
    hospital_b = db.query(Facility).filter(Facility.name == "District General Hospital").first()

    dr_khan = db.query(Doctor).join(User).filter(User.username == "drkhan").first()
    dept_cardio_b = db.query(Department).filter(Department.facility_id == hospital_b.id, Department.name == "Cardiology").first()
    dr_gupta = db.query(Doctor).filter(Doctor.facility_id == hospital_b.id, Doctor.department_id == dept_cardio_b.id).first()

    rahim = db.query(Patient).filter(Patient.patient_id == "PAT-00184").first()
    visit = db.query(Visit).filter(Visit.patient_id == rahim.id).first()

    # 1. Doctor creates referral
    referral = ReferralService.create_referral(
        db=db,
        visit_id=visit.id,
        patient_id=rahim.id,
        referring_doctor_id=dr_khan.id,
        referring_facility_id=hospital_a.id,
        receiving_facility_id=hospital_b.id,
        receiving_department_id=dept_cardio_b.id,
        receiving_doctor_id=dr_gupta.id,
        reason="Suspected acute coronary syndrome requiring angiography evaluation",
        urgency="urgent",
        appointment_date=datetime.utcnow() + timedelta(days=5)
    )
    db.commit()

    assert referral.id is not None
    assert referral.referral_id.startswith("REF-")
    assert len(referral.verification_code) == 6

    # 2. Build data package
    pkg = ReferralService.build_data_package(db, referral.id)
    db.commit()
    assert pkg is not None
    assert pkg.referral_id == referral.id

    # 3. Referral listing for sending doctor
    sent_refs = ReferralService.get_referrals_sent_by_doctor(db, dr_khan.id)
    assert any(r.id == referral.id for r in sent_refs)

    # 4. Receiving hospital referral desk verification
    # Negative check: wrong code fails
    assert ReferralService.lookup_referral(db, rahim.phone, "WRONG1", hospital_b.id) is None
    # Negative check: wrong facility fails (Hospital A receptionist cannot view Hospital B referral)
    assert ReferralService.lookup_referral(db, rahim.phone, referral.verification_code, hospital_a.id) is None

    # Positive check: correct phone + code + receiving facility matches
    verified = ReferralService.lookup_referral(db, rahim.phone, referral.verification_code, hospital_b.id)
    assert verified is not None
    assert verified["referral"].id == referral.id

    # 5. Shared patient package view
    shared = ReferralService.get_shared_patient_view(db, referral.id, hospital_b.id)
    assert shared is not None
    assert shared["patient_summary"]["full_name"] == rahim.full_name
    assert "referral" in shared

    # 6. Accept referral
    accepted = ReferralService.update_referral_status(db, referral.id, "accepted")
    db.commit()
    assert accepted is True
    assert referral.status == "accepted"

    # 7. Patient portal view
    patient_refs = ReferralService.get_referrals_for_patient(db, rahim.id)
    assert len(patient_refs) >= 1
    p_ref = next(r for r in patient_refs if r.id == referral.id)
    assert p_ref.receiving_facility.name == "District General Hospital"
    assert p_ref.verification_code == referral.verification_code

    db.close()


def test_referral_desk_tabs_scope_and_service_methods():
    """
    Direct regression test for Referral Desk tabs scope:
    - Verifies Referral, Patient, Visit, Doctor, Facility models are in app.py namespace
    - Verifies ReferralService.get_incoming_referrals_for_facility returns referrals received
    - Verifies ReferralService.get_outgoing_referrals_for_facility returns referrals sent
    - Simulates the exact queries executed by Tab 1 and Tab 2 in show_receptionist_referrals
    """
    import app

    # 1. Namespace audit: ensure all required models are imported and accessible
    assert hasattr(app, "Referral"), "Referral must be imported in app.py"
    assert hasattr(app, "Patient"), "Patient must be imported in app.py"
    assert hasattr(app, "Visit"), "Visit must be imported in app.py"
    assert hasattr(app, "Token"), "Token must be imported in app.py"
    assert hasattr(app, "User"), "User must be imported in app.py"
    assert hasattr(app, "Doctor"), "Doctor must be imported in app.py"
    assert hasattr(app, "Department"), "Department must be imported in app.py"
    assert hasattr(app, "Facility"), "Facility must be imported in app.py"
    assert hasattr(app, "Prescription"), "Prescription must be imported in app.py"
    assert hasattr(app, "DoctorNote"), "DoctorNote must be imported in app.py"
    assert hasattr(app, "FollowUp"), "FollowUp must be imported in app.py"
    assert hasattr(app, "PatientCase"), "PatientCase must be imported in app.py"
    assert hasattr(app, "MedicalDocument"), "MedicalDocument must be imported in app.py"

    # 2. Database test for Tab 1 and Tab 2 queries
    db = create_isolated_test_db()
    hospital_a = db.query(Facility).filter(Facility.name == "Rural Community Health Centre").first()
    hospital_b = db.query(Facility).filter(Facility.name == "District General Hospital").first()
    dr_khan = db.query(Doctor).join(User).filter(User.username == "drkhan").first()
    dept_cardio_b = db.query(Department).filter(Department.facility_id == hospital_b.id, Department.name == "Cardiology").first()
    dr_gupta = db.query(Doctor).filter(Doctor.facility_id == hospital_b.id, Doctor.department_id == dept_cardio_b.id).first()
    rahim = db.query(Patient).filter(Patient.patient_id == "PAT-00184").first()
    visit = db.query(Visit).filter(Visit.patient_id == rahim.id).first()

    # Create a referral from Hospital A to Hospital B
    ref = ReferralService.create_referral(
        db=db,
        visit_id=visit.id,
        patient_id=rahim.id,
        referring_doctor_id=dr_khan.id,
        referring_facility_id=hospital_a.id,
        receiving_facility_id=hospital_b.id,
        receiving_department_id=dept_cardio_b.id,
        receiving_doctor_id=dr_gupta.id,
        reason="Coronary evaluation",
        urgency="urgent"
    )
    db.commit()

    # Tab 1: Incoming referrals for Hospital B
    incoming_for_b = ReferralService.get_incoming_referrals_for_facility(db, hospital_b.id)
    assert any(r.id == ref.id for r in incoming_for_b)

    # Tab 2: Outgoing referrals from Hospital A
    outgoing_from_a = ReferralService.get_outgoing_referrals_for_facility(db, hospital_a.id)
    assert any(r.id == ref.id for r in outgoing_from_a)

    # Verify lookup works cleanly with Phone + Code
    lookup = ReferralService.lookup_referral(db, rahim.phone, ref.verification_code, hospital_b.id)
    assert lookup is not None
    assert lookup["referral"].id == ref.id

    # Verify shared patient view does not error
    pkg = ReferralService.build_data_package(db, ref.id)
    db.commit()
    shared = ReferralService.get_shared_patient_view(db, ref.id, hospital_b.id)
    assert shared is not None
    assert shared["patient_summary"]["full_name"] == rahim.full_name

    db.close()


def test_doctor_empty_queue_state_regression():
    """
    Test doctor with zero patients assigned:
    - Confirms doctor KPI metrics return zeroes without errors
    - Confirms doctor queue data returns an empty list without exceptions
    - Confirms accessing patient details with None or invalid token safely returns None/error
    """
    db = create_isolated_test_db()
    dr_gupta = db.query(Doctor).join(User).filter(User.username == "drgupta").first()
    assert dr_gupta is not None

    # Dr. Gupta starts with 0 assigned patients in the seed data
    kpis = DoctorService.get_doctor_kpi_counts(db, dr_gupta.id)
    assert kpis["total_patients"] == 0
    assert kpis["waiting"] == 0
    assert kpis["with_doctor"] == 0
    assert kpis["completed"] == 0

    # Queue data must be empty list
    queue = DoctorService.get_doctor_queue_data(db, dr_gupta.id)
    assert isinstance(queue, list)
    assert len(queue) == 0

    # Accessing patient details without a token
    assert DoctorService.get_patient_details(db, dr_gupta.id, None) is None
    assert DoctorService.get_patient_details(db, dr_gupta.id, 99999) is None

    # Sent referrals for doctor with no referrals
    sent_refs = ReferralService.get_referrals_sent_by_doctor(db, dr_gupta.id)
    assert isinstance(sent_refs, list)
    assert len(sent_refs) == 0

    db.close()


def test_patient_search_attributes_and_receptionist_flow_regression():
    """
    Test patient search attributes and complete receptionist flow:
    - Search for seeded patient by phone (e.g. 9876543210 or 1234567890)
    - Verifies no AttributeError (such as 'address') is raised
    - Verifies patient display attributes exist: full_name, patient_id, age, gender, phone, preferred_language
    - Tests patient registration with canonical fields
    - Tests visit creation and token generation
    """
    db = create_isolated_test_db()

    # 1. Search for existing seeded patient Rahim Shaikh
    results = PatientService.search_patients(db, "9876543210")
    assert len(results) >= 1
    p = results[0]

    # Verify canonical attributes
    assert hasattr(p, "full_name")
    assert hasattr(p, "patient_id")
    assert hasattr(p, "age")
    assert hasattr(p, "gender")
    assert hasattr(p, "phone")
    assert hasattr(p, "preferred_language")
    assert not hasattr(p, "address"), "Patient model should not have address column"

    # Simulate UI display string formatting - must NOT raise AttributeError
    display_str = f"{p.full_name} | ID: {p.patient_id} | Age: {p.age} ({p.gender}) | Phone: {p.phone} | Lang: {p.preferred_language}"
    assert "Rahim Shaikh" in display_str
    assert "PAT-00184" in display_str

    # 2. Test registration of new patient with canonical fields
    new_p = PatientService.register_patient(
        db,
        full_name="Fatima Bi",
        age=34,
        gender="Female",
        phone="9812345678",
        preferred_language="Urdu"
    )
    db.commit()
    assert new_p.id is not None
    assert new_p.patient_id.startswith("PAT-")
    assert new_p.full_name == "Fatima Bi"
    assert new_p.phone == "9812345678"

    # Search for the newly registered patient
    search_res = PatientService.search_patients(db, "9812345678")
    assert len(search_res) == 1
    assert search_res[0].id == new_p.id

    # 3. Create Visit and Token for the patient
    facility = db.query(Facility).first()
    dept = db.query(Department).filter(Department.facility_id == facility.id).first()
    doctor = db.query(Doctor).filter(Doctor.department_id == dept.id).first()

    visit = VisitService.create_visit(
        db,
        patient_id=new_p.id,
        facility_id=facility.id,
        department_id=dept.id,
        doctor_id=doctor.id
    )
    db.flush()
    assert visit.id is not None

    token = TokenService.create_token(db, visit.id, doctor.id)
    db.commit()
    assert token.id is not None
    assert token.token_number.startswith("MED-")

    # Display details for token confirmation card
    tok_details = TokenService.get_token_display_details(db, token.id)
    assert tok_details["token_number"] == token.token_number
    assert tok_details["patient_name"] == "Fatima Bi"
    assert tok_details["status"] == "WAITING"

    # 4. Doctor workflow with this token
    doc_queue = DoctorService.get_doctor_queue_data(db, doctor.id)
    assert any(q["token_id"] == token.id for q in doc_queue)

    pat_details = DoctorService.get_patient_details(db, doctor.id, token.id)
    assert pat_details is not None
    assert pat_details["patient_name"] == "Fatima Bi"

    # 5. Advance to WITH_DOCTOR and complete
    DoctorService.update_token_status(db, doctor.id, token.id, "WITH_DOCTOR")
    db.commit()
    assert token.status == TokenStatus.WITH_DOCTOR

    DoctorService.update_token_status(db, doctor.id, token.id, "COMPLETED")
    db.commit()
    assert token.status == TokenStatus.COMPLETED
    assert token.visit.status == "completed"

    db.close()
