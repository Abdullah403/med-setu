"""Assisted-access worker service for ASHA / Anganwadi workers (Phase 3A).

Provides facility-scoped operations for frontline workers who assist
villagers with patient registration, case intake, document attachment,
and connection to the healthcare workflow.

IMPORTANT: Workers do NOT diagnose, prescribe, or make clinical decisions.
They collect/record information and connect patients to the healthcare system.
"""
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from database.models import (
    Patient, Visit, PatientCase, MedicalDocument, Referral, FollowUp,
    User, Facility, Department, Doctor,
)
from services.authorization import (
    get_facility_id, patient_has_visits_at_facility, denial,
)
from services.patient_service import PatientService
from services.visit_service import VisitService
from services.case_service import PatientCaseService
from services.document_service import DocumentService
from services.referral_service import ReferralService
from services.followup_service import FollowUpService
from services.session_service import normalize_role


WORKER_ROLES = {"asha_worker", "anganwadi_worker"}


def _is_worker(user_data: Optional[dict]) -> bool:
    """Return True if user_data represents a worker role."""
    if not user_data:
        return False
    return normalize_role(user_data.get("role", "")) in WORKER_ROLES


def _require_worker(user_data: Optional[dict]):
    """Return an error dict if the user is not a worker. None if OK."""
    if not _is_worker(user_data):
        return denial("Unauthorized: This workspace is restricted to ASHA/Anganwadi workers.")
    return None


def _require_facility(user_data: Optional[dict]):
    """Return an error dict if the user has no facility. None if OK."""
    fid = get_facility_id(user_data)
    if not fid:
        return denial("Unauthorized: No facility context in session.")
    return None


