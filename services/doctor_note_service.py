"""Doctor notes service for MED-SETU."""
from typing import List, Optional
from sqlalchemy.orm import Session
from database.models import DoctorNote


class DoctorNoteService:
    """Service for managing clinical doctor notes for a visit."""

    @staticmethod
    def save_note(
        db: Session,
        visit_id: int,
        patient_id: int,
        doctor_id: int,
        diagnosis: str,
        examination_findings: str = "",
        treatment_plan: str = "",
        notes: str = "",
    ) -> DoctorNote:
        """Create or update a doctor note for a visit (one per visit)."""
        if not diagnosis or not diagnosis.strip():
            raise ValueError("Diagnosis is required")

        existing = db.query(DoctorNote).filter(DoctorNote.visit_id == visit_id).first()
        if existing:
            existing.diagnosis = diagnosis.strip()
            existing.examination_findings = (examination_findings or "").strip()
            existing.treatment_plan = (treatment_plan or "").strip()
            existing.notes = (notes or "").strip()
            db.flush()
            return existing

        note = DoctorNote(
            visit_id=visit_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            diagnosis=diagnosis.strip(),
            examination_findings=(examination_findings or "").strip(),
            treatment_plan=(treatment_plan or "").strip(),
            notes=(notes or "").strip(),
        )
        db.add(note)
        db.flush()
        return note

    @staticmethod
    def get_note_for_visit(db: Session, visit_id: int) -> Optional[DoctorNote]:
        """Get the doctor note for a specific visit."""
        return db.query(DoctorNote).filter(DoctorNote.visit_id == visit_id).first()

    @staticmethod
    def get_patient_notes_history(db: Session, patient_id: int) -> List[DoctorNote]:
        """Get all doctor notes for a patient ordered chronologically descending."""
        return (
            db.query(DoctorNote)
            .filter(DoctorNote.patient_id == patient_id)
            .order_by(DoctorNote.created_at.desc())
            .all()
        )
