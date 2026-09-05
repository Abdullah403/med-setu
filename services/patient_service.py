"""Patient management service"""
from datetime import datetime
from sqlalchemy.orm import Session
from database.models import Patient
from database.db import SessionLocal


class PatientService:
    """Service for patient operations"""
    
    @staticmethod
    def get_next_patient_id(db: Session) -> str:
        """Generate next patient ID (PAT-XXXXX)"""
        last_patient = db.query(Patient).order_by(Patient.id.desc()).first()
        
        if not last_patient:
            next_number = 1
        else:
            # Extract number from last patient ID (e.g., "PAT-00184" -> 184)
            try:
                last_number = int(last_patient.patient_id.split("-")[1])
                next_number = last_number + 1
            except (IndexError, ValueError):
                next_number = last_patient.id + 1
        
        return f"PAT-{next_number:05d}"
    
    @staticmethod
    def register_patient(
        db: Session,
        full_name: str,
        age: int,
        gender: str,
        phone: str,
        preferred_language: str = "English",
        address: str = ""
    ) -> Patient:
        """Register a new patient"""
        
        # Validate inputs
        if not full_name or not full_name.strip():
            raise ValueError("Full name is required")
        
        if not isinstance(age, int) or age < 0 or age > 150:
            raise ValueError("Age must be between 0 and 150")
        
        if not phone or not phone.strip():
            raise ValueError("Phone number is required")
        
        if not gender or not gender.strip():
            raise ValueError("Gender is required")
        
        # Check if patient with same phone exists
        existing = db.query(Patient).filter(Patient.phone == phone).first()
        if existing:
            raise ValueError(f"Patient with phone number {phone} already exists")
        
        # Generate unique patient ID
        patient_id = PatientService.get_next_patient_id(db)
        
        # Create patient
        patient = Patient(
            patient_id=patient_id,
            full_name=full_name.strip(),
            age=age,
            gender=gender.strip(),
            phone=phone.strip(),
            preferred_language=preferred_language.strip() or "English",
            created_at=datetime.utcnow()
        )
        
        db.add(patient)
        db.flush()  # Flush to ensure ID is assigned
        
        return patient
    
    @staticmethod
    def search_patients(
        db: Session,
        query: str,
        search_by: str = "all",
        include_deactivated: bool = False
    ):
        """Search for patients by phone, name, or ID. Excludes deactivated patients by default."""
        if not query or not query.strip():
            return []
        
        query = query.strip()
        results = []
        
        # Base filter: if not include_deactivated, ensure Patient.is_active == True
        base_filters = []
        if not include_deactivated:
            base_filters.append(Patient.is_active == True)
        
        if search_by in ["phone", "all"]:
            by_phone = db.query(Patient).filter(Patient.phone.contains(query), *base_filters).all()
            results.extend(by_phone)
        
        if search_by in ["name", "all"]:
            by_name = db.query(Patient).filter(Patient.full_name.ilike(f"%{query}%"), *base_filters).all()
            results.extend(by_name)
        
        if search_by in ["id", "all"]:
            by_id = db.query(Patient).filter(Patient.patient_id.contains(query), *base_filters).all()
            results.extend(by_id)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_results = []
        for patient in results:
            if patient.id not in seen:
                seen.add(patient.id)
                unique_results.append(patient)
        
        return unique_results

    @staticmethod
    def deactivate_patient(db: Session, patient_id: int, user_role: str = "receptionist"):
        """Deactivate a patient (soft delete). Prevents accidental visit creation."""
        user_role_clean = str(user_role).lower().split(".")[-1]
        if user_role_clean in ("doctor", "patient"):
            return {"success": False, "error": "Unauthorized: Doctors and patients cannot deactivate patient records."}
        
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return {"success": False, "error": "Patient not found."}
        
        patient.is_active = False
        db.commit()
        return {"success": True, "message": f"Patient {patient.full_name} ({patient.patient_id}) deactivated successfully."}

    @staticmethod
    def reactivate_patient(db: Session, patient_id: int, user_role: str = "receptionist"):
        """Reactivate a previously deactivated patient."""
        user_role_clean = str(user_role).lower().split(".")[-1]
        if user_role_clean in ("doctor", "patient"):
            return {"success": False, "error": "Unauthorized: Doctors and patients cannot reactivate patient records."}
        
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return {"success": False, "error": "Patient not found."}
        
        patient.is_active = True
        db.commit()
        return {"success": True, "message": f"Patient {patient.full_name} ({patient.patient_id}) reactivated successfully."}

    @staticmethod
    def edit_patient(
        db: Session,
        patient_id: int,
        full_name: str,
        age: int,
        gender: str,
        phone: str,
        preferred_language: str = "English",
        user_role: str = "receptionist"
    ):
        """Edit basic demographics of an existing patient."""
        user_role_clean = str(user_role).lower().split(".")[-1]
        if user_role_clean in ("doctor", "patient"):
            return {"success": False, "error": "Unauthorized: Doctors and patients cannot edit patient demographics."}
        
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return {"success": False, "error": "Patient not found."}
        
        if not full_name.strip() or not phone.strip() or age < 0:
            return {"success": False, "error": "Please provide valid full name, age, and phone number."}
        
        # Check phone uniqueness if phone is modified
        if phone.strip() != patient.phone:
            existing = db.query(Patient).filter(Patient.phone == phone.strip(), Patient.id != patient_id).first()
            if existing:
                return {"success": False, "error": f"Another patient with phone {phone} already exists."}
        
        patient.full_name = full_name.strip()
        patient.age = int(age)
        patient.gender = gender.strip()
        patient.phone = phone.strip()
        patient.preferred_language = preferred_language.strip() or "English"
        db.commit()
        return {"success": True, "message": f"Patient {patient.full_name} updated successfully."}

    @staticmethod
    def delete_patient(
        db: Session,
        patient_id: int,
        user_role: str = "hospital_admin",
        confirmed: bool = False
    ):
        """
        Permanently delete a patient and all dependent records in explicit dependency order.
        Strictly restricted to authorized administrative/demo-data roles.
        """
        user_role_clean = str(user_role).lower().split(".")[-1]
        
        # Security: DOCTORS and PATIENTS are strictly forbidden
        if user_role_clean in ("doctor", "patient"):
            return {
                "success": False,
                "error": "Unauthorized: Doctors and patients are not permitted to delete patient records."
            }
        
        # Security: Normal staff without administrative privileges cannot permanently delete
        authorized_roles = {"hospital_admin", "government", "admin", "demo_admin"}
        if user_role_clean not in authorized_roles:
            return {
                "success": False,
                "error": "Unauthorized: Permanent deletion requires an administrator role. Please use Deactivate Patient instead."
            }
        
        if not confirmed:
            return {
                "success": False,
                "error": "Deletion cancelled: Explicit confirmation required."
            }
        
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return {"success": False, "error": "Patient not found."}
        
        p_name = patient.full_name
        p_code = patient.patient_id
        
        try:
            from database.models import (
                Visit, Token, PatientCase, MedicalDocument, Prescription,
                DoctorNote, Referral, ReferralDataPackage, FollowUp
            )
            import os
            
            # 1. Referrals & Referral Data Packages
            referrals = db.query(Referral).filter(Referral.patient_id == patient_id).all()
            for ref in referrals:
                if ref.data_package:
                    if ref.data_package.pdf_path and os.path.exists(ref.data_package.pdf_path):
                        try:
                            os.remove(ref.data_package.pdf_path)
                        except Exception:
                            pass
                    db.delete(ref.data_package)
                db.delete(ref)
            
            # 2. Follow-ups
            fups = db.query(FollowUp).filter(FollowUp.patient_id == patient_id).all()
            for f in fups:
                db.delete(f)
            
            # 3. Doctor Notes
            notes = db.query(DoctorNote).filter(DoctorNote.patient_id == patient_id).all()
            for n in notes:
                db.delete(n)
            
            # 4. Prescriptions
            rxs = db.query(Prescription).filter(Prescription.patient_id == patient_id).all()
            for rx in rxs:
                db.delete(rx)
            
            # 5. Documents
            docs = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient_id).all()
            for d in docs:
                if d.file_path and os.path.exists(d.file_path):
                    try:
                        os.remove(d.file_path)
                    except Exception:
                        pass
                db.delete(d)
            
            # 6. Patient Cases
            cases = db.query(PatientCase).filter(PatientCase.patient_id == patient_id).all()
            for c in cases:
                db.delete(c)
            
            # 7. Visits & Tokens
            visits = db.query(Visit).filter(Visit.patient_id == patient_id).all()
            for v in visits:
                tokens = db.query(Token).filter(Token.visit_id == v.id).all()
                for tok in tokens:
                    db.delete(tok)
                db.delete(v)
            
            # 8. Delete Patient
            db.delete(patient)
            db.commit()
            
            return {
                "success": True,
                "message": f"Patient {p_name} ({p_code}) and all associated records permanently deleted."
            }
        except Exception as e:
            db.rollback()
            return {"success": False, "error": f"Failed to delete patient: {str(e)}"}
    
    @staticmethod
    def get_patient_by_id(db: Session, patient_id: str) -> Patient:
        """Get patient by patient ID"""
        return db.query(Patient).filter(Patient.patient_id == patient_id).first()

    @staticmethod
    def get_patient_by_identifier(db: Session, identifier: str) -> Patient:
        """Get a patient by either patient ID or phone number."""
        identifier = (identifier or "").strip()
        if not identifier:
            return None
        return db.query(Patient).filter(
            (Patient.patient_id == identifier) | (Patient.phone == identifier)
        ).first()
    
    @staticmethod
    def get_patient_by_phone(db: Session, phone: str) -> Patient:
        """Get patient by phone number"""
        return db.query(Patient).filter(Patient.phone == phone).first()

    @staticmethod
    def get_latest_visit_for_patient(db: Session, patient_id: int):
        """Return the latest visit for a patient, if any."""
        from database.models import Visit
        return db.query(Visit).filter(Visit.patient_id == patient_id).order_by(Visit.visit_date.desc()).first()
    
    @staticmethod
    def get_patient_record(db: Session, patient_record_id: int) -> Patient:
        """Get patient by database ID"""
        return db.query(Patient).filter(Patient.id == patient_record_id).first()
    
    @staticmethod
    def format_patient_for_display(patient: Patient) -> dict:
        """Format patient data for display"""
        if not patient:
            return None
        
        # Get last visit if any
        last_visit = None
        if patient.visits:
            last_visit = max(patient.visits, key=lambda v: v.created_at)
        
        return {
            "patient_id": patient.patient_id,
            "name": patient.full_name,
            "age": patient.age,
            "gender": patient.gender,
            "phone": patient.phone,
            "language": patient.preferred_language,
            "created_at": patient.created_at,
            "last_visit": last_visit.visit_date if last_visit else "No visits",
            "total_visits": len(patient.visits) if patient.visits else 0
        }
