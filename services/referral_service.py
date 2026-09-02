"""Referral service: create referrals, build data packages, verify receiving access."""
import json
import secrets
from datetime import datetime
from typing import List, Dict, Optional, Any
from sqlalchemy.orm import Session
from database.models import (
    Referral, ReferralDataPackage, Patient, Visit, Doctor, Facility,
    Department, PatientCase, MedicalDocument, Prescription, DoctorNote, FollowUp,
)


class ReferralService:
    """Service for inter-hospital referral operations."""

    # ── Referral ID generation ──

    @staticmethod
    def _next_referral_id(db: Session) -> str:
        year = datetime.utcnow().year
        last = (
            db.query(Referral)
            .filter(Referral.referral_id.like(f"REF-{year}-%"))
            .order_by(Referral.id.desc())
            .first()
        )
        if last:
            try:
                num = int(last.referral_id.split("-")[2]) + 1
            except (IndexError, ValueError):
                num = 1
        else:
            num = 1
        return f"REF-{year}-{num:05d}"

    @staticmethod
    def _generate_verification_code() -> str:
        """6-char alphanumeric verification code."""
        return secrets.token_hex(3).upper()  # e.g. "A3F7B2"

    # ── Create referral ──

    @staticmethod
    def create_referral(
        db: Session,
        visit_id: int,
        patient_id: int,
        referring_doctor_id: int,
        referring_facility_id: int,
        receiving_facility_id: int,
        receiving_department_id: int,
        receiving_doctor_id: Optional[int],
        reason: str,
        urgency: str = "routine",
        appointment_date: Optional[datetime] = None,
    ) -> Referral:
        if not reason or not reason.strip():
            raise ValueError("Referral reason is required")
        if urgency not in ("routine", "urgent", "emergency"):
            raise ValueError("Urgency must be routine, urgent, or emergency")
        if referring_facility_id == receiving_facility_id:
            raise ValueError("Cannot refer to the same facility")

        referral = Referral(
            referral_id=ReferralService._next_referral_id(db),
            visit_id=visit_id,
            patient_id=patient_id,
            referring_doctor_id=referring_doctor_id,
            referring_facility_id=referring_facility_id,
            receiving_facility_id=receiving_facility_id,
            receiving_department_id=receiving_department_id,
            receiving_doctor_id=receiving_doctor_id,
            reason=reason.strip(),
            urgency=urgency,
            appointment_date=appointment_date,
            verification_code=ReferralService._generate_verification_code(),
            status="pending",
        )
        db.add(referral)
        db.flush()
        return referral

    # ── Build data package ──

    @staticmethod
    def _mask_phone(phone: str) -> str:
        if not phone or len(phone) < 6:
            return "****"
        return phone[:2] + "*" * (len(phone) - 4) + phone[-2:]

    @staticmethod
    def build_data_package(db: Session, referral_id: int) -> ReferralDataPackage:
        """Build an immutable snapshot of patient data for the referral."""
        referral = db.query(Referral).filter(Referral.id == referral_id).first()
        if not referral:
            raise ValueError("Referral not found")

        # Already has a package?
        if referral.data_package:
            return referral.data_package

        patient = referral.patient
        visit = referral.visit

        # 1. Patient summary
        patient_summary = {
            "patient_id": patient.patient_id,
            "full_name": patient.full_name,
            "age": patient.age,
            "gender": patient.gender,
            "preferred_language": patient.preferred_language,
            "phone_masked": ReferralService._mask_phone(patient.phone),
        }

        # 2. Clinical summary from current visit case
        case = (
            db.query(PatientCase)
            .filter(PatientCase.patient_id == patient.id, PatientCase.visit_id == visit.id)
            .order_by(PatientCase.created_at.desc())
            .first()
        )
        clinical_summary = {
            "chief_complaint": case.chief_complaint if case else "",
            "duration": case.duration if case else "",
            "symptoms": case.symptoms if case else "",
            "additional_notes": case.additional_notes if case else "",
            "ai_summary": case.ai_summary if case else "",
            "red_flag_detected": case.red_flag_detected if case else False,
            "red_flags": case.red_flags if case else "",
        }

        # 3. Visit history (up to 10 most recent visits)
        visits = (
            db.query(Visit)
            .filter(Visit.patient_id == patient.id)
            .order_by(Visit.visit_date.desc())
            .limit(10)
            .all()
        )
        visit_history = []
        for v in visits:
            note = db.query(DoctorNote).filter(DoctorNote.visit_id == v.id).first()
            visit_history.append({
                "visit_id": v.visit_id,
                "visit_date": v.visit_date.strftime("%Y-%m-%d %H:%M") if v.visit_date else "",
                "department": v.department.name if v.department else "",
                "doctor": v.doctor.user.full_name if v.doctor and v.doctor.user else "",
                "facility": v.facility.name if v.facility else "",
                "status": v.status,
                "diagnosis": note.diagnosis if note else "",
            })

        # 4. Prescriptions from current visit
        prescriptions = (
            db.query(Prescription)
            .filter(Prescription.visit_id == visit.id)
            .order_by(Prescription.created_at)
            .all()
        )
        prescription_data = [
            {
                "medication_name": rx.medication_name,
                "dosage": rx.dosage,
                "frequency": rx.frequency,
                "duration": rx.duration,
                "instructions": rx.instructions,
                "prescribed_date": rx.created_at.strftime("%Y-%m-%d") if rx.created_at else "",
            }
            for rx in prescriptions
        ]

        # 5. Document references from current visit
        documents = (
            db.query(MedicalDocument)
            .filter(MedicalDocument.patient_id == patient.id, MedicalDocument.visit_id == visit.id)
            .order_by(MedicalDocument.created_at.desc())
            .all()
        )
        document_refs = [
            {
                "document_id": doc.id,
                "file_name": doc.file_name,
                "file_type": doc.file_type,
                "has_ocr_text": bool(doc.extracted_text),
                "extracted_text_preview": (doc.extracted_text or "")[:500],
            }
            for doc in documents
        ]

        # 6. Human-readable summary
        referral_summary = ReferralService._build_summary_text(
            patient_summary, clinical_summary, prescription_data,
            document_refs, referral
        )

        package = ReferralDataPackage(
            referral_id=referral.id,
            patient_summary=json.dumps(patient_summary),
            clinical_summary=json.dumps(clinical_summary),
            visit_history=json.dumps(visit_history),
            prescription_data=json.dumps(prescription_data),
            document_references=json.dumps(document_refs),
            referral_summary=referral_summary,
        )
        referral.data_package = package
        db.add(package)
        db.flush()
        return package

    @staticmethod
    def _build_summary_text(patient, clinical, prescriptions, documents, referral) -> str:
        lines = [
            "MED-SETU REFERRAL SUMMARY",
            "=" * 40,
            "",
            f"Referral ID: {referral.referral_id}",
            f"Date: {referral.created_at.strftime('%Y-%m-%d') if referral.created_at else 'N/A'}",
            f"Urgency: {referral.urgency.upper()}",
            "",
            "PATIENT INFORMATION",
            "-" * 30,
            f"Name: {patient['full_name']}",
            f"Patient ID: {patient['patient_id']}",
            f"Age: {patient['age']} | Gender: {patient['gender']}",
            f"Preferred Language: {patient['preferred_language']}",
            "",
            "REFERRING FACILITY",
            "-" * 30,
            f"Facility: {referral.referring_facility.name if referral.referring_facility else 'N/A'}",
            f"Doctor: {referral.referring_doctor.user.full_name if referral.referring_doctor and referral.referring_doctor.user else 'N/A'}",
            f"Specialization: {referral.referring_doctor.specialization if referral.referring_doctor else 'N/A'}",
            "",
            "RECEIVING FACILITY",
            "-" * 30,
            f"Facility: {referral.receiving_facility.name if referral.receiving_facility else 'N/A'}",
            f"Department: {referral.receiving_department.name if referral.receiving_department else 'N/A'}",
        ]
        if referral.receiving_doctor and referral.receiving_doctor.user:
            lines.append(f"Doctor: {referral.receiving_doctor.user.full_name}")
        if referral.appointment_date:
            lines.append(f"Appointment: {referral.appointment_date.strftime('%Y-%m-%d')}")
        lines += [
            "",
            "REASON FOR REFERRAL",
            "-" * 30,
            referral.reason,
            "",
            "CLINICAL SUMMARY",
            "-" * 30,
            f"Chief Complaint: {clinical.get('chief_complaint', 'N/A')}",
            f"Duration: {clinical.get('duration', 'N/A')}",
            f"Symptoms: {clinical.get('symptoms', 'N/A')}",
        ]
        if clinical.get("red_flag_detected"):
            lines.append(f"RED FLAGS: {clinical.get('red_flags', '')}")
        if prescriptions:
            lines += ["", "PRESCRIPTIONS", "-" * 30]
            for i, rx in enumerate(prescriptions, 1):
                lines.append(f"{i}. {rx['medication_name']} {rx['dosage']} - {rx['frequency']} - {rx['duration']}")
                if rx.get("instructions"):
                    lines.append(f"   Instructions: {rx['instructions']}")
        if documents:
            lines += ["", "ATTACHED DOCUMENTS", "-" * 30]
            for doc in documents:
                ocr_label = " (OCR text available)" if doc.get("has_ocr_text") else ""
                lines.append(f"- {doc['file_name']} ({doc['file_type']}){ocr_label}")

        lines += [
            "",
            "=" * 40,
            "Generated by MED-SETU Healthcare Platform",
        ]
        return "\n".join(lines)

    # ── PDF generation ──

    @staticmethod
    def generate_referral_pdf(db: Session, referral_id: int) -> Optional[str]:
        """Generate PDF and return file path. Returns None if reportlab not available."""
        referral = db.query(Referral).filter(Referral.id == referral_id).first()
        if not referral:
            return None

        package = referral.data_package
        if not package:
            package = db.query(ReferralDataPackage).filter(ReferralDataPackage.referral_id == referral.id).first()
            if package:
                referral.data_package = package

        if not package:
            return None

        try:
            from services.pdf_service import PDFService
            pdf_path = PDFService.generate_referral_pdf(referral)
            package.pdf_path = pdf_path
            db.flush()
            return pdf_path
        except Exception as e:
            print(f"PDF generation error: {e}")
            return None

    # ── Secure lookup for receiving hospital ──

    @staticmethod
    def lookup_referral(
        db: Session,
        phone: str,
        verification_code: str,
        receiving_facility_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Secure referral lookup.  All five checks must pass:
        1. Patient with this phone exists
        2. Referral for this patient exists
        3. Verification code matches
        4. Referral targets this facility
        5. Referral status is valid (not cancelled)

        Returns a generic error for ALL failure modes to avoid leaking patient existence.
        """
        phone = (phone or "").strip()
        verification_code = (verification_code or "").strip().upper()

        if not phone or not verification_code:
            return None

        patient = db.query(Patient).filter(Patient.phone == phone).first()
        if not patient:
            return None

        referral = (
            db.query(Referral)
            .filter(
                Referral.patient_id == patient.id,
                Referral.verification_code == verification_code,
                Referral.receiving_facility_id == receiving_facility_id,
                Referral.status.in_(["pending", "accepted", "in_progress"]),
            )
            .first()
        )
        if not referral:
            return None

        return {
            "referral": referral,
            "patient": patient,
        }

    # ── Shared patient view for receiving hospital ──

    @staticmethod
    def get_shared_patient_view(db: Session, referral_id: int, receiving_facility_id: int) -> Optional[Dict]:
        """Return curated patient data from the referral package. Verifies facility authorization."""
        referral = db.query(Referral).filter(Referral.id == referral_id).first()
        if not referral or referral.receiving_facility_id != receiving_facility_id:
            return None

        pkg = referral.data_package
        if not pkg:
            return None

        return {
            "referral": referral,
            "patient_summary": json.loads(pkg.patient_summary),
            "clinical_summary": json.loads(pkg.clinical_summary),
            "visit_history": json.loads(pkg.visit_history),
            "prescription_data": json.loads(pkg.prescription_data),
            "document_references": json.loads(pkg.document_references),
            "referral_summary": pkg.referral_summary,
            "pdf_path": pkg.pdf_path,
        }

    # ── Helper queries ──

    @staticmethod
    def get_referral_by_db_id(db: Session, referral_id: int) -> Optional[Referral]:
        return db.query(Referral).filter(Referral.id == referral_id).first()

    @staticmethod
    def get_referrals_sent_by_doctor(db: Session, doctor_id: int) -> List[Referral]:
        return (
            db.query(Referral)
            .filter(Referral.referring_doctor_id == doctor_id)
            .order_by(Referral.created_at.desc())
            .all()
        )

    @staticmethod
    def get_referrals_for_facility(db: Session, facility_id: int) -> List[Referral]:
        """Get referrals received by this facility."""
        return (
            db.query(Referral)
            .filter(Referral.receiving_facility_id == facility_id)
            .order_by(Referral.created_at.desc())
            .all()
        )

    @staticmethod
    def get_incoming_referrals_for_facility(db: Session, facility_id: int) -> List[Referral]:
        """Alias for get_referrals_for_facility."""
        return ReferralService.get_referrals_for_facility(db, facility_id)

    @staticmethod
    def get_outgoing_referrals_for_facility(db: Session, facility_id: int) -> List[Referral]:
        """Get referrals sent from this facility."""
        return (
            db.query(Referral)
            .filter(Referral.referring_facility_id == facility_id)
            .order_by(Referral.created_at.desc())
            .all()
        )

    @staticmethod
    def get_referrals_for_patient(db: Session, patient_id: int) -> List[Referral]:
        return (
            db.query(Referral)
            .filter(Referral.patient_id == patient_id)
            .order_by(Referral.created_at.desc())
            .all()
        )

    @staticmethod
    def get_available_facilities(db: Session, exclude_facility_id: int = None) -> List[Facility]:
        q = db.query(Facility).filter(Facility.is_active == True)
        if exclude_facility_id:
            q = q.filter(Facility.id != exclude_facility_id)
        return q.all()

    @staticmethod
    def get_departments_for_facility(db: Session, facility_id: int) -> List[Department]:
        return db.query(Department).filter(Department.facility_id == facility_id).all()

    @staticmethod
    def get_doctors_for_department(db: Session, department_id: int) -> List[Doctor]:
        return db.query(Doctor).filter(Doctor.department_id == department_id, Doctor.is_available == True).all()

    @staticmethod
    def update_referral_status(db: Session, referral_id: int, new_status: str) -> bool:
        valid = {"pending", "accepted", "in_progress", "completed", "cancelled"}
        if new_status not in valid:
            return False
        referral = db.query(Referral).filter(Referral.id == referral_id).first()
        if not referral:
            return False
        referral.status = new_status
        db.flush()
        return True

    @staticmethod
    def get_document_for_referral(db: Session, referral_id: int, document_id: int,
                                   receiving_facility_id: int) -> Optional[MedicalDocument]:
        """Allow receiving hospital to access a specific document referenced in the package."""
        referral = db.query(Referral).filter(Referral.id == referral_id).first()
        if not referral or referral.receiving_facility_id != receiving_facility_id:
            return None
        pkg = referral.data_package
        if not pkg:
            return None
        doc_refs = json.loads(pkg.document_references)
        allowed_ids = {d["document_id"] for d in doc_refs}
        if document_id not in allowed_ids:
            return None
        return db.query(MedicalDocument).filter(MedicalDocument.id == document_id).first()
