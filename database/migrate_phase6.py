"""Safe migration script for Phase 6.
Adds new tables and Hospital B seed data without touching existing data.
Idempotent — safe to run multiple times.
"""
import sqlite3
import os
import bcrypt

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "med_setu.db")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def run_migration():
    print(f"Migrating database: {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print("ERROR: med_setu.db not found. Run the app first to create it.")
        return False

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # ── Step 1: Create new tables via SQLAlchemy (additive) ──
    print("\n[1/5] Creating new tables...")
    from database.db import engine
    from database.models import Base
    Base.metadata.create_all(bind=engine)
    print("  ✓ Tables created (prescriptions, doctor_notes, referrals, referral_data_packages, follow_ups)")

    # ── Step 2: Add facility_id column to users if missing ──
    print("\n[2/5] Checking users.facility_id column...")
    columns = [row[1] for row in cursor.execute("PRAGMA table_info(users)").fetchall()]
    if "facility_id" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN facility_id INTEGER REFERENCES facilities(id)")
        print("  ✓ Added facility_id column to users")
    else:
        print("  ✓ facility_id column already exists")

    # ── Step 3: Set facility_id for existing users ──
    print("\n[3/5] Setting facility_id for existing users...")
    cursor.execute("UPDATE users SET facility_id = 1 WHERE facility_id IS NULL AND username IN ('receptionist', 'drkhan', 'drsharma')")
    conn.commit()
    print("  ✓ Existing users assigned to facility 1")

    # ── Step 4: Seed Hospital B ──
    print("\n[4/5] Seeding Hospital B data...")

    # Check if Hospital B already exists
    cursor.execute("SELECT id FROM facilities WHERE name = 'District General Hospital'")
    hospital_b = cursor.fetchone()

    if hospital_b:
        facility_b_id = hospital_b[0]
        print("  ✓ Hospital B already exists (id={})".format(facility_b_id))
    else:
        cursor.execute("""
            INSERT INTO facilities (name, facility_type, district, address, phone, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("District General Hospital", "District Hospital", "Pune",
              "456 Hospital Road, Pune, Maharashtra", "9876543211", True))
        facility_b_id = cursor.lastrowid
        print("  ✓ Hospital B created (id={})".format(facility_b_id))

    # Departments for Hospital B
    dept_map = {}
    for dept_name in ["Cardiology", "General Medicine", "Orthopedics"]:
        cursor.execute("SELECT id FROM departments WHERE name = ? AND facility_id = ?",
                        (dept_name, facility_b_id))
        existing = cursor.fetchone()
        if existing:
            dept_map[dept_name] = existing[0]
        else:
            cursor.execute("INSERT INTO departments (name, facility_id) VALUES (?, ?)",
                            (dept_name, facility_b_id))
            dept_map[dept_name] = cursor.lastrowid
            print(f"  ✓ Department '{dept_name}' created for Hospital B")

    # Users and doctors for Hospital B
    hospital_b_staff = [
        {
            "username": "receptionist_b",
            "password": "password123",
            "role": "RECEPTIONIST",
            "full_name": "Receptionist Hospital B",
            "is_doctor": False,
        },
        {
            "username": "drgupta",
            "password": "password123",
            "role": "DOCTOR",
            "full_name": "Dr. Anil Gupta",
            "is_doctor": True,
            "doctor_id_str": "DOC-003",
            "specialization": "Cardiology",
            "department": "Cardiology",
        },
        {
            "username": "drverma",
            "password": "password123",
            "role": "DOCTOR",
            "full_name": "Dr. Sneha Verma",
            "is_doctor": True,
            "doctor_id_str": "DOC-004",
            "specialization": "Orthopedics",
            "department": "Orthopedics",
        },
    ]

    for staff in hospital_b_staff:
        cursor.execute("SELECT id FROM users WHERE username = ?", (staff["username"],))
        existing_user = cursor.fetchone()

        if existing_user:
            user_id = existing_user[0]
            print(f"  ✓ User '{staff['username']}' already exists")
        else:
            pw_hash = hash_password(staff["password"])
            cursor.execute("""
                INSERT INTO users (username, password_hash, role, full_name, is_active, facility_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (staff["username"], pw_hash, staff["role"], staff["full_name"], True, facility_b_id))
            user_id = cursor.lastrowid
            print(f"  ✓ User '{staff['username']}' created")

        if staff["is_doctor"]:
            cursor.execute("SELECT id FROM doctors WHERE doctor_id = ?", (staff["doctor_id_str"],))
            existing_doc = cursor.fetchone()
            if not existing_doc:
                dept_id = dept_map[staff["department"]]
                cursor.execute("""
                    INSERT INTO doctors (user_id, facility_id, department_id, doctor_id, specialization, is_available)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (user_id, facility_b_id, dept_id, staff["doctor_id_str"], staff["specialization"], True))
                print(f"  ✓ Doctor '{staff['doctor_id_str']}' created")
            else:
                print(f"  ✓ Doctor '{staff['doctor_id_str']}' already exists")

    conn.commit()

    # ── Step 5: Verify ──
    print("\n[5/5] Verification...")
    for table in ["facilities", "departments", "users", "doctors", "patients", "visits", "tokens",
                   "patient_cases", "medical_documents", "prescriptions", "doctor_notes",
                   "referrals", "referral_data_packages", "follow_ups"]:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"  {table}: {count} rows")

    conn.close()
    print("\n✓ Migration complete. Existing data preserved.")
    return True


if __name__ == "__main__":
    run_migration()
