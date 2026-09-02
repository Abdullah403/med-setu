"""Services module for MED-SETU"""
from services.dashboard_service import DashboardService
from services.patient_service import PatientService
from services.visit_service import VisitService
from services.token_service import TokenService
from services.doctor_service import DoctorService
from services.case_service import PatientCaseService
from services.document_service import DocumentService
from services.prescription_service import PrescriptionService
from services.doctor_note_service import DoctorNoteService
from services.followup_service import FollowUpService
from services.referral_service import ReferralService
from services.pdf_service import PDFService
from services.patient_history_service import PatientHistoryService
from services.management_service import ManagementService
from services.ui_helpers import (
    set_page_style,
    render_kpi_cards,
    render_status_badge,
    render_queue_table,
    render_department_overview,
    render_facility_sidebar,
    render_coming_soon_page
)

__all__ = [
    "DashboardService",
    "PatientService",
    "VisitService",
    "TokenService",
    "DoctorService",
    "PatientCaseService",
    "DocumentService",
    "PrescriptionService",
    "DoctorNoteService",
    "FollowUpService",
    "ReferralService",
    "PDFService",
    "PatientHistoryService",
    "set_page_style",
    "render_kpi_cards",
    "render_status_badge",
    "render_queue_table",
    "render_department_overview",
    "render_facility_sidebar",
    "render_coming_soon_page"
]
