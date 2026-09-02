"""Seed data for MED-SETU database with demo data"""
from datetime import datetime, timedelta
import bcrypt
from sqlalchemy.orm import Session
from database.models import (
    User, Facility, Department, Doctor, Patient, Visit, Token,
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

        # Commit all changes
        db.commit()
        print("[OK] Seed data inserted successfully!")
        print(f"  - 2 Facilities verified")
        print(f"  - Demo doctors and departments verified")
        
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Error seeding database: {e}")
        raise
    finally:
        if own_session:
            db.close()


if __name__ == "__main__":
    print("Initializing database...")
    init_db()
    print("[OK] Database tables created")
    print("\nSeeding demo data...")
    seed_database()

