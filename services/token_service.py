"""Token management service"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from database.models import Token, TokenStatus, Visit
from database.db import SessionLocal


class TokenService:
    """Service for token/queue operations"""
    
    @staticmethod
    def get_next_token_number(db: Session) -> str:
        """Generate next token number for today (MED-XXXXX)"""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        # Get highest token number for today
        last_token = db.query(Token).filter(
            Token.token_date >= today_start,
            Token.token_date < today_end
        ).order_by(Token.id.desc()).first()
        
        if not last_token:
            next_number = 1
        else:
            # Extract number from token number (e.g., "MED-043" -> 43)
            try:
                last_number = int(last_token.token_number.split("-")[1])
                next_number = last_number + 1
            except (IndexError, ValueError):
                next_number = 1
        
        return f"MED-{next_number:03d}"
    
    @staticmethod
    def get_estimated_position(db: Session, token_number: str) -> int:
        """Get estimated position in queue"""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        # Extract token number
        try:
            current_num = int(token_number.split("-")[1])
        except (IndexError, ValueError):
            return 0
        
        # Count tokens with lower or equal number in WAITING or CALLED status
        waiting_count = db.query(Token).filter(
            Token.token_date >= today_start,
            Token.token_date < today_end,
            Token.status.in_([TokenStatus.WAITING, TokenStatus.CALLED])
        ).count()
        
        return waiting_count
    
    @staticmethod
    def create_token(
        db: Session,
        visit_id: int,
        doctor_id: int
    ) -> Token:
        """Create a new token for a visit"""
        
        if not visit_id or not doctor_id:
            raise ValueError("Visit and doctor are required")
        
        # Verify visit exists
        visit = db.query(Visit).filter(Visit.id == visit_id).first()
        if not visit:
            raise ValueError("Visit not found")
        
        # Generate unique token number for today
        token_number = TokenService.get_next_token_number(db)
        
        # Create token
        token = Token(
            token_number=token_number,
            visit_id=visit_id,
            doctor_id=doctor_id,
            token_date=datetime.utcnow(),
            status=TokenStatus.WAITING,
            created_at=datetime.utcnow()
        )
        
        db.add(token)
        db.flush()
        db.refresh(token)
        
        return token
    
    @staticmethod
    def get_token_by_number(db: Session, token_number: str) -> Token:
        """Get token by token number"""
        return db.query(Token).filter(Token.token_number == token_number).first()

    @staticmethod
    def get_token_by_id(db: Session, token_id: int) -> Optional[Token]:
        """Get token by primary key using the active session."""
        if not token_id:
            return None
        return db.query(Token).filter(Token.id == token_id).first()

    @staticmethod
    def get_token_display_details(db: Session, token_id: int) -> Optional[Dict[str, Any]]:
        """
        Get complete, session-safe dictionary of token display fields.
        Safely queries token, visit, patient, department, and doctor within the active session.
        Guaranteed safe from DetachedInstanceError across request lifecycles.
        """
        if not token_id:
            return None

        token = db.query(Token).filter(Token.id == token_id).first()
        if not token:
            return None

        visit = token.visit
        patient = visit.patient if visit else None
        department = visit.department if visit else None
        doctor = token.doctor
        doctor_user = doctor.user if doctor else None

        status_val = token.status.value if hasattr(token.status, "value") else str(token.status)

        return {
            "token_id": token.id,
            "token_number": token.token_number,
            "status": status_val,
            "token_date": token.token_date,
            "visit_id": visit.id if visit else None,
            "visit_id_str": visit.visit_id if visit else "Unknown",
            "patient_id": patient.id if patient else None,
            "patient_code": patient.patient_id if patient else "Unknown",
            "patient_name": patient.full_name if patient else "Unknown",
            "department_id": department.id if department else None,
            "department_name": department.name if department else "Unknown",
            "doctor_id": doctor.id if doctor else None,
            "doctor_name": doctor_user.full_name if doctor_user else "Unknown",
            "created_at": token.created_at,
        }

    @staticmethod
    def get_latest_token_for_patient(db: Session, patient_id: int) -> Token:
        """Get the latest token for a patient by traversing their latest visit."""
        from database.models import Visit
        visit = db.query(Visit).filter(Visit.patient_id == patient_id).order_by(Visit.visit_date.desc()).first()
        if not visit:
            return None
        return db.query(Token).filter(Token.visit_id == visit.id).order_by(Token.token_date.desc()).first()
    
    @staticmethod
    def format_token_for_display(token: Token, db: Optional[Session] = None) -> dict:
        """Format token data for display safely"""
        if not token:
            return None
        
        status_val = token.status.value if hasattr(token.status, "value") else str(token.status)
        est_pos = TokenService.get_estimated_position(db, token.token_number) if db else 1
        
        patient_name = "Unknown"
        patient_id = "Unknown"
        dept_name = "Unknown"
        doc_name = "Unknown"

        try:
            if token.visit:
                if token.visit.patient:
                    patient_name = token.visit.patient.full_name
                    patient_id = token.visit.patient.patient_id
                if token.visit.department:
                    dept_name = token.visit.department.name
            if token.doctor and token.doctor.user:
                doc_name = token.doctor.user.full_name
        except Exception:
            pass

        return {
            "token_number": token.token_number,
            "patient_name": patient_name,
            "patient_id": patient_id,
            "department": dept_name,
            "doctor": doc_name,
            "status": status_val,
            "token_date": token.token_date,
            "estimated_position": est_pos,
            "created_at": token.created_at
        }
    
    @staticmethod
    def update_token_status(db: Session, token_id: int, new_status: TokenStatus) -> Token:
        """Update token status and synchronize visit status"""
        token = db.query(Token).filter(Token.id == token_id).first()
        if not token:
            raise ValueError("Token not found")
        
        # Ensure new_status is enum or proper type
        if isinstance(new_status, str):
            for m in TokenStatus:
                if m.value.upper() == new_status.upper():
                    new_status = m
                    break

        token.status = new_status
        if token.visit:
            if token.status == TokenStatus.COMPLETED:
                token.visit.status = "completed"
            elif token.visit.status == "completed" and token.status != TokenStatus.COMPLETED:
                token.visit.status = "ongoing"

        db.flush()
        return token
    
    @staticmethod
    def get_today_waiting_count(db: Session) -> int:
        """Get count of waiting tokens for today"""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        return db.query(Token).filter(
            Token.token_date >= today_start,
            Token.token_date < today_end,
            Token.status == TokenStatus.WAITING
        ).count()