class WorkerService:
    """Service layer for ASHA/Anganwadi assisted-access operations.

    All methods enforce facility isolation at the service level.
    """

    # ── Dashboard ──

    @staticmethod
    def get_dashboard_stats(db: Session, user_data: dict) -> Dict[str, Any]:
        """Return facility-scoped operational stats for the worker dashboard.

        Returns counts of patients assisted today, pending follow-ups,
        active referrals, and recent assisted cases.
        """
        err = _require_worker(user_data)
        if err:
            return err
        err = _require_facility(user_data)
        if err:
            return err

        facility_id = get_facility_id(user_data)
        user_id = user_data.get("user_id")

        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        # Patients assisted today (visits created at this facility today)
        patients_today = db.query(Visit).filter(
            Visit.facility_id == facility_id,
            Visit.visit_date >= today_start,
            Visit.visit_date < today_end,
        ).count()

        # Pending follow-ups for patients at this facility
        pending_followups = db.query(FollowUp).join(Visit).filter(
            Visit.facility_id == facility_id,
            FollowUp.status == "scheduled",
        ).count()

        # Active referrals (outgoing from this facility, not completed/cancelled)
        active_referrals = db.query(Referral).filter(
            Referral.referring_facility_id == facility_id,
            Referral.status.in_(["pending", "accepted", "in_progress"]),
        ).count()

        # Recent assisted cases (visits at this facility, most recent 10)
        recent_visits = db.query(Visit).filter(
            Visit.facility_id == facility_id,
        ).order_by(Visit.created_at.desc()).limit(10).all()

        recent_cases = []
        for v in recent_visits:
            patient = v.patient
            case = db.query(PatientCase).filter(
                PatientCase.visit_id == v.id,
            ).order_by(PatientCase.created_at.desc()).first()
            recent_cases.append({
                "visit_id": v.visit_id,
                "patient_name": patient.full_name if patient else "Unknown",
                "patient_id": patient.patient_id if patient else "",
                "chief_complaint": case.chief_complaint if case else "No intake",
                "status": v.status,
                "date": v.visit_date.strftime("%Y-%m-%d %H:%M") if v.visit_date else "",
            })

        return {
            "success": True,
            "patients_today": patients_today,
            "pending_followups": pending_followups,
            "active_referrals": active_referrals,
            "recent_cases": recent_cases,
        }

    # ── Patient Search ──

    @staticmethod
    def search_patients(db: Session, user_data: dict, query: str) -> List[Patient]:
        """Search patients within the worker's facility.

        Only returns patients who have visits at the worker's facility.
        """
        err = _require_worker(user_data)
        if err:
            return []
        err = _require_facility(user_data)
        if err:
            return []

        facility_id = get_facility_id(user_data)
        return PatientService.search_patients(db, query, facility_id=facility_id)

    # ── Register / Assist New Patient ──

    @staticmethod
    def register_patient(
        db: Session,
        user_data: dict,
        full_name: str,
        age: int,
        gender: str,
        phone: str,
        preferred_language: str = "English",
    ) -> Dict[str, Any]:
        """Register a new patient on behalf of a villager.

        Uses the existing PatientService.register_patient method.
        Returns the created patient or an error dict.
        """
        err = _require_worker(user_data)
        if err:
            return err
        err = _require_facility(user_data)
        if err:
            return err

        try:
            patient = PatientService.register_patient(
                db, full_name, age, gender, phone, preferred_language
            )
            return {"success": True, "patient": patient}
        except ValueError as e:
            return {"success": False, "error": str(e)}

    # ── Assisted Case Intake ──

    @staticmethod
    def create_assisted_intake(
        db: Session,
        user_data: dict,
        patient_id: int,
        department_id: int,
        doctor_id: int,
        chief_complaint: str,
        duration: str = "",
        symptoms: str = "",
        additional_notes: str = "",
    ) -> Dict[str, Any]:
        """Create an assisted visit + case intake for a patient.

        This submits information into the existing healthcare workflow.
        The visit is created with the assigned doctor and department,
        and a PatientCase is attached with the worker-recorded intake.

        IMPORTANT: This is patient-reported / worker-entered information.
        Clinical diagnosis and treatment remain the responsibility of
        a qualified healthcare professional.
        """
        err = _require_worker(user_data)
        if err:
            return err
        err = _require_facility(user_data)
        if err:
            return err

        facility_id = get_facility_id(user_data)

        # Verify patient exists
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return {"success": False, "error": "Patient not found."}

        # Verify department belongs to this facility
        dept = db.query(Department).filter(
            Department.id == department_id,
            Department.facility_id == facility_id,
        ).first()
        if not dept:
            return {"success": False, "error": "Department not found at your facility."}

        # Verify doctor belongs to this facility
        doctor = db.query(Doctor).filter(
            Doctor.id == doctor_id,
            Doctor.facility_id == facility_id,
        ).first()
        if not doctor:
            return {"success": False, "error": "Doctor not found at your facility."}

        try:
            # Create visit using existing service
            visit = VisitService.create_visit(
                db, patient_id, facility_id, department_id, doctor_id
            )

            # Create case intake using existing service
            case = PatientCaseService.submit_case(
                db, patient_id, visit.id, chief_complaint, duration, symptoms, additional_notes
            )

            return {
                "success": True,
                "visit": visit,
                "case": case,
                "message": "Case intake submitted successfully. The patient is now in the healthcare queue.",
            }
        except ValueError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            db.rollback()
            return {"success": False, "error": f"Failed to create intake: {str(e)}"}

    # ── Document / Report Assistance ──

    @staticmethod
    def attach_document(
        db: Session,
        user_data: dict,
        patient_id: int,
        visit_id: int,
        uploaded_file,
        file_name: str,
    ) -> Dict[str, Any]:
        """Attach a document to a patient's visit on their behalf.

        Uses the existing DocumentService for storage and optional OCR.
        """
        err = _require_worker(user_data)
        if err:
            return err
        err = _require_facility(user_data)
        if err:
            return err

        facility_id = get_facility_id(user_data)

        # Verify visit belongs to this facility
        visit = db.query(Visit).filter(
            Visit.id == visit_id,
            Visit.facility_id == facility_id,
        ).first()
        if not visit:
            return {"success": False, "error": "Visit not found at your facility."}

        try:
            document = DocumentService.save_document(
                db, patient_id, visit_id, uploaded_file, file_name
            )
            return {"success": True, "document": document}
        except ValueError as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_documents_for_visit(
        db: Session, user_data: dict, patient_id: int, visit_id: int
    ) -> List:
        """Get documents for a specific visit, with facility authorization."""
        err = _require_worker(user_data)
        if err:
            return []
        err = _require_facility(user_data)
        if err:
            return []

        facility_id = get_facility_id(user_data)
        visit = db.query(Visit).filter(
            Visit.id == visit_id,
            Visit.facility_id == facility_id,
        ).first()
        if not visit:
            return []

        return DocumentService.get_documents_for_visit(db, patient_id, visit_id)

    # ── Referral View ──

    @staticmethod
    def get_facility_referrals(db: Session, user_data: dict) -> List[Dict[str, Any]]:
        """Get facility-scoped referrals for the worker to view.

        Returns referral information including status, destination,
        department, appointment date, and referral identifier.
        """
        err = _require_worker(user_data)
        if err:
            return []
        err = _require_facility(user_data)
        if err:
            return []

        facility_id = get_facility_id(user_data)

        # Get outgoing referrals from this facility
        referrals = ReferralService.get_outgoing_referrals_for_facility(db, facility_id)

        result = []
        for ref in referrals:
            patient = ref.patient
            result.append({
                "referral_id": ref.referral_id,
                "patient_name": patient.full_name if patient else "Unknown",
                "patient_id": patient.patient_id if patient else "",
                "receiving_facility": ref.receiving_facility.name if ref.receiving_facility else "Unknown",
                "department": ref.receiving_department.name if ref.receiving_department else "Unknown",
                "status": ref.status,
                "urgency": ref.urgency,
                "reason": ref.reason,
                "appointment_date": ref.appointment_date.strftime("%Y-%m-%d %H:%M") if ref.appointment_date else None,
                "created_at": ref.created_at.strftime("%Y-%m-%d") if ref.created_at else "",
            })

        return result

    @staticmethod
    def get_patient_referrals(db: Session, user_data: dict, patient_id: int) -> List[Dict[str, Any]]:
        """Get referrals for a specific patient, with facility authorization."""
        err = _require_worker(user_data)
        if err:
            return []
        err = _require_facility(user_data)
        if err:
            return []

        facility_id = get_facility_id(user_data)

        # Verify patient has visits at this facility
        if not patient_has_visits_at_facility(db, patient_id, facility_id):
            return []

        referrals = ReferralService.get_referrals_for_patient(db, patient_id)

        result = []
        for ref in referrals:
            result.append({
                "referral_id": ref.referral_id,
                "patient_name": ref.patient.full_name if ref.patient else "Unknown",
                "receiving_facility": ref.receiving_facility.name if ref.receiving_facility else "Unknown",
                "department": ref.receiving_department.name if ref.receiving_department else "Unknown",
                "status": ref.status,
                "urgency": ref.urgency,
                "reason": ref.reason,
                "appointment_date": ref.appointment_date.strftime("%Y-%m-%d %H:%M") if ref.appointment_date else None,
            })

        return result

    # ── Follow-up Support ──

    @staticmethod
    def get_facility_followups(db: Session, user_data: dict) -> List[Dict[str, Any]]:
        """Get facility-scoped follow-ups for the worker to view.

        Returns pending and completed follow-ups for patients at the facility.
        """
        err = _require_worker(user_data)
        if err:
            return []
        err = _require_facility(user_data)
        if err:
            return []

        facility_id = get_facility_id(user_data)

        followups = db.query(FollowUp).join(Visit).filter(
            Visit.facility_id == facility_id,
        ).order_by(FollowUp.follow_up_date.desc()).all()

        result = []
        for fu in followups:
            patient = fu.patient
            result.append({
                "followup_id": fu.id,
                "patient_name": patient.full_name if patient else "Unknown",
                "patient_id": patient.patient_id if patient else "",
                "follow_up_date": fu.follow_up_date.strftime("%Y-%m-%d %H:%M") if fu.follow_up_date else "",
                "reason": fu.reason,
                "status": fu.status,
                "visit_id": fu.visit.visit_id if fu.visit else "",
            })

        return result

    @staticmethod
    def update_followup_status(
        db: Session, user_data: dict, followup_id: int, new_status: str
    ) -> Dict[str, Any]:
        """Update a follow-up status (operational only, no clinical modification).

        Workers can only update status to 'completed' or 'missed'.
        """
        err = _require_worker(user_data)
        if err:
            return err
        err = _require_facility(user_data)
        if err:
            return err

        allowed_statuses = {"completed", "missed"}
        if new_status not in allowed_statuses:
            return {"success": False, "error": "Workers can only mark follow-ups as completed or missed."}

        facility_id = get_facility_id(user_data)

        # Verify follow-up belongs to this facility
        followup = db.query(FollowUp).filter(FollowUp.id == followup_id).first()
        if not followup:
            return {"success": False, "error": "Follow-up not found."}

        visit = db.query(Visit).filter(Visit.id == followup.visit_id).first()
        if not visit or visit.facility_id != facility_id:
            return {"success": False, "error": "Follow-up not found at your facility."}

        success = FollowUpService.update_followup_status(db, followup_id, new_status)
        if success:
            return {"success": True, "message": f"Follow-up marked as {new_status}."}
        return {"success": False, "error": "Failed to update follow-up status."}

    # ── Available departments and doctors (for intake form) ──

    @staticmethod
    def get_facility_departments(db: Session, user_data: dict) -> List[Department]:
        """Get departments at the worker's facility."""
        err = _require_worker(user_data)
        if err:
            return []
        err = _require_facility(user_data)
        if err:
            return []

        facility_id = get_facility_id(user_data)
        return db.query(Department).filter(Department.facility_id == facility_id).all()

    @staticmethod
    def get_facility_doctors(db: Session, user_data: dict, department_id: int = None) -> List[Doctor]:
        """Get available doctors at the worker's facility, optionally filtered by department."""
        err = _require_worker(user_data)
        if err:
            return []
        err = _require_facility(user_data)
        if err:
            return []

        facility_id = get_facility_id(user_data)
        q = db.query(Doctor).filter(
            Doctor.facility_id == facility_id,
            Doctor.is_available == True,
        )
        if department_id:
            q = q.filter(Doctor.department_id == department_id)
        return q.all()

    # ── Get patient details (for intake form pre-fill) ──

    @staticmethod
    def get_patient_details(db: Session, user_data: dict, patient_id: int) -> Optional[Dict[str, Any]]:
        """Get patient details with facility authorization."""
        err = _require_worker(user_data)
        if err:
            return err
        err = _require_facility(user_data)
        if err:
            return err

        facility_id = get_facility_id(user_data)

        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return {"success": False, "error": "Patient not found."}

        # Worker can see any active patient (they may assist them at their facility)
        if not patient.is_active:
            return {"success": False, "error": "Patient record is inactive."}

        return {
            "success": True,
            "patient": {
                "id": patient.id,
                "patient_id": patient.patient_id,
                "full_name": patient.full_name,
                "age": patient.age,
                "gender": patient.gender,
                "phone": patient.phone,
                "preferred_language": patient.preferred_language,
            },
        }


# Need timedelta for dashboard stats
from datetime import timedelta
