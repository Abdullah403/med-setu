"""Structured patient case capture and deterministic clinical summary."""
from typing import List
from database.models import PatientCase


class PatientCaseService:
    """Service for patient-submitted case information."""

    @staticmethod
    def detect_red_flags(*values: str) -> List[str]:
        """Return simple deterministic red-flag labels from free-text input."""
        combined = " ".join((v or "") for v in values).lower()
        patterns = {
            "difficulty breathing": ["difficulty breathing", "shortness of breath", "trouble breathing", "breathless"],
            "severe chest pain": ["severe chest pain", "chest pain", "heart pain"],
            "unconscious": ["unconscious", "passed out", "fainted", "loss of consciousness"],
            "heavy bleeding": ["heavy bleeding", "bleeding heavily", "severe bleeding"],
            "severe allergic reaction": ["severe allergic reaction", "anaphylaxis", "swelling of lips", "difficulty swallowing"],
            "stroke-like symptoms": ["weakness on one side", "facial droop", "slurred speech", "stroke"],
            "seizure": ["seizure", "convulsion", "fit"]
        }

        found = []
        for label, phrases in patterns.items():
            if any(phrase in combined for phrase in phrases):
                found.append(label)
        return found

    @staticmethod
    def build_ai_summary(chief_complaint: str, duration: str, symptoms: str, additional_notes: str, red_flags: List[str]) -> str:
        """Create a deterministic summary that is clearly doctor-reviewed."""
        summary_lines = [
            "AI-assisted summary — Doctor verification required",
            f"Chief Complaint: {chief_complaint or 'Not provided'}",
            f"Duration: {duration or 'Not provided'}",
            f"Symptoms: {symptoms or 'Not provided'}",
            f"Additional notes: {additional_notes or 'Not provided'}",
        ]

        if red_flags:
            summary_lines.append("Potential urgent symptom detected — seek immediate medical attention.")
            summary_lines.append(f"Detected red flags: {', '.join(red_flags)}")

        return "\n".join(summary_lines)

    @staticmethod
    def submit_case(db, patient_id: int, visit_id: int, chief_complaint: str, duration: str = "", symptoms: str = "", additional_notes: str = "") -> PatientCase:
        """Submit a patient case tied to a patient and visit."""
        if not patient_id or not visit_id:
            raise ValueError("Patient and visit are required")
        if not chief_complaint or not chief_complaint.strip():
            raise ValueError("Chief complaint is required")

        red_flags = PatientCaseService.detect_red_flags(chief_complaint, duration, symptoms, additional_notes)
        summary = PatientCaseService.build_ai_summary(chief_complaint, duration, symptoms, additional_notes, red_flags)

        case = PatientCase(
            patient_id=patient_id,
            visit_id=visit_id,
            chief_complaint=chief_complaint.strip(),
            duration=(duration or "").strip(),
            symptoms=(symptoms or "").strip(),
            additional_notes=(additional_notes or "").strip(),
            ai_summary=summary,
            red_flag_detected=bool(red_flags),
            red_flags=", ".join(red_flags),
        )

        db.add(case)
        db.commit()
        db.refresh(case)
        return case

    @staticmethod
    def get_case_for_visit(db, patient_id: int, visit_id: int):
        """Fetch the latest case for a patient/visit."""
        return db.query(PatientCase).filter(
            PatientCase.patient_id == patient_id,
            PatientCase.visit_id == visit_id
        ).order_by(PatientCase.created_at.desc()).first()
