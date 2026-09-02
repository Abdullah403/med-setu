"""Database models for MED-SETU application"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum

Base = declarative_base()


from sqlalchemy.types import TypeDecorator


class UserRole(str, enum.Enum):
    """User roles in the system"""
    RECEPTIONIST = "receptionist"
    DOCTOR = "doctor"
    HOSPITAL_ADMIN = "hospital_admin"
    GOVERNMENT_ADMIN = "government_admin"


class UserRoleType(TypeDecorator):
    """
    Robust TypeDecorator for UserRole enum.
    Seamlessly handles both enum names ('RECEPTIONIST') and enum values ('receptionist'),
    case-insensitively, in SQLite and across all queries.
    """
    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, UserRole):
            return value.name
        if isinstance(value, str):
            val_clean = value.strip()
            upper = val_clean.upper()
            if upper in UserRole.__members__:
                return upper
            lower = val_clean.lower()
            for member in UserRole:
                if member.value.lower() == lower:
                    return member.name
            return upper
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, UserRole):
            return value
        val_clean = str(value).strip()
        upper = val_clean.upper()
        if upper in UserRole.__members__:
            return UserRole[upper]
        lower = val_clean.lower()
        for member in UserRole:
            if member.value.lower() == lower:
                return member
        return UserRole[upper]


class TokenStatus(str, enum.Enum):
    """Token statuses in the queue system"""
    WAITING = "WAITING"
    CALLED = "CALLED"
    WITH_DOCTOR = "WITH_DOCTOR"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class User(Base):
    """User model for system access"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(UserRoleType, nullable=False)
    full_name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    facility_id = Column(Integer, ForeignKey("facilities.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    doctor = relationship("Doctor", back_populates="user", uselist=False)
    facility = relationship("Facility", foreign_keys=[facility_id])


class Facility(Base):
    """Healthcare facility model"""
    __tablename__ = "facilities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    facility_type = Column(String, nullable=False)  # e.g., "Rural Health Centre", "Hospital"
    district = Column(String, nullable=False)
    address = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)

    # Relationships
    departments = relationship("Department", back_populates="facility", cascade="all, delete-orphan")
    doctors = relationship("Doctor", back_populates="facility", cascade="all, delete-orphan")
    visits = relationship("Visit", back_populates="facility", cascade="all, delete-orphan")
    referrals_sent = relationship("Referral", back_populates="referring_facility",
                                  foreign_keys="[Referral.referring_facility_id]")
    referrals_received = relationship("Referral", back_populates="receiving_facility",
                                      foreign_keys="[Referral.receiving_facility_id]")


class Department(Base):
    """Department model within a facility"""
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)  # e.g., "General Medicine", "Dental"
    facility_id = Column(Integer, ForeignKey("facilities.id"), nullable=False)

    # Relationships
    facility = relationship("Facility", back_populates="departments")
    doctors = relationship("Doctor", back_populates="department", cascade="all, delete-orphan")
    visits = relationship("Visit", back_populates="department", cascade="all, delete-orphan")


