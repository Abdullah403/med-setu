"""Prescription management service for MED-SETU."""
from typing import List
from sqlalchemy.orm import Session
from database.models import Prescription


class PrescriptionService:
    """Service for prescription operations."""

    @staticmethod
    def create_prescription(
        db: Session,
        visit_id: int,
        patient_id: int,
        doctor_id: int,
        medication_name: str,
        dosage: str,
        frequency: str,
        duration: str,
        instructions: str = "",
    ) -> Prescription:
        """Create a new prescription entry."""
        if not medication_name or not medication_name.strip():
            raise ValueError("Medication name is required")
        if not dosage or not dosage.strip():
            raise ValueError("Dosage is required")
        if not frequency or not frequency.strip():
            raise ValueError("Frequency is required")
        if not duration or not duration.strip():
            raise ValueError("Duration is required")

        rx = Prescription(
            visit_id=visit_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            medication_name=medication_name.strip(),
            dosage=dosage.strip(),
            frequency=frequency.strip(),
            duration=duration.strip(),
            instructions=(instructions or "").strip(),
        )
        db.add(rx)
        db.flush()
        return rx

    @staticmethod
    def get_prescriptions_for_visit(db: Session, visit_id: int) -> List[Prescription]:
        """Get all prescriptions for a specific visit."""
        return (
            db.query(Prescription)
            .filter(Prescription.visit_id == visit_id)
            .order_by(Prescription.created_at)
            .all()
        )

    @staticmethod
    def get_patient_prescription_history(db: Session, patient_id: int) -> List[Prescription]:
        """Get all prescriptions across all visits for a patient."""
        return (
            db.query(Prescription)
            .filter(Prescription.patient_id == patient_id)
            .order_by(Prescription.created_at.desc())
            .all()
        )
