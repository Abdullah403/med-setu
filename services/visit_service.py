"""Visit management service"""
from datetime import datetime
from sqlalchemy.orm import Session
from database.models import Visit, Department, Doctor
from database.db import SessionLocal


class VisitService:
    """Service for visit operations"""
    
    @staticmethod
    def get_next_visit_id(db: Session) -> str:
        """Generate next visit ID (VIS-YYYY-XXXXX)"""
        current_year = datetime.utcnow().year
        
        # Get last visit ID for current year
        last_visit = db.query(Visit).filter(
            Visit.visit_id.like(f"VIS-{current_year}-%")
        ).order_by(Visit.id.desc()).first()
        
        if not last_visit:
            next_number = 1
        else:
            # Extract number from last visit ID (e.g., "VIS-2026-00091" -> 91)
            try:
                last_number = int(last_visit.visit_id.split("-")[2])
                next_number = last_number + 1
            except (IndexError, ValueError):
                next_number = last_visit.id + 1
        
        return f"VIS-{current_year}-{next_number:05d}"
    
    @staticmethod
    def get_departments(db: Session, facility_id: int = None):
        """Get all departments, optionally filtered by facility"""
        if facility_id:
            return db.query(Department).filter(Department.facility_id == facility_id).all()
        return db.query(Department).all()
    
    @staticmethod
    def get_doctors_by_department(db: Session, department_id: int):
        """Get all available doctors for a department"""
        return db.query(Doctor).filter(
            Doctor.department_id == department_id,
            Doctor.is_available == True
        ).all()
    
    @staticmethod
    def create_visit(
        db: Session,
        patient_id: int,
        facility_id: int,
        department_id: int,
        doctor_id: int
    ) -> Visit:
        """Create a new visit"""
        
        # Validate inputs
        if not patient_id or not facility_id or not department_id or not doctor_id:
            raise ValueError("All fields are required")
        
        # Generate unique visit ID
        visit_id = VisitService.get_next_visit_id(db)
        
        # Create visit
        visit = Visit(
            visit_id=visit_id,
            patient_id=patient_id,
            facility_id=facility_id,
            department_id=department_id,
            doctor_id=doctor_id,
            visit_date=datetime.utcnow(),
            status="ongoing",
            created_at=datetime.utcnow()
        )
        
        db.add(visit)
        db.flush()
        
        return visit
    
    @staticmethod
    def get_visit_by_id(db: Session, visit_id_str: str) -> Visit:
        """Get visit by visit ID string"""
        return db.query(Visit).filter(Visit.visit_id == visit_id_str).first()

    @staticmethod
    def get_visit_by_pk(db: Session, visit_pk: int) -> Visit:
        """Get visit by primary key integer"""
        return db.query(Visit).filter(Visit.id == visit_pk).first()
    
    @staticmethod
    def format_visit_for_display(visit: Visit) -> dict:
        """Format visit data for display"""
        if not visit:
            return None
        
        return {
            "visit_id": visit.visit_id,
            "patient_name": visit.patient.full_name if visit.patient else "Unknown",
            "patient_id": visit.patient.patient_id if visit.patient else "Unknown",
            "department": visit.department.name if visit.department else "Unknown",
            "doctor": visit.doctor.user.full_name if visit.doctor and visit.doctor.user else "Unknown",
            "visit_date": visit.visit_date,
            "status": visit.status,
            "created_at": visit.created_at
        }

    @staticmethod
    def delete_visit(db: Session, visit_id: int, user_role: str = "hospital_admin", confirmed: bool = False):
        """
        Permanently delete a visit and all visit-dependent records in safe cascade order.
        Strictly restricted to administrative roles.
        """
        user_role_clean = str(user_role).lower().split(".")[-1]
        authorized_roles = {"hospital_admin", "government", "admin", "demo_admin"}
        if user_role_clean not in authorized_roles:
            return {"success": False, "error": "Unauthorized: Visit deletion requires administrative privileges."}
        if not confirmed:
            return {"success": False, "error": "Confirmation required for visit deletion."}
        
        visit = db.query(Visit).filter(Visit.id == visit_id).first()
        if not visit:
            return {"success": False, "error": "Visit not found."}
        
        try:
            from database.models import (
                Referral, FollowUp, DoctorNote, Prescription, MedicalDocument, PatientCase, Token
            )
            # 1. Referrals attached to visit
            refs = db.query(Referral).filter(Referral.visit_id == visit_id).all()
            for r in refs:
                if r.data_package:
                    db.delete(r.data_package)
                db.delete(r)
            
            # 2. Follow-ups
            for f in db.query(FollowUp).filter(FollowUp.visit_id == visit_id).all():
                db.delete(f)
            # 3. Notes
            for n in db.query(DoctorNote).filter(DoctorNote.visit_id == visit_id).all():
                db.delete(n)
            # 4. Prescriptions
            for rx in db.query(Prescription).filter(Prescription.visit_id == visit_id).all():
                db.delete(rx)
            # 5. Documents
            for doc in db.query(MedicalDocument).filter(MedicalDocument.visit_id == visit_id).all():
                db.delete(doc)
            # 6. Cases
            for c in db.query(PatientCase).filter(PatientCase.visit_id == visit_id).all():
                db.delete(c)
            # 7. Tokens
            for t in db.query(Token).filter(Token.visit_id == visit_id).all():
                db.delete(t)
            
            v_code = visit.visit_id
            db.delete(visit)
            db.commit()
            return {"success": True, "message": f"Visit {v_code} and associated records deleted."}
        except Exception as e:
            db.rollback()
            return {"success": False, "error": f"Failed to delete visit: {str(e)}"}
