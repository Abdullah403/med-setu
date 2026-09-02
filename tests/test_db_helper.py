"""Test database helper to provide isolated in-memory databases for tests.
Prevents mutating the real med_setu.db file.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from database.models import Base
from database.seed_data import seed_database


def create_isolated_test_db() -> Session:
    """
    Create a clean, isolated in-memory SQLite database, build all tables,
    populate it with full seed data, and return an open Session.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        echo=False
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    db = TestingSessionLocal()
    seed_database(db_session=db)
    return db
