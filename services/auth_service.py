"""Authentication service for MED-SETU."""
from typing import Optional, Dict, Any
import bcrypt
from sqlalchemy.orm import Session
from database.models import User, Doctor, Facility, UserRole


class AuthService:
    """Authentication and session credential verification."""

    @staticmethod
    def authenticate(db: Session, username: str, password: str) -> Optional[Dict[str, Any]]:
        """
        Authenticate any user (receptionist, doctor, admin) against the database using bcrypt.
        Returns user info dictionary if authenticated and active, else None.
        """
        username = (username or "").strip()
        if not username or not password:
            return None

        user = db.query(User).filter(User.username == username).first()
        if not user or not user.is_active:
            return None

        password_bytes = password.encode("utf-8") if isinstance(password, str) else password
        stored_hash = user.password_hash.encode("utf-8") if isinstance(user.password_hash, str) else user.password_hash

        try:
            if not bcrypt.checkpw(password_bytes, stored_hash):
                return None
        except Exception:
            return None

        if isinstance(user.role, UserRole):
            role_str = user.role.value.lower()
        else:
            role_str = str(user.role).lower()
            if "." in role_str:
                role_str = role_str.split(".")[-1]

        facility_info = None
        if user.facility_id:
            facility = db.query(Facility).filter(Facility.id == user.facility_id).first()
            if facility:
                facility_info = {
                    "id": facility.id,
                    "name": facility.name,
                    "facility_type": facility.facility_type,
                    "district": facility.district,
                    "address": facility.address,
                }

        doctor_info = None
        if user.doctor:
            doc = user.doctor
            doctor_info = {
                "id": doc.id,
                "doctor_id": doc.id,  # numeric pk
                "doctor_code": doc.doctor_id,  # e.g. DOC-001
                "specialization": doc.specialization,
                "department_id": doc.department_id,
                "department_name": doc.department.name if doc.department else "",
                "facility_id": doc.facility_id,
                "facility_name": doc.facility.name if doc.facility else "",
                "facility_district": doc.facility.district if doc.facility else "",
            }
            if not facility_info and doc.facility:
                facility_info = {
                    "id": doc.facility.id,
                    "name": doc.facility.name,
                    "facility_type": doc.facility.facility_type,
                    "district": doc.facility.district,
                    "address": doc.facility.address,
                }

        # If user has no explicit facility_id, fallback to first facility for backward compatibility
        if not facility_info:
            first_facility = db.query(Facility).first()
            if first_facility:
                facility_info = {
                    "id": first_facility.id,
                    "name": first_facility.name,
                    "facility_type": first_facility.facility_type,
                    "district": first_facility.district,
                    "address": first_facility.address,
                }

        return {
            "user_id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "role": role_str,
            "facility": facility_info,
            "doctor": doctor_info,
        }
