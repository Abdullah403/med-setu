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


def ensure_schema_migrations():
    """Apply safe additive migrations to existing database non-destructively."""
    try:
        with engine.connect() as conn:
            res = conn.exec_driver_sql("PRAGMA table_info(patients)").fetchall()
            col_names = [r[1] for r in res]
            if col_names and "is_active" not in col_names:
                conn.exec_driver_sql("ALTER TABLE patients ADD COLUMN is_active BOOLEAN DEFAULT 1")
                conn.commit()
    except Exception as e:
        pass


ensure_schema_migrations()


def get_db():
    """Database dependency for FastAPI/Streamlit"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database - create all tables and seed data"""
    Base.metadata.create_all(bind=engine)
    # Seed database if empty
    from database.seed_data import seed_database
    seed_database()


def get_session() -> Session:
    """Get a new database session"""
    return SessionLocal()
