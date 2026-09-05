"""Facility-scoped authorization helpers for MED-SETU.

All service-layer authorization checks flow through these helpers.
They derive the actor's facility from the authenticated session payload
and validate that requested resources belong to that facility.

Key design principle: patients are NOT facility-scoped in the model.
A patient's facility membership is determined by whether they have visits
at that facility.
"""
from typing import Optional, Set
from sqlalchemy.orm import Session
from database.models import (
    Visit, Token, Doctor, User, Patient, Facility, Referral,
)
from services.session_service import normalize_role, denial


# ── Roles that bypass facility checks (global access) ──

GLOBAL_ROLES: Set[str] = {"government_admin", "government", "super_admin", "admin"}


def get_facility_id(user_data: Optional[dict]) -> Optional[int]:
    """Extract the facility_id from the authenticated session user_data dict.

    Returns None if user_data is missing or has no facility.
    """
    if not user_data:
        return None
    facility = user_data.get("facility")
    if facility and isinstance(facility, dict):
        return facility.get("id")
    return None


def get_doctor_id(user_data: Optional[dict]) -> Optional[int]:
    """Extract the doctor database PK from session user_data.

    Returns None if the user is not a doctor.
    """
    if not user_data:
        return None
    doctor = user_data.get("doctor")
    if doctor and isinstance(doctor, dict):
        return doctor.get("doctor_id") or doctor.get("id")
    return None


def is_global_role(user_data: Optional[dict]) -> bool:
    """Return True if the user's role grants global (non-facility-scoped) access."""
    if not user_data:
        return False
    role = normalize_role(user_data.get("role", ""))
    return role in GLOBAL_ROLES


def require_facility(user_data: Optional[dict]):
    """Return an authorization error dict if the user has no facility context.

    Returns None if the user has a valid facility.
    Returns an error dict (via denial()) if not.
    """
    if is_global_role(user_data):
        return None
    fid = get_facility_id(user_data)
    if not fid:
        return denial("Unauthorized: No facility context in session.")
    return None


def patient_has_visits_at_facility(db: Session, patient_id: int, facility_id: int) -> bool:
    """Check whether a patient has at least one visit at the given facility."""
    return db.query(Visit).filter(
        Visit.patient_id == patient_id,
        Visit.facility_id == facility_id,
    ).first() is not None


def visit_belongs_to_facility(db: Session, visit_id: int, facility_id: int) -> bool:
    """Check whether a visit belongs to the given facility."""
    return db.query(Visit).filter(
        Visit.id == visit_id,
        Visit.facility_id == facility_id,
    ).first() is not None


def token_belongs_to_facility(db: Session, token_id: int, facility_id: int) -> bool:
    """Check whether a token (via its visit) belongs to the given facility."""
    token = db.query(Token).filter(Token.id == token_id).first()
    if not token:
        return False
    return visit_belongs_to_facility(db, token.visit_id, facility_id)


def doctor_belongs_to_facility(db: Session, doctor_id: int, facility_id: int) -> bool:
    """Check whether a doctor belongs to the given facility."""
    return db.query(Doctor).filter(
        Doctor.id == doctor_id,
        Doctor.facility_id == facility_id,
    ).first() is not None


def user_belongs_to_facility(db: Session, user_id: int, facility_id: int) -> bool:
    """Check whether a user belongs to the given facility (via User.facility_id or Doctor.facility_id)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    if user.facility_id == facility_id:
        return True
    if user.doctor and user.doctor.facility_id == facility_id:
        return True
    return False


def check_patient_access(db: Session, patient_id: int, user_data: Optional[dict]):
    """Authorize access to a patient based on the user's facility context.

    - If user_data is not provided, skip facility check (backward compatibility).
    - Global roles: always allowed.
    - Facility-scoped roles: patient must have at least one visit at the user's facility.
    - Doctors: in addition to facility check, the doctor should have treated the patient
      (has a visit assigned to them). This is checked separately where needed.

    Returns None if authorized, or an error dict if not.
    """
    if not user_data:
        return None

    if is_global_role(user_data):
        return None

    fid = get_facility_id(user_data)
    if not fid:
        return denial("Unauthorized: No facility context in session.")

    if not patient_has_visits_at_facility(db, patient_id, fid):
        return denial("Patient not found at your facility.")

    return None


def check_visit_access(db: Session, visit_id: int, user_data: Optional[dict]):
    """Authorize access to a visit based on the user's facility context.
    Skips check if user_data is not provided (backward compatibility).

    Returns None if authorized, or an error dict if not.
    """
    if not user_data:
        return None

    if is_global_role(user_data):
        return None

    fid = get_facility_id(user_data)
    if not fid:
        return denial("Unauthorized: No facility context in session.")

    if not visit_belongs_to_facility(db, visit_id, fid):
        return denial("Visit not found at your facility.")

    return None


def check_token_access(db: Session, token_id: int, user_data: Optional[dict]):
    """Authorize access to a token based on the user's facility context.
    Skips check if user_data is not provided (backward compatibility).

    Returns None if authorized, or an error dict if not.
    """
    if not user_data:
        return None

    if is_global_role(user_data):
        return None

    fid = get_facility_id(user_data)
    if not fid:
        return denial("Unauthorized: No facility context in session.")

    if not token_belongs_to_facility(db, token_id, fid):
        return denial("Token not found at your facility.")

    return None


def check_doctor_access(db: Session, doctor_id: int, user_data: Optional[dict]):
    """Authorize access to a doctor based on the user's facility context.
    Skips check if user_data is not provided (backward compatibility).

    Returns None if authorized, or an error dict if not.
    """
    if not user_data:
        return None

    if is_global_role(user_data):
        return None

    fid = get_facility_id(user_data)
    if not fid:
        return denial("Unauthorized: No facility context in session.")

    if not doctor_belongs_to_facility(db, doctor_id, fid):
        return denial("Doctor not found at your facility.")

    return None


def check_staff_access(db: Session, target_user_id: int, user_data: Optional[dict]):
    """Authorize management access to a staff member based on the user's facility context.
    Skips check if user_data is not provided (backward compatibility).

    Returns None if authorized, or an error dict if not.
    """
    if not user_data:
        return None

    if is_global_role(user_data):
        return None

    fid = get_facility_id(user_data)
    if not fid:
        return denial("Unauthorized: No facility context in session.")

    if not user_belongs_to_facility(db, target_user_id, fid):
        return denial("Staff member not found at your facility.")

    return None
