"""Assisted-access worker service for ASHA / Anganwadi workers (Phase 3A+3B+3C).

Provides facility-scoped operations for frontline workers who assist
villagers with patient registration, case intake, document attachment,
connection to the healthcare workflow (clinical handoff), and community
follow-up.

IMPORTANT: Workers do NOT diagnose, prescribe, or make clinical decisions.
They collect/record information and connect patients to the healthcare system.
"""
from datetime import datetime, timedelta
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

# Phase 3C: Worker follow-up outcome constants
WORKER_OUTCOMES = {
    "CONTACTED",
    "PATIENT_ATTENDED",
    "PATIENT_DID_NOT_ATTEND",
    "RESCHEDULE_REQUIRED",
    "REPORT_PENDING",
    "PATIENT_UNAVAILABLE",
    "ESCALATED_TO_HEALTHCARE_TEAM",
}


def _is_worker(user_data: Optional[dict]) -> bool:
    if not user_data:
        return False
    return normalize_role(user_data.get("role", "")) in WORKER_ROLES


def _require_worker(user_data: Optional[dict]):
    if not _is_worker(user_data):
        return denial("Unauthorized: This workspace is restricted to ASHA/Anganwadi workers.")
    return None


def _require_facility(user_data: Optional[dict]):
    fid = get_facility_id(user_data)
    if not fid:
        return denial("Unauthorized: No facility context in session.")
    return None


