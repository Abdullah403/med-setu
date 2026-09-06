"""Seed data for MED-SETU database with demo data"""
from datetime import datetime, timedelta
import bcrypt
from sqlalchemy.orm import Session
from database.models import (
    User, Facility, Department, Doctor, Patient, Visit, Token,
    PatientCase, FollowUp, Referral, MedicalDocument,
    UserRole, TokenStatus
)
from database.db import SessionLocal, init_db


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def seed_database(db_session: Session = None):
    """Insert seed data into the database if it's empty."""
    own_session = False
    if db_session is None:
        db = SessionLocal()
        own_session = True
    else:
        db = db_session

    try:
        facility = db.query(Facility).first()
        if facility is not None:
            print("Database already contains facility data. Skipping seed.")
            return

        # ================= CREATE FACILITY =================
        facility = Facility(
            name="Rural Community Health Centre",
            facility_type="Community Health Centre",
            district="Thane",
            address="123 Main Road, Thane, Maharashtra",
            phone="9876543210",
            is_active=True
        )
        db.add(facility)
        db.flush()  # Flush to get the facility ID
        
        # ================= CREATE DEPARTMENTS =================
        dept_general = Department(
            name="General Medicine",
            facility_id=facility.id
        )
        dept_dental = Department(
            name="Dental",
            facility_id=facility.id
        )
        dept_cardiology = Department(
            name="Cardiology",
            facility_id=facility.id
        )
        db.add_all([dept_general, dept_dental, dept_cardiology])
        db.flush()
        
        # ================= CREATE USERS =================
        # Receptionist user for demo
        user_receptionist = User(
            username="receptionist",
            password_hash=hash_password("password123"),
            role=UserRole.RECEPTIONIST,
            full_name="Receptionist Demo",
            facility_id=facility.id,
            is_active=True
        )
        db.add(user_receptionist)
        db.flush()
        
        # Doctor users
        user_khan = User(
            username="drkhan",
            password_hash=hash_password("password123"),
            role=UserRole.DOCTOR,
            full_name="Dr. Mohammad Khan",
            facility_id=facility.id,
            is_active=True
        )
        user_sharma = User(
            username="drsharma",
            password_hash=hash_password("password123"),
            role=UserRole.DOCTOR,
            full_name="Dr. Priya Sharma",
            facility_id=facility.id,
            is_active=True
        )
        db.add_all([user_khan, user_sharma])
        db.flush()
        
        # ================= CREATE DOCTORS =================
        doctor_khan = Doctor(
            user_id=user_khan.id,
            facility_id=facility.id,
            department_id=dept_general.id,
            doctor_id="DOC-001",
            specialization="General Medicine",
            is_available=True
        )
        doctor_sharma = Doctor(
            user_id=user_sharma.id,
            facility_id=facility.id,
            department_id=dept_dental.id,
            doctor_id="DOC-002",
            specialization="Dental",
            is_available=True
        )
        db.add_all([doctor_khan, doctor_sharma])
        db.flush()
        
        # ================= CREATE PATIENTS =================
        patients_data = [
            {
                "patient_id": "PAT-00184",
                "full_name": "Rahim Shaikh",
                "age": 52,
                "gender": "Male",
                "phone": "9876543210",
                "preferred_language": "Hindi"
            },
            {
                "patient_id": "PAT-00185",
                "full_name": "Anjali Patel",
                "age": 34,
                "gender": "Female",
                "phone": "9123456789",
                "preferred_language": "English"
            },
            {
                "patient_id": "PAT-00186",
                "full_name": "Ramesh Kumar",
                "age": 61,
                "gender": "Male",
                "phone": "8765432109",
                "preferred_language": "Hindi"
            },
            {
                "patient_id": "PAT-00187",
                "full_name": "Meera Singh",
                "age": 28,
                "gender": "Female",
                "phone": "9988776655",
                "preferred_language": "Marathi"
            },
            {
                "patient_id": "PAT-00188",
                "full_name": "Vikram Desai",
                "age": 45,
                "gender": "Male",
                "phone": "9555443322",
                "preferred_language": "English"
            }
        ]
        
        patients = []
        for patient_data in patients_data:
            patient = Patient(**patient_data)
            db.add(patient)
            patients.append(patient)
        
        db.flush()
        
        # ================= CREATE VISITS =================
        now = datetime.utcnow()
        
        # Visit for Rahim Shaikh with Dr. Khan
        visit_rahim = Visit(
            visit_id="VIS-2026-00091",
            patient_id=patients[0].id,
            facility_id=facility.id,
            department_id=dept_general.id,
            doctor_id=doctor_khan.id,
            visit_date=now,
            status="ongoing"
        )
        db.add(visit_rahim)
        db.flush()
        
        # Additional visits for other patients
        visit_anjali = Visit(
            visit_id="VIS-2026-00092",
            patient_id=patients[1].id,
            facility_id=facility.id,
            department_id=dept_dental.id,
            doctor_id=doctor_sharma.id,
            visit_date=now - timedelta(hours=2),
            status="completed"
        )
        
        visit_ramesh = Visit(
            visit_id="VIS-2026-00093",
            patient_id=patients[2].id,
            facility_id=facility.id,
            department_id=dept_general.id,
            doctor_id=doctor_khan.id,
            visit_date=now - timedelta(hours=4),
            status="completed"
        )
        
        visit_meera = Visit(
            visit_id="VIS-2026-00094",
            patient_id=patients[3].id,
            facility_id=facility.id,
            department_id=dept_dental.id,
            doctor_id=doctor_sharma.id,
            visit_date=now + timedelta(hours=1),
            status="ongoing"
        )
        
        visit_vikram = Visit(
            visit_id="VIS-2026-00095",
            patient_id=patients[4].id,
            facility_id=facility.id,
            department_id=dept_general.id,
            doctor_id=doctor_khan.id,
            visit_date=now + timedelta(hours=3),
            status="ongoing"
        )
        
        db.add_all([visit_rahim, visit_anjali, visit_ramesh, visit_meera, visit_vikram])
        db.flush()
        
        # ================= CREATE TOKENS =================
        # Token for Rahim's visit
        token_rahim = Token(
            token_number="MED-043",
            visit_id=visit_rahim.id,
            doctor_id=doctor_khan.id,
            token_date=now,
            status=TokenStatus.WAITING
        )
        
        # Additional tokens
        token_anjali = Token(
            token_number="MED-041",
            visit_id=visit_anjali.id,
            doctor_id=doctor_sharma.id,
            token_date=now - timedelta(hours=2),
            status=TokenStatus.COMPLETED
        )
        
        token_ramesh = Token(
            token_number="MED-042",
            visit_id=visit_ramesh.id,
            doctor_id=doctor_khan.id,
            token_date=now - timedelta(hours=4),
            status=TokenStatus.COMPLETED
        )
        
        token_meera = Token(
            token_number="MED-044",
            visit_id=visit_meera.id,
            doctor_id=doctor_sharma.id,
            token_date=now + timedelta(hours=1),
            status=TokenStatus.CALLED
        )
        
        token_vikram = Token(
            token_number="MED-045",
            visit_id=visit_vikram.id,
            doctor_id=doctor_khan.id,
            token_date=now + timedelta(hours=3),
            status=TokenStatus.WAITING
        )
        
        db.add_all([token_rahim, token_anjali, token_ramesh, token_meera, token_vikram])
        db.flush()

        # ================= CREATE HOSPITAL B (District General Hospital) =================
        facility_b = db.query(Facility).filter(Facility.name == "District General Hospital").first()
        if not facility_b:
            facility_b = Facility(
                name="District General Hospital",
                facility_type="District Hospital",
                district="Pune",
                address="456 Hospital Road, Pune, Maharashtra",
                phone="9876543211",
                is_active=True
            )
            db.add(facility_b)
            db.flush()

            dept_cardio_b = Department(name="Cardiology", facility_id=facility_b.id)
            dept_gen_b = Department(name="General Medicine", facility_id=facility_b.id)
            dept_ortho_b = Department(name="Orthopedics", facility_id=facility_b.id)
            db.add_all([dept_cardio_b, dept_gen_b, dept_ortho_b])
            db.flush()

            user_rec_b = User(
                username="receptionist_b",
                password_hash=hash_password("password123"),
                role=UserRole.RECEPTIONIST,
                full_name="Receptionist Hospital B",
                facility_id=facility_b.id,
                is_active=True
            )
            user_gupta = User(
                username="drgupta",
                password_hash=hash_password("password123"),
                role=UserRole.DOCTOR,
                full_name="Dr. Anil Gupta",
                facility_id=facility_b.id,
                is_active=True
            )
            user_verma = User(
                username="drverma",
                password_hash=hash_password("password123"),
                role=UserRole.DOCTOR,
                full_name="Dr. Sneha Verma",
                facility_id=facility_b.id,
                is_active=True
            )
            db.add_all([user_rec_b, user_gupta, user_verma])
            db.flush()

            doctor_gupta = Doctor(
                user_id=user_gupta.id,
                facility_id=facility_b.id,
                department_id=dept_cardio_b.id,
                doctor_id="DOC-003",
                specialization="Cardiology",
                is_available=True
            )
            doctor_verma = Doctor(
                user_id=user_verma.id,
                facility_id=facility_b.id,
                department_id=dept_ortho_b.id,
                doctor_id="DOC-004",
                specialization="Orthopedics",
                is_available=True
            )
            db.add_all([doctor_gupta, doctor_verma])
            db.flush()

        # ================= CREATE HOSPITAL ADMIN ACCOUNTS =================
        _ensure_admin_accounts(db)

        # Commit all changes
        db.commit()
        print("[OK] Seed data inserted successfully!")
        print(f"  - 2 Facilities verified")
        print(f"  - Demo doctors and departments verified")
        print(f"  - Hospital Admin accounts verified")
        
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Error seeding database: {e}")
        raise
    finally:
        if own_session:
            db.close()


