"""Tests for UserRole enum compatibility across database representations.
Ensures both uppercase canonical names and legacy lowercase values load and authenticate seamlessly.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from database.models import Base, User, UserRole, Facility
from services.auth_service import AuthService
from database.seed_data import hash_password


def test_user_role_enum_bidirectional_compatibility():
    """Verify that UserRoleType handles lowercase, uppercase, and enum instances seamlessly."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # Create dummy facility
    fac = Facility(
        name="Test Clinic",
        facility_type="Clinic",
        district="Test District",
        address="Test Address",
        phone="1234567890",
    )
    db.add(fac)
    db.flush()

    pw = hash_password("password123")

    # 1. Insert via raw SQL using lowercase strings (legacy / raw insert style)
    db.execute(
        text(
            "INSERT INTO users (username, password_hash, role, full_name, is_active, facility_id) "
            "VALUES (:u, :p, :r, :fn, :a, :fid)"
        ),
        {"u": "legacy_rec", "p": pw, "r": "receptionist", "fn": "Legacy Rec", "a": True, "fid": fac.id},
    )
    db.execute(
        text(
            "INSERT INTO users (username, password_hash, role, full_name, is_active, facility_id) "
            "VALUES (:u, :p, :r, :fn, :a, :fid)"
        ),
        {"u": "legacy_doc", "p": pw, "r": "doctor", "fn": "Legacy Doc", "a": True, "fid": fac.id},
    )

    # 2. Insert via raw SQL using uppercase strings (canonical database style)
    db.execute(
        text(
            "INSERT INTO users (username, password_hash, role, full_name, is_active, facility_id) "
            "VALUES (:u, :p, :r, :fn, :a, :fid)"
        ),
        {"u": "canon_rec", "p": pw, "r": "RECEPTIONIST", "fn": "Canon Rec", "a": True, "fid": fac.id},
    )
    db.execute(
        text(
            "INSERT INTO users (username, password_hash, role, full_name, is_active, facility_id) "
            "VALUES (:u, :p, :r, :fn, :a, :fid)"
        ),
        {"u": "canon_doc", "p": pw, "r": "DOCTOR", "fn": "Canon Doc", "a": True, "fid": fac.id},
    )

    # 3. Insert via SQLAlchemy ORM using UserRole enum instances
    orm_user = User(
        username="orm_admin",
        password_hash=pw,
        role=UserRole.HOSPITAL_ADMIN,
        full_name="ORM Admin",
        facility_id=fac.id,
    )
    db.add(orm_user)
    db.commit()

    # --- Verification 1: Loading all rows without LookupError ---
    all_users = db.query(User).all()
    assert len(all_users) == 5

    user_map = {u.username: u for u in all_users}

    # Verify legacy lowercase rows coerced properly to UserRole
    assert user_map["legacy_rec"].role == UserRole.RECEPTIONIST
    assert user_map["legacy_rec"].role.value == "receptionist"
    assert user_map["legacy_doc"].role == UserRole.DOCTOR
    assert user_map["legacy_doc"].role.value == "doctor"

    # Verify canonical uppercase rows coerced properly to UserRole
    assert user_map["canon_rec"].role == UserRole.RECEPTIONIST
    assert user_map["canon_doc"].role == UserRole.DOCTOR

    # Verify ORM row
    assert user_map["orm_admin"].role == UserRole.HOSPITAL_ADMIN

    # --- Verification 2: AuthService authentication works for all variations ---
    auth_legacy = AuthService.authenticate(db, "legacy_rec", "password123")
    assert auth_legacy is not None
    assert auth_legacy["role"] == "receptionist"

    auth_canon = AuthService.authenticate(db, "canon_rec", "password123")
    assert auth_canon is not None
    assert auth_canon["role"] == "receptionist"

    auth_doc = AuthService.authenticate(db, "legacy_doc", "password123")
    assert auth_doc is not None
    assert auth_doc["role"] == "doctor"

    auth_admin = AuthService.authenticate(db, "orm_admin", "password123")
    assert auth_admin is not None
    assert auth_admin["role"] == "hospital_admin"

    db.close()
