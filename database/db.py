"""Database connection and configuration for MED-SETU"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from database.models import Base

# Database file path
DATABASE_URL = "sqlite:///./med_setu.db"

# Create SQLite engine
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite specific
    echo=False  # Set to True for SQL debugging
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


_migrations_applied = False


def ensure_schema_migrations():
    """Apply safe additive migrations to existing database non-destructively.

    Runs at most once per process via the lazy guard _ensure_migrations_once().
    """
    try:
        with engine.connect() as conn:
            res = conn.exec_driver_sql("PRAGMA table_info(patients)").fetchall()
            col_names = [r[1] for r in res]
            if col_names and "is_active" not in col_names:
                conn.exec_driver_sql("ALTER TABLE patients ADD COLUMN is_active BOOLEAN DEFAULT 1")
                conn.commit()
    except Exception:
        pass


def _ensure_migrations_once():
    """Run schema migrations at most once per process lifetime.

    This is called lazily from get_session() and init_db() instead of at
    import time, preventing accidental writes to med_setu.db when modules
    are merely imported (e.g. during tests or audits).
    """
    global _migrations_applied
    if _migrations_applied:
        return
    ensure_schema_migrations()
    _migrations_applied = True


def get_db():
    """Database dependency for FastAPI/Streamlit"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database - create all tables and seed data"""
    _ensure_migrations_once()
    Base.metadata.create_all(bind=engine)
    # Seed database if empty
    from database.seed_data import seed_database
    seed_database()
    # Ensure Hospital Admin demo accounts exist (safe for existing DBs)
    _ensure_admin_accounts()


def get_session() -> Session:
    """Get a new database session"""
    _ensure_migrations_once()
    return SessionLocal()


def _ensure_admin_accounts():
    """Add Hospital Admin demo accounts if they don't exist.

    Safe to call on existing databases — only inserts missing accounts.
    Does not modify or delete any existing records.
    """
    from database.models import User, Facility, UserRole
    from database.seed_data import hash_password

    db = SessionLocal()
    try:
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

        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
