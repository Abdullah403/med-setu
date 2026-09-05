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


def get_session() -> Session:
    """Get a new database session"""
    _ensure_migrations_once()
    return SessionLocal()