def _ensure_admin_accounts(db: Session):
    """Add Hospital Admin demo accounts if they don't already exist.

    Safe to call on existing databases — only inserts missing accounts.
    Does not modify or delete any existing records.
    """
    from database.models import UserRole

    # Facility A admin
    fac_a = db.query(Facility).filter(Facility.name.like("%Rural%")).first()
    if fac_a:
        existing_a = db.query(User).filter(User.username == "admin_a").first()
        if not existing_a:
            admin_a = User(
                username="admin_a",
                password_hash=hash_password("password123"),
                role=UserRole.HOSPITAL_ADMIN,
                full_name="Hospital Admin A",
                facility_id=fac_a.id,
                is_active=True,
            )
            db.add(admin_a)

    # Facility B admin
    fac_b = db.query(Facility).filter(Facility.name.like("%District%")).first()
    if fac_b:
        existing_b = db.query(User).filter(User.username == "admin_b").first()
        if not existing_b:
            admin_b = User(
                username="admin_b",
                password_hash=hash_password("password123"),
                role=UserRole.HOSPITAL_ADMIN,
                full_name="Hospital Admin B",
                facility_id=fac_b.id,
                is_active=True,
            )
            db.add(admin_b)

    # Government / Super Admin account (global, no facility)
    existing_gov = db.query(User).filter(User.username == "gov_admin").first()
    if not existing_gov:
        gov_admin = User(
            username="gov_admin",
            password_hash=hash_password("password123"),
            role=UserRole.GOVERNMENT_ADMIN,
            full_name="Super Admin",
            facility_id=None,
            is_active=True,
        )
        db.add(gov_admin)

    # ── ASHA / Anganwadi Worker demo accounts (Phase 3A) ──
    if fac_a:
        existing_asha = db.query(User).filter(User.username == "asha_demo").first()
        if not existing_asha:
            asha_worker = User(
                username="asha_demo",
                password_hash=hash_password("password123"),
                role=UserRole.ASHA_WORKER,
                full_name="ASHA Worker Demo",
                facility_id=fac_a.id,
                is_active=True,
            )
            db.add(asha_worker)

    if fac_b:
        existing_ang = db.query(User).filter(User.username == "anganwadi_demo").first()
        if not existing_ang:
            anganwadi_worker = User(
                username="anganwadi_demo",
                password_hash=hash_password("password123"),
                role=UserRole.ANGANWADI_WORKER,
                full_name="Anganwadi Worker Demo",
                facility_id=fac_b.id,
                is_active=True,
            )
            db.add(anganwadi_worker)

    # Flush so _ensure_phase3bc_demo_data can query newly added users
    db.flush()

    # ── Phase 3B+3C: Worker-submitted cases and follow-up scenarios ──
    _ensure_phase3bc_demo_data(db)


