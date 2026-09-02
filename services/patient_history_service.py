"""Patient history service for aggregating chronological patient records."""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from database.models import (
    Patient,
    Visit,
    PatientCase,
    Prescription,
    DoctorNote,
    MedicalDocument,
    Referral,
    FollowUp,
)


class PatientHistoryService:
    """Service for compiling comprehensive, chronological medical histories."""

    @staticmethod
    def get_full_history(db: Session, patient_id: int) -> Dict[str, Any]:
        """
        Compile full chronological medical timeline for a patient.
        Returns patient details and visit records containing cases, prescriptions,
        doctor notes, documents, referrals, and follow-ups.
        """
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return {}

        visits = (
            db.query(Visit)
            .filter(Visit.patient_id == patient_id)
            .order_by(Visit.visit_date.desc())
            .all()
        )

        timeline_visits = []
        for visit in visits:
            cases = (
                db.query(PatientCase)
                .filter(PatientCase.visit_id == visit.id)
                .order_by(PatientCase.created_at.desc())
                .all()
            )
            prescriptions = (
                db.query(Prescription)
                .filter(Prescription.visit_id == visit.id)
                .order_by(Prescription.created_at.asc())
                .all()
            )
            doctor_note = (
                db.query(DoctorNote)
                .filter(DoctorNote.visit_id == visit.id)
                .first()
            )
            documents = (
                db.query(MedicalDocument)
                .filter(MedicalDocument.visit_id == visit.id)
                .order_by(MedicalDocument.created_at.desc())
                .all()
            )
            referrals = (
                db.query(Referral)
                .filter(Referral.visit_id == visit.id)
                .order_by(Referral.created_at.desc())
                .all()
            )
            follow_ups = (
                db.query(FollowUp)
                .filter(FollowUp.visit_id == visit.id)
                .order_by(FollowUp.created_at.desc())
                .all()
            )

            timeline_visits.append({
                "visit": visit,
                "cases": cases,
                "prescriptions": prescriptions,
                "doctor_note": doctor_note,
                "documents": documents,
                "referrals": referrals,
                "follow_ups": follow_ups,
            })

        return {
            "patient": patient,
            "visits": timeline_visits,
        }

    @staticmethod
    def get_visit_detail(db: Session, visit_id: int) -> Optional[Dict[str, Any]]:
        """Fetch all clinical artifacts for a specific visit."""
        visit = db.query(Visit).filter(Visit.id == visit_id).first()
        if not visit:
            return None

        cases = (
            db.query(PatientCase)
            .filter(PatientCase.visit_id == visit.id)
            .order_by(PatientCase.created_at.desc())
            .all()
        )
        prescriptions = (
            db.query(Prescription)
            .filter(Prescription.visit_id == visit.id)
            .order_by(Prescription.created_at.asc())
            .all()
        )
        doctor_note = (
            db.query(DoctorNote)
            .filter(DoctorNote.visit_id == visit.id)
            .first()
        )
        documents = (
            db.query(MedicalDocument)
            .filter(MedicalDocument.visit_id == visit.id)
            .order_by(MedicalDocument.created_at.desc())
            .all()
        )
        referrals = (
            db.query(Referral)
            .filter(Referral.visit_id == visit.id)
            .order_by(Referral.created_at.desc())
            .all()
        )
        follow_ups = (
            db.query(FollowUp)
            .filter(FollowUp.visit_id == visit.id)
            .order_by(FollowUp.created_at.desc())
            .all()
        )

        return {
            "visit": visit,
            "cases": cases,
            "prescriptions": prescriptions,
            "doctor_note": doctor_note,
            "documents": documents,
            "referrals": referrals,
            "follow_ups": follow_ups,
        }