class Doctor(Base):
    """Doctor model"""
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    facility_id = Column(Integer, ForeignKey("facilities.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    doctor_id = Column(String, unique=True, nullable=False, index=True)  # e.g., "DOC-001"
    specialization = Column(String, nullable=False)  # e.g., "General Medicine", "Dental"
    is_available = Column(Boolean, default=True)

    # Relationships
    user = relationship("User", back_populates="doctor")
    facility = relationship("Facility", back_populates="doctors")
    department = relationship("Department", back_populates="doctors")
    visits = relationship("Visit", back_populates="doctor", cascade="all, delete-orphan")
    tokens = relationship("Token", back_populates="doctor", cascade="all, delete-orphan")
    prescriptions = relationship("Prescription", back_populates="doctor")
    doctor_notes = relationship("DoctorNote", back_populates="doctor")
    follow_ups = relationship("FollowUp", back_populates="doctor")
    referrals_sent = relationship("Referral", back_populates="referring_doctor",
                                   foreign_keys="[Referral.referring_doctor_id]")
    referrals_received = relationship("Referral", back_populates="receiving_doctor",
                                       foreign_keys="[Referral.receiving_doctor_id]")


class Patient(Base):
    """Patient model"""
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(String, unique=True, index=True, nullable=False)  # e.g., "PAT-00184"
    full_name = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    gender = Column(String, nullable=False)  # "Male", "Female", "Other"
    phone = Column(String, nullable=False)
    preferred_language = Column(String, default="English")  # e.g., "Hindi", "English"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    visits = relationship("Visit", back_populates="patient", cascade="all, delete-orphan")
    cases = relationship("PatientCase", back_populates="patient", cascade="all, delete-orphan")
    documents = relationship("MedicalDocument", back_populates="patient", cascade="all, delete-orphan")
    prescriptions = relationship("Prescription", back_populates="patient")
    doctor_notes = relationship("DoctorNote", back_populates="patient")
    referrals = relationship("Referral", back_populates="patient")
    follow_ups = relationship("FollowUp", back_populates="patient")


class PatientCase(Base):
    """Structured clinical case submitted by a patient for a visit."""
    __tablename__ = "patient_cases"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    visit_id = Column(Integer, ForeignKey("visits.id"), nullable=False)
    chief_complaint = Column(String, nullable=False)
    duration = Column(String, default="")
    symptoms = Column(String, default="")
    additional_notes = Column(String, default="")
    ai_summary = Column(String, default="")
    red_flag_detected = Column(Boolean, default=False)
    red_flags = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="cases")
    visit = relationship("Visit", back_populates="cases")


class MedicalDocument(Base):
    """Uploaded patient documents associated with a patient and visit."""
    __tablename__ = "medical_documents"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    visit_id = Column(Integer, ForeignKey("visits.id"), nullable=False)
    file_name = Column(String, nullable=False)
    stored_name = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    extracted_text = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="documents")
    visit = relationship("Visit", back_populates="documents")