def _ensure_phase3bc_demo_data(db: Session):
    """Add Phase 3B+3C demo data: worker-submitted cases, follow-ups, escalation scenarios.

    Safe to call on existing databases — only inserts missing records.
    Does not modify or delete any existing records.
    """
    from database.models import (
        PatientCase, FollowUp, Referral, MedicalDocument,
        Patient, Visit, Doctor, User, Facility, Department,
    )
    now = datetime.utcnow()

    # Find ASHA worker in Facility A
    asha = db.query(User).filter(
        User.username == "asha_demo",
        User.role == UserRole.ASHA_WORKER,
    ).first()
    if not asha:
        return

    fac_a = asha.facility
    if not fac_a:
        return

    # Find doctor and department in Facility A
    doctor = db.query(Doctor).filter(Doctor.facility_id == fac_a.id).first()
    if not doctor:
        return
    dept = db.query(Department).filter(Department.facility_id == fac_a.id).first()

    # Find an existing patient (Rahim Shaikh) for a worker-submitted case
    rahim = db.query(Patient).filter(Patient.patient_id == "PAT-00184").first()
    if rahim:
        existing_case = db.query(PatientCase).filter(
            PatientCase.patient_id == rahim.id,
            PatientCase.submitted_by_worker_id == asha.id,
        ).first()
        if not existing_case:
            # Create a visit for worker-submitted case
            visit_worker = Visit(
                visit_id="VIS-2026-W001",
                patient_id=rahim.id,
                facility_id=fac_a.id,
                department_id=dept.id if dept else doctor.department_id,
                doctor_id=doctor.id,
                visit_date=now - timedelta(hours=3),
                status="ongoing",
            )
            db.add(visit_worker)
            db.flush()

            case_worker = PatientCase(
                patient_id=rahim.id,
                visit_id=visit_worker.id,
                chief_complaint="Persistent cough for 5 days, mild fever",
                duration="5 days",
                symptoms="cough, low-grade fever, mild body ache",
                additional_notes="Patient reports worsening symptoms in the morning.",
                ai_summary="Possible upper respiratory infection. Monitor for 3-5 days. No immediate red flags.",
                red_flag_detected=False,
                submitted_by_worker_id=asha.id,
                submitted_at=now - timedelta(hours=3),
                worker_notes="Patient self-reported symptoms. Worker assisted with case intake.",
            )
            db.add(case_worker)
            db.flush()

            # Add a follow-up for this case (overdue)
            fu_overdue = FollowUp(
                visit_id=visit_worker.id,
                patient_id=rahim.id,
                doctor_id=doctor.id,
                follow_up_date=now - timedelta(days=1),
                reason="Post-intake symptom monitoring",
                status="scheduled",
            )
            db.add(fu_overdue)

            # Add a completed follow-up
            fu_completed = FollowUp(
                visit_id=visit_worker.id,
                patient_id=rahim.id,
                doctor_id=doctor.id,
                follow_up_date=now - timedelta(days=3),
                reason="Initial intake follow-up",
                status="completed",
                worker_outcome="PATIENT_ATTENDED",
                worker_outcome_at=now - timedelta(days=3),
                worker_outcome_by_id=asha.id,
                worker_outcome_notes="Patient reports mild improvement.",
                escalated=False,
            )
            db.add(fu_completed)

    # Find another patient (Anjali Patel) for escalation scenario
    anjali = db.query(Patient).filter(Patient.patient_id == "PAT-00185").first()
    if anjali:
        existing_esc = db.query(FollowUp).filter(
            FollowUp.patient_id == anjali.id,
            FollowUp.escalated == True,
        ).first()
        if not existing_esc:
            visit_anj = db.query(Visit).filter(
                Visit.patient_id == anjali.id,
            ).first()
            if visit_anj:
                fu_escalated = FollowUp(
                    visit_id=visit_anj.id,
                    patient_id=anjali.id,
                    doctor_id=doctor.id,
                    follow_up_date=now - timedelta(days=2),
                    reason="Post-dental procedure follow-up",
                    status="scheduled",
                    worker_outcome="PATIENT_DID_NOT_ATTEND",
                    worker_outcome_at=now - timedelta(days=2),
                    worker_outcome_by_id=asha.id,
                    worker_outcome_notes="Patient did not attend follow-up. Could not be reached by phone.",
                    escalated=True,
                    escalated_at=now - timedelta(days=2),
                )
                db.add(fu_escalated)

    # Find Vikram Desai for referral follow-up scenario
    vikram = db.query(Patient).filter(Patient.patient_id == "PAT-00188").first()
    if vikram:
        existing_ref = db.query(Referral).filter(
            Referral.patient_id == vikram.id,
        ).first()
        if not existing_ref:
            visit_vik = db.query(Visit).filter(
                Visit.patient_id == vikram.id,
            ).first()
            if visit_vik:
                # Find receiving facility (District General Hospital)
                fac_b = db.query(Facility).filter(Facility.name.like("%District%")).first()
                if fac_b:
                    cardio_b = db.query(Department).filter(
                        Department.facility_id == fac_b.id,
                        Department.name == "Cardiology",
                    ).first()
                    if cardio_b:
                        referral = Referral(
                            referral_id=f"REF-{now.year}-00099",
                            visit_id=visit_vik.id,
                            patient_id=vikram.id,
                            referring_doctor_id=doctor.id,
                            referring_facility_id=fac_a.id,
                            receiving_facility_id=fac_b.id,
                            receiving_department_id=cardio_b.id,
                            reason="Suspected cardiac issue requires specialist evaluation.",
                            urgency="urgent",
                            status="pending",
                            verification_code="A1B2C3",
                        )
                        db.add(referral)
                        db.flush()

                        fu_referral = FollowUp(
                            visit_id=visit_vik.id,
                            patient_id=vikram.id,
                            doctor_id=doctor.id,
                            follow_up_date=now + timedelta(days=2),
                            reason="Referral appointment follow-up",
                            status="scheduled",
                        )
                        db.add(fu_referral)


if __name__ == "__main__":
    print("Initializing database...")
    init_db()
    print("[OK] Database tables created")
    print("\nSeeding demo data...")
    seed_database()

