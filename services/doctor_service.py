"""Service layer for doctor dashboard operations"""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from database.models import Token, Visit, Patient, Doctor, Department, TokenStatus, User
from typing import List, Dict, Optional, Any


class DoctorService:
    """Service for doctor-specific queries and operations"""
    
    @staticmethod
    def authenticate_doctor(db: Session, username: str, password: str) -> Optional[Dict[str, Any]]:
        """
        Authenticate a doctor by username and password.
        Password can be a string or bytes.
        Returns doctor info if authenticated, None otherwise.
        """
        try:
            import bcrypt
            user = db.query(User).filter(User.username == username).first()
            if not user:
                return None
            
            # Convert password to bytes if string
            if isinstance(password, str):
                password_bytes = password.encode('utf-8')
            else:
                password_bytes = password
            
            # Verify password
            if not bcrypt.checkpw(password_bytes, user.password_hash.encode('utf-8')):
                return None
            
            # Get doctor info
            doctor = db.query(Doctor).filter(Doctor.user_id == user.id).first()
            if not doctor:
                return None
            
            return {
                "doctor_id": doctor.id,
                "user_id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "specialization": doctor.specialization,
                "department_id": doctor.department_id,
                "facility_id": doctor.facility_id
            }
        except Exception as e:
            print(f"Authentication error: {e}")
            return None
    
    @staticmethod
    def get_doctor_by_id(db: Session, doctor_id: int) -> Optional[Dict[str, Any]]:
        """Get doctor information by ID"""
        try:
            doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
            if not doctor:
                return None
            
            return {
                "doctor_id": doctor.id,
                "user_id": doctor.user_id,
                "full_name": doctor.user.full_name,
                "username": doctor.user.username,
                "specialization": doctor.specialization,
                "department_id": doctor.department_id,
                "department_name": doctor.department.name,
                "facility_id": doctor.facility_id,
                "facility_name": doctor.facility.name,
                "facility_district": doctor.facility.district
            }
        except Exception as e:
            print(f"Error fetching doctor: {e}")
            return None
    
    @staticmethod
    def get_doctor_kpi_counts(db: Session, doctor_id: int) -> Dict[str, int]:
        """
        Get KPI counts for a specific doctor (today's patients only).
        Returns: {total_patients, waiting, called, with_doctor, completed}
        """
        try:
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)
            
            # Query tokens for this doctor today
            tokens_today = db.query(Token).filter(
                and_(
                    Token.doctor_id == doctor_id,
                    Token.token_date >= today_start,
                    Token.token_date < today_end
                )
            ).all()
            
            total = len(tokens_today)
            waiting = sum(1 for t in tokens_today if t.status == TokenStatus.WAITING)
            called = sum(1 for t in tokens_today if t.status == TokenStatus.CALLED)
            with_doctor = sum(1 for t in tokens_today if t.status == TokenStatus.WITH_DOCTOR)
            completed = sum(1 for t in tokens_today if t.status == TokenStatus.COMPLETED)
            
            return {
                "total_patients": total,
                "waiting": waiting,
                "called": called,
                "with_doctor": with_doctor,
                "completed": completed
            }
        except Exception as e:
            print(f"Error getting KPI counts: {e}")
            return {"total_patients": 0, "waiting": 0, "called": 0, "with_doctor": 0, "completed": 0}
    
    @staticmethod
    def get_doctor_queue_data(db: Session, doctor_id: int) -> List[Dict[str, Any]]:
        """
        Get all tokens/patients assigned to this doctor (today).
        Returns list of tokens with patient and visit information.
        Only includes doctor's own patients.
        """
        try:
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)
            
            tokens = db.query(Token).filter(
                and_(
                    Token.doctor_id == doctor_id,
                    Token.token_date >= today_start,
                    Token.token_date < today_end
                )
            ).order_by(Token.token_date.desc()).all()
            
            queue_data = []
            for token in tokens:
                try:
                    visit = token.visit
                    patient = visit.patient
                    department = visit.department
                    
                    queue_data.append({
                        "token_id": token.id,
                        "token_number": token.token_number,
                        "patient_name": patient.full_name,
                        "patient_id": patient.patient_id,
                        "age": patient.age,
                        "gender": patient.gender,
                        "phone": patient.phone,
                        "preferred_language": patient.preferred_language,
                        "department": department.name,
                        "visit_id": visit.visit_id,
                        "visit_type": "Follow-up" if visit.status == "completed" else "New",
                        "status": token.status.value,
                        "token_date": token.token_date.strftime("%H:%M")
                    })
                except Exception as e:
                    print(f"Error processing token {token.id}: {e}")
                    continue
            
            return queue_data
        except Exception as e:
            print(f"Error getting queue data: {e}")
            return []
    
    @staticmethod
    def get_patient_details(db: Session, doctor_id: int, token_id: int) -> Optional[Dict[str, Any]]:
        """
        Get patient details for a specific token.
        Verifies the token belongs to this doctor (security check).
        """
        try:
            token = db.query(Token).filter(
                and_(
                    Token.id == token_id,
                    Token.doctor_id == doctor_id
                )
            ).first()
            
            if not token:
                return None
            
            visit = token.visit
            patient = visit.patient
            doctor = token.doctor
            department = visit.department
            
            return {
                "token_number": token.token_number,
                "token_status": token.status.value,
                "patient_name": patient.full_name,
                "patient_id": patient.patient_id,
                "patient_pk_id": patient.id,
                "patient_db_id": patient.id,
                "age": patient.age,
                "gender": patient.gender,
                "phone": patient.phone,
                "preferred_language": patient.preferred_language,
                "visit_id": visit.visit_id,
                "visit_db_id": visit.id,
                "visit_date": visit.visit_date.strftime("%Y-%m-%d %H:%M"),
                "visit_status": visit.status,
                "department": department.name,
                "doctor_name": doctor.user.full_name,
                "created_at": patient.created_at.strftime("%Y-%m-%d")
            }
        except Exception as e:
            print(f"Error getting patient details: {e}")
            return None
    
    @staticmethod
    def update_token_status(db: Session, doctor_id: int, token_id: int, new_status: str) -> bool:
        """
        Update token status and synchronize Visit.status.
        Security: Only allows doctor to update their own tokens.
        Valid transitions:
        - WAITING -> CALLED
        - CALLED -> WITH_DOCTOR
        - WITH_DOCTOR -> COMPLETED
        """
        try:
            token = db.query(Token).filter(
                and_(
                    Token.id == token_id,
                    Token.doctor_id == doctor_id
                )
            ).first()
            
            if not token:
                return False
            
            # Validate status transitions
            current = token.status.value
            valid_transitions = {
                "WAITING": ["CALLED", "WITH_DOCTOR"],
                "CALLED": ["WITH_DOCTOR", "WAITING"],
                "WITH_DOCTOR": ["COMPLETED", "CALLED"],
                "COMPLETED": ["COMPLETED"],
                "CANCELLED": ["CANCELLED"]
            }
            
            if new_status not in valid_transitions.get(current, []):
                return False
            
            try:
                status_enum = TokenStatus[new_status]
                token.status = status_enum

                # Synchronize Visit.status with Token.status
                from database.models import Visit
                visit = db.query(Visit).filter(Visit.id == token.visit_id).first()
                if visit:
                    if new_status == "COMPLETED":
                        visit.status = "completed"
                    elif new_status in ("CALLED", "WITH_DOCTOR"):
                        visit.status = "ongoing"

                db.commit()
                return True
            except KeyError:
                return False
                
        except Exception as e:
            print(f"Error updating token status: {e}")
            db.rollback()
            return False
    
    @staticmethod
    def get_queue_position(db: Session, doctor_id: int, token_id: int) -> Optional[int]:
        """Get the position of a token in the doctor's queue"""
        try:
            token = db.query(Token).filter(Token.id == token_id).first()
            if not token or token.doctor_id != doctor_id:
                return None
            
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)
            
            # Count tokens with WAITING or CALLED status that came before this one
            position = db.query(func.count(Token.id)).filter(
                and_(
                    Token.doctor_id == doctor_id,
                    Token.token_date >= today_start,
                    Token.token_date < today_end,
                    Token.status.in_([TokenStatus.WAITING, TokenStatus.CALLED]),
                    Token.token_date <= token.token_date
                )
            ).scalar()
            
            return position if position else 0
        except Exception as e:
            print(f"Error getting queue position: {e}")
            return None
