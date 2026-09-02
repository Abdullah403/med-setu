"""Administrative and Demo Data Management Service for MED-SETU."""
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from database.models import User, Doctor, Facility, Visit, Patient


class ManagementService:
    """Safe management of staff accounts, facilities, visits, and demo data."""

    @staticmethod
    def get_all_staff(db: Session) -> List[Dict[str, Any]]:
        """Retrieve all staff and doctor accounts."""
        users = db.query(User).order_by(User.id).all()
        staff_list = []
        for u in users:
            role_val = u.role.value if hasattr(u.role, "value") else str(u.role)
            if "." in role_val:
                role_val = role_val.split(".")[-1]
            doc_spec = u.doctor.specialization if u.doctor else ""
            fac_name = u.facility.name if u.facility else (u.doctor.facility.name if u.doctor and u.doctor.facility else "Unassigned")
            staff_list.append({
                "id": u.id,
                "username": u.username,
                "full_name": u.full_name,
                "role": role_val,
                "specialization": doc_spec,
                "facility": fac_name,
                "is_active": bool(u.is_active),
            })
        return staff_list

    @staticmethod
    def deactivate_staff(db: Session, user_id: int, requester_role: str = "hospital_admin") -> Dict[str, Any]:
        """Deactivate a staff account. Doctor records and historical visits remain intact."""
        role_clean = str(requester_role).lower().split(".")[-1]
        if role_clean == "doctor":
            return {"success": False, "error": "Unauthorized: Doctors cannot deactivate staff."}

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"success": False, "error": "Staff account not found."}

        user.is_active = False
        if user.doctor:
            user.doctor.is_available = False
        db.commit()
        return {"success": True, "message": f"Account for {user.full_name} ({user.username}) deactivated."}

    @staticmethod
    def reactivate_staff(db: Session, user_id: int, requester_role: str = "hospital_admin") -> Dict[str, Any]:
        """Reactivate a previously deactivated staff account."""
        role_clean = str(requester_role).lower().split(".")[-1]
        if role_clean == "doctor":
            return {"success": False, "error": "Unauthorized: Doctors cannot reactivate staff."}

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"success": False, "error": "Staff account not found."}

        user.is_active = True
        if user.doctor:
            user.doctor.is_available = True
        db.commit()
        return {"success": True, "message": f"Account for {user.full_name} ({user.username}) reactivated."}

    @staticmethod
    def get_all_facilities(db: Session) -> List[Dict[str, Any]]:
        """Retrieve all registered healthcare facilities."""
        facs = db.query(Facility).order_by(Facility.id).all()
        return [
            {
                "id": f.id,
                "name": f.name,
                "facility_type": f.facility_type,
                "district": f.district,
                "address": f.address,
                "phone": f.phone,
                "is_active": bool(f.is_active),
                "doctor_count": len(f.doctors) if f.doctors else 0,
                "visit_count": len(f.visits) if f.visits else 0,
            }
            for f in facs
        ]

    @staticmethod
    def deactivate_facility(db: Session, facility_id: int, requester_role: str = "hospital_admin") -> Dict[str, Any]:
        """Deactivate a facility. Historical visits and referrals are safely preserved."""
        role_clean = str(requester_role).lower().split(".")[-1]
        if role_clean == "doctor":
            return {"success": False, "error": "Unauthorized: Doctors cannot deactivate facilities."}

        fac = db.query(Facility).filter(Facility.id == facility_id).first()
        if not fac:
            return {"success": False, "error": "Facility not found."}

        fac.is_active = False
        db.commit()
        return {"success": True, "message": f"Facility {fac.name} deactivated."}

    @staticmethod
    def reactivate_facility(db: Session, facility_id: int, requester_role: str = "hospital_admin") -> Dict[str, Any]:
        """Reactivate a previously deactivated facility."""
        role_clean = str(requester_role).lower().split(".")[-1]
        if role_clean == "doctor":
            return {"success": False, "error": "Unauthorized: Doctors cannot reactivate facilities."}

        fac = db.query(Facility).filter(Facility.id == facility_id).first()
        if not fac:
            return {"success": False, "error": "Facility not found."}

        fac.is_active = True
        db.commit()
        return {"success": True, "message": f"Facility {fac.name} reactivated."}

    @staticmethod
    def get_recent_visits(db: Session, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent visits for administrative review."""
        visits = db.query(Visit).order_by(Visit.id.desc()).limit(limit).all()
        rows = []
        for v in visits:
            rows.append({
                "id": v.id,
                "visit_id": v.visit_id,
                "patient_name": v.patient.full_name if v.patient else "Deleted Patient",
                "patient_id": v.patient.patient_id if v.patient else "N/A",
                "department": v.department.name if v.department else "N/A",
                "doctor": v.doctor.user.full_name if v.doctor and v.doctor.user else "N/A",
                "date": v.visit_date.strftime("%Y-%m-%d %H:%M") if v.visit_date else "",
                "status": v.status,
                "token_count": len(v.tokens) if v.tokens else 0,
            })
        return rows

    @staticmethod
    def reset_and_seed_demo_dataset(db: Session, requester_role: str = "hospital_admin", confirmed: bool = False) -> Dict[str, Any]:
        """Controlled reset of demo transactional data and seeding of 5 clean SIH demo patients."""
        from database.demo_dataset import reset_and_seed_demo_dataset
        return reset_and_seed_demo_dataset(db, user_role=requester_role, confirmed=confirmed)

