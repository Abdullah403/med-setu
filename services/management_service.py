"""Administrative and Demo Data Management Service for MED-SETU."""
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from database.models import User, Doctor, Facility, Visit, Patient, Department
from services.session_service import is_role_allowed, ADMIN_LIKE_ROLES, denial
from services.authorization import (
    get_facility_id, is_global_role, check_staff_access, user_belongs_to_facility,
)


class ManagementService:
    """Safe management of staff accounts, facilities, visits, and demo data."""

    @staticmethod
    def get_all_staff(db: Session, user_data: dict = None) -> List[Dict[str, Any]]:
        """Retrieve staff and doctor accounts, scoped to the user's facility unless global."""
        q = db.query(User).order_by(User.id)
        if user_data and not is_global_role(user_data):
            fid = get_facility_id(user_data)
            if fid:
                q = q.filter(
                    (User.facility_id == fid) |
                    (User.id.in_(
                        db.query(Doctor.user_id).filter(Doctor.facility_id == fid)
                    ))
                )
        users = q.all()
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
    def create_doctor(
        db: Session,
        user_data: dict,
        full_name: str,
        username: str,
        password: str,
        department_id: int,
        specialization: str,
    ) -> Dict[str, Any]:
        """Create a new doctor account at the requester's facility.
        Enforces facility isolation via user_data."""
        if not is_role_allowed(user_data.get("role", ""), ADMIN_LIKE_ROLES):
            return denial("Unauthorized: Doctor creation requires administrative privileges.")

        fid = get_facility_id(user_data)
        if not fid:
            return denial("Unauthorized: No facility context in session.")

        # Validate department belongs to this facility
        dept = db.query(Department).filter(
            Department.id == department_id,
            Department.facility_id == fid,
        ).first()
        if not dept:
            return denial("Department not found at your facility.")

        # Check username uniqueness
        existing = db.query(User).filter(User.username == username.strip()).first()
        if existing:
            return denial(f"Username '{username.strip()}' already exists.")

        from database.seed_data import hash_password
        from database.models import UserRole

        user = User(
            username=username.strip(),
            password_hash=hash_password(password),
            role=UserRole.DOCTOR,
            full_name=full_name.strip(),
            facility_id=fid,
            is_active=True,
        )
        db.add(user)
        db.flush()

        # Generate next doctor_id
        last_doc = db.query(Doctor).order_by(Doctor.id.desc()).first()
        next_num = 1
        if last_doc:
            try:
                next_num = int(last_doc.doctor_id.split("-")[1]) + 1
            except (IndexError, ValueError):
                next_num = last_doc.id + 1
        doctor_code = f"DOC-{next_num:03d}"

        doctor = Doctor(
            user_id=user.id,
            facility_id=fid,
            department_id=department_id,
            doctor_id=doctor_code,
            specialization=specialization.strip(),
            is_available=True,
        )
        db.add(doctor)
        db.commit()

        return {
            "success": True,
            "message": f"Doctor {full_name} ({username}) created successfully.",
            "doctor_code": doctor_code,
        }

    @staticmethod
    def create_receptionist(
        db: Session,
        user_data: dict,
        full_name: str,
        username: str,
        password: str,
    ) -> Dict[str, Any]:
        """Create a new receptionist account at the requester's facility.
        Enforces facility isolation via user_data."""
        if not is_role_allowed(user_data.get("role", ""), ADMIN_LIKE_ROLES):
            return denial("Unauthorized: Receptionist creation requires administrative privileges.")

        fid = get_facility_id(user_data)
        if not fid:
            return denial("Unauthorized: No facility context in session.")

        # Check username uniqueness
        existing = db.query(User).filter(User.username == username.strip()).first()
        if existing:
            return denial(f"Username '{username.strip()}' already exists.")

        from database.seed_data import hash_password
        from database.models import UserRole

        user = User(
            username=username.strip(),
            password_hash=hash_password(password),
            role=UserRole.RECEPTIONIST,
            full_name=full_name.strip(),
            facility_id=fid,
            is_active=True,
        )
        db.add(user)
        db.commit()

        return {
            "success": True,
            "message": f"Receptionist {full_name} ({username}) created successfully.",
        }

    @staticmethod
    def deactivate_staff(db: Session, user_id: int, requester_role: str = "hospital_admin", user_data: dict = None) -> Dict[str, Any]:
        """Deactivate a staff account. Doctor records and historical visits remain intact."""
        if not is_role_allowed(requester_role, ADMIN_LIKE_ROLES):
            return denial("Unauthorized: Staff account management requires an administrative role.")

        auth_err = check_staff_access(db, user_id, user_data)
        if auth_err:
            return auth_err

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"success": False, "error": "Staff account not found."}

        user.is_active = False
        if user.doctor:
            user.doctor.is_available = False
        db.commit()
        return {"success": True, "message": f"Account for {user.full_name} ({user.username}) deactivated."}

    @staticmethod
    def reactivate_staff(db: Session, user_id: int, requester_role: str = "hospital_admin", user_data: dict = None) -> Dict[str, Any]:
        """Reactivate a previously deactivated staff account."""
        if not is_role_allowed(requester_role, ADMIN_LIKE_ROLES):
            return denial("Unauthorized: Staff account management requires an administrative role.")

        auth_err = check_staff_access(db, user_id, user_data)
        if auth_err:
            return auth_err

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
    def get_facility_profile(db: Session, facility_id: int) -> Dict[str, Any]:
        """Retrieve a single facility's profile information."""
        fac = db.query(Facility).filter(Facility.id == facility_id).first()
        if not fac:
            return {}
        return {
            "id": fac.id,
            "name": fac.name,
            "facility_type": fac.facility_type,
            "district": fac.district,
            "address": fac.address,
            "phone": fac.phone,
            "is_active": bool(fac.is_active),
            "doctor_count": len(fac.doctors) if fac.doctors else 0,
            "visit_count": len(fac.visits) if fac.visits else 0,
            "department_count": len(fac.departments) if fac.departments else 0,
        }

    @staticmethod
    def deactivate_facility(db: Session, facility_id: int, requester_role: str = "hospital_admin", user_data: dict = None) -> Dict[str, Any]:
        """Deactivate a facility. Historical visits and referrals are safely preserved."""
        if not is_role_allowed(requester_role, ADMIN_LIKE_ROLES):
            return denial("Unauthorized: Facility management requires an administrative role.")

        if not is_global_role(user_data):
            fid = get_facility_id(user_data)
            if fid and fid != facility_id:
                return denial("Unauthorized: Cannot manage a facility you do not belong to.")

        fac = db.query(Facility).filter(Facility.id == facility_id).first()
        if not fac:
            return {"success": False, "error": "Facility not found."}

        fac.is_active = False
        db.commit()
        return {"success": True, "message": f"Facility {fac.name} deactivated."}

    @staticmethod
    def reactivate_facility(db: Session, facility_id: int, requester_role: str = "hospital_admin", user_data: dict = None) -> Dict[str, Any]:
        """Reactivate a previously deactivated facility."""
        if not is_role_allowed(requester_role, ADMIN_LIKE_ROLES):
            return denial("Unauthorized: Facility management requires an administrative role.")

        if not is_global_role(user_data):
            fid = get_facility_id(user_data)
            if fid and fid != facility_id:
                return denial("Unauthorized: Cannot manage a facility you do not belong to.")

        fac = db.query(Facility).filter(Facility.id == facility_id).first()
        if not fac:
            return {"success": False, "error": "Facility not found."}

        fac.is_active = True
        db.commit()
        return {"success": True, "message": f"Facility {fac.name} reactivated."}

    @staticmethod
    def get_facility_departments(db: Session, facility_id: int) -> List[Dict[str, Any]]:
        """Retrieve departments for a specific facility."""
        depts = db.query(Department).filter(Department.facility_id == facility_id).order_by(Department.id).all()
        return [
            {
                "id": d.id,
                "name": d.name,
                "facility_id": d.facility_id,
                "doctor_count": len(d.doctors) if d.doctors else 0,
            }
            for d in depts
        ]

    @staticmethod
    def create_department(
        db: Session,
        user_data: dict,
        name: str,
    ) -> Dict[str, Any]:
        """Create a new department at the requester's facility.
        Enforces facility isolation via user_data."""
        if not is_role_allowed(user_data.get("role", ""), ADMIN_LIKE_ROLES):
            return denial("Unauthorized: Department creation requires administrative privileges.")

        fid = get_facility_id(user_data)
        if not fid:
            return denial("Unauthorized: No facility context in session.")

        name = name.strip()
        if not name:
            return denial("Department name is required.")

        # Check for duplicate department at this facility
        existing = db.query(Department).filter(
            Department.facility_id == fid,
            Department.name == name,
        ).first()
        if existing:
            return denial(f"Department '{name}' already exists at your facility.")

        dept = Department(name=name, facility_id=fid)
        db.add(dept)
        db.commit()

        return {
            "success": True,
            "message": f"Department '{name}' created successfully.",
        }

    @staticmethod
    def edit_department(
        db: Session,
        user_data: dict,
        department_id: int,
        new_name: str,
    ) -> Dict[str, Any]:
        """Rename a department at the requester's facility. Enforces facility isolation."""
        if not is_role_allowed(user_data.get("role", ""), ADMIN_LIKE_ROLES):
            return denial("Unauthorized: Department editing requires administrative privileges.")

        fid = get_facility_id(user_data)
        if not fid:
            return denial("Unauthorized: No facility context in session.")

        dept = db.query(Department).filter(
            Department.id == department_id,
            Department.facility_id == fid,
        ).first()
        if not dept:
            return denial("Department not found at your facility.")

        new_name = new_name.strip()
        if not new_name:
            return denial("Department name is required.")

        if new_name != dept.name:
            existing = db.query(Department).filter(
                Department.facility_id == fid,
                Department.name == new_name,
                Department.id != department_id,
            ).first()
            if existing:
                return denial(f"Department '{new_name}' already exists at your facility.")

        dept.name = new_name
        db.commit()
        return {"success": True, "message": f"Department renamed to '{new_name}'."}

    @staticmethod
    def deactivate_department(
        db: Session,
        user_data: dict,
        department_id: int,
    ) -> Dict[str, Any]:
        """Deactivate a department. Doctors in the department are not deleted.

        Note: The current Department model does not have an is_active column,
        so this method removes the department from active listings by verifying
        it has no active doctors. If it has doctors, we return an error.
        """
        if not is_role_allowed(user_data.get("role", ""), ADMIN_LIKE_ROLES):
            return denial("Unauthorized: Department management requires administrative privileges.")

        fid = get_facility_id(user_data)
        if not fid:
            return denial("Unauthorized: No facility context in session.")

        dept = db.query(Department).filter(
            Department.id == department_id,
            Department.facility_id == fid,
        ).first()
        if not dept:
            return denial("Department not found at your facility.")

        active_doctors = db.query(Doctor).filter(
            Doctor.department_id == department_id,
            Doctor.is_available == True,
        ).count()
        if active_doctors > 0:
            return denial(f"Cannot deactivate: {active_doctors} active doctor(s) still assigned to this department.")

        db.delete(dept)
        db.commit()
        return {"success": True, "message": f"Department '{dept.name}' has been removed."}

    @staticmethod
    def edit_doctor(
        db: Session,
        user_data: dict,
        doctor_user_id: int,
        full_name: str = None,
        specialization: str = None,
        department_id: int = None,
    ) -> Dict[str, Any]:
        """Edit a doctor's profile at the requester's facility. Enforces facility isolation."""
        from database.models import UserRole

        if not is_role_allowed(user_data.get("role", ""), ADMIN_LIKE_ROLES):
            return denial("Unauthorized: Doctor editing requires administrative privileges.")

        fid = get_facility_id(user_data)
        if not fid:
            return denial("Unauthorized: No facility context in session.")

        user = db.query(User).filter(User.id == doctor_user_id).first()
        if not user or user.role != UserRole.DOCTOR:
            return denial("Doctor account not found.")

        if not user_belongs_to_facility(db, doctor_user_id, fid):
            return denial("Doctor not found at your facility.")

        if full_name is not None:
            user.full_name = full_name.strip()

        doc = user.doctor
        if doc:
            if specialization is not None:
                doc.specialization = specialization.strip()
            if department_id is not None:
                dept = db.query(Department).filter(
                    Department.id == department_id,
                    Department.facility_id == fid,
                ).first()
                if not dept:
                    return denial("Department not found at your facility.")
                doc.department_id = department_id

        db.commit()
        return {"success": True, "message": f"Doctor '{user.full_name}' updated successfully."}

    @staticmethod
    def edit_facility_profile(
        db: Session,
        user_data: dict,
        name: str = None,
        address: str = None,
        phone: str = None,
        district: str = None,
    ) -> Dict[str, Any]:
        """Edit the hospital profile for the requester's facility. Enforces facility isolation."""
        if not is_role_allowed(user_data.get("role", ""), ADMIN_LIKE_ROLES):
            return denial("Unauthorized: Facility editing requires administrative privileges.")

        fid = get_facility_id(user_data)
        if not fid:
            return denial("Unauthorized: No facility context in session.")

        fac = db.query(Facility).filter(Facility.id == fid).first()
        if not fac:
            return denial("Facility not found.")

        if name is not None:
            fac.name = name.strip()
        if address is not None:
            fac.address = address.strip()
        if phone is not None:
            fac.phone = phone.strip()
        if district is not None:
            fac.district = district.strip()

        db.commit()
        return {"success": True, "message": f"Facility '{fac.name}' profile updated."}

    @staticmethod
    def get_recent_visits(db: Session, limit: int = 50, user_data: dict = None) -> List[Dict[str, Any]]:
        """Retrieve recent visits for administrative review, scoped to facility unless global."""
        q = db.query(Visit).order_by(Visit.id.desc())
        if user_data and not is_global_role(user_data):
            fid = get_facility_id(user_data)
            if fid:
                q = q.filter(Visit.facility_id == fid)
        visits = q.limit(limit).all()
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

