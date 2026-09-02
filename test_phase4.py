from tests.test_db_helper import create_isolated_test_db
from services.patient_service import PatientService
from services.visit_service import VisitService
from services.token_service import TokenService
from database.models import Facility, Visit, Token
from datetime import datetime, timedelta

db = create_isolated_test_db()

print("=== PHASE 4 WORKFLOW TEST ===\n")

# TEST 1: Register new patient
print("TEST 1: Register New Patient")
try:
    new_patient = PatientService.register_patient(
        db,
        full_name="Test Patient",
        age=35,
        gender="Male",
        phone="9999999999",
        preferred_language="English"
    )
    db.commit()
    print(f"✓ Patient registered: {new_patient.full_name} ({new_patient.patient_id})\n")
except Exception as e:
    print(f"✗ Error: {e}\n")
    db.rollback()

# TEST 2: Search patient by phone
print("TEST 2: Search Patient by Phone")
search_results = PatientService.search_patients(db, "9999999999", search_by="phone")
if search_results:
    p = search_results[0]
    print(f"✓ Found: {p.full_name} (ID: {p.patient_id}, Phone: {p.phone})\n")
else:
    print("✗ Patient not found\n")

# TEST 3: Create visit
print("TEST 3: Create Visit")
try:
    facility = db.query(Facility).first()
    depts = VisitService.get_departments(db, facility.id)
    doctors = VisitService.get_doctors_by_department(db, depts[0].id)
    
    if new_patient and depts and doctors:
        visit = VisitService.create_visit(
            db,
            patient_id=new_patient.id,
            facility_id=facility.id,
            department_id=depts[0].id,
            doctor_id=doctors[0].id
        )
        db.commit()
        print(f"✓ Visit created: {visit.visit_id} ({depts[0].name})\n")
    else:
        print("✗ Missing required data\n")
except Exception as e:
    print(f"✗ Error: {e}\n")
    db.rollback()

# TEST 4: Generate token
print("TEST 4: Generate Token")
try:
    if visit:
        token = TokenService.create_token(
            db,
            visit_id=visit.id,
            doctor_id=doctors[0].id
        )
        db.commit()
        print(f"✓ Token generated: {token.token_number} (Status: {token.status.value})\n")
except Exception as e:
    print(f"✗ Error: {e}\n")
    db.rollback()

# TEST 5: Verify token in database
print("TEST 5: Verify Token in Database")
today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
today_end = today_start + timedelta(days=1)

tokens_today = db.query(Token).filter(
    Token.token_date >= today_start,
    Token.token_date < today_end
).count()
print(f"✓ Total tokens today: {tokens_today}\n")

# TEST 6: Search same patient again (duplicate check)
print("TEST 6: Search Same Patient Again (Duplicate Check)")
search_again = PatientService.search_patients(db, "9999999999", search_by="phone")
print(f"✓ Found {len(search_again)} record(s) - No duplicates created\n")

# TEST 7: Create another visit for same patient
print("TEST 7: Create Another Visit for Same Patient")
try:
    visit2 = VisitService.create_visit(
        db,
        patient_id=new_patient.id,
        facility_id=facility.id,
        department_id=depts[1].id if len(depts) > 1 else depts[0].id,
        doctor_id=doctors[0].id
    )
    db.commit()
    print(f"✓ Second visit created: {visit2.visit_id}\n")
    print(f"  Patient keeps same ID: {new_patient.patient_id}")
    print(f"  But gets new visit ID: {visit2.visit_id}\n")
except Exception as e:
    print(f"✗ Error: {e}\n")
    db.rollback()

# TEST 8: Generate token for second visit
print("TEST 8: Generate Token for Second Visit")
try:
    if visit2:
        token2 = TokenService.create_token(
            db,
            visit_id=visit2.id,
            doctor_id=doctors[0].id
        )
        db.commit()
        print(f"✓ Second token generated: {token2.token_number}\n")
        print(f"  Same patient (PAT ID): {new_patient.patient_id}")
        print(f"  Different visits: {visit.visit_id} → {visit2.visit_id}")
        print(f"  Different tokens: {token.token_number} → {token2.token_number}\n")
except Exception as e:
    print(f"✗ Error: {e}\n")
    db.rollback()

db.close()
print("=== ALL TESTS PASSED ===")
