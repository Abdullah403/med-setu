"""Follow-up scheduling service for MED-SETU."""
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from database.models import FollowUp


class FollowUpService:
    """Service for managing patient follow-up appointments."""

    @staticmethod
    def schedule_followup(
        db: Session,
        visit_id: int,
        patient_id: int,
        doctor_id: int,
        follow_up_date: datetime,
        reason: str,
    ) -> FollowUp:
        """Schedule a new follow-up appointment."""
        if not follow_up_date:
            raise ValueError("Follow-up date is required")
        if not reason or not reason.strip():
            raise ValueError("Follow-up reason is required")

        followup = FollowUp(
            visit_id=visit_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            follow_up_date=follow_up_date,
            reason=reason.strip(),
            status="scheduled",
        )
        db.add(followup)
        db.flush()
        return followup

    @staticmethod
    def get_followups_for_patient(db: Session, patient_id: int) -> List[FollowUp]:
        """Get all follow-ups for a patient ordered by appointment date."""
        return (
            db.query(FollowUp)
            .filter(FollowUp.patient_id == patient_id)
            .order_by(FollowUp.follow_up_date.desc())
            .all()
        )

    @staticmethod
    def get_upcoming_followups_for_doctor(db: Session, doctor_id: int) -> List[FollowUp]:
        """Get upcoming scheduled follow-ups for a doctor."""
        return (
            db.query(FollowUp)
            .filter(
                FollowUp.doctor_id == doctor_id,
                FollowUp.status == "scheduled",
            )
            .order_by(FollowUp.follow_up_date.asc())
            .all()
        )

    @staticmethod
    def get_followups_for_visit(db: Session, visit_id: int) -> List[FollowUp]:
        """Get all follow-ups associated with a visit."""
        return (
            db.query(FollowUp)
            .filter(FollowUp.visit_id == visit_id)
            .order_by(FollowUp.created_at.desc())
            .all()
        )

    @staticmethod
    def update_followup_status(db: Session, followup_id: int, new_status: str) -> bool:
        """Update follow-up status (scheduled, completed, missed, cancelled)."""
        valid_statuses = {"scheduled", "completed", "missed", "cancelled"}
        if new_status not in valid_statuses:
            return False

        followup = db.query(FollowUp).filter(FollowUp.id == followup_id).first()
        if not followup:
            return False

        followup.status = new_status
        db.flush()
        return True
