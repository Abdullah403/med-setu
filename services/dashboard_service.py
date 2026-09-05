"""Database queries and services for the dashboard"""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from database.models import Visit, Token, Patient, Doctor, Department, Facility, TokenStatus, Referral
from database.db import get_session
from services.authorization import get_facility_id, is_global_role


class DashboardService:
    """Service for fetching dashboard data from database"""

    @staticmethod
    def get_today_visits(db: Session, facility_id: int = None):
        """Get all visits for today, optionally scoped to a facility."""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        q = db.query(Visit).filter(
            Visit.visit_date >= today_start,
            Visit.visit_date < today_end
        )
        if facility_id:
            q = q.filter(Visit.facility_id == facility_id)
        return q.all()

    @staticmethod
    def get_today_tokens(db: Session, facility_id: int = None):
        """Get all tokens for today with related data, optionally scoped to a facility."""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        q = db.query(Token).filter(
            Token.token_date >= today_start,
            Token.token_date < today_end
        )
        if facility_id:
            q = q.join(Visit, Token.visit_id == Visit.id).filter(Visit.facility_id == facility_id)
        return q.all()

    @staticmethod
    def get_kpi_counts(db: Session, facility_id: int = None):
        """Get KPI counts for today, optionally scoped to a facility."""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        visit_filter = [Visit.visit_date >= today_start, Visit.visit_date < today_end]
        token_date_filter = [Token.token_date >= today_start, Token.token_date < today_end]
        if facility_id:
            visit_filter.append(Visit.facility_id == facility_id)

        total_patients = db.query(Visit).filter(*visit_filter).count()

        token_base = db.query(Token).filter(*token_date_filter)
        if facility_id:
            token_base = token_base.join(Visit, Token.visit_id == Visit.id).filter(Visit.facility_id == facility_id)

        waiting_tokens = token_base.filter(Token.status == TokenStatus.WAITING).count()
        with_doctor = token_base.filter(Token.status == TokenStatus.WITH_DOCTOR).count()
        completed = token_base.filter(Token.status == TokenStatus.COMPLETED).count()

        pending_referrals_q = db.query(Referral).filter(Referral.status == "pending")
        if facility_id:
            pending_referrals_q = pending_referrals_q.filter(
                (Referral.receiving_facility_id == facility_id)
            )
        pending_referrals = pending_referrals_q.count()

        return {
            "total_patients": total_patients,
            "waiting": waiting_tokens,
            "with_doctor": with_doctor,
            "completed": completed,
            "pending_referrals": pending_referrals,
        }

    @staticmethod
    def get_department_queue_counts(db: Session, facility_id: int = None):
        """Get waiting patient counts per department, optionally scoped to a facility."""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        dept_q = db.query(Department)
        if facility_id:
            dept_q = dept_q.filter(Department.facility_id == facility_id)
        departments = dept_q.all()
        queue_data = []

        for dept in departments:
            waiting_count = db.query(Token).join(Visit).filter(
                Visit.department_id == dept.id,
                Visit.visit_date >= today_start,
                Visit.visit_date < today_end,
                Token.status == TokenStatus.WAITING
            ).count()

            queue_data.append({
                "name": dept.name,
                "waiting": waiting_count
            })

        return queue_data

    @staticmethod
    def get_active_doctors(db: Session, facility_id: int = None):
        """Get active doctors with their current patient status, optionally scoped to a facility."""
        q = db.query(Doctor).filter(Doctor.is_available == True)
        if facility_id:
            q = q.filter(Doctor.facility_id == facility_id)
        return q.all()

    @staticmethod
    def get_facility_info(db: Session, facility_id: int = None) -> Dict[str, Any]:
        """Get current facility information as a plain dictionary."""
        if facility_id:
            facility = db.query(Facility).filter(Facility.id == facility_id).first()
        else:
            facility = db.query(Facility).first()

        if facility is None:
            return {
                "id": None,
                "name": "Facility not configured",
                "facility_type": "Unknown",
                "district": "Unknown",
                "address": "Not available",
                "phone": "N/A",
                "is_active": False,
            }

        return {
            "id": facility.id,
            "name": getattr(facility, "name", None) or "Facility not configured",
            "facility_type": getattr(facility, "facility_type", None) or "Unknown",
            "district": getattr(facility, "district", None) or "Unknown",
            "address": getattr(facility, "address", None) or "Not available",
            "phone": getattr(facility, "phone", None) or "N/A",
            "is_active": getattr(facility, "is_active", True),
        }

    @staticmethod
    def get_queue_table_data(db: Session, facility_id: int = None):
        """Get formatted data for the queue table, optionally scoped to a facility."""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        q = db.query(Token).filter(
            Token.token_date >= today_start,
            Token.token_date < today_end
        )
        if facility_id:
            q = q.join(Visit, Token.visit_id == Visit.id).filter(Visit.facility_id == facility_id)
        tokens = q.order_by(Token.token_date.desc()).all()

        queue_data = []
        for token in tokens:
            try:
                token_time = token.token_date.strftime("%H:%M")
                queue_data.append({
                    "token_id": token.id,
                    "token_number": token.token_number,
                    "patient_name": token.visit.patient.full_name,
                    "patient_id": token.visit.patient.patient_id,
                    "age": token.visit.patient.age,
                    "department": token.visit.department.name,
                    "doctor_name": token.doctor.user.full_name,
                    "status": token.status.value,
                    "token_date": token_time,
                    # Backward-compatible aliases for older UI code paths.
                    "token": token.token_number,
                    "patient": token.visit.patient.full_name,
                    "doctor": token.doctor.user.full_name,
                    "time": token_time,
                })
            except (AttributeError, TypeError):
                # Skip tokens with missing relationships
                continue

        return queue_data

    @staticmethod
    def get_hourly_volume_data(db: Session, facility_id: int = None):
        """Get patient volume data by hour for chart, optionally scoped to a facility."""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        q = db.query(Token).filter(
            Token.token_date >= today_start,
            Token.token_date < today_end
        )
        if facility_id:
            q = q.join(Visit, Token.visit_id == Visit.id).filter(Visit.facility_id == facility_id)
        tokens = q.all()

        # Create hourly buckets
        hourly_data = {}
        for hour in range(24):
            hourly_data[f"{hour:02d}:00"] = 0

        for token in tokens:
            hour = token.token_date.hour
            key = f"{hour:02d}:00"
            if key in hourly_data:
                hourly_data[key] += 1

        # Convert to list format for plotting
        hours = list(hourly_data.keys())
        volumes = list(hourly_data.values())

        return hours, volumes
