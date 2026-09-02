"""Patient document upload and OCR support for MED-SETU prototype."""
import os
from typing import Optional
from sqlalchemy.orm import Session
from database.models import MedicalDocument

ALLOWED_TYPES = {"pdf", "jpg", "jpeg", "png"}
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")


class DocumentService:
    """Service for storing patient documents and optional OCR text extraction."""

    @staticmethod
    def ensure_upload_dir():
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        return UPLOAD_DIR

    @staticmethod
    def allowed_file(file_name: str) -> bool:
        if not file_name:
            return False
        return file_name.rsplit(".", 1)[-1].lower() in ALLOWED_TYPES

    @staticmethod
    def extract_text_from_file(file_path: str, file_type: str) -> str:
        """Attempt OCR extraction where dependencies are available; otherwise return empty string."""
        if file_type == "pdf":
            try:
                import PyPDF2
                reader = PyPDF2.PdfReader(file_path)
                pages = []
                for page in reader.pages:
                    text = page.extract_text() or ""
                    pages.append(text)
                return "\n\n".join(pages).strip()
            except Exception:
                return ""

        if file_type in {"jpg", "jpeg", "png"}:
            try:
                from PIL import Image
                import pytesseract
                image = Image.open(file_path)
                text = pytesseract.image_to_string(image)
                return text.strip()
            except Exception:
                return ""

        return ""

    @staticmethod
    def save_document(db: Session, patient_id: int, visit_id: int, uploaded_file, file_name: str) -> MedicalDocument:
        """Store an uploaded document and associate it with patient + visit."""
        if not patient_id or not visit_id:
            raise ValueError("Patient ID and Visit ID are required")
        if not uploaded_file or not file_name:
            raise ValueError("Document upload is required")
        if not DocumentService.allowed_file(file_name):
            raise ValueError("Unsupported file type. Allowed: PDF, JPG, JPEG, PNG")

        DocumentService.ensure_upload_dir()
        file_ext = file_name.rsplit(".", 1)[-1].lower()
        stored_name = f"{patient_id}_{visit_id}_{len(os.listdir(UPLOAD_DIR)) + 1}.{file_ext}"
        file_path = os.path.join(UPLOAD_DIR, stored_name)

        with open(file_path, "wb") as f:
            f.write(uploaded_file.read())

        extracted_text = DocumentService.extract_text_from_file(file_path, file_ext)
        document = MedicalDocument(
            patient_id=patient_id,
            visit_id=visit_id,
            file_name=file_name,
            stored_name=stored_name,
            file_type=file_ext,
            file_path=file_path,
            extracted_text=extracted_text,
        )

        db.add(document)
        db.commit()
        db.refresh(document)
        return document

    @staticmethod
    def get_documents_for_visit(db: Session, patient_id: int, visit_id: int):
        """Fetch patient documents belonging to only this patient + visit."""
        return db.query(MedicalDocument).filter(
            MedicalDocument.patient_id == patient_id,
            MedicalDocument.visit_id == visit_id
        ).order_by(MedicalDocument.created_at.desc()).all()

    @staticmethod
    def get_document_by_id(db: Session, document_id: int, patient_id: int, visit_id: int) -> Optional[MedicalDocument]:
        """Fetch a specific document with patient/visit restrictions."""
        return db.query(MedicalDocument).filter(
            MedicalDocument.id == document_id,
            MedicalDocument.patient_id == patient_id,
            MedicalDocument.visit_id == visit_id,
        ).first()
