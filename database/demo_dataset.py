"""Clean, Professional SIH Demo Dataset for MED-SETU.
Provides a controlled demo data reset + seed operation:
- Preserves schema, facilities, departments, staff accounts, authentication.
- Clears only existing demo/transactional patient data.
- Seeds exactly 5 coherent, realistic healthcare demo patients:
  1. Aarav Sharma (Primary Care - acute fever/pharyngitis)
  2. Fatima Khan (Chronic Condition - longitudinal diabetes history)
  3. Rahul Patil (High Priority Referral - acute chest pain -> Cardiology Pune)
  4. Meena Devi (Specialist Referral - severe knee pain -> Orthopedics Pune)
  5. Imran Shaikh (Document/Continuity - abdominal pain + diagnostic report + OCR)
"""
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any
from sqlalchemy.orm import Session

from database.models import (
    Facility, Department, Doctor, User, Patient, Visit, Token, TokenStatus,
    PatientCase, MedicalDocument, Prescription, DoctorNote, Referral,
    ReferralDataPackage, FollowUp
)


def reset_and_seed_demo_dataset(
    db: Session,
    user_role: str = "hospital_admin",
    confirmed: bool = False
) -> Dict[str, Any]:
    """
    Controlled Demo Data Reset & Seed:
    Safely resets transactional demo records and populates the 5 official SIH demo patients.
    Strictly preserves facilities, departments, doctors, and staff authentication.
    """
    role_clean = str(user_role).lower().split(".")[-1]
    if role_clean == "doctor":
        return {
            "success": False,
            "error": "Unauthorized: Doctors are not permitted to reset demo data."
        }

    authorized_roles = {"hospital_admin", "government", "admin", "demo_admin"}
    if role_clean not in authorized_roles:
        return {
            "success": False,
            "error": "Unauthorized: Demo reset requires administrative privileges."
        }

    if not confirmed:
        return {
            "success": False,
            "error": "Confirmation required: Please verify that you wish to reload the demo dataset."
        }

    try:
        # =========================================================================
        # 1. CLEAR ONLY TRANSACTIONAL PATIENT DATA (Strict dependency order)
        # =========================================================================
        packages_deleted = db.query(ReferralDataPackage).delete()
        referrals_deleted = db.query(Referral).delete()
        followups_deleted = db.query(FollowUp).delete()
        notes_deleted = db.query(DoctorNote).delete()
        prescriptions_deleted = db.query(Prescription).delete()
        documents_deleted = db.query(MedicalDocument).delete()
        cases_deleted = db.query(PatientCase).delete()
        tokens_deleted = db.query(Token).delete()
        visits_deleted = db.query(Visit).delete()
        patients_deleted = db.query(Patient).delete()

        db.flush()

        # =========================================================================
        # 2. RESOLVE PRESERVED FACILITIES, DEPARTMENTS & DOCTORS
        # =========================================================================
        fac_a = db.query(Facility).filter(Facility.name.like("%Rural%")).first()
        if not fac_a:
            fac_a = db.query(Facility).filter(Facility.id == 1).first()

        fac_b = db.query(Facility).filter(Facility.name.like("%District%")).first()
        if not fac_b:
            fac_b = db.query(Facility).filter(Facility.id == 2).first()

        if not fac_a or not fac_b:
            raise ValueError("Core facilities not found. Please ensure seed_database has initialized facilities.")

        # Departments
        dept_gen_a = db.query(Department).filter(
            Department.facility_id == fac_a.id,
            Department.name == "General Medicine"
        ).first()

        dept_cardio_b = db.query(Department).filter(
            Department.facility_id == fac_b.id,
            Department.name == "Cardiology"
        ).first()

        dept_ortho_b = db.query(Department).filter(
            Department.facility_id == fac_b.id,
            Department.name == "Orthopedics"
        ).first()

        # Doctors
        doc_khan = db.query(Doctor).filter(Doctor.doctor_id == "DOC-001").first()
        doc_sharma = db.query(Doctor).filter(Doctor.doctor_id == "DOC-002").first()
        doc_gupta = db.query(Doctor).filter(Doctor.doctor_id == "DOC-003").first()
        doc_verma = db.query(Doctor).filter(Doctor.doctor_id == "DOC-004").first()

        if not doc_khan or not doc_gupta or not doc_verma:
            raise ValueError("Core demo doctors not found.")

        now = datetime.utcnow()
        today_date = now.replace(minute=0, second=0, microsecond=0)

        # =========================================================================
        # 3. SEED 5 COHERENT DEMO PATIENTS
        # =========================================================================

        # -------------------------------------------------------------------------
        # PATIENT 1 — Aarav Sharma (Normal Primary Care Journey)
        # -------------------------------------------------------------------------
        pat_aarav = Patient(
            patient_id="PAT-00101",
            full_name="Aarav Sharma",
            age=28,
            gender="Male",
            phone="9000000001",
            preferred_language="Hindi",
            is_active=True,
            created_at=now - timedelta(days=3)
        )
        db.add(pat_aarav)
        db.flush()

        vis_aarav = Visit(
            visit_id="VIS-2026-00101",
            patient_id=pat_aarav.id,
            facility_id=fac_a.id,
            department_id=dept_gen_a.id,
            doctor_id=doc_khan.id,
            visit_date=today_date - timedelta(hours=3),
            status="completed",
            created_at=today_date - timedelta(hours=3, minutes=15)
        )
        db.add(vis_aarav)
        db.flush()

        tok_aarav = Token(
            token_number="MED-101",
            visit_id=vis_aarav.id,
            doctor_id=doc_khan.id,
            token_date=today_date - timedelta(hours=3, minutes=10),
            status=TokenStatus.COMPLETED,
            created_at=today_date - timedelta(hours=3, minutes=10)
        )
        db.add(tok_aarav)

        case_aarav = PatientCase(
            patient_id=pat_aarav.id,
            visit_id=vis_aarav.id,
            chief_complaint="Fever and sore throat for 3 days",
            duration="3 days",
            symptoms="Fever (101°F), sore throat, mild dry cough, generalized body ache, fatigue",
            additional_notes="No difficulty breathing, no chest pain. Symptoms began after seasonal rain exposure.",
            ai_summary="Acute pharyngitis / viral upper respiratory tract infection without acute red flags.",
            red_flag_detected=False,
            red_flags="",
            created_at=today_date - timedelta(hours=3, minutes=8)
        )
        db.add(case_aarav)

        note_aarav = DoctorNote(
            visit_id=vis_aarav.id,
            patient_id=pat_aarav.id,
            doctor_id=doc_khan.id,
            diagnosis="Acute Pharyngitis / Viral Upper Respiratory Infection",
            examination_findings="Temp: 100.6°F, BP: 120/78 mmHg, Pulse: 82 bpm regular. Throat: pharyngeal erythema, no tonsillar exudates. Chest: clear bilaterally, normal vesicular breath sounds.",
            treatment_plan="Symptomatic antipyretic, antihistaminic, throat lozenges, warm saline gargles, adequate oral hydration.",
            notes="Advised rest. Revisit if fever exceeds 102°F or persists beyond 5 days.",
            created_at=today_date - timedelta(hours=2, minutes=45)
        )
        db.add(note_aarav)

        rx_aarav_1 = Prescription(
            visit_id=vis_aarav.id,
            patient_id=pat_aarav.id,
            doctor_id=doc_khan.id,
            medication_name="Paracetamol",
            dosage="650mg",
            frequency="TDS (Thrice daily)",
            duration="3 days",
            instructions="Take after meals with water for fever and body ache",
            created_at=today_date - timedelta(hours=2, minutes=40)
        )
        rx_aarav_2 = Prescription(
            visit_id=vis_aarav.id,
            patient_id=pat_aarav.id,
            doctor_id=doc_khan.id,
            medication_name="Cetirizine",
            dosage="10mg",
            frequency="Once daily (At bedtime)",
            duration="5 days",
            instructions="For dry cough, throat tickle, and allergic symptoms",
            created_at=today_date - timedelta(hours=2, minutes=40)
        )
        db.add_all([rx_aarav_1, rx_aarav_2])

        fup_aarav = FollowUp(
            visit_id=vis_aarav.id,
            patient_id=pat_aarav.id,
            doctor_id=doc_khan.id,
            follow_up_date=today_date + timedelta(days=4),
            reason="Review fever resolution and throat healing",
            status="scheduled",
            created_at=today_date - timedelta(hours=2, minutes=35)
        )
        db.add(fup_aarav)

        # -------------------------------------------------------------------------
        # PATIENT 2 — Fatima Khan (Chronic Condition / Longitudinal History)
        # -------------------------------------------------------------------------
        pat_fatima = Patient(
            patient_id="PAT-00102",
            full_name="Fatima Khan",
            age=52,
            gender="Female",
            phone="9000000002",
            preferred_language="Hindi",
            is_active=True,
            created_at=now - timedelta(days=90)
        )
        db.add(pat_fatima)
        db.flush()

        # Historical Visit 1 (60 days ago)
        vis_fatima_1 = Visit(
            visit_id="VIS-2026-00041",
            patient_id=pat_fatima.id,
            facility_id=fac_a.id,
            department_id=dept_gen_a.id,
            doctor_id=doc_khan.id,
            visit_date=now - timedelta(days=60),
            status="completed",
            created_at=now - timedelta(days=60)
        )
        db.add(vis_fatima_1)
        db.flush()

        tok_fatima_1 = Token(
            token_number="MED-012",
            visit_id=vis_fatima_1.id,
            doctor_id=doc_khan.id,
            token_date=now - timedelta(days=60),
            status=TokenStatus.COMPLETED,
            created_at=now - timedelta(days=60)
        )
        db.add(tok_fatima_1)

        note_fatima_1 = DoctorNote(
            visit_id=vis_fatima_1.id,
            patient_id=pat_fatima.id,
            doctor_id=doc_khan.id,
            diagnosis="Type-2 Diabetes Mellitus - Routine Quarterly Follow-up",
            examination_findings="BP: 132/84 mmHg, Fasting Blood Sugar: 164 mg/dL, HbA1c: 7.8%, Weight: 68 kg.",
            treatment_plan="Started Metformin 500mg BD. Dietary glycemic counseling.",
            notes="Advised 30 minutes morning walking and reduced carbohydrate intake.",
            created_at=now - timedelta(days=60)
        )
        db.add(note_fatima_1)

        rx_fatima_1 = Prescription(
            visit_id=vis_fatima_1.id,
            patient_id=pat_fatima.id,
            doctor_id=doc_khan.id,
            medication_name="Metformin",
            dosage="500mg",
            frequency="BD (Twice daily)",
            duration="60 days",
            instructions="Take with morning and evening meals",
            created_at=now - timedelta(days=60)
        )
        db.add(rx_fatima_1)

        # Historical Visit 2 (30 days ago)
        vis_fatima_2 = Visit(
            visit_id="VIS-2026-00072",
            patient_id=pat_fatima.id,
            facility_id=fac_a.id,
            department_id=dept_gen_a.id,
            doctor_id=doc_khan.id,
            visit_date=now - timedelta(days=30),
            status="completed",
            created_at=now - timedelta(days=30)
        )
        db.add(vis_fatima_2)
        db.flush()

        tok_fatima_2 = Token(
            token_number="MED-028",
            visit_id=vis_fatima_2.id,
            doctor_id=doc_khan.id,
            token_date=now - timedelta(days=30),
            status=TokenStatus.COMPLETED,
            created_at=now - timedelta(days=30)
        )
        db.add(tok_fatima_2)

        note_fatima_2 = DoctorNote(
            visit_id=vis_fatima_2.id,
            patient_id=pat_fatima.id,
            doctor_id=doc_khan.id,
            diagnosis="Type-2 Diabetes Mellitus - Dose Titration Assessment",
            examination_findings="BP: 128/82 mmHg, Post-prandial Sugar: 184 mg/dL. Bilateral pedal pulses intact.",
            treatment_plan="Optimized Metformin to 850mg BD. Added Methylcobalamin.",
            notes="Patient tolerating medication. Emphasized foot care and eye examination.",
            created_at=now - timedelta(days=30)
        )
        db.add(note_fatima_2)

        rx_fatima_2 = Prescription(
            visit_id=vis_fatima_2.id,
            patient_id=pat_fatima.id,
            doctor_id=doc_khan.id,
            medication_name="Metformin",
            dosage="850mg",
            frequency="BD (Twice daily)",
            duration="30 days",
            instructions="Take with meals",
            created_at=now - timedelta(days=30)
        )
        db.add(rx_fatima_2)

        # Current Visit 3 (Today)
        vis_fatima_3 = Visit(
            visit_id="VIS-2026-00102",
            patient_id=pat_fatima.id,
            facility_id=fac_a.id,
            department_id=dept_gen_a.id,
            doctor_id=doc_khan.id,
            visit_date=today_date - timedelta(hours=2),
            status="completed",
            created_at=today_date - timedelta(hours=2, minutes=15)
        )
        db.add(vis_fatima_3)
        db.flush()

        tok_fatima_3 = Token(
            token_number="MED-102",
            visit_id=vis_fatima_3.id,
            doctor_id=doc_khan.id,
            token_date=today_date - timedelta(hours=2, minutes=10),
            status=TokenStatus.COMPLETED,
            created_at=today_date - timedelta(hours=2, minutes=10)
        )
        db.add(tok_fatima_3)

        case_fatima = PatientCase(
            patient_id=pat_fatima.id,
            visit_id=vis_fatima_3.id,
            chief_complaint="Increased fatigue and routine diabetes follow-up.",
            duration="2 weeks",
            symptoms="Generalized lethargy, occasional postprandial blurred vision, mild leg tiredness",
            additional_notes="Compliant with Metformin 850mg BD. Fasting glucose at home consistently ~170 mg/dL.",
            ai_summary="Longstanding type-2 diabetes mellitus requiring dual oral agent intensification.",
            red_flag_detected=False,
            red_flags="",
            created_at=today_date - timedelta(hours=2, minutes=8)
        )
        db.add(case_fatima)

        note_fatima_3 = DoctorNote(
            visit_id=vis_fatima_3.id,
            patient_id=pat_fatima.id,
            doctor_id=doc_khan.id,
            diagnosis="Type-2 Diabetes Mellitus - Suboptimal Glycemic Control with Fatigue",
            examination_findings="BP: 130/82 mmHg, Random Blood Sugar: 206 mg/dL, Urine Ketones: Negative. Foot monofilament test: intact bilateral protective sensation.",
            treatment_plan="Add Glimepiride 1mg OD before breakfast. Continue Metformin 850mg BD. Re-check HbA1c in 1 month.",
            notes="Educated patient on early symptoms of hypoglycemia and carrying glucose tablets.",
            created_at=today_date - timedelta(hours=1, minutes=45)
        )
        db.add(note_fatima_3)

        rx_fatima_3a = Prescription(
            visit_id=vis_fatima_3.id,
            patient_id=pat_fatima.id,
            doctor_id=doc_khan.id,
            medication_name="Glimepiride",
            dosage="1mg",
            frequency="Once daily (Before breakfast)",
            duration="30 days",
            instructions="Take 20 minutes before morning breakfast",
            created_at=today_date - timedelta(hours=1, minutes=40)
        )
        rx_fatima_3b = Prescription(
            visit_id=vis_fatima_3.id,
            patient_id=pat_fatima.id,
            doctor_id=doc_khan.id,
            medication_name="Metformin",
            dosage="850mg",
            frequency="BD (Twice daily)",
            duration="30 days",
            instructions="Take with morning and evening meals",
            created_at=today_date - timedelta(hours=1, minutes=40)
        )
        db.add_all([rx_fatima_3a, rx_fatima_3b])

        fup_fatima = FollowUp(
            visit_id=vis_fatima_3.id,
            patient_id=pat_fatima.id,
            doctor_id=doc_khan.id,
            follow_up_date=today_date + timedelta(days=30),
            reason="Evaluate response to dual oral hypoglycemic therapy & repeat HbA1c",
            status="scheduled",
            created_at=today_date - timedelta(hours=1, minutes=35)
        )
        db.add(fup_fatima)

        # -------------------------------------------------------------------------
        # PATIENT 3 — Rahul Patil (High Priority / Inter-Hospital Referral - Primary SIH Demo)
        # -------------------------------------------------------------------------
        pat_rahul = Patient(
            patient_id="PAT-00103",
            full_name="Rahul Patil",
            age=61,
            gender="Male",
            phone="9000000003",
            preferred_language="Marathi",
            is_active=True,
            created_at=now - timedelta(days=1)
        )
        db.add(pat_rahul)
        db.flush()

        vis_rahul = Visit(
            visit_id="VIS-2026-00103",
            patient_id=pat_rahul.id,
            facility_id=fac_a.id,
            department_id=dept_gen_a.id,
            doctor_id=doc_khan.id,
            visit_date=today_date - timedelta(hours=1),
            status="completed",
            created_at=today_date - timedelta(hours=1, minutes=15)
        )
        db.add(vis_rahul)
        db.flush()

        tok_rahul = Token(
            token_number="MED-103",
            visit_id=vis_rahul.id,
            doctor_id=doc_khan.id,
            token_date=today_date - timedelta(hours=1, minutes=10),
            status=TokenStatus.COMPLETED,
            created_at=today_date - timedelta(hours=1, minutes=10)
        )
        db.add(tok_rahul)

        case_rahul = PatientCase(
            patient_id=pat_rahul.id,
            visit_id=vis_rahul.id,
            chief_complaint="Chest discomfort with breathlessness since this morning.",
            duration="4 hours",
            symptoms="Substernal chest tightness radiating to left shoulder and arm, breathlessness on rest, cold diaphoresis, lightheadedness",
            additional_notes="Hypertensive for 8 years on irregular treatment. 12-lead ECG shows ST-segment depressions in leads II, III, aVF.",
            ai_summary="CRITICAL RED FLAG: Acute Coronary Syndrome (Unstable Angina / NSTEMI). Urgent inter-hospital cardiology transfer required.",
            red_flag_detected=True,
            red_flags="Substernal chest pressure with left arm radiation; acute dyspnea; diaphoresis; ECG ST depression.",
            created_at=today_date - timedelta(hours=1, minutes=8)
        )
        db.add(case_rahul)

        note_rahul = DoctorNote(
            visit_id=vis_rahul.id,
            patient_id=pat_rahul.id,
            doctor_id=doc_khan.id,
            diagnosis="Acute Coronary Syndrome (Suspected NSTEMI / Unstable Angina) - High Risk",
            examination_findings="BP: 154/96 mmHg, Pulse: 94 bpm regular, SpO2: 95% on ambient room air. Heart: S1 S2 present, no gallop, no pericardial rub. Lungs: bilateral vesicular sounds.",
            treatment_plan="Emergency stabilization: Aspirin 300mg stat chewed, Clopidogrel 300mg stat, Atorvastatin 80mg stat, Sorbitrate 5mg sublingual. Emergency referral to District General Hospital Pune Cardiology Department.",
            notes="Patient stabilized and prepared for immediate 108 ambulance transport with oxygen support.",
            created_at=today_date - timedelta(minutes=45)
        )
        db.add(note_rahul)

        rx_rahul_1 = Prescription(
            visit_id=vis_rahul.id,
            patient_id=pat_rahul.id,
            doctor_id=doc_khan.id,
            medication_name="Aspirin (Dispersible)",
            dosage="300mg",
            frequency="Stat (Immediate loading dose)",
            duration="Single dose",
            instructions="Chewed immediately in clinic for platelet inhibition",
            created_at=today_date - timedelta(minutes=40)
        )
        rx_rahul_2 = Prescription(
            visit_id=vis_rahul.id,
            patient_id=pat_rahul.id,
            doctor_id=doc_khan.id,
            medication_name="Clopidogrel",
            dosage="300mg",
            frequency="Stat (Immediate loading dose)",
            duration="Single dose",
            instructions="Take with water as emergency antiplatelet dual-therapy",
            created_at=today_date - timedelta(minutes=40)
        )
        rx_rahul_3 = Prescription(
            visit_id=vis_rahul.id,
            patient_id=pat_rahul.id,
            doctor_id=doc_khan.id,
            medication_name="Atorvastatin",
            dosage="80mg",
            frequency="Stat (High-intensity loading)",
            duration="Single dose",
            instructions="Immediate vascular plaque stabilization",
            created_at=today_date - timedelta(minutes=40)
        )
        db.add_all([rx_rahul_1, rx_rahul_2, rx_rahul_3])

        # Inter-Hospital Referral to Pune District Hospital Cardiology
        ref_rahul = Referral(
            referral_id="REF-2026-00101",
            visit_id=vis_rahul.id,
            patient_id=pat_rahul.id,
            referring_doctor_id=doc_khan.id,
            referring_facility_id=fac_a.id,
            receiving_facility_id=fac_b.id,
            receiving_department_id=dept_cardio_b.id,
            receiving_doctor_id=doc_gupta.id,
            reason="Urgent specialist evaluation of Acute Coronary Syndrome, Troponin-I assay, and urgent coronary angiography.",
            urgency="urgent",
            appointment_date=today_date + timedelta(days=1, hours=2),
            verification_code="MED-PUNE-CARDIO-881",
            status="pending",
            created_at=today_date - timedelta(minutes=35)
        )
        db.add(ref_rahul)
        db.flush()

        pkg_rahul_data = {
            "patient_summary": json.dumps({
                "patient_id": pat_rahul.patient_id,
                "full_name": pat_rahul.full_name,
                "age": pat_rahul.age,
                "gender": pat_rahul.gender,
                "phone": "9000000003",
                "language": pat_rahul.preferred_language
            }),
            "clinical_summary": json.dumps({
                "chief_complaint": case_rahul.chief_complaint,
                "duration": case_rahul.duration,
                "symptoms": case_rahul.symptoms,
                "red_flag_detected": True,
                "red_flags": case_rahul.red_flags,
                "diagnosis": note_rahul.diagnosis,
                "findings": note_rahul.examination_findings,
                "treatment_given": note_rahul.treatment_plan
            }),
            "visit_history": json.dumps([{
                "visit_id": vis_rahul.visit_id,
                "date": vis_rahul.visit_date.strftime("%Y-%m-%d %H:%M"),
                "facility": fac_a.name,
                "department": "General Medicine",
                "doctor": doc_khan.user.full_name
            }]),
            "prescription_data": json.dumps([
                {"medication": "Aspirin (Dispersible)", "medication_name": "Aspirin (Dispersible)", "dosage": "300mg", "frequency": "Stat loading", "duration": "Single dose"},
                {"medication": "Clopidogrel", "medication_name": "Clopidogrel", "dosage": "300mg", "frequency": "Stat loading", "duration": "Single dose"},
                {"medication": "Atorvastatin", "medication_name": "Atorvastatin", "dosage": "80mg", "frequency": "Stat loading", "duration": "Single dose"}
            ]),
            "document_references": "[]",
            "referral_summary": (
                "URGENT CARDIOLOGY REFERRAL: 61M presenting with acute substernal chest heaviness, "
                "left shoulder radiation, diaphoresis, and ECG ST depressions. Pre-treated with Aspirin 300mg, "
                "Clopidogrel 300mg, Atorvastatin 80mg loading. Referred from Rural CHC Thane to "
                "Dr. Anil Gupta (Cardiology), District General Hospital Pune for emergency coronary care."
            )
        }
        pkg_rahul = ReferralDataPackage(
            referral_id=ref_rahul.id,
            patient_summary=pkg_rahul_data["patient_summary"],
            clinical_summary=pkg_rahul_data["clinical_summary"],
            visit_history=pkg_rahul_data["visit_history"],
            prescription_data=pkg_rahul_data["prescription_data"],
            document_references=pkg_rahul_data["document_references"],
            referral_summary=pkg_rahul_data["referral_summary"],
            pdf_path=None,
            created_at=today_date - timedelta(minutes=30)
        )
        db.add(pkg_rahul)

        # -------------------------------------------------------------------------
        # PATIENT 4 — Meena Devi (Orthopedic Specialist Referral)
        # -------------------------------------------------------------------------
        pat_meena = Patient(
            patient_id="PAT-00104",
            full_name="Meena Devi",
            age=47,
            gender="Female",
            phone="9000000004",
            preferred_language="Hindi",
            is_active=True,
            created_at=now - timedelta(days=25)
        )
        db.add(pat_meena)
        db.flush()

        # Historical Visit (21 days ago)
        vis_meena_1 = Visit(
            visit_id="VIS-2026-00085",
            patient_id=pat_meena.id,
            facility_id=fac_a.id,
            department_id=dept_gen_a.id,
            doctor_id=doc_khan.id,
            visit_date=now - timedelta(days=21),
            status="completed",
            created_at=now - timedelta(days=21)
        )
        db.add(vis_meena_1)
        db.flush()

        note_meena_1 = DoctorNote(
            visit_id=vis_meena_1.id,
            patient_id=pat_meena.id,
            doctor_id=doc_khan.id,
            diagnosis="Right Knee Arthralgia / Suspected Early Osteoarthritis",
            examination_findings="Right knee joint tenderness over medial compartment, mild morning stiffness.",
            treatment_plan="Paracetamol 650mg SOS, quadriceps strengthening, hot fomentation.",
            notes="Advised weight management and avoidance of cross-legged sitting.",
            created_at=now - timedelta(days=21)
        )
        db.add(note_meena_1)

        # Current Visit (Today - in waiting queue for consultation)
        vis_meena_2 = Visit(
            visit_id="VIS-2026-00104",
            patient_id=pat_meena.id,
            facility_id=fac_a.id,
            department_id=dept_gen_a.id,
            doctor_id=doc_khan.id,
            visit_date=today_date - timedelta(minutes=45),
            status="ongoing",
            created_at=today_date - timedelta(minutes=45)
        )
        db.add(vis_meena_2)
        db.flush()

        tok_meena = Token(
            token_number="MED-104",
            visit_id=vis_meena_2.id,
            doctor_id=doc_khan.id,
            token_date=today_date - timedelta(minutes=40),
            status=TokenStatus.WAITING,
            created_at=today_date - timedelta(minutes=40)
        )
        db.add(tok_meena)

        case_meena = PatientCase(
            patient_id=pat_meena.id,
            visit_id=vis_meena_2.id,
            chief_complaint="Severe right knee pain for several weeks.",
            duration="6 weeks, acute worsening past 2 weeks",
            symptoms="Continuous right knee aching pain, morning joint stiffness >20 mins, audible crepitus while climbing stairs, restricted mobility",
            additional_notes="Failed conservative analgesic therapy. Joint swelling noticeable after walking 100 meters.",
            ai_summary="Progressive unicompartmental osteoarthritis right knee with secondary effusion.",
            red_flag_detected=False,
            red_flags="",
            created_at=today_date - timedelta(minutes=38)
        )
        db.add(case_meena)

        note_meena_2 = DoctorNote(
            visit_id=vis_meena_2.id,
            patient_id=pat_meena.id,
            doctor_id=doc_khan.id,
            diagnosis="Moderate to Severe Right Knee Osteoarthritis with Joint Effusion",
            examination_findings="Right knee: marked medial joint line tenderness, audible crepitus on passive flexion, restricted flexion to 90°, mild effusion.",
            treatment_plan="Referred to Dr. Sneha Verma, Orthopedics Department, District General Hospital Pune for digital standing X-ray, joint aspiration assessment, and intra-articular therapy.",
            notes="Prescribed short course of Aceclofenac + Paracetamol for pain relief bridge.",
            created_at=today_date - timedelta(minutes=20)
        )
        db.add(note_meena_2)

        rx_meena = Prescription(
            visit_id=vis_meena_2.id,
            patient_id=pat_meena.id,
            doctor_id=doc_khan.id,
            medication_name="Aceclofenac + Paracetamol",
            dosage="100mg/325mg",
            frequency="BD (Twice daily, after meals)",
            duration="7 days",
            instructions="Take after breakfast and dinner with water",
            created_at=today_date - timedelta(minutes=18)
        )
        db.add(rx_meena)

        # Referral to Pune District Hospital Orthopedics
        ref_meena = Referral(
            referral_id="REF-2026-00102",
            visit_id=vis_meena_2.id,
            patient_id=pat_meena.id,
            referring_doctor_id=doc_khan.id,
            referring_facility_id=fac_a.id,
            receiving_facility_id=fac_b.id,
            receiving_department_id=dept_ortho_b.id,
            receiving_doctor_id=doc_verma.id,
            reason="Specialist orthopedic evaluation of chronic right knee osteoarthritis, digital radiograph, and advanced management plan.",
            urgency="routine",
            appointment_date=today_date + timedelta(days=3, hours=4),
            verification_code="MED-PUNE-ORTHO-412",
            status="pending",
            created_at=today_date - timedelta(minutes=15)
        )
        db.add(ref_meena)
        db.flush()

        pkg_meena_data = {
            "patient_summary": json.dumps({
                "patient_id": pat_meena.patient_id,
                "full_name": pat_meena.full_name,
                "age": pat_meena.age,
                "gender": pat_meena.gender,
                "phone": "9000000004",
                "language": pat_meena.preferred_language
            }),
            "clinical_summary": json.dumps({
                "chief_complaint": case_meena.chief_complaint,
                "duration": case_meena.duration,
                "symptoms": case_meena.symptoms,
                "diagnosis": note_meena_2.diagnosis,
                "findings": note_meena_2.examination_findings,
                "treatment_given": note_meena_2.treatment_plan
            }),
            "visit_history": json.dumps([{
                "visit_id": vis_meena_1.visit_id,
                "date": vis_meena_1.visit_date.strftime("%Y-%m-%d"),
                "diagnosis": "Right Knee Arthralgia"
            }]),
            "prescription_data": json.dumps([
                {"medication": "Aceclofenac + Paracetamol", "medication_name": "Aceclofenac + Paracetamol", "dosage": "100mg/325mg", "frequency": "BD", "duration": "7 days"}
            ]),
            "document_references": "[]",
            "referral_summary": (
                "ORTHOPEDIC REFERRAL: 47F with 6-week progressive right knee osteoarthritis, "
                "crepitus, and joint effusion unresponsive to primary care analgesics. Referred to "
                "Dr. Sneha Verma, Orthopedics, District General Hospital Pune for imaging and joint evaluation."
            )
        }
        pkg_meena = ReferralDataPackage(
            referral_id=ref_meena.id,
            patient_summary=pkg_meena_data["patient_summary"],
            clinical_summary=pkg_meena_data["clinical_summary"],
            visit_history=pkg_meena_data["visit_history"],
            prescription_data=pkg_meena_data["prescription_data"],
            document_references=pkg_meena_data["document_references"],
            referral_summary=pkg_meena_data["referral_summary"],
            pdf_path=None,
            created_at=today_date - timedelta(minutes=10)
        )
        db.add(pkg_meena)

        # -------------------------------------------------------------------------
        # PATIENT 5 — Imran Shaikh (Document Upload / OCR / Continuity Case)
        # -------------------------------------------------------------------------
        pat_imran = Patient(
            patient_id="PAT-00105",
            full_name="Imran Shaikh",
            age=36,
            gender="Male",
            phone="9000000005",
            preferred_language="Marathi",
            is_active=True,
            created_at=now - timedelta(days=50)
        )
        db.add(pat_imran)
        db.flush()

        # Historical Visit 1 (45 days ago)
        vis_imran_1 = Visit(
            visit_id="VIS-2026-00058",
            patient_id=pat_imran.id,
            facility_id=fac_a.id,
            department_id=dept_gen_a.id,
            doctor_id=doc_khan.id,
            visit_date=now - timedelta(days=45),
            status="completed",
            created_at=now - timedelta(days=45)
        )
        db.add(vis_imran_1)
        db.flush()

        note_imran_1 = DoctorNote(
            visit_id=vis_imran_1.id,
            patient_id=pat_imran.id,
            doctor_id=doc_khan.id,
            diagnosis="Dyspepsia / Acid Peptic Disease - Initial presentation",
            examination_findings="Epigastric fullness, no organomegaly, no rebound tenderness.",
            treatment_plan="Pantoprazole 40mg OD before breakfast for 14 days. Dietary guidance.",
            notes="Advised to avoid late-night spicy meals and carbonated drinks.",
            created_at=now - timedelta(days=45)
        )
        db.add(note_imran_1)

        # Historical Visit 2 (15 days ago)
        vis_imran_2 = Visit(
            visit_id="VIS-2026-00088",
            patient_id=pat_imran.id,
            facility_id=fac_a.id,
            department_id=dept_gen_a.id,
            doctor_id=doc_khan.id,
            visit_date=now - timedelta(days=15),
            status="completed",
            created_at=now - timedelta(days=15)
        )
        db.add(vis_imran_2)
        db.flush()

        note_imran_2 = DoctorNote(
            visit_id=vis_imran_2.id,
            patient_id=pat_imran.id,
            doctor_id=doc_khan.id,
            diagnosis="Subacute Dyspepsia - Ultrasound Abdomen Advised",
            examination_findings="Persistent epigastric tenderness. Advised whole abdomen ultrasound.",
            treatment_plan="Advised USG Abdomen and complete blood count. Switched to Rabeprazole 20mg.",
            notes="Patient requested prescription to get scan done at local diagnostic center.",
            created_at=now - timedelta(days=15)
        )
        db.add(note_imran_2)

        # Current Visit 3 (Today - in waiting queue for report review)
        vis_imran_3 = Visit(
            visit_id="VIS-2026-00105",
            patient_id=pat_imran.id,
            facility_id=fac_a.id,
            department_id=dept_gen_a.id,
            doctor_id=doc_khan.id,
            visit_date=today_date - timedelta(minutes=20),
            status="ongoing",
            created_at=today_date - timedelta(minutes=20)
        )
        db.add(vis_imran_3)
        db.flush()

        tok_imran = Token(
            token_number="MED-105",
            visit_id=vis_imran_3.id,
            doctor_id=doc_khan.id,
            token_date=today_date - timedelta(minutes=18),
            status=TokenStatus.WAITING,
            created_at=today_date - timedelta(minutes=18)
        )
        db.add(tok_imran)

        case_imran = PatientCase(
            patient_id=pat_imran.id,
            visit_id=vis_imran_3.id,
            chief_complaint="Recurring abdominal discomfort with previous diagnostic reports.",
            duration="Past 3 weeks, intermittent postprandial fullness",
            symptoms="Epigastric burning, post-meal bloating, occasional regurgitation, mild nausea without vomiting",
            additional_notes="Brought ultrasound abdomen scan report completed at diagnostic center. Showing Grade-1 Fatty Liver, no gallstones.",
            ai_summary="Non-ulcer dyspepsia / gastroesophageal reflux with ultrasound correlation.",
            red_flag_detected=False,
            red_flags="",
            created_at=today_date - timedelta(minutes=16)
        )
        db.add(case_imran)

        # Uploaded Demo Document with OCR Text
        ocr_report_text = (
            "=========================================================\n"
            "THANE DIAGNOSTIC & IMAGING CENTRE — ULTRASOUND REPORT\n"
            "=========================================================\n"
            "Patient Name: Imran Shaikh | Age: 36 Yrs / Male\n"
            "Referred By : Dr. Mohammad Khan (Rural CHC Thane)\n"
            "Date of Scan: 2026-08-28 | Scan Type: Whole Abdomen & Pelvis\n"
            "---------------------------------------------------------\n"
            "SONOGRAPHIC FINDINGS:\n"
            "• Liver: Normal size (14.2 cm), smooth regular margins. Diffuse\n"
            "  increase in parenchymal echogenicity with sound attenuation,\n"
            "  consistent with Grade-1 Hepatic Steatosis (Fatty Liver).\n"
            "  No focal solid or cystic space-occupying lesion identified.\n"
            "• Gallbladder: Well-distended with physiological bile. Normal\n"
            "  wall thickness (2.2 mm). No calculus, sludge, or polyps.\n"
            "• Biliary Tree: Common bile duct is normal caliber (3.8 mm).\n"
            "• Pancreas: Normal contour, size, and parenchymal echotexture.\n"
            "• Spleen: Normal in size (10.4 cm) and homogeneous.\n"
            "• Kidneys: Both kidneys normal in size, shape, and cortical\n"
            "  thickness. Corticomedullary differentiation is well preserved.\n"
            "  No calculus or hydronephrosis in either kidney.\n"
            "• Urinary Bladder: Normal distension, smooth mucosal margin.\n"
            "---------------------------------------------------------\n"
            "IMPRESSION:\n"
            "1. Grade-1 Diffuse Hepatic Steatosis (Fatty Infiltration).\n"
            "2. No cholelithiasis, pancreatitis, or intra-abdominal mass.\n"
            "========================================================="
        )
        doc_imran = MedicalDocument(
            patient_id=pat_imran.id,
            visit_id=vis_imran_3.id,
            file_name="USG_Abdomen_Pelvis_Report.pdf",
            stored_name="demo_usg_report_imran_shaikh.pdf",
            file_type="application/pdf",
            file_path="uploads/demo_usg_report_imran_shaikh.pdf",
            extracted_text=ocr_report_text,
            created_at=today_date - timedelta(minutes=14)
        )
        db.add(doc_imran)

        note_imran_3 = DoctorNote(
            visit_id=vis_imran_3.id,
            patient_id=pat_imran.id,
            doctor_id=doc_khan.id,
            diagnosis="Non-Ulcer Dyspepsia (Functional Gastropathy) with Grade-1 Hepatic Steatosis",
            examination_findings="Abdomen: soft, non-tender to superficial palpation, mild epigastric tenderness on deep palpation, no hepatosplenomegaly, normal bowel sounds. USG report confirmed: Grade-1 Fatty Liver, normal gallbladder.",
            treatment_plan="Rabeprazole 20mg + Levosulpiride 75mg SR once daily before breakfast. Lifestyle and dietary intervention: brisk walking 45 min/day, reduce saturated fats and refined sugars.",
            notes="Ultrasound findings reassuring. Re-evaluated in 2 weeks for symptom resolution.",
            created_at=today_date - timedelta(minutes=10)
        )
        db.add(note_imran_3)

        rx_imran_1 = Prescription(
            visit_id=vis_imran_3.id,
            patient_id=pat_imran.id,
            doctor_id=doc_khan.id,
            medication_name="Rabeprazole + Levosulpiride SR",
            dosage="20mg/75mg",
            frequency="Once daily (Before breakfast)",
            duration="14 days",
            instructions="Take 30 minutes before morning breakfast with water",
            created_at=today_date - timedelta(minutes=8)
        )
        rx_imran_2 = Prescription(
            visit_id=vis_imran_3.id,
            patient_id=pat_imran.id,
            doctor_id=doc_khan.id,
            medication_name="Magaldrate + Simethicone Oral Gel",
            dosage="10 ml",
            frequency="TDS (After meals and at bedtime)",
            duration="7 days",
            instructions="Shake well before use. For immediate acid neutralization and bloating",
            created_at=today_date - timedelta(minutes=8)
        )
        db.add_all([rx_imran_1, rx_imran_2])

        fup_imran = FollowUp(
            visit_id=vis_imran_3.id,
            patient_id=pat_imran.id,
            doctor_id=doc_khan.id,
            follow_up_date=today_date + timedelta(days=14),
            reason="Review response to prokinetic therapy and lifestyle modifications",
            status="scheduled",
            created_at=today_date - timedelta(minutes=5)
        )
        db.add(fup_imran)

        db.commit()

        return {
            "success": True,
            "message": "Demo dataset loaded successfully.",
            "records_cleared": {
                "patients": patients_deleted,
                "visits": visits_deleted,
                "tokens": tokens_deleted,
                "cases": cases_deleted,
                "notes": notes_deleted,
                "prescriptions": prescriptions_deleted,
                "referrals": referrals_deleted,
                "packages": packages_deleted,
                "followups": followups_deleted,
                "documents": documents_deleted
            },
            "patients_seeded": [
                {"id": pat_aarav.id, "patient_id": pat_aarav.patient_id, "name": pat_aarav.full_name, "token": "MED-101", "status": "COMPLETED"},
                {"id": pat_fatima.id, "patient_id": pat_fatima.patient_id, "name": pat_fatima.full_name, "token": "MED-102", "status": "COMPLETED"},
                {"id": pat_rahul.id, "patient_id": pat_rahul.patient_id, "name": pat_rahul.full_name, "token": "MED-103", "status": "COMPLETED (Referral)"},
                {"id": pat_meena.id, "patient_id": pat_meena.patient_id, "name": pat_meena.full_name, "token": "MED-104", "status": "WAITING (Referral)"},
                {"id": pat_imran.id, "patient_id": pat_imran.patient_id, "name": pat_imran.full_name, "token": "MED-105", "status": "WAITING (Doc/OCR)"}
            ]
        }
    except Exception as e:
        db.rollback()
        return {
            "success": False,
            "error": f"Failed to reset demo dataset: {str(e)}"
        }