class Visit(Base):
    """Healthcare visit model"""
    __tablename__ = "visits"

    id = Column(Integer, primary_key=True, index=True)
    visit_id = Column(String, unique=True, index=True, nullable=False)  # e.g., "VIS-2026-00091"
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    facility_id = Column(Integer, ForeignKey("facilities.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    visit_date = Column(DateTime, nullable=False)
    status = Column(String, default="ongoing")  # "ongoing", "completed", "cancelled"
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    patient = relationship("Patient", back_populates="visits")
    facility = relationship("Facility", back_populates="visits")
    department = relationship("Department", back_populates="visits")
    doctor = relationship("Doctor", back_populates="visits")
    tokens = relationship("Token", back_populates="visit", cascade="all, delete-orphan")
    cases = relationship("PatientCase", back_populates="visit", cascade="all, delete-orphan")
    documents = relationship("MedicalDocument", back_populates="visit", cascade="all, delete-orphan")
    prescriptions = relationship("Prescription", back_populates="visit")
    doctor_note = relationship("DoctorNote", back_populates="visit", uselist=False)
    referrals = relationship("Referral", back_populates="visit")
    follow_ups = relationship("FollowUp", back_populates="visit")


class Token(Base):
    """Queue token model - temporary identifier for patient queue"""
    __tablename__ = "tokens"

    id = Column(Integer, primary_key=True, index=True)
    token_number = Column(String, nullable=False, index=True)  # e.g., "MED-043"
    visit_id = Column(Integer, ForeignKey("visits.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    token_date = Column(DateTime, default=datetime.utcnow)
    status = Column(Enum(TokenStatus), default=TokenStatus.WAITING)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    visit = relationship("Visit", back_populates="tokens")
    doctor = relationship("Doctor", back_populates="tokens")


# ==================== NEW PHASE 6 MODELS ====================


class Prescription(Base):
    """Prescription model - medicines prescribed by doctor for a visit"""
    __tablename__ = "prescriptions"

    id = Column(Integer, primary_key=True, index=True)
    visit_id = Column(Integer, ForeignKey("visits.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    medication_name = Column(String, nullable=False)
    dosage = Column(String, nullable=False)
    frequency = Column(String, nullable=False)
    duration = Column(String, nullable=False)
    instructions = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    visit = relationship("Visit", back_populates="prescriptions")
    patient = relationship("Patient", back_populates="prescriptions")
    doctor = relationship("Doctor", back_populates="prescriptions")


class DoctorNote(Base):
    """Doctor's clinical notes for a visit (one per visit)"""
    __tablename__ = "doctor_notes"

    id = Column(Integer, primary_key=True, index=True)
    visit_id = Column(Integer, ForeignKey("visits.id"), nullable=False, unique=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    diagnosis = Column(String, nullable=False)
    examination_findings = Column(String, default="")
    treatment_plan = Column(String, default="")
    notes = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    visit = relationship("Visit", back_populates="doctor_note")
    patient = relationship("Patient", back_populates="doctor_notes")
    doctor = relationship("Doctor", back_populates="doctor_notes")


class Referral(Base):
    """Inter-hospital referral"""
    __tablename__ = "referrals"

    id = Column(Integer, primary_key=True, index=True)
    referral_id = Column(String, unique=True, index=True, nullable=False)  # "REF-2026-00001"
    visit_id = Column(Integer, ForeignKey("visits.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    referring_doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    referring_facility_id = Column(Integer, ForeignKey("facilities.id"), nullable=False)
    receiving_facility_id = Column(Integer, ForeignKey("facilities.id"), nullable=False)
    receiving_department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    receiving_doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    reason = Column(String, nullable=False)
    urgency = Column(String, nullable=False, default="routine")  # routine, urgent, emergency
    appointment_date = Column(DateTime, nullable=True)
    verification_code = Column(String, nullable=False, index=True)
    status = Column(String, default="pending")  # pending, accepted, in_progress, completed, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    visit = relationship("Visit", back_populates="referrals")
    patient = relationship("Patient", back_populates="referrals")
    referring_doctor = relationship("Doctor", back_populates="referrals_sent",
                                    foreign_keys=[referring_doctor_id])
    receiving_doctor = relationship("Doctor", back_populates="referrals_received",
                                     foreign_keys=[receiving_doctor_id])
    referring_facility = relationship("Facility", back_populates="referrals_sent",
                                      foreign_keys=[referring_facility_id])
    receiving_facility = relationship("Facility", back_populates="referrals_received",
                                       foreign_keys=[receiving_facility_id])
    receiving_department = relationship("Department", foreign_keys=[receiving_department_id])
    data_package = relationship("ReferralDataPackage", back_populates="referral", uselist=False)


class ReferralDataPackage(Base):
    """Snapshot of patient data shared with receiving facility for a referral"""
    __tablename__ = "referral_data_packages"

    id = Column(Integer, primary_key=True, index=True)
    referral_id = Column(Integer, ForeignKey("referrals.id"), nullable=False, unique=True)
    patient_summary = Column(Text, nullable=False)        # JSON: basic patient info
    clinical_summary = Column(Text, nullable=False)        # JSON: case data
    visit_history = Column(Text, default="[]")             # JSON: past visits
    prescription_data = Column(Text, default="[]")         # JSON: prescriptions
    document_references = Column(Text, default="[]")       # JSON: doc metadata
    referral_summary = Column(Text, nullable=False)        # Human-readable summary
    pdf_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    referral = relationship("Referral", back_populates="data_package")


class FollowUp(Base):
    """Follow-up scheduling"""
    __tablename__ = "follow_ups"

    id = Column(Integer, primary_key=True, index=True)
    visit_id = Column(Integer, ForeignKey("visits.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    follow_up_date = Column(DateTime, nullable=False)
    reason = Column(String, nullable=False)
    status = Column(String, default="scheduled")  # scheduled, completed, missed, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    visit = relationship("Visit", back_populates="follow_ups")
    patient = relationship("Patient", back_populates="follow_ups")
    doctor = relationship("Doctor", back_populates="follow_ups")