class WorkerService:
    """Service layer for ASHA/Anganwadi assisted-access operations.

    All methods enforce facility isolation at the service level.
    """

    # ═══════════════════════════════════════════════════════════════
    # DASHBOARD
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def get_dashboard_stats(db: Session, user_data: dict) -> Dict[str, Any]:
        """Return facility-scoped operational stats for the worker dashboard."""
        err = _require_worker(user_data)
        if err:
            return err
        err = _require_facility(user_data)
        if err:
            return err

        facility_id = get_facility_id(user_data)
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        # Patients assisted today
        patients_today = db.query(Visit).filter(
            Visit.facility_id == facility_id,
            Visit.visit_date >= today_start,
            Visit.visit_date < today_end,
        ).count()

        # Pending follow-ups
        pending_followups = db.query(FollowUp).join(Visit).filter(
            Visit.facility_id == facility_id,
            FollowUp.status == "scheduled",
        ).count()

        # Overdue follow-ups (due date passed, still scheduled)
        overdue_followups = db.query(FollowUp).join(Visit).filter(
            Visit.facility_id == facility_id,
            FollowUp.status == "scheduled",
            FollowUp.follow_up_date < now,
        ).count()

        # Escalated follow-ups
        escalated_count = db.query(FollowUp).join(Visit).filter(
            Visit.facility_id == facility_id,
            FollowUp.escalated == True,
            FollowUp.status == "scheduled",
        ).count()

        # Active referrals
        active_referrals = db.query(Referral).filter(
            Referral.referring_facility_id == facility_id,
            Referral.status.in_(["pending", "accepted", "in_progress"]),
        ).count()

        # Draft cases (submitted by worker, not yet completed by doctor)
        draft_cases = db.query(PatientCase).join(Visit).filter(
            Visit.facility_id == facility_id,
            PatientCase.submitted_by_worker_id.isnot(None),
            Visit.status == "ongoing",
        ).count()

        # Recent assisted cases
        recent_visits = db.query(Visit).filter(
            Visit.facility_id == facility_id,
        ).order_by(Visit.created_at.desc()).limit(10).all()

        recent_cases = []
        for v in recent_visits:
            patient = v.patient
            case = db.query(PatientCase).filter(
                PatientCase.visit_id == v.id,
            ).order_by(PatientCase.created_at.desc()).first()
            is_assisted = case is not None and case.submitted_by_worker_id is not None
            recent_cases.append({
                "visit_id": v.visit_id,
                "patient_name": patient.full_name if patient else "Unknown",
                "patient_id": patient.patient_id if patient else "",
                "chief_complaint": case.chief_complaint if case else "No intake",
                "status": v.status,
                "is_assisted_intake": is_assisted,
                "submitted_at": case.submitted_at.strftime("%Y-%m-%d %H:%M") if case and case.submitted_at else None,
                "date": v.visit_date.strftime("%Y-%m-%d %H:%M") if v.visit_date else "",
            })

        return {
            "success": True,
            "patients_today": patients_today,
            "pending_followups": pending_followups,
            "overdue_followups": overdue_followups,
            "escalated_count": escalated_count,
            "active_referrals": active_referrals,
            "draft_cases": draft_cases,
            "recent_cases": recent_cases,
        }

    # ═══════════════════════════════════════════════════════════════
    # PATIENT SEARCH
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def search_patients(db: Session, user_data: dict, query: str) -> List[Patient]:
        """Search patients within the worker's facility."""
        err = _require_worker(user_data)
        if err:
            return []
        err = _require_facility(user_data)
        if err:
            return []
        facility_id = get_facility_id(user_data)
        return PatientService.search_patients(db, query, facility_id=facility_id)

    # ═══════════════════════════════════════════════════════════════
    # REGISTER / ASSIST NEW PATIENT
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def register_patient(
        db: Session, user_data: dict, full_name: str, age: int,
        gender: str, phone: str, preferred_language: str = "English",
    ) -> Dict[str, Any]:
        """Register a new patient on behalf of a villager."""
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

    # ═══════════════════════════════════════════════════════════════
    # PHASE 3B: ASSISTED CASE INTAKE + CLINICAL HANDOFF
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def create_assisted_intake(
        db: Session, user_data: dict, patient_id: int, department_id: int,
        doctor_id: int, chief_complaint: str, duration: str = "",
        symptoms: str = "", additional_notes: str = "",
    ) -> Dict[str, Any]:
        """Create an assisted visit + case intake for a patient.

        The case is created in DRAFT state. The worker must call
        submit_case_to_healthcare() to formally submit it.
        """
        err = _require_worker(user_data)
        if err:
            return err
        err = _require_facility(user_data)
        if err:
            return err

        facility_id = get_facility_id(user_data)
        user_id = user_data.get("user_id")

        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return {"success": False, "error": "Patient not found."}

        dept = db.query(Department).filter(
            Department.id == department_id,
            Department.facility_id == facility_id,
        ).first()
        if not dept:
            return {"success": False, "error": "Department not found at your facility."}

        doctor = db.query(Doctor).filter(
            Doctor.id == doctor_id,
            Doctor.facility_id == facility_id,
        ).first()
        if not doctor:
            return {"success": False, "error": "Doctor not found at your facility."}

        try:
            visit = VisitService.create_visit(
                db, patient_id, facility_id, department_id, doctor_id
            )

            case = PatientCaseService.submit_case(
                db, patient_id, visit.id, chief_complaint, duration, symptoms, additional_notes
            )

            # Track worker identity on the case
            case.submitted_by_worker_id = user_id
            db.flush()

            return {
                "success": True,
                "visit": visit,
                "case": case,
                "message": "Case intake created. Review and submit to healthcare team when ready.",
            }
        except ValueError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            db.rollback()
            return {"success": False, "error": f"Failed to create intake: {str(e)}"}

    @staticmethod
    def submit_case_to_healthcare(
        db: Session, user_data: dict, case_id: int, worker_notes: str = "",
    ) -> Dict[str, Any]:
        """Submit an assisted case to the healthcare workflow.

        After submission:
        - worker cannot silently rewrite the clinical information
        - the case is marked as submitted with timestamp
        - healthcare staff can review it
        """
        err = _require_worker(user_data)
        if err:
            return err
        err = _require_facility(user_data)
        if err:
            return err

        facility_id = get_facility_id(user_data)
        user_id = user_data.get("user_id")

        case = db.query(PatientCase).filter(PatientCase.id == case_id).first()
        if not case:
            return {"success": False, "error": "Case not found."}

        # Verify visit belongs to this facility
        visit = db.query(Visit).filter(
            Visit.id == case.visit_id,
            Visit.facility_id == facility_id,
        ).first()
        if not visit:
            return {"success": False, "error": "Case not found at your facility."}

        # Already submitted?
        if case.submitted_at is not None:
            return {"success": False, "error": "Case has already been submitted."}

        case.submitted_at = datetime.utcnow()
        case.worker_notes = (worker_notes or "").strip()
        db.flush()

        return {
            "success": True,
            "message": "Case submitted to healthcare team. The patient is now in the clinical workflow.",
            "submitted_at": case.submitted_at.strftime("%Y-%m-%d %H:%M"),
        }

    @staticmethod
    def get_assisted_case_details(
        db: Session, user_data: dict, case_id: int,
    ) -> Dict[str, Any]:
        """Get details of an assisted case with facility authorization.

        Returns case, visit, patient, documents, and worker metadata.
        """
        err = _require_worker(user_data)
        if err:
            return err
        err = _require_facility(user_data)
        if err:
            return err

        facility_id = get_facility_id(user_data)

        case = db.query(PatientCase).filter(PatientCase.id == case_id).first()
        if not case:
            return {"success": False, "error": "Case not found."}

        visit = db.query(Visit).filter(
            Visit.id == case.visit_id,
            Visit.facility_id == facility_id,
        ).first()
        if not visit:
            return {"success": False, "error": "Case not found at your facility."}

        patient = case.patient
        documents = DocumentService.get_documents_for_visit(db, patient.id, visit.id)

        worker_name = ""
        if case.submitted_by_worker_id:
            worker_user = db.query(User).filter(User.id == case.submitted_by_worker_id).first()
            worker_name = worker_user.full_name if worker_user else ""

        doctor_name = ""
        if visit.doctor and visit.doctor.user:
            doctor_name = visit.doctor.user.full_name

        dept_name = visit.department.name if visit.department else ""

        return {
            "success": True,
            "case": {
                "id": case.id,
                "chief_complaint": case.chief_complaint,
                "duration": case.duration,
                "symptoms": case.symptoms,
                "additional_notes": case.additional_notes,
                "ai_summary": case.ai_summary,
                "red_flag_detected": case.red_flag_detected,
                "red_flags": case.red_flags,
                "worker_notes": case.worker_notes,
                "submitted_at": case.submitted_at.strftime("%Y-%m-%d %H:%M") if case.submitted_at else None,
                "submitted_by_worker": worker_name,
                "created_at": case.created_at.strftime("%Y-%m-%d %H:%M") if case.created_at else "",
            },
            "visit": {
                "visit_id": visit.visit_id,
                "status": visit.status,
                "department": dept_name,
                "doctor": doctor_name,
                "visit_date": visit.visit_date.strftime("%Y-%m-%d %H:%M") if visit.visit_date else "",
            },
            "patient": {
                "patient_id": patient.patient_id,
                "full_name": patient.full_name,
                "age": patient.age,
                "gender": patient.gender,
                "phone": patient.phone,
                "preferred_language": patient.preferred_language,
            },
            "documents": [
                {
                    "file_name": doc.file_name,
                    "file_type": doc.file_type,
                    "has_ocr_text": bool(doc.extracted_text),
                    "created_at": doc.created_at.strftime("%Y-%m-%d %H:%M") if doc.created_at else "",
                }
                for doc in documents
            ],
            "is_submitted": case.submitted_at is not None,
        }

    @staticmethod
    def get_worker_submitted_cases(
        db: Session, user_data: dict,
    ) -> List[Dict[str, Any]]:
        """Get all cases submitted by this worker at their facility."""
        err = _require_worker(user_data)
        if err:
            return []
        err = _require_facility(user_data)
        if err:
            return []

        facility_id = get_facility_id(user_data)
        user_id = user_data.get("user_id")

        cases = db.query(PatientCase).join(Visit).filter(
            Visit.facility_id == facility_id,
            PatientCase.submitted_by_worker_id == user_id,
        ).order_by(PatientCase.created_at.desc()).all()

        result = []
        for case in cases:
            visit = case.visit
            patient = case.patient
            result.append({
                "case_id": case.id,
                "visit_id": visit.visit_id if visit else "",
                "patient_name": patient.full_name if patient else "Unknown",
                "patient_id": patient.patient_id if patient else "",
                "chief_complaint": case.chief_complaint,
                "status": visit.status if visit else "",
                "is_submitted": case.submitted_at is not None,
                "submitted_at": case.submitted_at.strftime("%Y-%m-%d %H:%M") if case.submitted_at else None,
                "created_at": case.created_at.strftime("%Y-%m-%d %H:%M") if case.created_at else "",
            })

        return result

    # ═══════════════════════════════════════════════════════════════
    # DOCUMENT / REPORT ASSISTANCE
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def attach_document(
        db: Session, user_data: dict, patient_id: int, visit_id: int,
        uploaded_file, file_name: str,
    ) -> Dict[str, Any]:
        """Attach a document to a patient's visit on their behalf."""
        err = _require_worker(user_data)
        if err:
            return err
        err = _require_facility(user_data)
        if err:
            return err

        facility_id = get_facility_id(user_data)
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
        db: Session, user_data: dict, patient_id: int, visit_id: int,
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

    # ═══════════════════════════════════════════════════════════════
    # REFERRAL VIEW (Phase 3A + 3C)
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def get_facility_referrals(db: Session, user_data: dict) -> List[Dict[str, Any]]:
        """Get facility-scoped referrals for the worker to view."""
        err = _require_worker(user_data)
        if err:
            return []
        err = _require_facility(user_data)
        if err:
            return []

        facility_id = get_facility_id(user_data)
        referrals = ReferralService.get_outgoing_referrals_for_facility(db, facility_id)

        result = []
        for ref in referrals:
            patient = ref.patient
            # Check if there's an associated follow-up
            associated_followup = db.query(FollowUp).filter(
                FollowUp.visit_id == ref.visit_id,
            ).order_by(FollowUp.created_at.desc()).first()

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
                "has_followup": associated_followup is not None,
                "followup_status": associated_followup.status if associated_followup else None,
            })

        return result

    @staticmethod
    def get_patient_referrals(
        db: Session, user_data: dict, patient_id: int,
    ) -> List[Dict[str, Any]]:
        """Get referrals for a specific patient, with facility authorization."""
        err = _require_worker(user_data)
        if err:
            return []
        err = _require_facility(user_data)
        if err:
            return []

        facility_id = get_facility_id(user_data)
        if not patient_has_visits_at_facility(db, patient_id, facility_id):
            return []

        referrals = ReferralService.get_referrals_for_patient(db, patient_id)

        return [
            {
                "referral_id": ref.referral_id,
                "patient_name": ref.patient.full_name if ref.patient else "Unknown",
                "receiving_facility": ref.receiving_facility.name if ref.receiving_facility else "Unknown",
                "department": ref.receiving_department.name if ref.receiving_department else "Unknown",
                "status": ref.status,
                "urgency": ref.urgency,
                "reason": ref.reason,
                "appointment_date": ref.appointment_date.strftime("%Y-%m-%d %H:%M") if ref.appointment_date else None,
            }
            for ref in referrals
        ]

    # ═══════════════════════════════════════════════════════════════
    # PHASE 3C: FOLLOW-UP WORK QUEUE + OUTCOMES + ESCALATION
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def get_facility_followups(
        db: Session, user_data: dict, status_filter: str = None,
    ) -> List[Dict[str, Any]]:
        """Get facility-scoped follow-ups with enhanced operational details.

        status_filter: 'scheduled', 'overdue', 'completed', 'missed', or None for all.
        """
        err = _require_worker(user_data)
        if err:
            return []
        err = _require_facility(user_data)
        if err:
            return []

        facility_id = get_facility_id(user_data)
        now = datetime.utcnow()

        q = db.query(FollowUp).join(Visit).filter(
            Visit.facility_id == facility_id,
        )

        if status_filter == "overdue":
            q = q.filter(
                FollowUp.status == "scheduled",
                FollowUp.follow_up_date < now,
            )
        elif status_filter == "scheduled":
            q = q.filter(FollowUp.status == "scheduled")
        elif status_filter in ("completed", "missed", "cancelled"):
            q = q.filter(FollowUp.status == status_filter)

        followups = q.order_by(FollowUp.follow_up_date.desc()).all()

        result = []
        for fu in followups:
            patient = fu.patient
            visit = fu.visit

            # Get referral info if visit has one
            referral = db.query(Referral).filter(
                Referral.visit_id == visit.id if visit else False,
            ).first()

            is_overdue = (
                fu.status == "scheduled" and fu.follow_up_date < now
            )

            worker_outcome_user = ""
            if fu.worker_outcome_by_id:
                wu = db.query(User).filter(User.id == fu.worker_outcome_by_id).first()
                worker_outcome_user = wu.full_name if wu else ""

            result.append({
                "followup_id": fu.id,
                "patient_name": patient.full_name if patient else "Unknown",
                "patient_id": patient.patient_id if patient else "",
                "follow_up_date": fu.follow_up_date.strftime("%Y-%m-%d %H:%M") if fu.follow_up_date else "",
                "reason": fu.reason,
                "status": fu.status,
                "is_overdue": is_overdue,
                "visit_id": visit.visit_id if visit else "",
                # Worker outcome fields
                "worker_outcome": fu.worker_outcome or "",
                "worker_outcome_at": fu.worker_outcome_at.strftime("%Y-%m-%d %H:%M") if fu.worker_outcome_at else "",
                "worker_outcome_by": worker_outcome_user,
                "worker_outcome_notes": fu.worker_outcome_notes or "",
                "escalated": fu.escalated,
                "escalated_at": fu.escalated_at.strftime("%Y-%m-%d %H:%M") if fu.escalated_at else "",
                # Referral context
                "has_referral": referral is not None,
                "referral_status": referral.status if referral else "",
                "referral_id": referral.referral_id if referral else "",
                "referral_destination": referral.receiving_facility.name if referral and referral.receiving_facility else "",
                "referral_appointment": referral.appointment_date.strftime("%Y-%m-%d %H:%M") if referral and referral.appointment_date else "",
            })

        return result

    @staticmethod
    def record_worker_outcome(
        db: Session, user_data: dict, followup_id: int,
        outcome: str, notes: str = "",
    ) -> Dict[str, Any]:
        """Record a worker-reported follow-up outcome.

        This is an operational status, NOT a clinical diagnosis.
        """
        err = _require_worker(user_data)
        if err:
            return err
        err = _require_facility(user_data)
        if err:
            return err

        if outcome not in WORKER_OUTCOMES:
            return {
                "success": False,
                "error": f"Invalid outcome. Allowed: {', '.join(sorted(WORKER_OUTCOMES))}",
            }

        facility_id = get_facility_id(user_data)
        user_id = user_data.get("user_id")

        followup = db.query(FollowUp).filter(FollowUp.id == followup_id).first()
        if not followup:
            return {"success": False, "error": "Follow-up not found."}

        visit = db.query(Visit).filter(Visit.id == followup.visit_id).first()
        if not visit or visit.facility_id != facility_id:
            return {"success": False, "error": "Follow-up not found at your facility."}

        followup.worker_outcome = outcome
        followup.worker_outcome_at = datetime.utcnow()
        followup.worker_outcome_by_id = user_id
        followup.worker_outcome_notes = (notes or "").strip()

        # Auto-update status based on outcome
        if outcome == "PATIENT_ATTENDED":
            followup.status = "completed"
        elif outcome == "PATIENT_DID_NOT_ATTEND":
            followup.status = "missed"

        db.flush()

        return {
            "success": True,
            "message": f"Follow-up outcome recorded: {outcome}",
        }

    @staticmethod
    def escalate_followup(
        db: Session, user_data: dict, followup_id: int, reason: str = "",
    ) -> Dict[str, Any]:
        """Escalate a follow-up to the healthcare team.

        This is an operational escalation. The worker must NOT diagnose.
        """
        err = _require_worker(user_data)
        if err:
            return err
        err = _require_facility(user_data)
        if err:
            return err

        facility_id = get_facility_id(user_data)

        followup = db.query(FollowUp).filter(FollowUp.id == followup_id).first()
        if not followup:
            return {"success": False, "error": "Follow-up not found."}

        visit = db.query(Visit).filter(Visit.id == followup.visit_id).first()
        if not visit or visit.facility_id != facility_id:
            return {"success": False, "error": "Follow-up not found at your facility."}

        if followup.escalated:
            return {"success": False, "error": "Follow-up is already escalated."}

        followup.escalated = True
        followup.escalated_at = datetime.utcnow()
        followup.worker_outcome = "ESCALATED_TO_HEALTHCARE_TEAM"
        followup.worker_outcome_at = datetime.utcnow()
        followup.worker_outcome_by_id = user_data.get("user_id")
        if reason:
            followup.worker_outcome_notes = (followup.worker_outcome_notes + "\n" if followup.worker_outcome_notes else "") + f"Escalation reason: {reason.strip()}"

        db.flush()

        return {
            "success": True,
            "message": "Follow-up escalated to healthcare team.",
        }

    @staticmethod
    def update_followup_status(
        db: Session, user_data: dict, followup_id: int, new_status: str,
    ) -> Dict[str, Any]:
        """Update a follow-up status (operational only, no clinical modification).

        Workers can update status to 'completed' or 'missed'.
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

    # ═══════════════════════════════════════════════════════════════
    # DEPARTMENTS / DOCTORS
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def get_facility_departments(db: Session, user_data: dict) -> List[Department]:
        err = _require_worker(user_data)
        if err:
            return []
        err = _require_facility(user_data)
        if err:
            return []
        facility_id = get_facility_id(user_data)
        return db.query(Department).filter(Department.facility_id == facility_id).all()

    @staticmethod
    def get_facility_doctors(
        db: Session, user_data: dict, department_id: int = None,
    ) -> List[Doctor]:
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

    # ═══════════════════════════════════════════════════════════════
    # PATIENT DETAILS
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def get_patient_details(
        db: Session, user_data: dict, patient_id: int,
    ) -> Optional[Dict[str, Any]]:
        err = _require_worker(user_data)
        if err:
            return err
        err = _require_facility(user_data)
        if err:
            return err

        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return {"success": False, "error": "Patient not found."}
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
